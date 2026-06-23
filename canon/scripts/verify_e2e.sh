#!/usr/bin/env bash
# W4 acceptance: verify canon RAG stack + optional gateway e2e.
set -euo pipefail
export PYTHONPATH=/opt/vajra
export VAJRA_CANON_PG_DSN="${VAJRA_CANON_PG_DSN:-postgresql://vajra:vajra@127.0.0.1:5433/canon}"
GW="${VAJRA_GATEWAY_URL:-http://127.0.0.1:8081}"

echo "== embed :8005 =="
curl -sf http://127.0.0.1:8005/health | head -c 200; echo

echo "== rerank :8007 =="
curl -sf http://127.0.0.1:8007/health | head -c 200; echo

echo "== postgres chunks =="
/opt/vajra/.venv/bin/python - <<'PY'
import psycopg, os
conn = psycopg.connect(os.environ["VAJRA_CANON_PG_DSN"])
with conn.cursor() as cur:
    cur.execute("SELECT count(*) FROM canon_chunks")
    print("chunks:", cur.fetchone()[0])
    cur.execute("SELECT count(*) FILTER (WHERE completed), count(*) FROM ingest_progress")
    print("ingest volumes:", cur.fetchone())
PY

echo "== retrieval smoke =="
/opt/vajra/.venv/bin/python - <<'PY'
import psycopg, os
from canon.ingest.embed_client import embed_queries
from canon.query.pipeline import embed_text, plan_query, retrieve_with_plan
from canon.query.preprocess import preprocess_query
dsn = os.environ["VAJRA_CANON_PG_DSN"]
q = "金剛經的核心主題是什麼？"
pq = preprocess_query(q)
plan = plan_query(pq)
emb = embed_queries([embed_text(pq, plan)])[0]
with psycopg.connect(dsn) as conn:
    hits, _ = retrieve_with_plan(conn, pq, plan, emb)
print("hits:", len(hits), "top:", hits[0].get("canon_id") if hits else None)
PY

if curl -sf "${GW}/v1/modes" >/dev/null 2>&1; then
  echo "== gateway canon_rag (needs qwen :8003) =="
  if curl -sf -X POST "${GW}/v1/task" \
    -H 'Content-Type: application/json' \
    -d '{"mode":"canon_rag","channel":"web_public_hermes","message":"心經如何說色與空？"}' \
    | head -c 500; then
    echo
  else
    echo "(gateway e2e skipped: qwen or upstream unavailable)"
  fi
else
  echo "gateway not running at ${GW} (skip e2e)"
fi

echo "== eval harness =="
/opt/vajra/.venv/bin/python -m canon.eval.run_eval --k 5 \
  --report "/opt/vajra/data/logs/canon_eval_verify_$(date +%Y%m%d).json"

echo "OK"
