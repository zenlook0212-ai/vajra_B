"""Patch Open WebUI middleware: bind Canon tools only for on-topic questions."""
from __future__ import annotations

import sys
from pathlib import Path

MIDDLEWARE = Path("/app/backend/open_webui/utils/middleware.py")
MARKER_SCOPE = "# vajra: scope Canon tools to on-topic"
MARKER_BIND = "# vajra: auto-bind model toolIds"

HELPER_INSERT = """import re as _vajra_re

_VAJRA_CHITCHAT_RE = _vajra_re.compile(
    r"^(?:"
    r"h+i+h*i|hi+|hello+|hey+|yo+|test+|ok+|okay+|"
    r"你好|您好|嗨|哈[喽囉]|在嗎|在吗|谢谢|謝謝|多谢|多謝|"
    r"再见|再見|拜拜|bye+|good\\s*(?:morning|night|bye)|"
    r"你是誰|你是谁|who\\s*are\\s*you|"
    r"[\\U0001F300-\\U0001FAFF\\s]+"
    r")$",
    _vajra_re.I,
)
_VAJRA_CANON_SIGNAL_RE = _vajra_re.compile(
    r"CBETA|cbeta|大藏|大正|T\\d{2}|"
    r"佛經|佛经|佛典|藏經|藏经|經文|经藏|律藏|論藏|论藏|契經|"
    r"阿含|般若|金剛|金刚|楞嚴|楞严|華嚴|华严|法華|法华|"
    r"唯識|唯识|八識|八识|四諦|四谛|八正道|十二因緣|十二因缘|"
    r"涅槃|菩薩|菩萨|如來|如来|羅漢|罗汉|比丘|"
    r"戒律|禁律|法相|法眼|禪|禅|定|慧|"
    r"序品|序|卷|品|章|"
    r"《[^》]{1,20}》|"
    r"[\\u4e00-\\u9fff]{2,}經|[\\u4e00-\\u9fff]{1,3}經",
    _vajra_re.I,
)


def _vajra_is_canon_question(question: str) -> bool:
    q = (question or "").strip()
    if not q:
        return False
    if _VAJRA_CHITCHAT_RE.match(q):
        return False
    if _VAJRA_CANON_SIGNAL_RE.search(q):
        return True
    if len(q) < 6 and not _vajra_re.search(r"[\\u4e00-\\u9fff]{2,}", q):
        return False
    return False


"""

SCOPE_INJECT = f"""    if tool_ids:
        _vajra_uq = get_last_user_message(form_data.get('messages', []))
        if _vajra_uq and not _vajra_is_canon_question(_vajra_uq):
            tool_ids = None
            {MARKER_SCOPE}
    terminal_id = form_data.pop('terminal_id', None)"""

SCOPE_ANCHOR = f"""            {MARKER_BIND}
    terminal_id = form_data.pop('terminal_id', None)"""

PASSTHROUGH_ANCHOR = "# vajra: canon RAG passthrough\ndef _vajra_canon_passthrough_text(tool_results):"
PASSTHROUGH_REPLACE = (
    "# vajra: canon RAG passthrough\n" + HELPER_INSERT + "def _vajra_canon_passthrough_text(tool_results):"
)


def main() -> None:
    if not MIDDLEWARE.is_file():
        print(f"ERROR: {MIDDLEWARE} not found", file=sys.stderr)
        sys.exit(1)

    text = MIDDLEWARE.read_text(encoding="utf-8")
    changed = False

    if MARKER_SCOPE not in text:
        if SCOPE_ANCHOR not in text:
            print("ERROR: toolIds bind anchor not found", file=sys.stderr)
            sys.exit(1)
        text = text.replace(SCOPE_ANCHOR, SCOPE_INJECT, 1)
        changed = True
        print("patched canon scope")

    if "def _vajra_is_canon_question" not in text:
        if PASSTHROUGH_ANCHOR not in text:
            print("ERROR: passthrough anchor not found", file=sys.stderr)
            sys.exit(1)
        text = text.replace(PASSTHROUGH_ANCHOR, PASSTHROUGH_REPLACE, 1)
        changed = True
        print("injected _vajra_is_canon_question helper")

    if changed:
        MIDDLEWARE.write_text(text, encoding="utf-8")
    print("canon scope OK", MIDDLEWARE)


if __name__ == "__main__":
    main()
