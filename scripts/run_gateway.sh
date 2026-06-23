#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export VAJRA_MODELS_YAML="${VAJRA_MODELS_YAML:-$ROOT/models.yaml}"
export PYTHONPATH="$ROOT"
# Prefer .venv (canon/pg deps); fall back to venv.
if [[ -n "${VAJRA_GATEWAY_PYTHON:-}" ]]; then
  PY="$VAJRA_GATEWAY_PYTHON"
elif [[ -x "$ROOT/.venv/bin/python" ]]; then
  PY="$ROOT/.venv/bin/python"
else
  PY="$ROOT/venv/bin/python"
fi
# Port 8080 is often taken (e.g. ephemeris / Open WebUI). Use VAJRA_GATEWAY_PORT=8081 if needed.
exec "$PY" -m uvicorn gateway.app:app \
  --host "${VAJRA_GATEWAY_HOST:-0.0.0.0}" \
  --port "${VAJRA_GATEWAY_PORT:-8081}"
