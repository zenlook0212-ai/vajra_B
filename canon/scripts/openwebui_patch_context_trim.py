"""Patch Open WebUI: trim chat history for qwen35b (max-model-len 8192)."""
from __future__ import annotations

import os
import sys
from pathlib import Path

MIDDLEWARE = Path("/app/backend/open_webui/utils/middleware.py")
MARKER = "# vajra: trim context for 8192-token models"

HELPER_BLOCK = '''
# vajra: context trim helpers (qwen35b max-model-len=8192)
def _vajra_msg_text(content):
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for p in content:
            if isinstance(p, dict):
                t = p.get("type")
                if t in ("text", "output_text"):
                    parts.append(str(p.get("text") or ""))
                elif t == "tool_result":
                    parts.append(str(p.get("content") or p.get("text") or ""))
        return "".join(parts)
    return str(content or "")


def _vajra_msgs_token_est(messages):
    total = 0
    for m in messages or []:
        total += max(1, len(_vajra_msg_text(m.get("content"))) // 2)
    return total


def _vajra_trim_messages(messages, budget=6800):
    if not messages:
        return messages
    if _vajra_msgs_token_est(messages) <= budget:
        return messages
    system = [m for m in messages if m.get("role") == "system"]
    rest = [m for m in messages if m.get("role") != "system"]
    while len(rest) > 2 and _vajra_msgs_token_est(system + rest) > budget:
        rest.pop(0)
    out = system + rest
    while _vajra_msgs_token_est(out) > budget and rest:
        trimmed = False
        for m in rest:
            c = m.get("content")
            if isinstance(c, str) and len(c) > 800:
                m["content"] = c[: min(2400, len(c) // 2)] + "\\n…（為符合 8192 context，中段對話已裁剪）"
                trimmed = True
                break
        if not trimmed and len(rest) > 1:
            rest.pop(0)
        else:
            break
        out = system + rest
    return out

'''

INJECT_AFTER = "    form_data = apply_params_to_form_data(form_data, model)"
INJECT_BLOCK = f"""    form_data = apply_params_to_form_data(form_data, model)
    {MARKER}
    _vajra_mid = str(form_data.get('model') or model.get('id') or '')
    if _vajra_mid.startswith('qwen35b'):
        _vajra_budget = int(os.environ.get('VAJRA_WEBUI_CTX_BUDGET', '6800'))
        form_data['messages'] = _vajra_trim_messages(form_data.get('messages') or [], _vajra_budget)
        if not form_data.get('max_tokens'):
            form_data['max_tokens'] = int(os.environ.get('VAJRA_WEBUI_MAX_TOKENS', '512'))"""


def main() -> None:
    if not MIDDLEWARE.is_file():
        print(f"ERROR: {MIDDLEWARE} not found", file=sys.stderr)
        sys.exit(1)

    text = MIDDLEWARE.read_text(encoding="utf-8")
    if MARKER in text:
        print("already patched context trim", MIDDLEWARE)
        return

    if "def _vajra_trim_messages" not in text:
        anchor = "# vajra: canon RAG passthrough"
        if anchor not in text:
            print("ERROR: vajra passthrough anchor not found", file=sys.stderr)
            sys.exit(1)
        text = text.replace(anchor, HELPER_BLOCK.strip() + "\n\n" + anchor, 1)

    if INJECT_AFTER not in text:
        print("ERROR: apply_params_to_form_data anchor not found", file=sys.stderr)
        sys.exit(1)
    text = text.replace(INJECT_AFTER, INJECT_BLOCK, 1)

    if "import os\n" not in text[:800] and "import os" not in text.split("\n")[:30]:
        text = "import os\n" + text

    MIDDLEWARE.write_text(text, encoding="utf-8")
    print("patched context trim", MIDDLEWARE)


if __name__ == "__main__":
    main()
