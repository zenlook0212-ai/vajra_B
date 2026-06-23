#!/usr/bin/env bash
set -euo pipefail
export PYTHONPATH=/opt/vajra
export VAJRA_CANON_PG_DSN="${VAJRA_CANON_PG_DSN:-postgresql://vajra:vajra@127.0.0.1:5433/canon}"
mkdir -p /opt/vajra/data/logs
/opt/vajra/.venv/bin/python -m canon.eval.run_eval --report "/opt/vajra/data/logs/canon_eval_$(date +%Y%m%d).json"
