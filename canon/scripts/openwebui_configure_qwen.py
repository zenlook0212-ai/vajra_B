"""Configure qwen35b workspace model: disable thinking + optional system prompt."""
import json
import sqlite3
import sys
import time

DB = "/app/backend/data/webui.db"

PARAMS = {
    "custom_params": {
        "chat_template_kwargs": {"enable_thinking": False},
    },
    "system": (
        "你是繁體中文助理。禁止輸出任何內部思考、草稿或英文規劃步驟"
        "（例如 thinking process、Analyze User Input、redacted_thinking）。"
        "回覆第一行必須直接是給使用者的正文。"
    ),
}


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
    params_json = json.dumps(PARAMS, ensure_ascii=False)
    meta_json = json.dumps(
        {"description": "qwen35b with thinking disabled for Vajra stack"},
        ensure_ascii=False,
    )
    model_id = "qwen35b"
    cur.execute("SELECT id FROM model WHERE id=?", (model_id,))
    if cur.fetchone():
        cur.execute(
            "UPDATE model SET params=?, meta=?, updated_at=?, is_active=1 WHERE id=?",
            (params_json, meta_json, now, model_id),
        )
        print("updated model", model_id)
    else:
        cur.execute(
            "INSERT INTO model (id,user_id,base_model_id,name,params,meta,updated_at,created_at,is_active) "
            "VALUES (?,?,?,?,?,?,?,?,1)",
            (model_id, user_id, None, "qwen35b", params_json, meta_json, now, now),
        )
        print("inserted model", model_id)
    conn.commit()


if __name__ == "__main__":
    main()
