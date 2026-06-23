#!/usr/bin/env bash
# 從 Vajra 專案啟動 Telegram bot（實際腳本在 hermes-gateway）。
# 覆寫目錄：export VAJRA_TELEGRAM_ROOT=/path/to/hermes-gateway
set -euo pipefail
BOT_HOME="${VAJRA_TELEGRAM_ROOT:-/home/zenlook/hermes-gateway}"
LAUNCHER="$BOT_HOME/run_telegram_bot.sh"
if [[ ! -f "$LAUNCHER" ]]; then
  echo "run_telegram_bot.sh not found: $LAUNCHER" >&2
  echo "Set VAJRA_TELEGRAM_ROOT to your hermes-gateway checkout." >&2
  exit 1
fi
exec bash "$LAUNCHER" "$@"
