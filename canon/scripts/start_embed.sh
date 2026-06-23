#!/usr/bin/env bash
set -euo pipefail
export PYTHONPATH=/opt/vajra
export EMBED_MODEL="${EMBED_MODEL:-/data/models/Qwen3-Embedding-4B}"
export VAJRA_CANON_EMBED_DIM="${VAJRA_CANON_EMBED_DIM:-2048}"
export EMBED_DEVICE="${EMBED_DEVICE:-cuda}"
exec /opt/vajra/.venv/bin/uvicorn canon.services.embed.app:app --host 0.0.0.0 --port 8005 --workers 1
