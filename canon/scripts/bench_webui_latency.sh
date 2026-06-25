#!/usr/bin/env bash
# Measure Canon RAG latency: gateway direct + qwen35b single tool round-trip.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
GW="${VAJRA_GATEWAY_URL:-http://127.0.0.1:8081}"
QWEN="${VAJRA_QWEN_URL:-http://127.0.0.1:8003/v1}"
LOG_DIR="${ROOT}/data/logs"
STAMP="$(date +%Y%m%d)"
REPORT="${LOG_DIR}/latency_${STAMP}.json"
QUESTION="${1:-長阿含經序提到如來出世的大教有幾種？}"

mkdir -p "${LOG_DIR}"

export GW QWEN QUESTION REPORT
python3 - <<'PY'
import json
import os
import time
from urllib import request

GW = os.environ["GW"]
QWEN = os.environ["QWEN"]
QUESTION = os.environ["QUESTION"]
REPORT = os.environ["REPORT"]


def post(url: str, body: dict, timeout: int = 300) -> tuple[dict, float]:
    data = json.dumps(body, ensure_ascii=False).encode("utf-8")
    req = request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    t0 = time.perf_counter()
    with request.urlopen(req, timeout=timeout) as resp:
        out = json.load(resp)
    return out, time.perf_counter() - t0


results: dict = {"question": QUESTION, "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}

# Gateway direct
try:
    gw_body, gw_sec = post(
        f"{GW}/v1/task",
        {"mode": "canon_rag", "channel": "web", "message": QUESTION},
    )
    ans = gw_body.get("output", {}).get("answer", "")
    hits = gw_body.get("meta", {}).get("rag", {}).get("hits", 0)
    results["gateway"] = {
        "latency_sec": round(gw_sec, 2),
        "hits": hits,
        "has_T01": "【T01" in ans,
        "has_sanjiao": all(x in ans for x in ("禁律", "契經", "法相")),
    }
except Exception as e:
    results["gateway"] = {"error": str(e)}

# qwen35b round 1: single tool call
tool_spec = {
    "type": "function",
    "function": {
        "name": "search_tripitaka",
        "description": "查詢 CBETA 大藏經",
        "parameters": {
            "type": "object",
            "properties": {"question": {"type": "string"}},
            "required": ["question"],
        },
    },
}
try:
    r1, r1_sec = post(
        f"{QWEN}/chat/completions",
        {
            "model": "qwen35b",
            "messages": [{"role": "user", "content": QUESTION}],
            "tools": [tool_spec],
            "tool_choice": "required",
            "parallel_tool_calls": False,
            "chat_template_kwargs": {"enable_thinking": False},
        },
    )
    msg = r1["choices"][0]["message"]
    tool_calls = msg.get("tool_calls") or []
    results["qwen_round1"] = {
        "latency_sec": round(r1_sec, 2),
        "tool_call_count": len(tool_calls),
        "tool_names": [tc.get("function", {}).get("name") for tc in tool_calls],
    }

    if len(tool_calls) == 1:
        args = json.loads(tool_calls[0]["function"]["arguments"])
        gw_body, gw_sec = post(
            f"{GW}/v1/task",
            {"mode": "canon_rag", "channel": "web", "message": args.get("question", QUESTION)},
        )
        tool_text = gw_body.get("output", {}).get("answer", "")
        links = gw_body.get("output", {}).get("similar_sutra_links", [])
        if links:
            tool_text += "\n\n**CBETA 連結**\n" + "\n".join(
                f"- [{x['label']}]({x['url']})" for x in links[:5]
            )
        results["tool_exec"] = {"latency_sec": round(gw_sec, 2)}

        r2, r2_sec = post(
            f"{QWEN}/chat/completions",
            {
                "model": "qwen35b",
                "messages": [
                    {"role": "user", "content": QUESTION},
                    msg,
                    {
                        "role": "tool",
                        "tool_call_id": tool_calls[0]["id"],
                        "name": "search_tripitaka",
                        "content": tool_text,
                    },
                ],
                "tool_choice": "none",
                "chat_template_kwargs": {"enable_thinking": False},
            },
        )
        content = r2["choices"][0]["message"].get("content", "")
        results["qwen_round2"] = {
            "latency_sec": round(r2_sec, 2),
            "content_len": len(content),
            "has_T01": "【T01" in content,
        }
        results["e2e_simulated_sec"] = round(r1_sec + gw_sec + r2_sec, 2)
        results["webui_passthrough_est_sec"] = round(r1_sec + gw_sec, 2)
        results["note"] = (
            "webui_passthrough_est_sec = round1 + gateway; "
            "Open WebUI middleware skips qwen round2 when tool returns 【T…】+ CBETA."
        )
except Exception as e:
    results["qwen_error"] = str(e)

with open(REPORT, "w", encoding="utf-8") as f:
    json.dump(results, f, ensure_ascii=False, indent=2)

print(json.dumps(results, ensure_ascii=False, indent=2))
print(f"\nreport: {REPORT}")
PY
