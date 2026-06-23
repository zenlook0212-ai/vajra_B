#!/usr/bin/env bash
# PEP 668：在專用 venv 內安裝閘道依賴。
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
if [[ ! -d "$ROOT/venv" ]]; then
  python3 -m venv "$ROOT/venv"
fi
"$ROOT/venv/bin/pip" install -U pip
"$ROOT/venv/bin/pip" install -r "$ROOT/requirements-gateway.txt"
echo "OK: use  $ROOT/venv/bin/python  and  $ROOT/venv/bin/uvicorn"
