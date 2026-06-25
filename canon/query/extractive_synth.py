"""Fast extractive synthesis for D-class (skip LLM when snippets have coords)."""

from __future__ import annotations

import os
import re
from typing import Any

from canon.query.display_sanitize import sanitize_display_markdown

# Scholar-facing labels: canon_id -> display (override vol defaults)
_KNOWN_SUTRA_LABELS: dict[str, str] = {
    "T01N0001": "長阿含 T1",
    "T02N0099": "雜阿含 T99",
    "T02N0125": "增一阿含 T125",
    "T02N0147": "雜阿含 T147",
    "T08N0235": "金剛般若 T235",
}

_VOL_SERIES: dict[str, str] = {
    "T01": "長阿含",
    "T02": "阿含部",
    "T03": "本緣部",
    "T06": "般若部",
    "T07": "般若部",
    "T08": "般若部",
    "T09": "般若部",
    "T11": "華嚴部",
    "T12": "華嚴／淨土",
    "T14": "密教",
    "T16": "論藏",
    "T24": "律藏",
    "T25": "論藏",
    "T26": "論藏",
    "T30": "論藏",
    "T33": "論疏",
    "T34": "論疏",
    "T36": "禪／密",
    "T41": "論疏",
    "T43": "論疏",
    "T44": "論疏",
    "T48": "禪宗",
}

_SENT_SPLIT = re.compile(r"(?<=[。；！？])")
_CBETA_NOTE_RE = re.compile(r"\[\d+\]")
_HTML_RE = re.compile(r"<[^>]+>")
_COORD_CITE_RE = re.compile(r"【([A-Z]{1,3}\d+n\d+_[^】]+)】", re.I)


def d_synth_mode() -> str:
    """D-class synthesis: hybrid | extractive | llm."""
    mode = os.environ.get("VAJRA_RAG_D_SYNTH", "").strip().lower()
    if mode in ("hybrid", "extractive", "llm"):
        return mode
    if mode in ("full", "structured"):
        return "llm"
    if mode in ("fast",):
        return "extractive"
    # Legacy VAJRA_RAG_FAST_D_SYNTH
    fast = os.environ.get("VAJRA_RAG_FAST_D_SYNTH", "").strip().lower()
    if fast in ("0", "false", "no", "off"):
        return "llm"
    if fast in ("1", "true", "yes", "on"):
        return "extractive"
    return "hybrid"


def use_fast_d_synth() -> bool:
    return d_synth_mode() == "extractive"


def _clean_snippet_text(text: str) -> str:
    raw = (text or "").strip()
    raw = _HTML_RE.sub("", raw)
    raw = _CBETA_NOTE_RE.sub("", raw)
    return re.sub(r"\s+", "", raw)


def _trim_at_boundary(text: str, *, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text
    window = text[:max_chars]
    for sep in ("。", "；", "！", "？", "，"):
        idx = window.rfind(sep)
        if idx >= max(40, int(max_chars * 0.45)):
            return window[: idx + 1]
    trimmed = window.rstrip("，、；")
    return trimmed + "…" if trimmed else text[:max_chars] + "…"


def _polish_excerpt(excerpt: str) -> str:
    """Drop a trailing fragment after the last complete clause."""
    if not excerpt or excerpt.endswith(("。", "；", "！", "？", "…")):
        return excerpt
    for sep in ("。", "；", "！", "？"):
        idx = excerpt.rfind(sep)
        if idx >= max(20, len(excerpt) // 4):
            return excerpt[: idx + 1]
    if len(excerpt) > 8:
        return excerpt + "…"
    return excerpt


def _excerpt(text: str, *, max_chars: int = 260) -> str:
    raw = _clean_snippet_text(text)
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
            if len(out) < len(raw):
                if not out.endswith(("。", "；", "！", "？")):
                    return _trim_at_boundary(out, max_chars=max_chars)
                return out + "…"
            return out
    return _trim_at_boundary(raw, max_chars=max_chars)


def _excerpt_polished(text: str, *, max_chars: int = 260) -> str:
    return _polish_excerpt(_excerpt(text, max_chars=max_chars))


def _coord_ref(sn: dict[str, Any]) -> str | None:
    meta = sn.get("metadata") or {}
    coord = meta.get("coord_start") or meta.get("coord") or ""
    if not coord:
        return None
    inner = str(coord).strip().strip("【】")
    return f"【{inner}】"


def scholar_canon_label(canon_id: str, *, fallback_index: int = 0) -> str:
    """Scholar label e.g. 雜阿含 T99 from T02n0099."""
    cid = (canon_id or "").upper().strip()
    if cid in _KNOWN_SUTRA_LABELS:
        return _KNOWN_SUTRA_LABELS[cid]
    m = re.match(r"^(T\d+)N(\d+)$", cid)
    if m:
        vol, num = m.group(1), m.group(2)
        series = _VOL_SERIES.get(vol, vol)
        return f"{series} T{int(num)}"
    if fallback_index:
        return f"義理面向{fallback_index}"
    return cid or "未知經"


def _aspect_label(sn: dict[str, Any], index: int) -> str:
    canon = str((sn.get("metadata") or {}).get("canon_id") or sn.get("canon_id") or "")
    if canon:
        return scholar_canon_label(canon, fallback_index=index)
    return f"義理面向{index}"


def _aspect_summary_label(aspect_line: str) -> str:
    m = re.match(r"\d+\.\s*【([^】]+)】", aspect_line)
    return m.group(1) if m else "相關面向"


def _normalize_coord_key(coord: str) -> str:
    c = coord.strip().strip("【】").rstrip("_")
    return f"{c}_".upper()


def _allowed_coords_from_aspects(aspects_body: str) -> set[str]:
    return {_normalize_coord_key(m.group(1)) for m in _COORD_CITE_RE.finditer(aspects_body or "")}


def build_d_class_aspects(
    snippets: list[dict[str, Any]],
    *,
    max_aspects: int = 4,
) -> list[str] | None:
    """Extractive aspect bullets with CBETA coords (no summary)."""
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
        excerpt = _excerpt_polished(str(sn.get("text") or ""))
        if not excerpt:
            continue
        label = _aspect_label(sn, len(aspects) + 1)
        aspects.append(f"{len(aspects) + 1}. 【{label}】{excerpt}{ref}")
        if len(aspects) >= max_aspects:
            break

    if len(aspects) < 2:
        return None
    return aspects


def format_d_aspects_body(aspects: list[str]) -> str:
    return "【義理面向】\n" + "\n".join(aspects)


def _build_summary(user_message: str, aspects: list[str]) -> str:
    q = user_message.strip().rstrip("？?") or "此問題"
    labels: list[str] = []
    for line in aspects:
        label = _aspect_summary_label(line)
        if label not in labels:
            labels.append(label)
    label_txt = "、".join(labels[:4])
    n = len(aspects)
    return (
        f"依檢索語料，「{q}」可從 {label_txt} 等 {n} 個面向摘錄原典段落（見上列坐標）。"
        f"以下均附 CBETA 坐標與連結，供進一步查閱。"
    )


def parse_hybrid_summary_text(llm_out: str) -> str:
    """Keep only the 綜合回答 body from LLM output."""
    text = (llm_out or "").strip()
    if "【綜合回答】" in text:
        text = text.split("【綜合回答】", 1)[1].strip()
    if "【義理面向】" in text:
        text = text.split("【義理面向】", 1)[0].strip()
    return text.strip()


def sanitize_hybrid_summary(summary: str, aspects_body: str) -> str:
    """Drop coordinate cites in summary that were not in the extractive aspects."""
    allowed = _allowed_coords_from_aspects(aspects_body)
    if not allowed:
        return _COORD_CITE_RE.sub("", summary or "")

    def repl(match: re.Match[str]) -> str:
        key = _normalize_coord_key(match.group(1))
        return match.group(0) if key in allowed else ""

    return sanitize_display_markdown(_COORD_CITE_RE.sub(repl, summary or ""))


def template_d_summary(user_message: str, aspects_body: str) -> str:
    lines = [ln.strip() for ln in (aspects_body or "").splitlines() if re.match(r"^\d+\.", ln.strip())]
    return _build_summary(user_message, lines)


def assemble_hybrid_d_answer(aspects_body: str, summary: str) -> str:
    body = f"{aspects_body}\n\n【綜合回答】\n{summary.strip()}"
    return sanitize_display_markdown(body)


def fast_d_class_answer(
    user_message: str,
    snippets: list[dict[str, Any]],
    *,
    max_aspects: int = 4,
) -> str | None:
    """Build structured D-class answer from retrieval snippets (no LLM)."""
    aspects = build_d_class_aspects(snippets, max_aspects=max_aspects)
    if not aspects:
        return None
    body = format_d_aspects_body(aspects)
    body += f"\n\n【綜合回答】\n{_build_summary(user_message, aspects)}"
    return body
