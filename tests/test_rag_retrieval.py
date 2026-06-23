"""RAG helpers (embedding parsing, Chroma-shaped wiring)."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from gateway.rag_retrieval import (
    build_rag_prompt,
    extract_openai_embedding_vector,
    extract_similar_sutra_links,
    merge_snippet_lists,
    order_snippets_by_distance,
)


def test_extract_embedding_vector() -> None:
    v = extract_openai_embedding_vector({"data": [{"embedding": [0.1, 2.0]}]})
    assert v == [0.1, 2.0]


def test_order_snippets_by_distance() -> None:
    sn = [
        {"text": "b", "distance": 0.5},
        {"text": "a", "distance": 0.1},
    ]
    ordered = order_snippets_by_distance(sn)
    assert [x["text"] for x in ordered] == ["a", "b"]


def test_merge_snippet_lists_dedupes() -> None:
    a = [{"text": "same", "distance": 0.1}]
    b = [{"text": "same", "distance": 0.2}, {"text": "other", "distance": 0.3}]
    m = merge_snippet_lists(a, b, max_total=10)
    texts = [x["text"] for x in m]
    assert texts.count("same") == 1
    assert "other" in texts


def test_extract_similar_sutra_links() -> None:
    sn = [
        {
            "text": "如 TX19n0011 所說……",
            "metadata": {"source": "T12n0345"},
            "distance": 0.01,
        }
    ]
    links = extract_similar_sutra_links(sn, limit=5)
    assert links
    assert all("cbetaonline.dila.edu.tw" in x["url"] for x in links)


def test_build_rag_prompt_contains_snippets() -> None:
    prompt = build_rag_prompt(
        "為何修慈？",
        [{"text": "慈心功德略說", "metadata": {"source": "mock"}, "distance": 0.05}],
    )
    assert "為何修慈" in prompt
    assert "慈心功德" in prompt


def test_canon_rag_injects_retrieved_text_into_qwen_prompt(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("VAJRA_CANON_PG_DSN", "postgresql://vajra:vajra@127.0.0.1:5433/canon")
    with patch("gateway.app.embeddings_request", new_callable=AsyncMock) as emb:
        emb.return_value = {"data": [{"embedding": [0.0] * 2048}]}
        with patch(
            "gateway.app.pg_retrieval.pg_query_snippets",
            new_callable=AsyncMock,
        ) as pq:
            pq.return_value = (
                [
                    {
                        "text": "檢索片段測試經文",
                        "distance": 0.1,
                        "metadata": {
                            "canon_id": "T01N0001",
                            "coord_start": "T01n0001_p0001a05",
                        },
                    },
                ],
                None,
                None,
            )
            with patch(
                "gateway.app._llm_chat_completion",
                new_callable=AsyncMock,
            ) as llm:
                llm.return_value = ("回答", {})
                with patch("gateway.app.asyncio.to_thread", new_callable=AsyncMock):
                    r = client.post(
                        "/v1/task",
                        json={
                            "mode": "canon_rag",
                            "channel": "web",
                            "message": "問題本體",
                        },
                    )
    assert r.status_code == 200
    assert llm.await_count == 1
    messages = llm.call_args.kwargs["messages"]
    assert len(messages) == 2
    assert messages[0]["role"] == "system"
    assert "佛典研究助手" in messages[0]["content"]
    assert messages[1]["role"] == "user"
    assert "檢索片段測試經文" in messages[1]["content"]
    body = r.json()
    assert body["meta"]["rag"]["hits"] == 1
    assert body["meta"]["rag"]["backend"] == "pgvector"
    assert body["output"]["retrieval_preview"]
    assert isinstance(body["output"].get("similar_sutra_links"), list)
