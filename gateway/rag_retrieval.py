"""Optional Chroma HTTP retrieval for ``canon_rag`` (embedding → similar chunks).

Supports Chroma **v2** REST (`/api/v2/tenants/.../databases/.../collections`, default for
``chromadb/chroma:latest``). Legacy **v1** base URL ending with ``/api/v1`` is retained for old
deployments only (often returns HTTP 410 on current images).
"""

from __future__ import annotations

import logging
import os
import re
from typing import Any

import httpx

logger = logging.getLogger(__name__)

_UUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    re.I,
)

_TIBETAN_HINT_RE = re.compile(r"[\u0F00-\u0FFF]")
_CANON_ID_RE = re.compile(r"\b([A-Z]{1,3}\d+n\d+[a-zA-Z]?)\b", re.I)


def extract_openai_embedding_vector(resp: dict[str, Any]) -> list[float] | None:
    """Parse vLLM/OpenAI-style ``/v1/embeddings`` JSON → first vector."""
    data = resp.get("data")
    if not isinstance(data, list) or not data:
        return None
    item = data[0]
    if not isinstance(item, dict):
        return None
    emb = item.get("embedding")
    if not isinstance(emb, list) or not emb:
        return None
    if not isinstance(emb[0], (int, float)):
        return None
    return [float(x) for x in emb]


def chroma_api_configured() -> bool:
    """True when operator set ``VAJRA_CHROMA_API_ROOT`` (any supported form)."""
    return bool(os.environ.get("VAJRA_CHROMA_API_ROOT", "").strip())


def chroma_collections_base() -> tuple[str | None, str]:
    """
    Resolve the URL prefix whose children are ``/collections`` and
    ``/collections/{id}/query``.

    * v2 (default): ``http://host:8040`` → adds
      ``/api/v2/tenants/{tenant}/databases/{database}``.
    * v2 explicit: URL already containing ``/tenants/`` and ``/databases``.
    * v1 legacy: suffix ``/api/v1``.
    """
    raw_in = os.environ.get("VAJRA_CHROMA_API_ROOT", "").strip().rstrip("/")
    if not raw_in:
        return None, "v2"

    if raw_in.endswith("/api/v1"):
        logger.warning(
            "Chroma v1 API base detected; upstream images often return 410. "
            "Prefer http://host:port (v2 auto) or a full /api/v2/tenants/... path."
        )
        return raw_in, "v1"

    if "/tenants/" in raw_in and "/databases/" in raw_in:
        return raw_in, "v2"

    base = raw_in[:-8].rstrip("/") if raw_in.endswith("/api/v2") else raw_in
    tenant = os.environ.get("VAJRA_CHROMA_TENANT", "default_tenant").strip()
    database = os.environ.get("VAJRA_CHROMA_DATABASE", "default_database").strip()
    return f"{base}/api/v2/tenants/{tenant}/databases/{database}", "v2"


def chroma_api_root() -> str | None:
    """Resolved collections REST prefix (compatible with older call sites)."""
    url, _ = chroma_collections_base()
    return url


def chroma_collection_name() -> str:
    return os.environ.get("VAJRA_CHROMA_COLLECTION", "canon").strip() or "canon"


def rag_top_k() -> int:
    try:
        return max(1, min(32, int(os.environ.get("VAJRA_RAG_TOP_K", "8"))))
    except ValueError:
        return 8


def _looks_like_uuid(s: str) -> bool:
    return bool(_UUID_RE.match(s.strip()))


def _collections_iter(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [x for x in payload if isinstance(x, dict)]
    if isinstance(payload, dict):
        inner = payload.get("collections") or payload.get("data") or []
        if isinstance(inner, list):
            return [x for x in inner if isinstance(x, dict)]
    return []


async def chroma_resolve_collection_id(
    client: httpx.AsyncClient,
    collections_base: str,
    name_or_id: str,
    *,
    timeout_sec: float = 20.0,
) -> str:
    """Return Chroma ``collection_id`` (UUID); accept raw UUID or match by ``name``."""
    cand = name_or_id.strip()
    base = collections_base.rstrip("/")
    if _looks_like_uuid(cand):
        return cand
    url = f"{base}/collections"
    r = await client.get(url, timeout=timeout_sec)

    try:
        r.raise_for_status()
    except httpx.HTTPStatusError as exc:
        if exc.response is not None and exc.response.status_code == 410:
            raise ValueError(
                "Chroma returned HTTP 410 (v1 API removed). "
                "Set VAJRA_CHROMA_API_ROOT to http://127.0.0.1:8040 "
                "(v2 auto) or a full /api/v2/tenants/.../databases/... URL."
            ) from exc
        raise

    for c in _collections_iter(r.json()):
        nid = str(c.get("id", "") or "")
        nm = str(c.get("name", "") or "")
        if nm == cand or nid == cand:
            if nid:
                return nid
    raise ValueError(f"Chroma collection {cand!r} not found under {url}")


async def chroma_query_snippets(
    client: httpx.AsyncClient,
    *,
    embedding: list[float],
    api_root: str | None = None,
    collection: str | None = None,
    n_results: int | None = None,
    timeout_sec: float = 45.0,
) -> tuple[list[dict[str, Any]], str | None]:
    """
    Query Chroma over REST.

    Returns (snippets, error_message). On success error_message is None.
    Each snippet: ``text``, optional ``distance``, optional ``metadata``.
    """
    explicit = (api_root or "").strip().rstrip("/") if api_root else None
    if explicit:
        collections_base = explicit
    else:
        collections_base, _kind = chroma_collections_base()

    if not collections_base:
        return [], "VAJRA_CHROMA_API_ROOT not set"

    coll = collection or chroma_collection_name()
    k = int(n_results) if n_results is not None else rag_top_k()

    try:
        cid = await chroma_resolve_collection_id(client, collections_base, coll)
        body: dict[str, Any] = {
            "query_embeddings": [embedding],
            "n_results": k,
            "include": ["documents", "metadatas", "distances"],
        }
        qr = await client.post(
            f"{collections_base.rstrip('/')}/collections/{cid}/query",
            params={"limit": max(k, 1), "offset": 0},
            json=body,
            timeout=timeout_sec,
        )
        qr.raise_for_status()
        out = qr.json()
    except (ValueError, httpx.HTTPError, TypeError, KeyError) as exc:
        logger.warning("Chroma retrieval failed: %s", exc)
        return [], str(exc)

    docs_outer = out.get("documents") or []
    docs = docs_outer[0] if docs_outer else []
    dist_outer = out.get("distances") or []
    dists = dist_outer[0] if dist_outer else []
    meta_outer = out.get("metadatas") or []
    metas = meta_outer[0] if meta_outer else []

    snippets: list[dict[str, Any]] = []
    if not isinstance(docs, list):
        return snippets, None
    for i, raw_t in enumerate(docs):
        if raw_t is None:
            continue
        text = str(raw_t).strip()
        if not text:
            continue
        dist_val = None
        if isinstance(dists, list) and i < len(dists):
            try:
                dist_val = float(dists[i])
            except (TypeError, ValueError):
                dist_val = None
        meta_row: dict[str, Any] = {}
        if isinstance(metas, list) and i < len(metas) and isinstance(metas[i], dict):
            meta_row = dict(metas[i])
        snippets.append({"text": text, "distance": dist_val, "metadata": meta_row})
    return snippets, None


def rag_diffusion_enabled() -> bool:
    """Second-pass embedding on snippet-derived seed (semantic diffusion)."""
    return os.environ.get("VAJRA_RAG_DIFFUSION", "1").strip().lower() not in (
        "0",
        "false",
        "no",
        "off",
    )


def diffusion_seed_text(
    snippets: list[dict[str, Any]],
    *,
    max_chars: int = 480,
) -> str:
    """Pack top snippet texts into a short string for a second embedding query."""
    parts: list[str] = []
    for sn in snippets[:4]:
        t = str(sn.get("text") or "").strip()
        if not t:
            continue
        parts.append(t[:240])
        if len(parts) >= 2:
            break
    blob = "\n".join(parts).strip()
    return blob[:max_chars] if blob else ""


def _snippet_dedupe_key(sn: dict[str, Any]) -> str:
    """De-dupe by normalized excerpt text (diffusion often returns overlapping hits)."""
    return str(sn.get("text") or "").strip()[:320]


def merge_snippet_lists(
    primary: list[dict[str, Any]],
    secondary: list[dict[str, Any]],
    *,
    max_total: int = 14,
) -> list[dict[str, Any]]:
    """Union two Chroma hit lists with stable de-duplication by text+distance key."""
    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    for bucket in (primary, secondary):
        for sn in bucket:
            k = _snippet_dedupe_key(sn)
            if k in seen:
                continue
            seen.add(k)
            out.append(sn)
            if len(out) >= max_total:
                return out
    return out


def order_snippets_by_distance(snippets: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Ascending distance (lower = closer); unknown distance last."""

    def dist_key(sn: dict[str, Any]) -> float:
        d = sn.get("distance")
        if d is None:
            return 9e18
        try:
            return float(d)
        except (TypeError, ValueError):
            return 9e18

    return sorted(snippets, key=dist_key)


def prioritize_scoped_canon_snippets(
    snippets: list[dict[str, Any]],
    canon_prefixes: list[str] | None,
) -> list[dict[str, Any]]:
    """For A/C scoped queries, surface primary canon chunks before commentary."""
    if not snippets or not canon_prefixes:
        return snippets
    prefixes = [p.upper() for p in canon_prefixes if p]
    if not prefixes:
        return snippets

    def matches(sn: dict[str, Any]) -> bool:
        meta = sn.get("metadata") if isinstance(sn.get("metadata"), dict) else {}
        cid = str((meta or {}).get("canon_id") or sn.get("canon_id") or "").upper()
        return any(cid.startswith(p) for p in prefixes)

    primary = [sn for sn in snippets if matches(sn)]
    secondary = [sn for sn in snippets if sn not in primary]
    return primary + secondary


def rag_synth_profile(user_message: str) -> str:
    """Heuristic expert route for RAG synthesizer (system prompt + temperature)."""
    msg = user_message.strip()
    if not msg:
        return "default"
    if len(_TIBETAN_HINT_RE.findall(msg)) >= 4:
        return "tibetan"
    if re.search(r"巴利|巴利文|Pāli|Pali|tipiṭaka|三藏", msg, re.I):
        return "pali_source"
    if re.search(r"梵文|梵語|sanskrit|天城", msg, re.I):
        return "sanskrit_lexicon"
    return "default"


def rag_synthesizer_system_message(profile: str) -> str:
    base = (
        "你是協助讀者理解佛典的繁體中文助理。"
        "只能根據檢索到的片段作答；若片段不足請明說，不可捏造章節或經號。"
    )
    extras: dict[str, str] = {
        "default": "",
        "tibetan": " 使用者文字含較多藏文：可簡述藏語術語對應的漢譯習慣，仍須以片段為據。",
        "pali_source": " 使用者關心巴利語境：專名音譯／意譯請一致並對照片段，避免混用不同傳承用語。",
        "sanskrit_lexicon": " 使用者關心梵文語境：專名請一致採用通行漢譯或標明梵音，仍須以片段為據。",
    }
    return (base + extras.get(profile, "")).strip()


def rag_synth_temperature(profile: str) -> float:
    try:
        raw = float(os.environ.get("VAJRA_RAG_SYNTH_TEMP_BASE", "0.2"))
    except ValueError:
        raw = 0.2
    if profile == "tibetan":
        raw += 0.03
    return max(0.05, min(0.45, raw))


def canon_id_to_cbeta_reader_url(canon_id: str) -> str | None:
    """Best-effort HTTPS link into CBETA Online (Dila) reader."""
    m = _CANON_ID_RE.search(canon_id.strip().upper())
    if not m:
        return None
    cid = m.group(1).upper()
    return f"https://cbetaonline.dila.edu.tw/zh/{cid}_001"


def extract_similar_sutra_links(
    snippets: list[dict[str, Any]],
    *,
    limit: int = 5,
) -> list[dict[str, str]]:
    """Collect CBETA-style canon ids (Txxn####, TX…) from snippet text/metadata."""
    out: list[dict[str, str]] = []
    seen: set[str] = set()
    for sn in snippets:
        blobs: list[str] = []
        meta = sn.get("metadata")
        if isinstance(meta, dict):
            for v in meta.values():
                if v:
                    blobs.append(str(v))
        blobs.append(str(sn.get("text") or "")[:4000])
        big = "\n".join(blobs)
        for m in _CANON_ID_RE.finditer(big):
            cid = m.group(1).upper()
            if cid in seen:
                continue
            seen.add(cid)
            url = canon_id_to_cbeta_reader_url(cid)
            if url:
                out.append({"label": cid, "url": url, "canon": cid})
            if len(out) >= limit:
                return out
    return out


def build_rag_prompt(user_message: str, snippets: list[dict[str, Any]]) -> str:
    blocks: list[str] = []
    for i, sn in enumerate(snippets, start=1):
        src = sn.get("metadata") or {}
        ref = ""
        if isinstance(src, dict) and src:
            ref_bits = []
            for key in ("source", "file", "sutra", "id"):
                if key in src and src[key]:
                    ref_bits.append(f"{key}={src[key]}")
            if ref_bits:
                ref = "(" + "; ".join(ref_bits) + ")"
        excerpt = sn.get("text", "")
        blocks.append(f"[片段{i}]{ref}\n{excerpt}")

    corpus = "\n\n---\n\n".join(blocks).strip()
    return (
        f"使用者問題：\n{user_message.strip()}\n\n"
        f"以下是從經典／語料向量庫檢索到的相關片段（可能不完整）；請僅在有依據時引用，避免捏造典籍或章節；"
        f"片段不足請明說並給概括性指引。\n\n{corpus}\n\n請以繁體中文作答。"
    )
