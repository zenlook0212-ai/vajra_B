"""SQLite translation memory: cache translate-mode draft+polished by source text hash."""

from __future__ import annotations

import asyncio
import hashlib
import sqlite3
from pathlib import Path

def source_key_sha256(source: str) -> str:
    """Stable key for trimmed UTF-8 source text."""
    return hashlib.sha256(source.strip().encode("utf-8")).hexdigest()


def _init_schema(con: sqlite3.Connection) -> None:
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS tm_segments (
            source_key TEXT PRIMARY KEY,
            draft TEXT NOT NULL,
            polished TEXT NOT NULL,
            used_monlam INTEGER NOT NULL DEFAULT 1,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    con.commit()


def tm_init_sync(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(path) as con:
        _init_schema(con)


async def tm_init(path: Path) -> None:
    await asyncio.to_thread(tm_init_sync, path)


async def tm_get(path: Path, source_key: str) -> tuple[str, str, bool] | None:
    def _run() -> tuple[str, str, bool] | None:
        with sqlite3.connect(path) as con:
            cur = con.execute(
                "SELECT draft, polished, used_monlam FROM tm_segments WHERE source_key = ?",
                (source_key,),
            )
            row = cur.fetchone()
            if row is None:
                return None
            return str(row[0]), str(row[1]), bool(row[2])

    return await asyncio.to_thread(_run)


async def tm_put(path: Path, source_key: str, draft: str, polished: str, *, used_monlam: bool) -> None:
    def _run() -> None:
        with sqlite3.connect(path) as con:
            _init_schema(con)
            con.execute(
                """
                INSERT INTO tm_segments(source_key, draft, polished, used_monlam)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(source_key) DO UPDATE SET
                    draft=excluded.draft,
                    polished=excluded.polished,
                    used_monlam=excluded.used_monlam,
                    created_at=CURRENT_TIMESTAMP
                """,
                (source_key, draft, polished, 1 if used_monlam else 0),
            )
            con.commit()

    await asyncio.to_thread(_run)
