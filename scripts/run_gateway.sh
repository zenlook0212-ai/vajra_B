#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export VAJRA_MODELS_YAML="${VAJRA_MODELS_YAML:-$ROOT/models.yaml}"
export PYTHONPATH="$ROOT"
export VAJRA_CANON_PG_DSN="${VAJRA_CANON_PG_DSN:-postgresql://vajra:vajra@127.0.0.1:5433/canon}"
export VAJRA_CANON_CACHE_KEY_VERSION="${VAJRA_CANON_CACHE_KEY_VERSION:-phase_2c_v5}"
# D-class: hybrid（摘錄+LLM綜合）| extractive（全快）| llm（全LLM）。例：VAJRA_RAG_D_SYNTH=extractive
export VAJRA_RAG_D_SYNTH="${VAJRA_RAG_D_SYNTH:-hybrid}"
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
