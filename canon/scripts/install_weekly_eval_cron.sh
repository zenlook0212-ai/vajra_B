#!/usr/bin/env bash
# Install weekly canon RAG eval cron (Sunday 03:00)
set -euo pipefail
LINE='0 3 * * 0 /opt/vajra/canon/scripts/weekly_eval.sh >> /opt/vajra/data/logs/canon_eval_cron.log 2>&1'
mkdir -p /opt/vajra/data/logs
chmod +x /opt/vajra/canon/scripts/weekly_eval.sh
( crontab -l 2>/dev/null | grep -v 'weekly_eval.sh'; echo "$LINE" ) | crontab -
echo "Installed: $LINE"
