"""Fast extractive synthesis for D-class (skip LLM when snippets have coords)."""

from __future__ import annotations

import os
import re
from typing import Any

_ASPECT_LABELS: dict[str, str] = {
    "T01": "阿含／長部",
    "T02": "阿含經",
    "T03": "般若部",
    "T06": "般若部",
    "T08": "般若部",
    "T09": "大乘論疏",
    "T12": "淨土／華嚴",
    "T14": "密教",
    "T16": "論藏",
    "T24": "律藏",
    "T48": "禪宗",
}

_SENT_SPLIT = re.compile(r"(?<=[。；！？])")


def use_fast_d_synth() -> bool:
    return os.environ.get("VAJRA_RAG_FAST_D_SYNTH", "1").strip().lower() not in (
        "0",
        "false",
        "no",
        "off",
    )


def _coord_ref(sn: dict[str, Any]) -> str | None:
    meta = sn.get("metadata") or {}
    coord = meta.get("coord_start") or meta.get("coord") or ""
    if not coord:
        return None
    inner = str(coord).strip().strip("【】")
    return f"【{inner}】"


def _aspect_label(sn: dict[str, Any], index: int) -> str:
    canon = str((sn.get("metadata") or {}).get("canon_id") or sn.get("canon_id") or "")
    cid = canon.upper()
    if len(cid) >= 3 and cid.startswith("T"):
        vol = cid[:3]
        if vol in _ASPECT_LABELS:
            return _ASPECT_LABELS[vol]
    return f"義理面向{index}"


def _excerpt(text: str, *, max_chars: int = 180) -> str:
    raw = re.sub(r"\s+", "", (text or "").strip())
    if not raw:
        return ""
    parts = [p for p in _SENT_SPLIT.split(raw) if p.strip()]
    if parts:
        out = ""
        for part in parts:
            if len(out) + len(part) > max_chars:
                break
            out += part
        if out:
            return out
    return raw[:max_chars] + ("…" if len(raw) > max_chars else "")


def fast_d_class_answer(
    user_message: str,
    snippets: list[dict[str, Any]],
    *,
    max_aspects: int = 4,
) -> str | None:
    """Build structured D-class answer from retrieval snippets (no LLM)."""
    if not snippets:
        return None

    aspects: list[str] = []
    seen_canon: set[str] = set()
    for sn in snippets:
        ref = _coord_ref(sn)
        if not ref:
            continue
        canon = str((sn.get("metadata") or {}).get("canon_id") or sn.get("canon_id") or "")
        key = canon.upper() or ref
        if key in seen_canon:
            continue
        seen_canon.add(key)
        excerpt = _excerpt(str(sn.get("text") or ""))
        if not excerpt:
            continue
        label = _aspect_label(sn, len(aspects) + 1)
        aspects.append(f"{len(aspects) + 1}. 【{label}】{excerpt}{ref}")
        if len(aspects) >= max_aspects:
            break

    if len(aspects) < 2:
        return None

    q = user_message.strip().rstrip("？?")
    summary_bits = [a.split("】", 1)[-1][:60] for a in aspects[:3]]
    summary = (
        f"依檢索段落，「{q}」可從以下經典面向理解："
        + "；".join(summary_bits)
        + "。以下各點均附 CBETA 坐標，供進一步查閱。"
    )
    body = "【義理面向】\n" + "\n".join(aspects)
    body += f"\n\n【綜合回答】\n{summary}"
    return body
