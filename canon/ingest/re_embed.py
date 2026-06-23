#!/usr/bin/env python3
"""Re-embed canon_chunks with passage prompts (query/passage alignment)."""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

import psycopg

from canon.ingest.embed_client import embed_passages

DEFAULT_DSN = "postgresql://vajra:vajra@127.0.0.1:5433/canon"
CHECKPOINT_EVERY = 500


def load_checkpoint(path: Path) -> int:
    if not path.is_file():
        return 0
    data = json.loads(path.read_text(encoding="utf-8"))
    return int(data.get("last_id", 0))


def save_checkpoint(path: Path, last_id: int, *, updated: int, elapsed: float) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "last_id": last_id,
                "updated": updated,
                "elapsed_sec": round(elapsed, 1),
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


def fetch_batch(
    conn: psycopg.Connection,
    *,
    series: str,
    after_id: int,
    limit: int,
) -> list[tuple[int, str]]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT id, text
            FROM canon_chunks
            WHERE series = %s AND id > %s
            ORDER BY id
            LIMIT %s
            """,
            (series, after_id, limit),
        )
        return [(int(r[0]), str(r[1])) for r in cur.fetchall()]


def update_embeddings(
    conn: psycopg.Connection,
    series: str,
    rows: list[tuple[int, list[float]]],
) -> None:
    with conn.cursor() as cur:
        cur.executemany(
            "UPDATE canon_chunks SET embedding = %s::halfvec WHERE id = %s AND series = %s",
            [(json.dumps(emb), cid, series) for cid, emb in rows],
        )
    conn.commit()


def re_embed(
    *,
    dsn: str,
    series: str,
    batch_size: int,
    after_id: int,
    limit: int | None,
    checkpoint: Path,
) -> dict[str, Any]:
    updated = 0
    last_id = after_id
    t0 = time.perf_counter()

    with psycopg.connect(dsn) as conn:
        while True:
            if limit is not None and updated >= limit:
                break
            fetch_n = batch_size
            if limit is not None:
                fetch_n = min(batch_size, limit - updated)
            batch = fetch_batch(conn, series=series, after_id=last_id, limit=fetch_n)
            if not batch:
                break

            ids = [r[0] for r in batch]
            texts = [r[1] for r in batch]
            embeddings = embed_passages(texts)
            update_embeddings(conn, series, list(zip(ids, embeddings, strict=True)))

            updated += len(batch)
            last_id = ids[-1]

            if updated % CHECKPOINT_EVERY < batch_size:
                elapsed = time.perf_counter() - t0
                rate = updated / elapsed if elapsed > 0 else 0.0
                print(f"re-embedded {updated} chunks (last_id={last_id}, {rate:.1f}/s)")
                save_checkpoint(checkpoint, last_id, updated=updated, elapsed=elapsed)

    elapsed = time.perf_counter() - t0
    save_checkpoint(checkpoint, last_id, updated=updated, elapsed=elapsed)
    return {
        "updated": updated,
        "last_id": last_id,
        "elapsed_sec": round(elapsed, 1),
        "chunks_per_sec": round(updated / elapsed, 2) if elapsed > 0 else 0.0,
    }


def main() -> None:
    p = argparse.ArgumentParser(description="Re-embed canon chunks with passage prompts")
    p.add_argument("--series", default="T")
    p.add_argument("--batch-size", type=int, default=16)
    p.add_argument("--after-id", type=int, default=None)
    p.add_argument("--limit", type=int, default=None, help="max chunks to update (smoke test)")
    p.add_argument("--checkpoint", type=Path, default=Path("/opt/vajra/data/logs/re_embed_checkpoint.json"))
    p.add_argument("--dsn", default=os.environ.get("VAJRA_CANON_PG_DSN", DEFAULT_DSN))
    args = p.parse_args()

    after_id = args.after_id
    if after_id is None:
        after_id = load_checkpoint(args.checkpoint)

    stats = re_embed(
        dsn=args.dsn,
        series=args.series.strip().upper()[:2],
        batch_size=args.batch_size,
        after_id=after_id,
        limit=args.limit,
        checkpoint=args.checkpoint,
    )
    print(json.dumps(stats, indent=2))
    if stats["updated"] == 0 and args.limit is None:
        print("nothing to update", file=sys.stderr)


if __name__ == "__main__":
    main()
