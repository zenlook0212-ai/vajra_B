#!/usr/bin/env bash
# Canon RAG go-live acceptance: service health + A/B/D gateway smoke.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
GW="${VAJRA_GATEWAY_URL:-http://127.0.0.1:8081}"
LOG_DIR="${ROOT}/data/logs"
STAMP="$(date +%Y%m%d)"
REPORT="${LOG_DIR}/go_live_${STAMP}.json"
TIMEOUT="${VAJRA_GO_LIVE_TIMEOUT:-180}"

mkdir -p "${LOG_DIR}"

failures=0

log() { echo "$*"; }

check_health() {
  local name="$1" url="$2"
  if curl -sf -m 10 "${url}" >/dev/null; then
    log "OK  ${name}"
    return 0
  fi
  log "FAIL ${name} (${url})"
  failures=$((failures + 1))
  return 1
}

log "== service health =="
check_health "embed :8005" "http://127.0.0.1:8005/health" || true
check_health "rerank :8007" "http://127.0.0.1:8007/health" || true
check_health "gateway :8081" "${GW}/v1/modes" || true
check_health "open-webui :3000" "http://127.0.0.1:3000/health" || true
if curl -sf -m 10 "http://127.0.0.1:8003/health" >/dev/null 2>&1; then
  log "OK  qwen35b :8003"
else
  log "WARN qwen35b :8003 (canon_rag synthesis may fail)"
fi

if ! curl -sf -m 10 "${GW}/v1/modes" | grep -q canon_rag; then
  log "FAIL gateway missing canon_rag mode"
  failures=$((failures + 1))
fi

log ""
log "== A/B/D acceptance =="

export GW TIMEOUT failures REPORT
python3 - <<'PY'
import json
import os
import re
import subprocess
import sys
import time
from urllib import request

GW = os.environ["GW"]
TIMEOUT = int(os.environ.get("TIMEOUT", "180"))
failures = int(os.environ.get("failures", "0"))

CASES = [
    ("A", "長阿含經序提到如來出世的大教有幾種？"),
    ("B", "金剛般若波羅蜜經如何說應無所住而生其心？"),
    ("D", "佛經中如何說四諦？"),
]

results = []

def post_task(question: str) -> dict:
    body = json.dumps(
        {"mode": "canon_rag", "channel": "web", "message": question},
        ensure_ascii=False,
    ).encode("utf-8")
    req = request.Request(
        f"{GW}/v1/task",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with request.urlopen(req, timeout=TIMEOUT) as resp:
        return json.loads(resp.read().decode("utf-8"))


def evaluate(cat: str, data: dict) -> dict:
    out = data.get("output", {})
    ans = out.get("answer", "")
    hits = data.get("meta", {}).get("rag", {}).get("hits", 0)
    links = out.get("similar_sutra_links", [])
    checks = {
        "hits_ge_3": hits >= 3,
        "has_t_coord": "【T" in ans,
        "no_thinking": not re.search(r"thinking process", ans, re.I),
    }
    if cat == "B":
        checks["t08_series"] = "T08" in ans or any(
            "T08" in str(x.get("label", "")) for x in links
        )
    else:
        checks["t08_series"] = True
    return {
        "cat": cat,
        "pass": all(checks.values()),
        "hits": hits,
        "answer_len": len(ans),
        "checks": checks,
        "preview": ans[:240],
    }


for cat, question in CASES:
    print(f"\n== test {cat} ==")
    try:
        data = post_task(question)
        row = evaluate(cat, data)
    except Exception as exc:
        row = {"cat": cat, "pass": False, "error": str(exc)}
    results.append(row)
    print(json.dumps(row, ensure_ascii=False, indent=2))
    if not row.get("pass"):
        failures += 1

report = {
    "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
    "gateway": GW,
    "failures": failures,
    "results": results,
}
report_path = os.environ["REPORT"]
with open(report_path, "w", encoding="utf-8") as f:
    json.dump(report, f, ensure_ascii=False, indent=2)
print(f"\nreport: {report_path}")

print(f"\n{'ALL PASS' if failures == 0 else f'FAILED ({failures} checks)'}")
sys.exit(1 if failures else 0)
PY
