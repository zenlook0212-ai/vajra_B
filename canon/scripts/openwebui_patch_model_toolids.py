"""Patch Open WebUI middleware: auto-bind model meta toolIds.

The frontend sends tool_ids from model.info.meta.toolIds (Chat.svelte), but the
backend never merges them when tool_ids is missing. Without this, qwen35b chats
skip Canon RAG and the model hallucinates instead of calling search_tripitaka.
"""
from __future__ import annotations

import sys
from pathlib import Path

MIDDLEWARE = Path("/app/backend/open_webui/utils/middleware.py")
MARKER = "# vajra: auto-bind model toolIds"

ANCHOR = "    tool_ids = form_data.pop('tool_ids', None)"
INJECT = f"""    tool_ids = form_data.pop('tool_ids', None)
    if not tool_ids:
        _vajra_meta_tools = (model.get('info', {{}}) or {{}}).get('meta', {{}}).get('toolIds') or []
        if _vajra_meta_tools:
            tool_ids = list(_vajra_meta_tools)
            {MARKER}"""


def main() -> None:
    if not MIDDLEWARE.is_file():
        print(f"ERROR: {MIDDLEWARE} not found", file=sys.stderr)
        sys.exit(1)

    text = MIDDLEWARE.read_text(encoding="utf-8")
    if MARKER in text:
        print("already patched model toolIds", MIDDLEWARE)
        return

    if ANCHOR not in text:
        print("ERROR: tool_ids anchor not found", file=sys.stderr)
        sys.exit(1)

    text = text.replace(ANCHOR, INJECT, 1)
    MIDDLEWARE.write_text(text, encoding="utf-8")
    print("patched model toolIds", MIDDLEWARE)


if __name__ == "__main__":
    main()
