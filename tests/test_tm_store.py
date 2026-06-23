"""Translation-memory SQLite helpers (asyncio.to_thread wrappers)."""

from __future__ import annotations

import pytest

from gateway import tm_store
from gateway.config import translation_memory_db_path


@pytest.mark.asyncio
async def test_tm_put_get_roundtrip(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("VAJRA_TM_DB", str(tmp_path / "tm.sqlite"))
    path = translation_memory_db_path()
    await tm_store.tm_init(path)
    key = tm_store.source_key_sha256("  hello  ")
    await tm_store.tm_put(path, key, "draft-a", "polish-b", used_monlam=True)
    row = await tm_store.tm_get(path, key)
    assert row == ("draft-a", "polish-b", True)
