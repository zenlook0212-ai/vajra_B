"""Ensure LIST partitions exist for each CBETA series catalog."""

from __future__ import annotations

import argparse
import os
from pathlib import Path

import psycopg

SERIES_RE = None  # top-level dirs only


def discover_series(corpus: Path) -> list[str]:
    out: list[str] = []
    for child in sorted(corpus.iterdir()):
        if not child.is_dir() or not child.name.isalpha():
            continue
        name = child.name.upper()
        key = name if len(name) <= 2 else name[:2]
        if key not in out:
            out.append(key)
    return out


def ensure_partition(conn: psycopg.Connection, series: str) -> None:
    s = series.strip().upper()
    key = s if len(s) <= 2 else s[:2]
    tbl = f"canon_chunks_{key.strip().replace(' ', '_')}"
    with conn.cursor() as cur:
        cur.execute(
            f"""
            CREATE TABLE IF NOT EXISTS {tbl} PARTITION OF canon_chunks
            FOR VALUES IN (%s)
            """,
            (key,),
        )
        cur.execute(
            f"CREATE INDEX IF NOT EXISTS {tbl}_canon_id_idx ON {tbl} (canon_id)"
        )
        cur.execute(
            f"""
            CREATE INDEX IF NOT EXISTS {tbl}_embedding_hnsw ON {tbl}
            USING hnsw (embedding halfvec_cosine_ops) WITH (m = 16, ef_construction = 64)
            """
        )
        cur.execute(
            f"CREATE INDEX IF NOT EXISTS {tbl}_tsv_gin ON {tbl} USING gin (tsv)"
        )
    conn.commit()


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--corpus", type=Path, default=Path("/home/zenlook/cbeta-text"))
    p.add_argument(
        "--dsn",
        default=os.environ.get(
            "VAJRA_CANON_PG_DSN", "postgresql://vajra:vajra@127.0.0.1:5433/canon"
        ),
    )
    args = p.parse_args()
    series_list = discover_series(args.corpus)
    with psycopg.connect(args.dsn) as conn:
        for s in series_list:
            ensure_partition(conn, s)
            print(f"partition ok: {s!r}")


if __name__ == "__main__":
    main()
