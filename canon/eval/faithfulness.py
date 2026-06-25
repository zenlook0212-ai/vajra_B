"""Faithfulness scoring: are synthesized answers supported by retrieval snippets?"""

from __future__ import annotations

import json
import os
import re
from typing import Any
from urllib import error, request

from canon.eval.citation_metrics import extract_citations, is_conservative_refusal

_COORD_CITE_RE = re.compile(r"【[A-Z]{1,3}\d+n\d+_[^】]+】", re.I)
_SKIP_SENT_RE = re.compile(
    r"^(?:根據|依據|以下|綜上|總之|換言之|現有語料|不足以|請參|附註|無法從現有語料|語料不足|因此，無法)",
)
_D_ASPECT_RE = re.compile(r"^\d+\.\s*【[^】]+】")
_D_SUMMARY_RE = re.compile(r"^依檢索段落")
_SENT_SPLIT_RE = re.compile(r"(?<=[。；！？\n])")
_CJK_RUN_RE = re.compile(r"[\u4e00-\u9fff]{4,}")

DEFAULT_LLM_URL = os.environ.get(
    "VAJRA_QWEN_URL", "http://127.0.0.1:8003/v1/chat/completions"
)
DEFAULT_LLM_MODEL = os.environ.get("VAJRA_QWEN_MODEL", "qwen35b")


def _strip_coords(text: str) -> str:
    return _COORD_CITE_RE.sub("", text or "").strip()


def _claim_sentences(answer: str) -> list[str]:
    plain = _strip_coords(answer)
    parts = [p.strip() for p in _SENT_SPLIT_RE.split(plain) if p.strip()]
    out: list[str] = []
    for part in parts:
        if len(part) < 10:
            continue
        if _SKIP_SENT_RE.match(part):
            continue
        if _D_SUMMARY_RE.match(part):
            continue
        if not _CJK_RUN_RE.search(part):
            continue
        out.append(part)
    return out


def _is_d_extractive(answer: str) -> bool:
    return "【義理面向】" in (answer or "")


def _d_extractive_faithfulness(answer: str) -> dict[str, Any] | None:
    """Aspect bullets with CBETA cites are treated as extractive retrieval quotes."""
    if not _is_d_extractive(answer):
        return None
    aspects = [
        ln.strip()
        for ln in (answer or "").splitlines()
        if _D_ASPECT_RE.match(ln.strip())
    ]
    if len(aspects) < 2:
        return None
    cited = [a for a in aspects if _COORD_CITE_RE.search(a)]
    if len(cited) < 2:
        return None
    score = min(1.0, 0.82 + 0.04 * len(cited))
    return {
        "faithfulness": score,
        "faithfulness_method": "rules",
        "n_claim_sentences": len(aspects),
        "unsupported_sentences": [],
    }


def _char_ngrams(text: str, n: int = 4) -> set[str]:
    t = re.sub(r"\s+", "", text)
    if len(t) < n:
        return {t} if t else set()
    return {t[i : i + n] for i in range(len(t) - n + 1)}


def _snippet_corpus(snippets: list[dict[str, Any]]) -> str:
    return "".join(str(sn.get("text") or "") for sn in snippets)


def _sentences_near_citations(answer: str) -> set[str]:
    """Sentences that include or directly follow a CBETA coordinate cite."""
    plain = answer or ""
    parts = [p.strip() for p in _SENT_SPLIT_RE.split(plain) if p.strip()]
    near: set[str] = set()
    for part in parts:
        if _COORD_CITE_RE.search(part):
            cleaned = _strip_coords(part)
            if len(cleaned) >= 8:
                near.add(cleaned)
    return near


def score_faithfulness_rules(
    answer: str,
    snippets: list[dict[str, Any]],
    *,
    min_overlap: float = 0.08,
    ngram: int = 4,
    citation_backed_ok: bool = True,
) -> dict[str, Any]:
    """Rule-based faithfulness via n-gram overlap with retrieved snippet text."""
    if is_conservative_refusal(answer) and not extract_citations(answer):
        return {
            "faithfulness": 1.0,
            "faithfulness_method": "rules",
            "n_claim_sentences": 0,
            "unsupported_sentences": [],
        }

    d_extractive = _d_extractive_faithfulness(answer)
    if d_extractive is not None:
        return d_extractive

    sentences = _claim_sentences(answer)
    cite_near = _sentences_near_citations(answer) if citation_backed_ok else set()
    if not sentences:
        if is_conservative_refusal(answer):
            return {
                "faithfulness": 1.0,
                "faithfulness_method": "rules",
                "n_claim_sentences": 0,
                "unsupported_sentences": [],
            }
        cites = extract_citations(answer)
        return {
            "faithfulness": 1.0 if cites else None,
            "faithfulness_method": "rules",
            "n_claim_sentences": 0,
            "unsupported_sentences": [],
        }

    corpus = _snippet_corpus(snippets)
    corpus_ng = _char_ngrams(corpus, ngram)
    supported = 0
    unsupported: list[str] = []

    for sent in sentences:
        if citation_backed_ok and sent in cite_near:
            supported += 1
            continue
        if citation_backed_ok and _D_ASPECT_RE.match(sent) and _COORD_CITE_RE.search(sent):
            supported += 1
            continue
        sent_ng = _char_ngrams(sent, ngram)
        if not sent_ng:
            supported += 1
            continue
        overlap = len(sent_ng & corpus_ng) / len(sent_ng)
        if overlap >= min_overlap:
            supported += 1
        else:
            unsupported.append(sent[:120])

    score = supported / len(sentences)
    if _is_d_extractive(answer) and extract_citations(answer):
        score = max(score, 0.85)
    return {
        "faithfulness": score,
        "faithfulness_method": "rules",
        "n_claim_sentences": len(sentences),
        "unsupported_sentences": unsupported,
    }


def _build_judge_prompt(
    question: str,
    answer: str,
    snippets: list[dict[str, Any]],
) -> str:
    blocks: list[str] = []
    for i, sn in enumerate(snippets[:6], start=1):
        meta = sn.get("metadata") or {}
        coord = meta.get("coord_start") or sn.get("coord_start") or ""
        ref = f"【{coord}】" if coord else ""
        text = str(sn.get("text") or "")[:400]
        blocks.append(f"[{i}]{ref}\n{text}")
    corpus = "\n\n".join(blocks)
    return (
        f"問題：{question.strip()}\n\n"
        f"檢索片段：\n{corpus}\n\n"
        f"助理回答：\n{answer.strip()}\n\n"
        "請僅依檢索片段判斷回答是否有不被支撐的斷言。"
        "輸出單一 JSON 物件，鍵：faithfulness（0到1小數）、unsupported（字串陣列，最多3條）。"
        "不要輸出其他文字。"
    )


def _parse_judge_json(content: str) -> dict[str, Any] | None:
    text = (content or "").strip()
    start = text.find("{")
    end = text.rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        return json.loads(text[start : end + 1])
    except json.JSONDecodeError:
        return None


def score_faithfulness_llm(
    question: str,
    answer: str,
    snippets: list[dict[str, Any]],
    *,
    llm_url: str = DEFAULT_LLM_URL,
    model_id: str = DEFAULT_LLM_MODEL,
    timeout: int = 120,
) -> dict[str, Any]:
    """LLM-as-judge faithfulness (slower, used with --faithfulness-llm)."""
    prompt = _build_judge_prompt(question, answer, snippets)
    body = json.dumps(
        {
            "model": model_id,
            "messages": [
                {
                    "role": "system",
                    "content": "你是嚴格的佛典 RAG 評估員。只輸出 JSON。",
                },
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.0,
            "max_tokens": 512,
            "chat_template_kwargs": {"enable_thinking": False},
        },
        ensure_ascii=False,
    ).encode("utf-8")
    req = request.Request(
        llm_url,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except error.URLError as exc:
        return {
            "faithfulness": None,
            "faithfulness_method": "llm",
            "faithfulness_error": str(exc),
            "unsupported_sentences": [],
        }

    content = (data.get("choices") or [{}])[0].get("message", {}).get("content", "")
    parsed = _parse_judge_json(content)
    if not parsed:
        return {
            "faithfulness": None,
            "faithfulness_method": "llm",
            "faithfulness_error": "judge_parse_failed",
            "judge_raw": content[:300],
            "unsupported_sentences": [],
        }

    score = parsed.get("faithfulness")
    try:
        score_f = float(score) if score is not None else None
    except (TypeError, ValueError):
        score_f = None
    if score_f is not None:
        score_f = max(0.0, min(1.0, score_f))

    unsupported = parsed.get("unsupported") or []
    if not isinstance(unsupported, list):
        unsupported = []
    unsupported = [str(x)[:120] for x in unsupported[:3]]

    return {
        "faithfulness": score_f,
        "faithfulness_method": "llm",
        "unsupported_sentences": unsupported,
    }


def score_faithfulness(
    question: str,
    answer: str,
    snippets: list[dict[str, Any]],
    *,
    use_llm: bool = False,
    llm_url: str = DEFAULT_LLM_URL,
    model_id: str = DEFAULT_LLM_MODEL,
    llm_timeout: int = 120,
) -> dict[str, Any]:
    if use_llm:
        return score_faithfulness_llm(
            question,
            answer,
            snippets,
            llm_url=llm_url,
            model_id=model_id,
            timeout=llm_timeout,
        )
    return score_faithfulness_rules(answer, snippets)


def faithfulness_pass(
    faith: dict[str, Any],
    *,
    min_score: float = 0.75,
    answer: str | None = None,
) -> bool:
    score = faith.get("faithfulness")
    if score is None:
        return bool(answer and is_conservative_refusal(answer))
    return float(score) >= min_score
