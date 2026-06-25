#!/usr/bin/env python3
"""Open WebUI E2E latency: real /api/chat/completions with Canon RAG model."""

from __future__ import annotations

import json
import os
import subprocess
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from urllib import error, request

BASE = os.environ.get("OPEN_WEBUI_URL", "http://127.0.0.1:3000")
MODEL = os.environ.get("CANON_RAG_MODEL", "qwen35b")
LOG_DIR = Path(os.environ.get("VAJRA_LOG_DIR", "/opt/vajra/data/logs"))
EMAIL = os.environ.get("OPEN_WEBUI_EMAIL", "zenlook0212@gmail.com")
PASSWORD = os.environ.get("OPEN_WEBUI_PASSWORD", "CanonRag2026!")

CASES = [
    ("A_scoped", "長阿含經序提到如來出世的大教有幾種？"),
    ("D_doctrine", "佛經中如何說四諦？"),
    ("D_cold", "佛經中如何說菩提心？（延遲基準測試）"),
    ("chitchat", "hihi"),
]


def _api_key_from_docker() -> str | None:
    try:
        out = subprocess.check_output(
            [
                "docker",
                "exec",
                os.environ.get("OPEN_WEBUI_CONTAINER", "open-webui"),
                "python3",
                "-c",
                "import sqlite3; c=sqlite3.connect('/app/backend/data/webui.db'); print(c.execute('SELECT key FROM api_key LIMIT 1').fetchone()[0])",
            ],
            stderr=subprocess.DEVNULL,
            timeout=15,
        )
        key = out.decode().strip()
        return key or None
    except (subprocess.SubprocessError, OSError):
        return None


def _token() -> str:
    body = json.dumps({"email": EMAIL, "password": PASSWORD}).encode()
    req = request.Request(
        f"{BASE}/api/v1/auths/signin",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with request.urlopen(req, timeout=30) as resp:
        return json.load(resp)["token"]


def chat(token: str, question: str) -> tuple[dict, float]:
    payload = {
        "model": MODEL,
        "messages": [{"id": str(uuid.uuid4()), "role": "user", "content": question}],
        "stream": False,
    }
    data = json.dumps(payload, ensure_ascii=False).encode()
    req = request.Request(
        f"{BASE}/api/chat/completions",
        data=data,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {token}",
        },
        method="POST",
    )
    t0 = time.perf_counter()
    with request.urlopen(req, timeout=600) as resp:
        out = json.load(resp)
    return out, time.perf_counter() - t0


def analyze(case_id: str, question: str, resp: dict, latency: float) -> dict:
    msg = (resp.get("choices") or [{}])[0].get("message") or {}
    content = msg.get("content") or ""
    tool_calls = msg.get("tool_calls") or []
    err = resp.get("detail") or resp.get("error")
    return {
        "case": case_id,
        "question": question,
        "latency_sec": round(latency, 2),
        "content_len": len(content),
        "tool_call_count": len(tool_calls),
        "has_T_coord": "【T" in content,
        "has_cbeta_link": "cbetaonline.dila.edu.tw" in content,
        "is_refusal": "不閒聊" in content,
        "error": str(err) if err and not content else None,
        "preview": content[:220].replace("\n", " "),
    }


def main() -> int:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d")
    report_path = LOG_DIR / f"webui_e2e_latency_{stamp}.json"
    LOG_DIR.mkdir(parents=True, exist_ok=True)

    try:
        token = _token()
    except error.URLError as exc:
        out = {"error": f"auth failed: {exc}", "base": BASE}
        report_path.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(out, ensure_ascii=False, indent=2))
        return 1

    results: dict = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "base": BASE,
        "model": MODEL,
        "cases": [],
    }

    for case_id, question in CASES:
        try:
            resp, sec = chat(token, question)
            row = analyze(case_id, question, resp, sec)
        except error.URLError as exc:
            row = {
                "case": case_id,
                "question": question,
                "latency_sec": None,
                "error": str(exc),
            }
        results["cases"].append(row)
        print(json.dumps(row, ensure_ascii=False))

    latencies = [c["latency_sec"] for c in results["cases"] if c.get("latency_sec")]
    if latencies:
        results["summary"] = {
            "n": len(latencies),
            "min_sec": round(min(latencies), 2),
            "max_sec": round(max(latencies), 2),
            "avg_sec": round(sum(latencies) / len(latencies), 2),
        }

    report_path.write_text(
        json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"\nreport: {report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
