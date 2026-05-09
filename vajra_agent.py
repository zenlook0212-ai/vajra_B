"""Vajra translation agent: async Qwen worker (8000) + Hermes auditor (8001)."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import subprocess
from typing import Any, TypedDict, cast

import httpx
from tenacity import (
    before_sleep_log,
    retry,
    stop_after_attempt,
    wait_exponential,
)

logger = logging.getLogger(__name__)

# Defaults match verified local vLLM topology; override via VAJRA_* env vars.
_DEFAULT_WORKER_URL = "http://127.0.0.1:8000/v1/chat/completions"
_DEFAULT_MANAGER_URL = "http://127.0.0.1:8001/v1/chat/completions"
_DEFAULT_WORKER_MODEL = "qwen-36b"
_DEFAULT_MANAGER_MODEL = "hermes-36b"


class AuditResult(TypedDict):
    """Structured doctrinal audit output from the manager model."""

    original: str
    translation: str
    approved: bool
    issues: list[str]


def _log_gpu_state_sync() -> None:
    """Log GPU memory via NVML; on failure, log nvidia-smi output."""
    try:
        import pynvml

        pynvml.nvmlInit()
        try:
            handle = pynvml.nvmlDeviceGetHandleByIndex(0)
            mem_info = pynvml.nvmlDeviceGetMemoryInfo(handle)
            logger.error(
                "GPU Memory: %.1fGB / %.1fGB",
                mem_info.used / 1024**3,
                mem_info.total / 1024**3,
            )
        finally:
            try:
                pynvml.nvmlShutdown()
            except Exception as shutdown_err:
                logger.warning("pynvml.nvmlShutdown failed: %s", shutdown_err)
    except Exception as nvml_err:
        logger.error("NVML GPU state failed: %s", nvml_err)
        try:
            result = subprocess.run(
                ["nvidia-smi"],
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
            )
            merged = (result.stdout or "") + (result.stderr or "")
            logger.error("nvidia-smi:\n%s", merged[:8000])
        except Exception as smi_err:
            logger.error("nvidia-smi fallback failed: %s", smi_err)


async def _log_gpu_state_async() -> None:
    """Run GPU logging in a thread to avoid blocking NVML/subprocess on the event loop."""
    await asyncio.to_thread(_log_gpu_state_sync)


def _strip_json_fence(content: str) -> str:
    text = content.strip()
    if not text.startswith("```"):
        return text
    lines = text.split("\n")
    if lines and lines[0].startswith("```"):
        lines = lines[1:]
    if lines and lines[-1].strip() in ("```", "```json"):
        lines = lines[:-1]
    return "\n".join(lines).strip()


def _coerce_audit_payload(data: dict[str, Any]) -> AuditResult:
    required = ("original", "translation", "approved", "issues")
    missing = [k for k in required if k not in data]
    if missing:
        raise ValueError(f"audit JSON missing keys: {missing}")
    issues_raw = data["issues"]
    if not isinstance(issues_raw, list):
        raise ValueError("audit JSON 'issues' must be a list")
    issues = [str(x) for x in issues_raw]
    normalized: AuditResult = {
        "original": str(data["original"]),
        "translation": str(data["translation"]),
        "approved": bool(data["approved"]),
        "issues": issues,
    }
    return normalized


def _parse_audit_json(content: str) -> AuditResult:
    raw = _strip_json_fence(content)
    data = json.loads(raw)
    if not isinstance(data, dict):
        raise ValueError("audit output must be a JSON object")
    return _coerce_audit_payload(cast(dict[str, Any], data))


_TRANSLATION_TAG_PATTERN = re.compile(
    r"<translation>(.*?)</translation>",
    re.DOTALL,
)


def extract_translation(text: str) -> tuple[str, bool]:
    """
    Parse worker output: first ``<translation>...</translation>`` pair, else first line.

    When ``stop=["</translation>"]`` is used, many servers omit the closing tag from
    ``message.content``; in that case we still take the substring after the opening
    tag (not counted as ``tag_missing``).

    :returns: ``(snippet, tag_missing)`` — ``tag_missing`` is True only for first-line fallback.
    """
    match = _TRANSLATION_TAG_PATTERN.search(text)
    if match:
        return (match.group(1).strip(), False)
    marker = "<translation>"
    open_idx = text.find(marker)
    if open_idx != -1:
        inner = text[open_idx + len(marker) :]
        close_idx = inner.find("</translation>")
        if close_idx != -1:
            return (inner[:close_idx].strip(), False)
        return (inner.strip(), False)
    normalized = text.replace("\r\n", "\n")
    first_line = normalized.split("\n", 1)[0].strip()
    return (first_line, True)


class VajraAgent:
    """
    Coordinate worker (Tibetan draft translation) and manager (doctrinal audit).

    Uses ``httpx.AsyncClient``, ``asyncio.Semaphore(2)`` for outbound concurrency,
    and tenacity exponential backoff on HTTP failures.
    """

    def __init__(
        self,
        *,
        worker_url: str | None = None,
        manager_url: str | None = None,
        worker_model: str | None = None,
        manager_model: str | None = None,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self._worker_url = worker_url or os.environ.get(
            "VAJRA_WORKER_URL", _DEFAULT_WORKER_URL
        )
        self._manager_url = manager_url or os.environ.get(
            "VAJRA_MANAGER_URL", _DEFAULT_MANAGER_URL
        )
        self._worker_model = worker_model or os.environ.get(
            "VAJRA_WORKER_MODEL", _DEFAULT_WORKER_MODEL
        )
        self._manager_model = manager_model or os.environ.get(
            "VAJRA_MANAGER_MODEL", _DEFAULT_MANAGER_MODEL
        )
        self._client = http_client or httpx.AsyncClient(
            timeout=httpx.Timeout(120.0),
        )
        self._owns_client = http_client is None
        self._semaphore = asyncio.Semaphore(2)

    async def aclose(self) -> None:
        """Close the HTTP client if this agent created it."""
        if self._owns_client:
            await self._client.aclose()

    async def __aenter__(self) -> VajraAgent:
        return self

    async def __aexit__(self, exc_type: object, exc: object, tb: object) -> None:
        await self.aclose()

    async def _post_chat_completion_text(
        self,
        url: str,
        model: str,
        messages: list[dict[str, str]],
        *,
        temperature: float,
        max_tokens: int,
        stop: list[str] | None = None,
        enable_thinking: bool = True,
    ) -> str:
        @retry(
            stop=stop_after_attempt(3),
            wait=wait_exponential(multiplier=2, min=2, max=10),
            before_sleep=before_sleep_log(logger, logging.WARNING),
            reraise=True,
        )
        async def _request() -> str:
            body: dict[str, Any] = {
                "model": model,
                "messages": messages,
                "temperature": temperature,
                "max_tokens": max_tokens,
            }
            if stop is not None:
                body["stop"] = stop
            if not enable_thinking:
                body["chat_template_kwargs"] = {"enable_thinking": False}
            response = await self._client.post(url, json=body)
            response.raise_for_status()
            payload = response.json()
            choices = payload.get("choices")
            if not isinstance(choices, list) or not choices:
                raise ValueError("chat completion response has no choices")
            message = choices[0].get("message")
            if not isinstance(message, dict):
                raise ValueError("chat completion choice has no message")
            content = message.get("content")
            if not isinstance(content, str):
                raise ValueError("chat completion message has no string content")
            return content

        return await _request()

    async def translate_tibetan(self, text: str) -> str:
        """
        Call the worker on port 8000 (``VAJRA_WORKER_URL``) for Tibetan draft translation.

        :param text: Source Tibetan string.
        :returns: Model translation output (plain text).
        """
        stripped = text.strip()
        if not stripped:
            raise ValueError("text must be non-empty")

        messages: list[dict[str, str]] = [
            {
                "role": "system",
                "content": (
                    "你是藏文翻譯助手，僅作語言轉換，"
                    "將使用者提供的藏文譯成通順的現代漢語，不要添加教義詮釋或任何閒談。"
                    "你只允許輸出這一行格式（不要有其他文字）："
                    "<translation>譯文內容</translation>"
                ),
            },
            {"role": "user", "content": stripped},
        ]
        try:
            async with self._semaphore:
                raw = await self._post_chat_completion_text(
                    self._worker_url,
                    self._worker_model,
                    messages,
                    temperature=0.0,
                    max_tokens=256,
                    stop=["</translation>"],
                    enable_thinking=False,
                )
        except Exception as exc:
            logger.error("translate_tibetan request failed: %s", exc)
            await _log_gpu_state_async()
            raise

        out, tag_missing = extract_translation(raw)
        if tag_missing:
            logger.warning(
                "translate_tibetan: missing <translation> tags, using first-line fallback"
            )
        logger.info("translate_tibetan completed (%d chars output)", len(out))
        return out

    async def audit_translation(self, original: str, translated: str) -> AuditResult:
        """
        Call the manager on port 8001 (``VAJRA_MANAGER_URL``) for doctrinal audit.

        Expects a single JSON object:
        ``{"original": str, "translation": str, "approved": bool, "issues": list}``.
        """
        if not original.strip() or not translated.strip():
            raise ValueError("original and translated must be non-empty")

        system = (
            "你是佛教文獻審核員。比對原文與譯文是否符合白名單教義來源，"
            "並檢查是否誤入黑名單附佛外道或民間信仰表述。"
            "只輸出一個 JSON 物件，鍵為 original, translation, approved, issues。"
            "issues 為字串列表；approved 為布林；original 與 translation 填寫你評估用的兩段文字（與輸入一致即可）。"
            "不要輸出任何 JSON 以外的文字。"
        )
        user = json.dumps(
            {"original": original.strip(), "translation": translated.strip()},
            ensure_ascii=False,
        )
        messages: list[dict[str, str]] = [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ]
        try:
            async with self._semaphore:
                raw_content = await self._post_chat_completion_text(
                    self._manager_url,
                    self._manager_model,
                    messages,
                    temperature=0.2,
                    max_tokens=4096,
                )
        except Exception as exc:
            logger.error("audit_translation request failed: %s", exc)
            await _log_gpu_state_async()
            raise

        try:
            audit = _parse_audit_json(raw_content)
        except Exception as exc:
            logger.error("audit_translation parse failed: %s", exc)
            await _log_gpu_state_async()
            raise ValueError(f"invalid audit JSON: {exc}") from exc

        logger.info(
            "audit_translation completed approved=%s issues=%d",
            audit["approved"],
            len(audit["issues"]),
        )
        return audit


async def test_run() -> None:
    """
    Simulate a short Tibetan line: worker translate then manager audit (full dual path).

    Example text: Tibetan greeting (བཀྲ་ཤིས་བདེ་ལེགས།).
    """
    sample = "བཀྲ་ཤིས་བདེ་ལེགས།"
    async with VajraAgent() as agent:
        logger.info("test_run: translating sample Tibetan")
        zh = await agent.translate_tibetan(sample)
        logger.info("test_run: draft translation obtained (%d chars)", len(zh))
        audit = await agent.audit_translation(sample, zh)
        logger.info(
            "test_run: audit approved=%s issues=%s translation_preview=%r",
            audit["approved"],
            audit["issues"],
            zh[:200],
        )


def _configure_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )


if __name__ == "__main__":
    _configure_logging()
    asyncio.run(test_run())
