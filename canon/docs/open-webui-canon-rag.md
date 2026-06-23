# Open WebUI — CBETA canon RAG 接入

方案 B 閘道端點：`POST /v1/task`（Vajra gateway 預設 **8081**；本機 8080 常被其他服務佔用）。

## 環境變數（閘道主機）

```bash
export VAJRA_CANON_PG_DSN=postgresql://vajra:vajra@127.0.0.1:5433/canon
export VAJRA_GATEWAY_URL=http://127.0.0.1:8081
export VAJRA_HERMES_CANON_RAG=on_demand
```

## 方式 A：Open WebUI Function / Tool（推薦）

在 Open WebUI Admin → Functions 新增：

```python
"""
title: CBETA Canon RAG
author: vajra
version: 0.1.0
"""
import os
import requests

GATEWAY = os.environ.get("VAJRA_GATEWAY_URL", "http://127.0.0.1:8081")


class Tools:
    def search_tripitaka(self, question: str) -> str:
        """查詢 CBETA 大藏經語料並返回答案與引用。"""
        r = requests.post(
            f"{GATEWAY}/v1/task",
            json={
                "mode": "canon_rag",
                "channel": "web_public_hermes",
                "message": question,
            },
            timeout=300,
        )
        r.raise_for_status()
        data = r.json()
        out = data.get("output", {})
        answer = out.get("answer", "")
        links = out.get("similar_sutra_links", [])
        link_txt = "\n".join(f"- [{x['label']}]({x['url']})" for x in links[:5])
        return f"{answer}\n\n**CBETA 連結**\n{link_txt}" if link_txt else answer
```

## 方式 B：第二 API 連線

若閘道提供 OpenAI-compatible 代理，可在 Open WebUI → Settings → Connections 新增 Base URL。

## 每週 eval

```bash
0 3 * * 0 cd /opt/vajra && PYTHONPATH=/opt/vajra python -m canon.eval.run_eval --report /opt/vajra/data/logs/canon_eval.json
```

見 [`canon/scripts/weekly_eval.sh`](canon/scripts/weekly_eval.sh)。
