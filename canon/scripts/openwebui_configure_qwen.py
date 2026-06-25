"""Configure qwen35b workspace models: Canon RAG + thinking variant."""
import json
import sqlite3
import sys
import time

DB = "/app/backend/data/webui.db"

MODELS = [
    {
        "id": "qwen35b",
        "base_model_id": None,
        "name": "qwen35b · 佛典RAG",
        "params": {
            "function_calling": "native",
            "custom_params": {
                "chat_template_kwargs": {"enable_thinking": False},
                "parallel_tool_calls": False,
            },
            "system": (
                "你是繁體中文佛典助理。禁止輸出 thinking process 等內部思考。"
                "本模型僅回答佛經、大藏經、CBETA 考據。"
                "若使用者問題非佛典考據（閒聊、打招呼等），直接回覆："
                "「我是佛典助理，不閒聊。請問大藏經、CBETA 或某部經的內容／出處／義理。」"
                "禁止呼叫任何工具。"
                "當使用者問佛經、大藏經、CBETA、佛典義理（含「十二因緣」「四諦」「緣起」等簡短術語）時，"
                "若問題是要「列出全藏出處」「還有哪些經」「經目列表」等，"
                "呼叫 list_tripitaka_occurrences（keyword 用核心詞，如十二因緣、四諦）；"
                "其餘義理綜述題呼叫 search_tripitaka。"
                "不可憑記憶捏造經文、經號或英文譯名。"
                "禁止不經工具直接列出十二有支、Nidānas、T06 No.378 等百科式內容。"
                "義理題只允許呼叫 search_tripitaka 一次；question 參數必須使用使用者完整原問，"
                "禁止改寫關鍵詞（如序品、法教）後重複呼叫。"
                "若 search_tripitaka 或 list_tripitaka_occurrences 已返回含【T…】坐標與 CBETA 連結的內容，"
                "原樣輸出（僅可排版），禁止改寫經文、坐標或連結，禁止再次呼叫任何工具。"
            ),
        },
        "meta": {
            "description": "佛典 RAG（thinking 關）— 義理綜述 + 全藏出處表；逐條全文請用 CBETA Online",
            "toolIds": ["cbeta_canon_rag"],
            "capabilities": {"builtin_tools": False},
        },
    },
    {
        "id": "qwen35b-thinking",
        "base_model_id": "qwen35b",
        "name": "qwen35b · 深度推理",
        "params": {
            "custom_params": {
                "chat_template_kwargs": {"enable_thinking": True},
            },
            "system": (
                "你是繁體中文助理。可使用內部思考輔助推理，但最終回覆請以繁體中文正文呈現。"
                "本模型無 CBETA 檢索工具。"
                "若問題涉及佛經、大藏經、十二因緣、四諦、緣起、CBETA 考據，"
                "不得自行回答或列出十二有支／英文譯名／經號；"
                "請回覆：「佛典考據請改用 qwen35b · 佛典RAG 模型（含 search_tripitaka）。」"
            ),
        },
        "meta": {
            "description": "深度推理（thinking 開）— 一般難題；佛典考據請選「qwen35b · 佛典RAG」",
            "capabilities": {"builtin_tools": False},
        },
    },
]


def upsert_model(
    cur: sqlite3.Cursor,
    *,
    user_id: str,
    model_id: str,
    base_model_id: str | None,
    name: str,
    params: dict,
    meta: dict,
    now: int,
) -> None:
    params_json = json.dumps(params, ensure_ascii=False)
    meta_json = json.dumps(meta, ensure_ascii=False)
    cur.execute("SELECT id FROM model WHERE id=?", (model_id,))
    if cur.fetchone():
        cur.execute(
            "UPDATE model SET base_model_id=?, name=?, params=?, meta=?, updated_at=?, is_active=1 WHERE id=?",
            (base_model_id, name, params_json, meta_json, now, model_id),
        )
        print("updated model", model_id)
    else:
        cur.execute(
            "INSERT INTO model (id,user_id,base_model_id,name,params,meta,updated_at,created_at,is_active) "
            "VALUES (?,?,?,?,?,?,?,?,1)",
            (model_id, user_id, base_model_id, name, params_json, meta_json, now, now),
        )
        print("inserted model", model_id)


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
    for spec in MODELS:
        upsert_model(
            cur,
            user_id=user_id,
            model_id=spec["id"],
            base_model_id=spec["base_model_id"],
            name=spec["name"],
            params=spec["params"],
            meta=spec["meta"],
            now=now,
        )
    conn.commit()


if __name__ == "__main__":
    main()
