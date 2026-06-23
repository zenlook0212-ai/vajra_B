"""Load `models.yaml` and optional policy YAML paths from environment."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml

_REPO_ROOT = Path(__file__).resolve().parent.parent


def _default_models_path() -> Path:
    return Path(os.environ.get("VAJRA_MODELS_YAML", str(_REPO_ROOT / "models.yaml")))


def load_models_yaml(path: Path | None = None) -> dict[str, Any]:
    """Load endpoints config; raises FileNotFoundError if missing."""
    p = path or _default_models_path()
    raw = p.read_text(encoding="utf-8")
    data = yaml.safe_load(raw)
    if not isinstance(data, dict) or "endpoints" not in data:
        raise ValueError("models.yaml must contain top-level 'endpoints' mapping")
    endpoints = data["endpoints"]
    if not isinstance(endpoints, dict):
        raise ValueError("models.yaml 'endpoints' must be a mapping")
    for name, spec in endpoints.items():
        if not isinstance(spec, dict) or "url" not in spec or "model_id" not in spec:
            raise ValueError(f"endpoint {name!r} needs url + model_id")
    return data


def routing_yaml_path() -> Path:
    return Path(os.environ.get("VAJRA_ROUTING_YAML", str(_REPO_ROOT / "config" / "routing.yaml")))


def audit_policy_yaml_path() -> Path:
    return Path(
        os.environ.get("VAJRA_AUDIT_YAML", str(_REPO_ROOT / "config" / "audit_policy.yaml"))
    )


def translation_memory_db_path() -> Path:
    return Path(
        os.environ.get(
            "VAJRA_TM_DB",
            str(_REPO_ROOT / "data" / "translation_memory.sqlite"),
        )
    )


def translation_memory_enabled() -> bool:
    return os.environ.get("VAJRA_TRANSLATION_MEMORY", "1").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


def ocr_batch_max_images() -> int:
    try:
        return max(1, min(48, int(os.environ.get("VAJRA_OCR_BATCH_MAX", "16"))))
    except ValueError:
        return 16


def vllm_chat_timeout_sec() -> float:
    """OpenAI-compat chat/completions HTTP read timeout (whole request)."""
    try:
        v = float(os.environ.get("VAJRA_VLLM_CHAT_TIMEOUT_SEC", "180"))
        return max(30.0, min(900.0, v))
    except ValueError:
        return 180.0


def vllm_embed_timeout_sec() -> float:
    try:
        v = float(os.environ.get("VAJRA_VLLM_EMBED_TIMEOUT_SEC", "120"))
        return max(15.0, min(600.0, v))
    except ValueError:
        return 120.0
