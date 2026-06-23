"""Install CBETA Canon RAG tool into Open WebUI SQLite (run inside container)."""
import asyncio
import json
import os
import sqlite3
import sys
import time

sys.path.insert(0, "/app/backend")
os.environ["WEBUI_SECRET_KEY"] = open("/app/backend/.webui_secret_key").read().strip()

from open_webui.utils.tools import get_tool_specs, load_tool_module_by_id

TOOL_PATH = "/tmp/openwebui_canon_rag.py"
CONTENT = open(TOOL_PATH).read()
if "title:" not in CONTENT.split("\n", 1)[0]:
    CONTENT = '"""\ntitle: CBETA Canon RAG\nauthor: vajra\nversion: 0.1.0\n"""\n' + CONTENT


async def main() -> None:
    tool_id = "cbeta_canon_rag"
    mod, fm = await load_tool_module_by_id(tool_id, content=CONTENT)
    specs = get_tool_specs(mod)
    conn = sqlite3.connect("/app/backend/data/webui.db")
    cur = conn.cursor()
    cur.execute("SELECT id FROM user WHERE role=? LIMIT 1", ("admin",))
    user_id = cur.fetchone()[0]
    now = int(time.time())
    meta = json.dumps(
        {"description": "CBETA Canon RAG via Vajra gateway", "manifest": fm},
        ensure_ascii=False,
    )
    specs_json = json.dumps(specs, ensure_ascii=False)
    cur.execute("SELECT id FROM tool WHERE id=?", (tool_id,))
    if cur.fetchone():
        cur.execute(
            "UPDATE tool SET content=?, specs=?, meta=?, updated_at=? WHERE id=?",
            (CONTENT, specs_json, meta, now, tool_id),
        )
        print("updated", tool_id)
    else:
        cur.execute(
            "INSERT INTO tool (id,user_id,name,content,specs,meta,valves,updated_at,created_at) VALUES (?,?,?,?,?,?,?,?,?)",
            (tool_id, user_id, "CBETA Canon RAG", CONTENT, specs_json, meta, "{}", now, now),
        )
        print("inserted", tool_id)
    conn.commit()


if __name__ == "__main__":
    asyncio.run(main())
