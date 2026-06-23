#!/usr/bin/env python3
"""Write canon ingest benchmark JSON from ingest_progress + logs."""

from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path

import psycopg

DSN = os.environ.get(
    "VAJRA_CANON_PG_DSN", "postgresql://vajra:vajra@127.0.0.1:5433/canon"
)
OUT = Path(os.environ.get("CANON_BENCHMARK_OUT", "/opt/vajra/data/logs/canon_ingest_benchmark.json"))
LOG_GLOB = "/opt/vajra/data/logs/canon_ingest_T_*.log"
RATE_RE = re.compile(r"ingested (\d+) chunks from .+ in ([\d.]+)s \(([\d.]+) chunks/s\)")


def parse_log_rates() -> list[float]:
    rates: list[float] = []
    for path in sorted(Path("/opt/vajra/data/logs").glob("canon_ingest_T_*.log")):
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            m = RATE_RE.search(line)
            if m:
                rates.append(float(m.group(3)))
    return rates


def main() -> None:
    rates = parse_log_rates()
    with psycopg.connect(DSN) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT count(*) FROM canon_chunks_T")
            chunks = cur.fetchone()[0]
            cur.execute(
                "SELECT count(*) FILTER (WHERE completed), count(*) FROM ingest_progress"
            )
            done, total_files = cur.fetchone()
            cur.execute(
                "SELECT sum(chunk_count) FROM ingest_progress WHERE completed"
            )
            done_chunks = cur.fetchone()[0] or 0

    total_t_files = len(list(Path("/home/zenlook/cbeta-text/T").rglob("new.txt")))
    avg_rate = sum(rates) / len(rates) if rates else 0.0
    remaining_files = total_t_files - done
    est_remaining_chunks = max(0, chunks) / max(done, 1) * remaining_files if done else 0
    eta_hours = (est_remaining_chunks / avg_rate / 3600) if avg_rate > 0 else None

    report = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "series": "T",
        "volumes_total": total_t_files,
        "volumes_completed": done,
        "volumes_in_progress_table": total_files,
        "chunks_in_db": chunks,
        "chunks_from_completed_volumes": done_chunks,
        "ingest_rates_chunks_per_sec": {
            "samples": len(rates),
            "min": min(rates) if rates else None,
            "max": max(rates) if rates else None,
            "avg": round(avg_rate, 2),
        },
        "eta_hours_at_avg_rate": round(eta_hours, 2) if eta_hours else None,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
