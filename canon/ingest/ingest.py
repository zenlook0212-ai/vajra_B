#!/usr/bin/env python3
"""CBETA coord-first ingest with checkpoint."""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

import psycopg

from canon.ingest.cbeta_parser import iter_segments
from canon.ingest.coord_chunker import Chunk, chunk_segments
from canon.ingest.embed_client import embed_passages

CHECKPOINT_EVERY = 1000
DEFAULT_DSN = "postgresql://vajra:vajra@127.0.0.1:5433/canon"


def series_from_path(corpus: Path, file_path: Path) -> str:
    rel = file_path.relative_to(corpus)
    name = rel.parts[0].upper()
    return name if len(name) <= 2 else name[:2]


def discover_files(
    corpus: Path,
    *,
    series: str | None = None,
    volume: str | None = None,
) -> list[Path]:
    root = corpus
    if series:
        root = corpus / series.strip()
    files: list[Path] = []
    if volume:
        cand = root / volume / "new.txt"
        if cand.is_file():
            return [cand]
        raise FileNotFoundError(cand)
    for p in sorted(root.rglob("new.txt")):
        files.append(p)
    return files


def is_complete(conn: psycopg.Connection, file_path: str) -> bool:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT completed FROM ingest_progress WHERE file_path = %s",
            (file_path,),
        )
        row = cur.fetchone()
        return bool(row and row[0])


def load_progress(
    conn: psycopg.Connection, file_path: str
) -> tuple[str | None, int, bool]:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT last_coord, chunk_count, completed FROM ingest_progress WHERE file_path = %s",
            (file_path,),
        )
        row = cur.fetchone()
    if not row:
        return None, 0, False
    return row[0] or None, int(row[1] or 0), bool(row[2])


def chunks_after_resume(chunks: list[Chunk], last_coord: str | None) -> list[Chunk]:
    if not last_coord:
        return chunks
    resumed: list[Chunk] = []
    for chunk in chunks:
        if chunk.coord_end <= last_coord:
            continue
        resumed.append(chunk)
    return resumed


def save_checkpoint(
    conn: psycopg.Connection,
    file_path: str,
    last_coord: str,
    chunk_count: int,
    *,
    completed: bool = False,
) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO ingest_progress (file_path, last_coord, chunk_count, completed, updated_at)
            VALUES (%s, %s, %s, %s, now())
            ON CONFLICT (file_path) DO UPDATE SET
              last_coord = EXCLUDED.last_coord,
              chunk_count = EXCLUDED.chunk_count,
              completed = EXCLUDED.completed,
              updated_at = now()
            """,
            (file_path, last_coord, chunk_count, completed),
        )
    conn.commit()


def insert_chunks(
    conn: psycopg.Connection,
    chunks: list[Chunk],
    embeddings: list[list[float]],
) -> None:
    rows = [
        (
            c.series,
            c.canon_id,
            c.coord_start,
            c.coord_end,
            c.text,
            c.char_len,
            c.file_path,
            json.dumps(emb),
        )
        for c, emb in zip(chunks, embeddings, strict=True)
    ]
    with conn.cursor() as cur:
        cur.executemany(
            """
            INSERT INTO canon_chunks
              (series, canon_id, coord_start, coord_end, text, char_len, file_path, embedding)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s::halfvec)
            """,
            rows,
        )
    conn.commit()


def ingest_file(
    conn: psycopg.Connection,
    corpus: Path,
    file_path: Path,
    *,
    batch_size: int = 32,
    skip_embed: bool = False,
) -> int:
    series = series_from_path(corpus, file_path)
    fp = str(file_path.resolve())
    if is_complete(conn, fp):
        print(f"skip (done): {fp}")
        return 0

    last_coord, prior_count, _ = load_progress(conn, fp)
    segments = list(iter_segments(file_path))
    chunks = chunk_segments(segments, series=series, file_path=fp)
    if not chunks:
        print(f"empty: {fp}")
        return 0

    if last_coord:
        chunks = chunks_after_resume(chunks, last_coord)
        if not chunks:
            save_checkpoint(conn, fp, last_coord, prior_count, completed=True)
            print(f"resume complete (no remaining chunks): {fp}")
            return 0
        print(f"resume from {last_coord}: {fp} ({prior_count} chunks already, {len(chunks)} remaining)")

    total = prior_count
    t0 = time.perf_counter()

    for i in range(0, len(chunks), batch_size):
        batch = chunks[i : i + batch_size]
        if skip_embed:
            embeddings = [[0.0] * 2048 for _ in batch]
        else:
            embeddings = embed_passages([c.text for c in batch])
        insert_chunks(conn, batch, embeddings)
        total += len(batch)

        if (total - prior_count) % CHECKPOINT_EVERY < batch_size or i + batch_size >= len(chunks):
            save_checkpoint(conn, fp, batch[-1].coord_end, total)

    save_checkpoint(conn, fp, chunks[-1].coord_end, total, completed=True)
    elapsed = time.perf_counter() - t0
    added = total - prior_count
    rate = added / elapsed if elapsed > 0 else 0
    print(f"ingested {added} chunks from {fp} in {elapsed:.1f}s ({rate:.1f} chunks/s, total {total})")
    return added


def main() -> None:
    p = argparse.ArgumentParser(description="CBETA canon ingest")
    p.add_argument("--corpus", type=Path, default=Path("/home/zenlook/cbeta-text"))
    p.add_argument("--series", type=str, default=None, help="e.g. T")
    p.add_argument("--volume", type=str, default=None, help="e.g. T01")
    p.add_argument("--batch-size", type=int, default=32)
    p.add_argument("--skip-embed", action="store_true", help="dry-run without embed API")
    p.add_argument(
        "--dsn",
        default=os.environ.get("VAJRA_CANON_PG_DSN", DEFAULT_DSN),
    )
    args = p.parse_args()

    files = discover_files(args.corpus, series=args.series, volume=args.volume)
    if not files:
        print("no files found", file=sys.stderr)
        sys.exit(1)

    grand = 0
    t0 = time.perf_counter()
    with psycopg.connect(args.dsn) as conn:
        for fp in files:
            grand += ingest_file(
                conn,
                args.corpus,
                fp,
                batch_size=args.batch_size,
                skip_embed=args.skip_embed,
            )
    elapsed = time.perf_counter() - t0
    print(f"TOTAL: {grand} chunks in {elapsed:.1f}s ({grand/elapsed:.2f} chunks/s)")


if __name__ == "__main__":
    main()
