#!/usr/bin/env bash
# Re-embed all T-series chunks with passage prompts (resume-safe).
set -euo pipefail
export PYTHONPATH=/opt/vajra
export VAJRA_CANON_PG_DSN="${VAJRA_CANON_PG_DSN:-postgresql://vajra:vajra@127.0.0.1:5433/canon}"
LOG="/opt/vajra/data/logs/re_embed_$(date +%Y%m%d_%H%M).log"
mkdir -p /opt/vajra/data/logs
echo "start $(date -Is)" | tee "$LOG"
/usr/bin/time -f 'elapsed=%e' \
  /opt/vajra/.venv/bin/python -m canon.ingest.re_embed --series T --batch-size 16 2>&1 | tee -a "$LOG"
echo "done $(date -Is)" | tee -a "$LOG"
echo "running post-re-embed eval..." | tee -a "$LOG"
/opt/vajra/.venv/bin/python -m canon.eval.run_eval --k 5 \
  --report "/opt/vajra/data/logs/canon_eval_post_reembed_$(date +%Y%m%d).json" 2>&1 | tee -a "$LOG"
