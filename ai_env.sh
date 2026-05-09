#!/usr/bin/env bash
export DATA_ROOT=/data
export MODELS=/data/models
export TMPDIR=/data/tmp

if ! mountpoint -q "$DATA_ROOT"; then
  echo "[VAJRA] ERROR: /data not mounted. Abort." >&2
  return 1 2>/dev/null || exit 1
fi

echo "[VAJRA] env loaded: DATA_ROOT=${DATA_ROOT}, MODELS=${MODELS}"
