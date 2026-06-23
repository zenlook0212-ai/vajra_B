"""Chroma URL resolution (v2 vs legacy v1 suffix)."""

from __future__ import annotations

import pytest

from gateway.rag_retrieval import chroma_api_configured, chroma_collections_base


def test_collections_base_v2_from_host_port(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("VAJRA_CHROMA_API_ROOT", "http://127.0.0.1:8040")
    base, kind = chroma_collections_base()
    assert kind == "v2"
    assert base is not None
    assert base.endswith("/default_database")
    assert "/api/v2/tenants/default_tenant/databases/default_database" in base


def test_collections_base_explicit_tenant_db(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("VAJRA_CHROMA_API_ROOT", "http://127.0.0.1:8040")
    monkeypatch.setenv("VAJRA_CHROMA_TENANT", "t1")
    monkeypatch.setenv("VAJRA_CHROMA_DATABASE", "dbx")
    base, _ = chroma_collections_base()
    assert base.endswith("/dbx")
    assert "/tenants/t1/" in (base or "")


def test_collections_base_v1_suffix(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("VAJRA_CHROMA_API_ROOT", "http://localhost:9999/api/v1")
    base, kind = chroma_collections_base()
    assert kind == "v1"
    assert base == "http://localhost:9999/api/v1"


def test_chroma_api_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("VAJRA_CHROMA_API_ROOT", raising=False)
    assert chroma_api_configured() is False
    monkeypatch.setenv("VAJRA_CHROMA_API_ROOT", "http://x:8")
    assert chroma_api_configured() is True
