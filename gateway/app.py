"""
FastAPI unified gateway: Telegram + Web share the same `/v1/task` contract.

Uses `models.yaml` for vLLM URLs; never hardcodes host ports in handlers.
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
import re
import subprocess
from contextlib import asynccontextmanager
from enum import Enum
from typing import Any

import httpx
import yaml
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, model_validator

from gateway.config import (
    audit_policy_yaml_path,
    load_models_yaml,
    ocr_batch_max_images,
    routing_yaml_path,
    translation_memory_db_path,
    translation_memory_enabled,
)
from gateway import hermes_conditional
from gateway import ops as gateway_ops
from gateway import pg_retrieval
from gateway import rag_retrieval
from gateway import tm_store
from gateway.llm_client import acquire_llm_slot, chat_completion, embeddings_request

logger = logging.getLogger(__name__)

_TIBETAN_RE = re.compile(r"[\u0F00-\u0FFF]")
_QUICK_CHAT_GREETING_RE = re.compile(
    r"^\s*(hi|hello|hey|你好|您好|哈囉|在嗎|在吗|嗨)\s*[!！?？.。~～]*\s*$",
    re.IGNORECASE,
)


class TaskMode(str, Enum):
    translate = "translate"
    ocr = "ocr"
    deep_think = "deep_think"
    canon_rag = "canon_rag"
    canon_survey = "canon_survey"
    chat = "chat"
    model_admin = "model_admin"


class Channel(str, Enum):
    web = "web"
    telegram = "telegram"
    internal = "internal"


class TaskRequest(BaseModel):
    mode: TaskMode
    channel: Channel = Channel.web
    """Client channel; affects default Hermes tier for audited modes."""
    message: str = Field(default="", max_length=65536)
    image_base64: str | None = Field(
        default=None,
        description="Raw base64 (no data: URL prefix) for single-image OCR.",
    )
    images_base64: list[str] | None = Field(
        default=None,
        description="Multiple raw base64 images for parallel/batch OCR (mode=ocr).",
        max_length=48,
    )
    skip_translation_memory: bool = Field(
        default=False,
        description="translate mode: bypass SQLite TM cache lookup/store.",
    )
    ops: dict[str, Any] | None = Field(
        default=None,
        description="model_admin JSON: action + optional container; see Gateway spec.",
    )
    client_request_id: str | None = Field(default=None, max_length=128)
    survey_page: int = Field(default=1, ge=1, description="canon_survey: 1-based page.")
    survey_page_size: int = Field(
        default=15, ge=5, le=50, description="canon_survey: canons per page."
    )
    audit_override: str | None = Field(
        default=None,
        description="H0|H1|H2; only honored for channel=internal and env allow list.",
    )

    @model_validator(mode="after")
    def _ocr_payload_present(self) -> TaskRequest:
        if self.mode != TaskMode.ocr:
            return self
        has_single = bool(self.image_base64 and self.image_base64.strip())
        has_batch = bool(self.images_base64 and len(self.images_base64) > 0)
        if not has_single and not has_batch:
            raise ValueError(
                "ocr requires image_base64 or non-empty images_base64 list",
            )
        return self


class TaskResponse(BaseModel):
    ok: bool = True
    mode: TaskMode
    channel: Channel
    audit_level: str | None = None
    output: dict[str, Any] = Field(default_factory=dict)
    meta: dict[str, Any] = Field(default_factory=dict)


def _count_tibetan_glyphs(text: str) -> int:
    return len(_TIBETAN_RE.findall(text))


def _tibetan_ratio(text: str) -> float:
    if not text.strip():
        return 0.0
    return _count_tibetan_glyphs(text) / max(len(text.replace("\n", "")), 1)


def _routing_language_thresholds() -> tuple[int, float]:
    path = routing_yaml_path()
    if not path.is_file():
        return 8, 0.4
    cfg = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    lc = cfg.get("language_detection") or {}
    n = int(lc.get("min_tibetan_chars_for_monlam", 8))
    r = float(lc.get("min_tibetan_ratio_for_monlam", 0.4))
    return n, r


def _default_audit_for_channel(channel: Channel) -> str:
    path = audit_policy_yaml_path()
    if not path.is_file():
        return "H2"
    cfg = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    cmap = cfg.get("channel_default_audit") or {}
    key = channel.value if channel != Channel.internal else "internal"
    return str(cmap.get(key, cmap.get("web", "H2")))


def _resolve_audit_level(channel: Channel, override: str | None) -> str:
    base = _default_audit_for_channel(channel)
    if override and channel == Channel.internal:
        allow = os.environ.get("VAJRA_ALLOW_INTERNAL_AUDIT_OVERRIDE", "1") == "1"
        if allow and override.upper() in {"H0", "H1", "H2"}:
            return override.upper()
    return base.upper()


def _endpoints_maps(cfg: dict[str, Any]) -> dict[str, dict[str, str]]:
    eps: dict[str, dict[str, str]] = {}
    for name, spec in cfg["endpoints"].items():
        eps[str(name)] = {"url": str(spec["url"]), "model_id": str(spec["model_id"])}
    return eps


def _disabled_task_modes() -> frozenset[str]:
    raw = os.environ.get("VAJRA_DISABLED_MODES", "")
    return frozenset(x.strip().lower() for x in raw.split(",") if x.strip())


def _chat_max_tokens() -> int:
    raw = os.environ.get("VAJRA_CHAT_MAX_TOKENS", "768").strip()
    try:
        n = int(raw)
    except ValueError:
        n = 768
    return max(128, min(n, 2048))


def _is_quick_chat_greeting(text: str) -> bool:
    if not text:
        return False
    return bool(_QUICK_CHAT_GREETING_RE.match(text))


def _quick_chat_reply() -> str:
    return (
        "您好！我是佛學與語言助理。可直接貼上問題、藏文片段或圖片，我會幫你快速處理。\n"
        "<Logic_Gate>\n"
        "推理依據：\n"
        "－「邏輯推論」──簡短問候屬社交啟動語境，採用低延遲固定回覆並引導下一步提問。\n"
        "</Logic_Gate>"
    )


_HERMES_AUDIT_SYSTEM = (
    "你是教義與引用審核助理。請只輸出一段 JSON，勿其他文字。"
    '格式：{"original": str, "translation": str, "approved": bool, "issues": [str, ...]}'
)

_CHAT_LOGIC_GATE_SYSTEM = (
    "你是佛學與語言助理。用戶目前為輕量 **/chat** 對話模式（未強制經文向量檢索）。\n"
    "禁止輸出任何內部思考、草稿或規劃步驟；"
    "不得輸出例如 Here's a thinking process / Analyze User Input / Draft Response / Check Against Constraints / </think> 等內容。\n"
    "回覆第一行必須直接是給使用者的繁體中文正文。\n"
    "除正文外，回覆**文末必須**保留以下標籤與結構（標籤名稱勿改）：\n"
    "<Logic_Gate>\n"
    "推理依據：（擇一或兩項並陳，各一行簡述）\n"
    "－「原文證據」──僅當你引用可指明的典籍／原典文句或經號（例如 TX19n0011）時使用，並簡列出處；\n"
    "－「邏輯推論」──當主要依靠佛學通說、推理或常識，而**沒有**具體原典文據時使用。\n"
    "若兩者皆有，請分開標示。\n"
    "</Logic_Gate>"
)


async def _hermes_audit(
    client: httpx.AsyncClient,
    eps: dict[str, dict[str, str]],
    *,
    original: str,
    draft: str,
    audit_level: str,
) -> dict[str, Any]:
    if audit_level == "H0":
        return {
            "original": original,
            "translation": draft,
            "approved": True,
            "issues": [],
            "skipped": True,
        }
    he = eps.get("hermes")
    if not he:
        raise HTTPException(status_code=503, detail="Hermes endpoint not configured")
    messages: list[dict[str, str]] = [
        {"role": "system", "content": _HERMES_AUDIT_SYSTEM},
        {
            "role": "user",
            "content": f"原文：\n{original}\n\n待審稿：\n{draft}\n",
        },
    ]
    try:
        content, _raw = await _llm_chat_completion(
            client,
            url=he["url"],
            model_id=he["model_id"],
            messages=messages,
            max_tokens=4096,
            temperature=0.2,
        )
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Hermes audit failed: %s", exc)
        if audit_level == "H2":
            raise HTTPException(
                status_code=503,
                detail="Hermes unavailable; H2 policy blocks external output.",
            ) from exc
        return {
            "original": original,
            "translation": draft,
            "approved": False,
            "issues": [f"hermes_error: {exc!s}"],
            "fallback": True,
        }

    try:
        obj = json.loads(content)
    except json.JSONDecodeError:
        if audit_level == "H2":
            raise HTTPException(
                status_code=502,
                detail="Hermes returned non-JSON; H2 cannot proceed.",
            )
        return {
            "original": original,
            "translation": draft,
            "approved": False,
            "issues": ["hermes_non_json"],
            "raw": content[:2000],
        }
    if not isinstance(obj, dict):
        raise HTTPException(status_code=502, detail="Hermes JSON must be an object")
    return obj


async def _hermes_audit_translate_rag_safe(
    client: httpx.AsyncClient,
    eps: dict[str, dict[str, str]],
    *,
    original: str,
    draft: str,
    audit_level: str,
    reason: str,
) -> dict[str, Any]:
    """
    translate / canon_rag 可選審核：不因 Hermes 失敗而中斷主鏈（回傳 bypass 標記）。
    """
    try:
        return await _hermes_audit(
            client,
            eps,
            original=original,
            draft=draft,
            audit_level=audit_level,
        )
    except HTTPException as exc:
        det = exc.detail
        detail = det if isinstance(det, str) else str(det)
        logger.warning(
            "%s optional Hermes audit HTTPException: %s",
            reason,
            detail[:500],
        )
        return {
            "original": original,
            "translation": draft,
            "approved": True,
            "issues": [f"hermes_bypass_http:{detail[:400]}"],
            "bypass": True,
        }
    except Exception as exc:
        logger.exception("%s optional Hermes audit failed", reason)
        return {
            "original": original,
            "translation": draft,
            "approved": True,
            "issues": [f"hermes_bypass_error:{exc!s}"[:400]],
            "bypass": True,
        }


async def _llm_chat_completion(
    client: httpx.AsyncClient,
    *,
    url: str,
    model_id: str,
    messages: list[dict[str, str]],
    max_tokens: int,
    temperature: float,
    extra_body: dict[str, Any] | None = None,
) -> tuple[str, dict[str, Any]]:
    """Call vLLM OpenAI-compat chat; surface failures as HTTPException (never raw 500)."""
    try:
        return await chat_completion(
            client,
            url=url,
            model_id=model_id,
            messages=messages,
            max_tokens=max_tokens,
            temperature=temperature,
            extra_body=extra_body,
        )
    except httpx.HTTPStatusError as exc:
        snippet = ""
        try:
            snippet = (exc.response.text or "")[:800]
        except Exception:
            snippet = ""
        logger.exception("vLLM HTTPStatusError url=%s", url)
        raise HTTPException(
            status_code=502,
            detail=f"vLLM status {exc.response.status_code}: {snippet or exc!s}",
        ) from exc
    except (httpx.ReadError, httpx.RemoteProtocolError) as exc:
        logger.warning(
            "vLLM transport cut mid-response url=%s: %s (see vLLM container logs)",
            url,
            exc,
        )
        raise HTTPException(
            status_code=503,
            detail=(
                "vLLM 回應傳輸中斷（連線讀取被切斷）；常見：容器重啟、GPU OOM、"
                "或生成時間過長。請查 qwen/monlam/hermes 日誌；"
                "可加大環境變數 VAJRA_VLLM_CHAT_TIMEOUT_SEC（秒）並重啟閘道後重試。"
                f" {type(exc).__name__}: {exc!s}"
            ),
        ) from exc
    except httpx.RequestError as exc:
        logger.exception("vLLM RequestError url=%s", url)
        why = str(exc).strip() or f"{type(exc).__name__}({exc!r})"
        raise HTTPException(
            status_code=503,
            detail=f"vLLM unreachable ({url}): {why}",
        ) from exc
    except (TypeError, ValueError, KeyError) as exc:
        logger.exception("vLLM response parse error url=%s", url)
        raise HTTPException(
            status_code=502,
            detail=f"vLLM bad response: {exc!s}",
        ) from exc


async def _ocr_qwen_vl_post(
    vl: dict[str, str],
    raw: bytes,
    user_text: str,
) -> str:
    """Single-image OCR via OpenAI-compatible VL payload."""
    b64url = base64.b64encode(raw).decode("ascii")
    user_content: list[dict[str, Any]] = [
        {
            "type": "image_url",
            "image_url": {"url": f"data:image/jpeg;base64,{b64url}"},
        },
        {
            "type": "text",
            "text": user_text
            or "請辨識圖中文字，保持段落；以繁體中文輸出辨識結果。",
        },
    ]
    payload: dict[str, Any] = {
        "model": vl["model_id"],
        "messages": [{"role": "user", "content": user_content}],
        "max_tokens": 4096,
        "temperature": 0.1,
    }
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(180.0)) as _c:
            async with acquire_llm_slot():
                r = await _c.post(vl["url"], json=payload)
                r.raise_for_status()
                data = r.json()
    except httpx.HTTPStatusError as exc:
        snippet = (exc.response.text or "")[:600]
        raise HTTPException(
            status_code=502,
            detail=f"qwen_vl status {exc.response.status_code}: {snippet or exc!s}",
        ) from exc
    except httpx.RequestError as exc:
        why = str(exc).strip() or f"{type(exc).__name__}({exc!r})"
        raise HTTPException(
            status_code=503,
            detail=f"qwen_vl unreachable: {why}",
        ) from exc
    except (TypeError, ValueError, KeyError) as exc:
        raise HTTPException(
            status_code=502,
            detail=f"qwen_vl bad response: {exc!s}",
        ) from exc
    choices = data.get("choices") or []
    msg = (choices[0].get("message") or {}) if choices else {}
    content = msg.get("content") if isinstance(msg.get("content"), str) else ""
    return content or str(msg)


def create_app() -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        """Load ``models.yaml``；失敗時仍啟動服務（`/health` 可用），並記錄例外。"""
        app.state.models_cfg = {}
        app.state.endpoints = {}
        setattr(app.state, "http_client", None)
        try:
            cfg = load_models_yaml()
            app.state.models_cfg = cfg
            app.state.endpoints = _endpoints_maps(cfg)
            logger.info("Gateway loaded %d endpoints", len(app.state.endpoints))
        except Exception as exc:
            logger.exception("Gateway lifespan startup: models.yaml failed: %s", exc)
        try:
            if translation_memory_enabled():
                p_tm = translation_memory_db_path()
                await tm_store.tm_init(p_tm)
                logger.info("Translation memory initialized at %s", p_tm)
        except Exception as exc:
            logger.exception("Translation memory init failed (continuing): %s", exc)

        if os.environ.get("VAJRA_VRAM_LOG_ON_START", "1").strip() == "1":
            try:
                _, gpu_rows = await gateway_ops.nvidia_gpu_memory_csv()
                thr_raw = os.environ.get("VAJRA_VRAM_WARN_FREE_MIB", "4096")
                thr_mib = max(512, int(thr_raw))
                advisory = gateway_ops.vram_advisory_rows(
                    gpu_rows, warn_below_mib=thr_mib
                )
                for hint in advisory.get("hints", []):
                    logger.warning("%s", hint)
            except Exception as exc:
                logger.warning("VRAM startup check skipped: %s", exc)

        yield
        cl = getattr(app.state, "http_client", None)
        if cl is not None:
            await cl.aclose()

    app = FastAPI(
        title="Vajra Gateway",
        description="Unified API for Telegram + Web; modes map to local vLLM stacks.",
        version="0.1.0",
        lifespan=lifespan,
    )

    if os.environ.get("VAJRA_GATEWAY_DEBUG", "").strip().lower() in (
        "1",
        "true",
        "yes",
    ):
        @app.exception_handler(Exception)
        async def _debug_unhandled_exc(_request, exc: Exception) -> JSONResponse:
            logger.exception("Unhandled gateway error")
            return JSONResponse(
                status_code=500,
                content={"detail": str(exc), "type": type(exc).__name__},
            )

    async def _http() -> httpx.AsyncClient:
        if getattr(app.state, "http_client", None) is None:
            app.state.http_client = httpx.AsyncClient(
                timeout=httpx.Timeout(120.0),
                limits=httpx.Limits(max_connections=20, max_keepalive_connections=10),
            )
        return app.state.http_client

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/v1/modes")
    async def list_modes() -> dict[str, Any]:
        rpath = routing_yaml_path()
        routes: dict[str, Any] = {}
        lang: dict[str, Any] = {}
        if rpath.is_file():
            raws = yaml.safe_load(rpath.read_text(encoding="utf-8")) or {}
            routes = raws.get("routes") or {}
            lang = raws.get("language_detection") or {}
        ap_path = audit_policy_yaml_path()
        audit_subset: dict[str, Any] = {}
        if ap_path.is_file():
            ap = yaml.safe_load(ap_path.read_text(encoding="utf-8")) or {}
            for key in ("audit_levels", "channel_default_audit"):
                if key in ap:
                    audit_subset[key] = ap[key]
        return {
            "modes": [m.value for m in TaskMode],
            "channels": [c.value for c in Channel],
            "routes": routes,
            "language_detection": lang,
            "audit_policy": audit_subset,
        }

    @app.post("/v1/task", response_model=TaskResponse)
    async def run_task(request: Request, body: TaskRequest) -> TaskResponse:
        eps: dict[str, dict[str, str]] = getattr(
            app.state, "endpoints", {}
        ) or {}
        http = await _http()
        dm = _disabled_task_modes()
        if body.mode.value.lower() in dm:
            raise HTTPException(
                status_code=503,
                detail=f"mode {body.mode.value!r} disabled by VAJRA_DISABLED_MODES",
            )
        audit_level = _resolve_audit_level(body.channel, body.audit_override)
        meta: dict[str, Any] = {
            "client_request_id": body.client_request_id,
            "audit_level": audit_level,
        }

        if body.mode == TaskMode.model_admin:
            token = os.environ.get("VAJRA_ADMIN_TOKEN", "").strip()
            hdr = request.headers.get("X-Admin-Token") or request.headers.get(
                "x-admin-token"
            )
            if not token or hdr != token:
                raise HTTPException(status_code=403, detail="admin token required")
            raw_ops = body.ops or {}
            act = str(raw_ops.get("action", "snapshot")).strip().lower()

            if act == "snapshot":
                try:
                    txt = await gateway_ops.nvidia_smi_text(timeout_sec=30.0)
                except (OSError, subprocess.TimeoutExpired) as exc:
                    raise HTTPException(
                        status_code=500, detail=str(exc)
                    ) from exc
                return TaskResponse(
                    mode=body.mode,
                    channel=body.channel,
                    audit_level=audit_level,
                    output={"nvidia_smi": txt[:12000]},
                    meta=meta,
                )

            if act == "vram_json":
                try:
                    raw_csv, gpu_rows = await gateway_ops.nvidia_gpu_memory_csv()
                except (OSError, subprocess.TimeoutExpired) as exc:
                    raise HTTPException(
                        status_code=500, detail=str(exc)
                    ) from exc
                thr_raw = os.environ.get("VAJRA_VRAM_WARN_FREE_MIB", "4096")
                thr_mib = max(512, int(thr_raw))
                adv = gateway_ops.vram_advisory_rows(gpu_rows, warn_below_mib=thr_mib)
                return TaskResponse(
                    mode=body.mode,
                    channel=body.channel,
                    audit_level=audit_level,
                    output={"nvidia_smi_csv": raw_csv, **adv},
                    meta=meta,
                )

            if act == "docker_ps":
                try:
                    lines = await gateway_ops.docker_ps_lines()
                except (OSError, subprocess.TimeoutExpired) as exc:
                    raise HTTPException(
                        status_code=500, detail=str(exc)
                    ) from exc
                return TaskResponse(
                    mode=body.mode,
                    channel=body.channel,
                    audit_level=audit_level,
                    output={"docker_ps": lines[:12000]},
                    meta=meta,
                )

            if act == "docker_start":
                try:
                    res = await gateway_ops.docker_start_allowed(
                        str(raw_ops.get("container", ""))
                    )
                except ValueError as exc:
                    raise HTTPException(status_code=400, detail=str(exc)) from exc
                except (OSError, subprocess.TimeoutExpired) as exc:
                    raise HTTPException(
                        status_code=500, detail=str(exc)
                    ) from exc
                return TaskResponse(
                    mode=body.mode,
                    channel=body.channel,
                    audit_level=audit_level,
                    output={"docker": res},
                    meta=meta,
                )

            if act == "docker_stop":
                try:
                    res = await gateway_ops.docker_stop_allowed(
                        str(raw_ops.get("container", ""))
                    )
                except ValueError as exc:
                    raise HTTPException(status_code=400, detail=str(exc)) from exc
                except (OSError, subprocess.TimeoutExpired) as exc:
                    raise HTTPException(
                        status_code=500, detail=str(exc)
                    ) from exc
                return TaskResponse(
                    mode=body.mode,
                    channel=body.channel,
                    audit_level=audit_level,
                    output={"docker": res},
                    meta=meta,
                )

            raise HTTPException(
                status_code=400,
                detail="unknown ops.action; use snapshot|vram_json|docker_ps|docker_start|docker_stop",
            )

        if body.mode == TaskMode.chat:
            cid = (body.client_request_id or "").strip()
            skip_logic_gate = body.channel == Channel.internal and cid.startswith(
                "summarize-"
            )
            if (
                body.channel in {Channel.web, Channel.telegram}
                and _is_quick_chat_greeting(body.message)
            ):
                return TaskResponse(
                    mode=body.mode,
                    channel=body.channel,
                    audit_level=audit_level,
                    output={"reply": _quick_chat_reply()},
                    meta={**meta, "logic_gate": "chat_quick_reply"},
                )
            q = eps.get("qwen")
            if not q:
                raise HTTPException(status_code=503, detail="qwen endpoint missing")
            if skip_logic_gate:
                chat_messages: list[dict[str, str]] = [
                    {"role": "user", "content": body.message},
                ]
            else:
                chat_messages = [
                    {"role": "system", "content": _CHAT_LOGIC_GATE_SYSTEM},
                    {"role": "user", "content": body.message},
                ]
            text, _ = await _llm_chat_completion(
                http,
                url=q["url"],
                model_id=q["model_id"],
                messages=chat_messages,
                max_tokens=_chat_max_tokens(),
                temperature=0.2,
            )
            meta["logic_gate"] = "off" if skip_logic_gate else "chat_enforced"
            return TaskResponse(
                mode=body.mode,
                channel=body.channel,
                audit_level=audit_level,
                output={"reply": text},
                meta=meta,
            )

        if body.mode == TaskMode.ocr:
            vl = eps.get("qwen_vl")
            if not vl:
                raise HTTPException(status_code=503, detail="qwen_vl endpoint missing")
            prompt = body.message or ""

            if body.images_base64 and len(body.images_base64) > 0:
                nmax = ocr_batch_max_images()
                imgs = body.images_base64[:nmax]
                meta["ocr_batch"] = True
                meta["ocr_batch_requested"] = len(body.images_base64)
                meta["ocr_batch_processed"] = len(imgs)

                async def _one_page(idx: int, b64: str) -> dict[str, Any]:
                    try:
                        raw_b = base64.b64decode(b64, validate=True)
                    except Exception as exc:
                        return {
                            "index": idx,
                            "ok": False,
                            "error": f"invalid base64: {exc}",
                        }
                    try:
                        text = await _ocr_qwen_vl_post(vl, raw_b, prompt)
                        return {"index": idx, "ok": True, "ocr_text": text}
                    except HTTPException as exc:
                        det = exc.detail
                        err = det if isinstance(det, str) else str(det)
                        return {"index": idx, "ok": False, "error": err}

                pages = await asyncio.gather(
                    *[_one_page(i, b64) for i, b64 in enumerate(imgs)]
                )
                merged = "\n\n---\n\n".join(
                    str(p.get("ocr_text", ""))
                    for p in pages
                    if p.get("ok") and p.get("ocr_text")
                )
                return TaskResponse(
                    mode=body.mode,
                    channel=body.channel,
                    audit_level=audit_level,
                    output={
                        "batch": True,
                        "pages": list(pages),
                        "merged_text": merged,
                    },
                    meta=meta,
                )

            if not body.image_base64 or not body.image_base64.strip():
                raise HTTPException(
                    status_code=400,
                    detail="ocr requires image_base64 or images_base64",
                )
            try:
                raw_single = base64.b64decode(body.image_base64, validate=True)
            except Exception as exc:
                raise HTTPException(
                    status_code=400,
                    detail=f"invalid base64: {exc}",
                ) from exc
            text_out = await _ocr_qwen_vl_post(vl, raw_single, prompt)
            return TaskResponse(
                mode=body.mode,
                channel=body.channel,
                audit_level=audit_level,
                output={"batch": False, "ocr_text": text_out},
                meta=meta,
            )

        if body.mode == TaskMode.translate:
            tm_path = translation_memory_db_path()
            tm_key = tm_store.source_key_sha256(body.message)
            if (
                translation_memory_enabled()
                and not body.skip_translation_memory
                and body.message.strip()
            ):
                hit = await tm_store.tm_get(tm_path, tm_key)
                if hit:
                    d_cache, p_cache, um_cache = hit
                    return TaskResponse(
                        mode=body.mode,
                        channel=body.channel,
                        audit_level=audit_level,
                        output={
                            "draft": d_cache,
                            "polished": p_cache,
                            "translation_memory_hit": True,
                        },
                        meta={
                            **meta,
                            "used_monlam": um_cache,
                            "tibetan_glyphs": _count_tibetan_glyphs(body.message),
                            "tibetan_ratio": round(
                                _tibetan_ratio(body.message), 4
                            ),
                        },
                    )

            min_chars, ratio_th = _routing_language_thresholds()
            ratio = _tibetan_ratio(body.message)
            count = _count_tibetan_glyphs(body.message)
            use_monlam = count >= min_chars or ratio >= ratio_th
            meta["tibetan_glyphs"] = count
            meta["tibetan_ratio"] = round(ratio, 4)
            meta["used_monlam"] = use_monlam

            draft = ""
            if use_monlam:
                m = eps.get("monlam")
                if not m:
                    raise HTTPException(status_code=503, detail="monlam endpoint missing")
                draft, _ = await _llm_chat_completion(
                    http,
                    url=m["url"],
                    model_id=m["model_id"],
                    messages=[
                        {
                            "role": "user",
                            "content": f"請將以下藏文譯成通順繁體中文：\n{body.message}",
                        }
                    ],
                    max_tokens=4096,
                    temperature=0.1,
                )
            else:
                q = eps.get("qwen")
                if not q:
                    raise HTTPException(status_code=503, detail="qwen endpoint missing")
                draft, _ = await _llm_chat_completion(
                    http,
                    url=q["url"],
                    model_id=q["model_id"],
                    messages=[
                        {
                            "role": "user",
                            "content": f"請翻譯為繁體中文（非藏文主導則直接翻）：\n{body.message}",
                        }
                    ],
                    max_tokens=4096,
                    temperature=0.2,
                )

            polished = draft
            if use_monlam:
                q = eps.get("qwen")
                if q:
                    polish_prompt = (
                        "以下為藏文經由專用模型初譯之中文稿，請僅作繁體中文通順與佛學用語潤飾，"
                        "勿改變教義與事實；若初譯明顯有誤請輕微修正並加註「潤飾備註」。\n\n"
                        f"{draft}"
                    )
                    polished, _ = await _llm_chat_completion(
                        http,
                        url=q["url"],
                        model_id=q["model_id"],
                        messages=[{"role": "user", "content": polish_prompt}],
                        max_tokens=4096,
                        temperature=0.15,
                    )

            if translation_memory_enabled() and not body.skip_translation_memory:
                try:
                    await tm_store.tm_put(
                        tm_path,
                        tm_key,
                        draft,
                        polished,
                        used_monlam=use_monlam,
                    )
                except Exception as exc:
                    logger.warning("translation memory store failed: %s", exc)

            hermes_tr: dict[str, Any] | None = None
            if hermes_conditional.should_hermes_after_translate(used_monlam=use_monlam):
                hermes_tr = await _hermes_audit_translate_rag_safe(
                    http,
                    eps,
                    original=body.message,
                    draft=polished,
                    audit_level=audit_level,
                    reason="translate",
                )
                meta["hermes_translate_audit"] = True
            else:
                meta["hermes_translate_audit"] = False

            out_tr: dict[str, Any] = {
                "draft": draft,
                "polished": polished,
                "translation_memory_hit": False,
            }
            if hermes_tr is not None:
                out_tr["hermes_audit"] = hermes_tr

            return TaskResponse(
                mode=body.mode,
                channel=body.channel,
                audit_level=audit_level,
                output=out_tr,
                meta=meta,
            )

        if body.mode == TaskMode.deep_think:
            q = eps.get("qwen")
            if not q:
                raise HTTPException(status_code=503, detail="qwen endpoint missing")
            draft, _ = await _llm_chat_completion(
                http,
                url=q["url"],
                model_id=q["model_id"],
                messages=[
                    {
                        "role": "system",
                        "content": "你是佛學與語言助理。請先簡要推理，再給出條理清楚繁體中文結論。",
                    },
                    {"role": "user", "content": body.message},
                ],
                max_tokens=4096,
                temperature=0.3,
            )
            audit = await _hermes_audit(
                http,
                eps,
                original=body.message,
                draft=draft,
                audit_level=audit_level,
            )
            if (
                audit_level == "H1"
                and isinstance(audit, dict)
                and audit.get("approved") is False
            ):
                meta["hermes_review"] = "warning_unapproved_output"
            return TaskResponse(
                mode=body.mode,
                channel=body.channel,
                audit_level=audit_level,
                output={"draft": draft, "audit": audit},
                meta=meta,
            )

        if body.mode == TaskMode.canon_survey:
            if not pg_retrieval.pg_configured():
                raise HTTPException(
                    status_code=503,
                    detail="VAJRA_CANON_PG_DSN required for canon_survey",
                )
            import psycopg
            from canon.query.survey import format_survey_markdown, survey_occurrences

            q = (body.message or "").strip()
            if not q:
                raise HTTPException(status_code=400, detail="message required for canon_survey")
            with psycopg.connect(pg_retrieval.pg_dsn()) as conn:
                report = survey_occurrences(
                    conn,
                    q,
                    page=body.survey_page,
                    page_size=body.survey_page_size,
                )
            answer = format_survey_markdown(
                report,
                cbeta_url_fn=rag_retrieval.canon_id_to_cbeta_reader_url,
            )
            meta["canon_survey"] = {
                "total_hits": report.get("total_hits"),
                "canon_count": report.get("canon_count"),
                "terms_searched": report.get("terms_searched"),
            }
            return TaskResponse(
                mode=body.mode,
                channel=body.channel,
                audit_level=audit_level,
                output={
                    "answer": answer,
                    "survey": report,
                    "similar_sutra_links": [
                        {
                            "label": g["canon_id"],
                            "url": rag_retrieval.canon_id_to_cbeta_reader_url(g["canon_id"]),
                        }
                        for g in (report.get("groups") or [])
                        if rag_retrieval.canon_id_to_cbeta_reader_url(g.get("canon_id", ""))
                    ],
                },
                meta=meta,
            )

        if body.mode == TaskMode.canon_rag:
            qe = eps.get("qwen_embed") or eps.get("nemotron_embed")
            q = eps.get("qwen")
            if not qe or not q:
                raise HTTPException(
                    status_code=503,
                    detail="qwen_embed and qwen required for canon_rag",
                )
            if not pg_retrieval.pg_configured():
                raise HTTPException(
                    status_code=503,
                    detail="VAJRA_CANON_PG_DSN required for canon_rag (方案 B)",
                )

            from canon.query.pipeline import embed_text, plan_query
            from canon.query.preprocess import preprocess_query
            from canon.query.prompt_budget import (
                estimate_tokens,
                llm_input_token_budget,
                truncate_chars,
                truncate_to_token_budget,
            )
            from canon.query.prompts import (
                build_canon_d_hybrid_summary_prompt,
                build_canon_synth_prompt,
                build_canon_synth_prompt_d_class,
                hybrid_summary_system_message,
                synthesizer_system_message,
            )

            _max_msg = int(os.environ.get("VAJRA_MAX_USER_MESSAGE_CHARS", "4096"))
            pq = preprocess_query(truncate_chars(body.message, _max_msg))
            query_plan = plan_query(pq)
            _embed_tok = int(os.environ.get("VAJRA_EMBED_MAX_TOKENS", "2048"))
            embed_input = truncate_to_token_budget(
                embed_text(pq, query_plan),
                _embed_tok,
            )

            try:
                emb = await embeddings_request(
                    http,
                    url=qe["url"],
                    model_id=qe["model_id"],
                    input_text=embed_input,
                    input_type="query",
                )
            except Exception as exc:
                logger.warning("embed failed: %s", exc)
                emb = {"error": str(exc)}

            snippets: list[dict[str, Any]] = []
            pg_err: str | None = None
            cached_answer: str | None = None
            vec: list[float] | None = None
            if isinstance(emb, dict) and "error" not in emb and "data" in emb:
                vec = rag_retrieval.extract_openai_embedding_vector(emb)

            if vec:
                snippets, pg_err, _sub_terms, cached_answer = await pg_retrieval.pg_query_snippets(
                    pq=pq,
                    plan=query_plan,
                    embedding=vec,
                    series=pq.series_hint,
                )

            snippets = rag_retrieval.order_snippets_by_distance(snippets)
            snippets = rag_retrieval.prioritize_scoped_canon_snippets(
                snippets, pq.canon_prefixes
            )
            similar_links = rag_retrieval.extract_similar_sutra_links(snippets)

            answer: str = ""
            synth_prompt: str = ""
            d_hybrid_aspects_body: str | None = None
            synth_use_hybrid_summary = False

            if cached_answer and snippets:
                rag_status = "cache_hit"
                answer = cached_answer
            elif snippets:
                k_prompt = rag_retrieval.rag_top_k()
                for_llm = snippets[:k_prompt]
                from canon.query.extractive_synth import (
                    assemble_hybrid_d_answer,
                    build_d_class_aspects,
                    d_synth_mode,
                    fast_d_class_answer,
                    format_d_aspects_body,
                    parse_hybrid_summary_text,
                    sanitize_hybrid_summary,
                    template_d_summary,
                )

                fast_answer: str | None = None
                if query_plan.query_type == "D":
                    d_mode = d_synth_mode()
                    if d_mode == "extractive":
                        fast_answer = fast_d_class_answer(body.message, for_llm)
                    elif d_mode == "hybrid":
                        aspects = build_d_class_aspects(for_llm)
                        if aspects:
                            d_hybrid_aspects_body = format_d_aspects_body(aspects)
                            synth_prompt = build_canon_d_hybrid_summary_prompt(
                                body.message, d_hybrid_aspects_body
                            )
                            synth_use_hybrid_summary = True
                            rag_status = "pg_hit_hybrid_d"
                    # d_mode == "llm" falls through to full d_class prompt below

                if fast_answer:
                    rag_status = "pg_hit_fast_d"
                    answer = fast_answer
                elif not synth_use_hybrid_summary:
                    if query_plan.query_type == "D":
                        synth_prompt = build_canon_synth_prompt_d_class(
                            body.message, for_llm
                        )
                    else:
                        synth_prompt = build_canon_synth_prompt(body.message, for_llm)
                    rag_status = "pg_hit"
            else:
                synth_prompt = (
                    "使用者問題：\n"
                    f"{body.message}\n\n"
                    "（PostgreSQL 向量庫未返回片段；請保守作答，勿捏造典籍出處。）\n"
                    "請以繁體中文簡答。"
                )
                if pg_err:
                    rag_status = f"pg_miss:{pg_err[:200]}"
                else:
                    rag_status = "pg_empty"

            verbose = os.environ.get("VAJRA_RAG_VERBOSE_JSON", "").strip().lower() in (
                "1",
                "true",
                "yes",
            )

            preview: list[dict[str, Any]] = []
            for i, sn in enumerate(snippets[: rag_retrieval.rag_top_k()]):
                row: dict[str, Any] = {
                    "rank": i + 1,
                    "distance": sn.get("distance"),
                    "preview": sn.get("text", "")[:500],
                }
                if verbose:
                    row["full_text"] = sn.get("text", "")
                    row["metadata"] = sn.get("metadata") or {}
                preview.append(row)

            synth_profile = rag_retrieval.rag_synth_profile(body.message)
            synth_kind = "standard"
            if query_plan.query_type == "D":
                if rag_status == "pg_hit_fast_d":
                    synth_kind = "d_extractive"
                elif rag_status == "pg_hit_hybrid_d":
                    synth_kind = "d_hybrid"
                else:
                    synth_kind = "d_structured"
            meta["rag"] = {
                "backend": "pgvector",
                "query_intent": pq.intent,
                "query_type": query_plan.query_type,
                "series_hint": pq.series_hint,
                "hits": len(snippets),
                "status": rag_status,
                "synthesis": synth_kind,
            }

            if not answer:
                if synth_use_hybrid_summary and d_hybrid_aspects_body:
                    sys_msg = hybrid_summary_system_message()
                    max_tok = 512
                else:
                    sys_msg = synthesizer_system_message(query_type=query_plan.query_type)
                    max_tok = 1024 if query_plan.query_type == "D" else 2048
                synth_temp = rag_retrieval.rag_synth_temperature(synth_profile)
                _budget = llm_input_token_budget(reserve_output=max_tok)
                _sys_tok = estimate_tokens(sys_msg)
                synth_prompt = truncate_to_token_budget(
                    synth_prompt,
                    max(256, _budget - _sys_tok),
                )
                llm_summary, _ = await _llm_chat_completion(
                    http,
                    url=q["url"],
                    model_id=q["model_id"],
                    messages=[
                        {"role": "system", "content": sys_msg},
                        {"role": "user", "content": synth_prompt},
                    ],
                    max_tokens=max_tok,
                    temperature=synth_temp,
                    extra_body={"chat_template_kwargs": {"enable_thinking": False}},
                )
                if synth_use_hybrid_summary and d_hybrid_aspects_body:
                    summary = sanitize_hybrid_summary(
                        parse_hybrid_summary_text(llm_summary),
                        d_hybrid_aspects_body,
                    )
                    if not summary.strip():
                        summary = template_d_summary(body.message, d_hybrid_aspects_body)
                    answer = assemble_hybrid_d_answer(d_hybrid_aspects_body, summary)
                else:
                    answer = llm_summary

            if vec and snippets and rag_status in (
                "pg_hit",
                "pg_hit_fast_d",
                "pg_hit_hybrid_d",
            ):
                await asyncio.to_thread(
                    pg_retrieval.store_answer_cache,
                    pq=pq,
                    embedding=vec,
                    snippets=snippets[: rag_retrieval.rag_top_k()],
                    answer=answer,
                )

            from canon.query.display_sanitize import sanitize_display_markdown

            answer = sanitize_display_markdown(answer)

            out: dict[str, Any] = {
                "embedding_response": emb if verbose else {},
                "answer": answer,
                "retrieval_preview": preview,
                "similar_sutra_links": similar_links,
            }

            _teaser_mode = os.environ.get("VAJRA_RAG_SURVEY_TEASER", "doctrine").strip().lower()
            from canon.query.survey import survey_teaser_enabled

            teaser_on = survey_teaser_enabled(
                _teaser_mode,
                query_type=str(query_plan.query_type or ""),
            )
            if teaser_on and snippets and rag_status in (
                "pg_hit",
                "pg_hit_fast_d",
                "pg_hit_hybrid_d",
                "cache_hit",
            ):
                from canon.query.survey import (
                    format_survey_teaser,
                    primary_survey_keyword,
                    survey_occurrences,
                )

                survey_kw = primary_survey_keyword(body.message)
                if survey_kw:
                    import psycopg

                    teaser_page_size = int(os.environ.get("VAJRA_SURVEY_TEASER_CANONS", "5")) + 5

                    def _teaser_sync() -> dict[str, Any]:
                        with psycopg.connect(pg_retrieval.pg_dsn()) as conn:
                            return survey_occurrences(
                                conn,
                                survey_kw,
                                page=1,
                                page_size=teaser_page_size,
                            )

                    try:
                        teaser_report = await asyncio.to_thread(_teaser_sync)
                        teaser = format_survey_teaser(
                            teaser_report,
                            cbeta_url_fn=rag_retrieval.canon_id_to_cbeta_reader_url,
                        )
                        if teaser:
                            out["survey_teaser"] = teaser
                            out["survey_keyword"] = survey_kw
                            meta["survey_teaser"] = {
                                "keyword": survey_kw,
                                "total_canon_count": teaser_report.get("total_canon_count"),
                            }
                    except Exception as exc:
                        logger.warning("survey teaser failed: %s", exc)

            if not verbose and isinstance(emb, dict):
                slim = dict(emb)
                data = slim.get("data")
                if isinstance(data, list) and data:
                    dims = []
                    try:
                        e0 = data[0].get("embedding") if isinstance(data[0], dict) else None
                        if isinstance(e0, list):
                            dims.append(len(e0))
                    except (AttributeError, TypeError, KeyError):
                        pass
                    out["embedding_response"] = {
                        "summary": {"vectors": len(data), "dims": dims},
                    }
                elif "error" in slim:
                    out["embedding_response"] = {"error": slim.get("error")}

            hermes_cr: dict[str, Any] | None = None
            if hermes_conditional.should_hermes_after_canon_rag(rag_hits=len(snippets)):
                hermes_cr = await _hermes_audit_translate_rag_safe(
                    http,
                    eps,
                    original=body.message,
                    draft=answer,
                    audit_level=audit_level,
                    reason="canon_rag",
                )
                out["hermes_audit"] = hermes_cr
                meta["hermes_canon_audit"] = True
            else:
                meta["hermes_canon_audit"] = False

            return TaskResponse(
                mode=body.mode,
                channel=body.channel,
                audit_level=audit_level,
                output=out,
                meta=meta,
            )

        raise HTTPException(status_code=400, detail="unsupported mode")

    return app


app = create_app()


def get_app() -> FastAPI:
    return app
