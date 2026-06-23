"""
Open WebUI Function: CBETA Canon RAG
Copy to Open WebUI Admin → Functions, or mount this file.
"""
import os
import requests

GATEWAY = os.environ.get("VAJRA_GATEWAY_URL", "http://127.0.0.1:8081")


class Tools:
    def search_tripitaka(self, question: str) -> str:
        """查詢 CBETA 大藏經語料，返回答案與 CBETA 連結。"""
        r = requests.post(
            f"{GATEWAY}/v1/task",
            json={
                "mode": "canon_rag",
                "channel": "web",
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
