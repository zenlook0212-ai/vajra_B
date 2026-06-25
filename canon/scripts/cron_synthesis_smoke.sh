#!/usr/bin/env bash
# Weekly synthesis smoke — add to crontab, e.g.:
# 0 3 * * 1 /opt/vajra/canon/scripts/cron_synthesis_smoke.sh >> /var/log/canon-rag-eval.log 2>&1
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
export VAJRA_CANON_PG_DSN="${VAJRA_CANON_PG_DSN:-postgresql://vajra:vajra@127.0.0.1:5433/canon}"
export PYTHONPATH="${ROOT}/..:${PYTHONPATH:-}"
cd "$ROOT"
python3 -m canon.eval.run_eval_synthesis --limit 12 --report /tmp/canon_synthesis_smoke.json
echo "smoke ok $(date -Iseconds) report=/tmp/canon_synthesis_smoke.json"
