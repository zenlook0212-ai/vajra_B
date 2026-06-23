#!/usr/bin/env bash
# 全 T 系 ingest + benchmark
set -euo pipefail
export PYTHONPATH=/opt/vajra
export VAJRA_CANON_PG_DSN="${VAJRA_CANON_PG_DSN:-postgresql://vajra:vajra@127.0.0.1:5433/canon}"
LOG="/opt/vajra/data/logs/canon_ingest_T_$(date +%Y%m%d_%H%M).log"
mkdir -p /opt/vajra/data/logs
echo "start $(date -Is)" | tee "$LOG"
/usr/bin/time -f 'elapsed=%e' \
  /opt/vajra/.venv/bin/python -m canon.ingest.ingest --series T --batch-size 16 2>&1 | tee -a "$LOG"
echo "done $(date -Is)" | tee -a "$LOG"
PYTHONPATH=/opt/vajra VAJRA_CANON_PG_DSN="${VAJRA_CANON_PG_DSN:-postgresql://vajra:vajra@127.0.0.1:5433/canon}" \
  /opt/vajra/.venv/bin/python /opt/vajra/canon/scripts/write_benchmark.py | tee -a "$LOG"
