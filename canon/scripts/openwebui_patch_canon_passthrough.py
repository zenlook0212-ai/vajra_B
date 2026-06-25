"""Patch Open WebUI middleware: passthrough Canon RAG tool output (skip LLM round 2).

When search_tripitaka returns text with CBETA coords + links, emit it directly
instead of calling generate_chat_completion again (~20-25s saved).
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

MIDDLEWARE = Path("/app/backend/open_webui/utils/middleware.py")
MARKER = "# vajra: canon RAG passthrough"

HELPER_ANCHOR = "async def streaming_chat_response_handler(response, ctx):"

HELPER_BLOCK = """# vajra: canon RAG passthrough
def _vajra_canon_passthrough_text(tool_results):
    for r in tool_results:
        txt = str(r.get('content') or '')
        low = txt.lower()
        if '【T' in txt or 'cbetaonline.dila.edu.tw' in low:
            return txt
    return None


async def streaming_chat_response_handler(response, ctx):"""

OLD_HELPER_RE = re.compile(
    r"# vajra: canon RAG passthrough\ndef _vajra_canon_passthrough_text\(tool_results\):.*?return None\n\n",
    re.DOTALL,
)

GEN_CC_FULL = """                        res = await generate_chat_completion(
                            request,
                            new_form_data,
                            user,
                            bypass_system_prompt=True,
                        )"""

GEN_CC_FULL_CI = """                            res = await generate_chat_completion(
                                request,
                                new_form_data,
                                user,
                                bypass_system_prompt=True,
                            )"""

GEN_CC_BROKEN = """                        res = await generate_chat_completion(

                        if isinstance(res, StreamingResponse):"""

GEN_CC_BROKEN_CI = """                            res = await generate_chat_completion(

                            if isinstance(res, StreamingResponse):"""

PASSTHROUGH_BODY = """                        _vajra_pt = _vajra_canon_passthrough_text(results)
                        if _vajra_pt is not None:
                            for _item in reversed(output):
                                if _item.get('type') == 'message':
                                    _item['content'] = [{'type': 'output_text', 'text': _vajra_pt}]
                                    _item['status'] = 'completed'
                                    break
                            else:
                                output.append(
                                    {
                                        'type': 'message',
                                        'id': output_id('msg'),
                                        'status': 'completed',
                                        'role': 'assistant',
                                        'content': [{'type': 'output_text', 'text': _vajra_pt}],
                                    }
                                )
                            tool_calls.clear()
                            await event_emitter(
                                {
                                    'type': 'chat:completion',
                                    'data': {
                                        'content': serialize_output(output),
                                        'output': output,
                                    },
                                }
                            )
                            break

"""

PASSTHROUGH_BODY_CI = PASSTHROUGH_BODY.replace("                        ", "                            ")

OLD_PASSTHROUGH_RE = re.compile(
    r" {24}_vajra_pt = _vajra_canon_passthrough_text\(results\).*? {24}break\n\n",
    re.DOTALL,
)

OLD_PASSTHROUGH_CI_RE = re.compile(
    r" {28}_vajra_pt = _vajra_canon_passthrough_text\(results\).*? {28}break\n\n",
    re.DOTALL,
)


def _upgrade_passthrough_blocks(text: str) -> tuple[str, bool]:
    changed = False
    if OLD_PASSTHROUGH_RE.search(text):
        text = OLD_PASSTHROUGH_RE.sub(PASSTHROUGH_BODY, text, count=1)
        changed = True
    if OLD_PASSTHROUGH_CI_RE.search(text):
        text = OLD_PASSTHROUGH_CI_RE.sub(PASSTHROUGH_BODY_CI, text, count=1)
        changed = True
    return text, changed


def main() -> None:
    if not MIDDLEWARE.is_file():
        print(f"ERROR: {MIDDLEWARE} not found", file=sys.stderr)
        sys.exit(1)

    text = MIDDLEWARE.read_text(encoding="utf-8")
    changed = False

    # Repair truncated generate_chat_completion from a bad prior patch.
    if GEN_CC_BROKEN in text:
        text = text.replace(
            GEN_CC_BROKEN,
            GEN_CC_FULL + "\n\n                        if isinstance(res, StreamingResponse):",
            1,
        )
        changed = True
        print("repaired truncated generate_chat_completion (main)")
    if GEN_CC_BROKEN_CI in text:
        text = text.replace(
            GEN_CC_BROKEN_CI,
            GEN_CC_FULL_CI + "\n\n                            if isinstance(res, StreamingResponse):",
            1,
        )
        changed = True
        print("repaired truncated generate_chat_completion (ci)")

    if OLD_HELPER_RE.search(text):
        text = OLD_HELPER_RE.sub(HELPER_BLOCK.split("async def")[0], text, count=1)
        changed = True
        print("upgraded passthrough matcher")

    text, upgraded = _upgrade_passthrough_blocks(text)
    if upgraded:
        changed = True
        print("upgraded passthrough emit block")

    if MARKER in text and "_vajra_canon_passthrough_text" in text:
        if PASSTHROUGH_BODY.strip() in text and "'cbetaonline.dila.edu.tw'" in text:
            if changed:
                MIDDLEWARE.write_text(text, encoding="utf-8")
                print("upgraded passthrough", MIDDLEWARE)
            else:
                print("already patched passthrough", MIDDLEWARE)
            return

    if MARKER not in text:
        if HELPER_ANCHOR not in text:
            print("ERROR: streaming_chat_response_handler anchor not found", file=sys.stderr)
            sys.exit(1)
        text = text.replace(HELPER_ANCHOR, HELPER_BLOCK, 1)
        changed = True

    if PASSTHROUGH_BODY.strip() not in text:
        if GEN_CC_FULL not in text:
            print("ERROR: generate_chat_completion anchor (tool loop) not found", file=sys.stderr)
            sys.exit(1)
        text = text.replace(GEN_CC_FULL, PASSTHROUGH_BODY + GEN_CC_FULL, 1)
        changed = True

    if PASSTHROUGH_BODY_CI.strip() not in text:
        if GEN_CC_FULL_CI not in text:
            print("ERROR: generate_chat_completion anchor (CI loop) not found", file=sys.stderr)
            sys.exit(1)
        text = text.replace(GEN_CC_FULL_CI, PASSTHROUGH_BODY_CI + GEN_CC_FULL_CI, 1)
        changed = True

    MIDDLEWARE.write_text(text, encoding="utf-8")
    print("patched passthrough", MIDDLEWARE)


if __name__ == "__main__":
    main()
