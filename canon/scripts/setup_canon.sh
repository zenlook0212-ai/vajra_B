#!/usr/bin/env bash
# CBETA canon RAG 方案 B — 初始化 Postgres + schema + 下載 embedding 模型
set -euo pipefail
cd /opt/vajra

export VAJRA_CANON_PG_DSN="${VAJRA_CANON_PG_DSN:-postgresql://vajra:vajra@127.0.0.1:5433/canon}"

echo "=== 1. Start PostgreSQL ==="
docker compose up -d postgres
for i in $(seq 1 30); do
  if docker compose exec -T postgres pg_isready -U vajra -d canon >/dev/null 2>&1; then
    break
  fi
  sleep 2
done

echo "=== 2. Apply schema ==="
docker compose exec -T postgres psql -U vajra -d canon < canon/schema/001_init.sql
docker compose exec -T postgres psql -U vajra -d canon < canon/schema/002_indexes.sql
docker compose exec -T postgres psql -U vajra -d canon < canon/schema/003_pg_trgm.sql

echo "=== 3. Download Qwen3-Embedding-4B (if missing) ==="
if [ ! -d /data/models/Qwen3-Embedding-4B ]; then
  huggingface-cli download Qwen/Qwen3-Embedding-4B --local-dir /data/models/Qwen3-Embedding-4B
fi

echo "=== 4. Python deps ==="
pip install -q -r canon/requirements.txt

echo "=== Done. Next: docker compose up -d qwen3-embed && python -m canon.ingest.ingest --series T --volume T01 ==="
