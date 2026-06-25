"""Install Canon RAG outlet guard as global Open WebUI filter."""
import json
import sqlite3
import sys
import time

FILTER_ID = "canon_rag_guard"
FILTER_PATH = "/tmp/openwebui_canon_rag_filter.py"
DB = "/app/backend/data/webui.db"

CONTENT = open(FILTER_PATH, encoding="utf-8").read()
if "title:" not in CONTENT:
    CONTENT = (
        '"""\n'
        "title: Canon RAG Guard\n"
        "author: vajra\n"
        "version: 0.1.0\n"
        '"""\n' + CONTENT
    )


def main() -> None:
    conn = sqlite3.connect(DB)
    cur = conn.cursor()
    cur.execute("SELECT id FROM user WHERE role=? LIMIT 1", ("admin",))
    row = cur.fetchone()
    if not row:
        print("ERROR: no admin user", file=sys.stderr)
        sys.exit(1)
    user_id = row[0]
    now = int(time.time())
    meta = json.dumps(
        {
            "description": "Block parametric canon answers without CBETA coords",
            "manifest": {
                "title": "Canon RAG Guard",
                "author": "vajra",
                "version": "0.1.0",
            },
        },
        ensure_ascii=False,
    )
    cur.execute("SELECT id FROM function WHERE id=?", (FILTER_ID,))
    if cur.fetchone():
        cur.execute(
            "UPDATE function SET content=?, meta=?, type=?, is_active=1, is_global=1, updated_at=? WHERE id=?",
            (CONTENT, meta, "filter", now, FILTER_ID),
        )
        print("updated filter", FILTER_ID)
    else:
        cur.execute(
            "INSERT INTO function "
            "(id,user_id,name,type,content,meta,valves,is_active,is_global,created_at,updated_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (
                FILTER_ID,
                user_id,
                "Canon RAG Guard",
                "filter",
                CONTENT,
                meta,
                "{}",
                1,
                1,
                now,
                now,
            ),
        )
        print("inserted filter", FILTER_ID)
    conn.commit()


if __name__ == "__main__":
    main()
