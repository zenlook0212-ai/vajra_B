# CBETA Canon RAG (方案 B)

PostgreSQL + pgvector + Qwen3-Embedding-4B + hybrid RRF + mxbai rerank.

## Quick start

```bash
# 1. Postgres
cd /opt/vajra && docker compose up -d postgres
docker compose exec -T postgres psql -U vajra -d canon < canon/schema/001_init.sql
docker compose exec -T postgres psql -U vajra -d canon < canon/schema/002_indexes.sql

# 2. Embedding (:8005)
/opt/vajra/canon/scripts/start_embed.sh

# 3. Rerank (:8007)
docker compose up -d mxbai-rerank

# 4. Ingest smoke (T01)
export PYTHONPATH=/opt/vajra VAJRA_CANON_PG_DSN=postgresql://vajra:vajra@127.0.0.1:5433/canon
python -m canon.ingest.ingest --series T --volume T01 --batch-size 64

# 5. Gateway
export VAJRA_CANON_PG_DSN=postgresql://vajra:vajra@127.0.0.1:5433/canon
export VAJRA_HERMES_CANON_RAG=on_demand
./scripts/run_gateway.sh
```

## Notes

- Embeddings use `halfvec(2048)` (pgvector HNSW limit for `vector` is 2000 dims).
- Embedding service: sentence-transformers on GPU (`canon/services/embed/`).
- Logs: `/opt/vajra/data/logs/`
- Full T ingest: `canon/scripts/ingest_all_T.sh`
- Re-embed passages (after query/passage split): `canon/scripts/re_embed_all.sh`
- W4 verify: `canon/scripts/verify_e2e.sh`
- Weekly eval: `canon/scripts/install_weekly_eval_cron.sh`
- **使用者指南（RAG vs CBETA）**: [`canon/docs/USER_GUIDE_ZH.md`](docs/USER_GUIDE_ZH.md)
