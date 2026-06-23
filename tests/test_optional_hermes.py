"""Optional Hermes on translate / canon_rag (mocked LLM + Hermes)."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from gateway.hermes_conditional import (
    should_hermes_after_canon_rag,
    should_hermes_after_translate,
)


def test_flags_translate_default_off(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("VAJRA_HERMES_TRANSLATE", raising=False)
    assert should_hermes_after_translate(used_monlam=False) is False
    assert should_hermes_after_translate(used_monlam=True) is False


def test_flags_translate_monlam_only(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("VAJRA_HERMES_TRANSLATE", "monlam_only")
    assert should_hermes_after_translate(used_monlam=False) is False
    assert should_hermes_after_translate(used_monlam=True) is True


def test_flags_canon_hits(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("VAJRA_HERMES_CANON_RAG", "hits")
    assert should_hermes_after_canon_rag(rag_hits=0) is False
    assert should_hermes_after_canon_rag(rag_hits=2) is True


def test_translate_invokes_hermes_when_enabled(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("VAJRA_TRANSLATION_MEMORY", "0")
    monkeypatch.setenv("VAJRA_HERMES_TRANSLATE", "1")
    hermes_json = json.dumps(
        {"original": "a", "translation": "b", "approved": True, "issues": []},
        ensure_ascii=False,
    )
    with patch("gateway.app._hermes_audit", new_callable=AsyncMock) as hm:
        hm.return_value = {
            "original": "a",
            "translation": "b",
            "approved": True,
            "issues": [],
        }
        with patch("gateway.app.chat_completion", new_callable=AsyncMock) as llm:
            llm.side_effect = [
                ("譯文輸出", {}),
                (hermes_json, {}),
            ]
            r = client.post(
                "/v1/task",
                json={"mode": "translate", "channel": "web", "message": "hello"},
            )
    assert r.status_code == 200
    body = r.json()
    assert body["output"]["polished"] == "譯文輸出"
    assert body["output"].get("hermes_audit", {}).get("approved") is True
    assert body["meta"].get("hermes_translate_audit") is True
    assert hm.await_count == 1


def test_translate_hermes_bypass_on_http_exception(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("VAJRA_TRANSLATION_MEMORY", "0")
    monkeypatch.setenv("VAJRA_HERMES_TRANSLATE", "1")
    with patch("gateway.app._hermes_audit", new_callable=AsyncMock) as hm:
        hm.side_effect = HTTPException(status_code=503, detail="hermes down")
        with patch("gateway.app.chat_completion", new_callable=AsyncMock) as llm:
            llm.return_value = ("保留譯文", {})
            r = client.post(
                "/v1/task",
                json={"mode": "translate", "channel": "web", "message": "hello"},
            )
    assert r.status_code == 200
    ha = r.json()["output"].get("hermes_audit")
    assert isinstance(ha, dict)
    assert ha.get("bypass") is True
    assert ha.get("approved") is True
    assert r.json()["output"]["polished"] == "保留譯文"


def test_canon_rag_invokes_hermes_when_flag_hits(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("VAJRA_CANON_PG_DSN", "postgresql://vajra:vajra@127.0.0.1:5433/canon")
    monkeypatch.setenv("VAJRA_HERMES_CANON_RAG", "hits")
    hermes_json = json.dumps(
        {"original": "q", "translation": "t", "approved": True, "issues": []},
        ensure_ascii=False,
    )
    with patch("gateway.app.embeddings_request", new_callable=AsyncMock) as emb:
        emb.return_value = {"data": [{"embedding": [0.0] * 2048}]}
        with patch(
            "gateway.app.pg_retrieval.pg_query_snippets",
            new_callable=AsyncMock,
        ) as pq:
            pq.return_value = (
                [{"text": "片段", "distance": 0.1, "metadata": {"canon_id": "T01N0001"}}],
                None,
                None,
            )
            with patch("gateway.app._hermes_audit", new_callable=AsyncMock) as hm:
                hm.return_value = {
                    "original": "q",
                    "translation": "t",
                    "approved": True,
                    "issues": [],
                }
                with patch(
                    "gateway.app._llm_chat_completion",
                    new_callable=AsyncMock,
                ) as llm:
                    llm.side_effect = [
                        ("RAG回答", {}),
                        (hermes_json, {}),
                    ]
                    r = client.post(
                        "/v1/task",
                        json={
                            "mode": "canon_rag",
                            "channel": "web",
                            "message": "何謂空性",
                        },
                    )
    assert r.status_code == 200
    body = r.json()
    assert "RAG回答" in body["output"]["answer"]
    assert body["output"].get("hermes_audit", {}).get("approved") is True
    assert body["meta"].get("hermes_canon_audit") is True
    assert hm.await_count == 1
