"""Patch Open WebUI native FC: scope tool_choice for Canon RAG latency.

v1: tool_choice=required on first turn only (vLLM streaming tool_call deltas).
v2: tool_choice=none + empty tools on tool-result continuations (block re-query loops).
"""
from __future__ import annotations

import sys
from pathlib import Path

MIDDLEWARE = Path("/app/backend/open_webui/utils/middleware.py")
MARKER_V1 = "# vajra: native FC tool_choice scope"
MARKER_V2 = "# vajra: block tools after tool result"

INJECT_AFTER = """                if inlet_filter_tools:
                    form_data['tools'].extend(inlet_filter_tools)"""

INJECT_BLOCK = """                if inlet_filter_tools:
                    form_data['tools'].extend(inlet_filter_tools)
                # vajra: native FC tool_choice scope — first turn only for vLLM streaming
                form_data['tool_choice'] = 'required'"""

CONTINUATION_BEFORE = """                    try:
                        new_form_data = {"""

CONTINUATION_V1 = """                    try:
                        form_data.pop('tool_choice', None)  # vajra: native FC tool_choice scope
                        new_form_data = {"""

CONTINUATION_V2 = """                    try:
                        form_data.pop('tool_choice', None)  # vajra: native FC tool_choice scope
                        form_data['tool_choice'] = 'none'  # vajra: block tools after tool result
                        form_data['tools'] = []
                        new_form_data = {"""

CONTINUATION_BEFORE_CI = """                        try:
                            new_form_data = {"""

CONTINUATION_V1_CI = """                        try:
                            form_data.pop('tool_choice', None)  # vajra: native FC tool_choice scope
                            new_form_data = {"""

CONTINUATION_V2_CI = """                        try:
                            form_data.pop('tool_choice', None)  # vajra: native FC tool_choice scope
                            form_data['tool_choice'] = 'none'  # vajra: block tools after tool result
                            form_data['tools'] = []
                            new_form_data = {"""


def main() -> None:
    if not MIDDLEWARE.is_file():
        print(f"ERROR: {MIDDLEWARE} not found", file=sys.stderr)
        sys.exit(1)

    text = MIDDLEWARE.read_text(encoding="utf-8")
    if MARKER_V2 in text:
        print("already patched v2", MIDDLEWARE)
        return

    if MARKER_V1 not in text:
        if INJECT_AFTER not in text:
            print("ERROR: native FC tools anchor not found", file=sys.stderr)
            sys.exit(1)
        text = text.replace(INJECT_AFTER, INJECT_BLOCK, 1)
        if CONTINUATION_BEFORE not in text:
            print("ERROR: tool continuation anchor not found", file=sys.stderr)
            sys.exit(1)
        text = text.replace(CONTINUATION_BEFORE, CONTINUATION_V1, 1)
        if CONTINUATION_BEFORE_CI in text:
            text = text.replace(CONTINUATION_BEFORE_CI, CONTINUATION_V1_CI, 1)

    if CONTINUATION_V1 in text:
        text = text.replace(CONTINUATION_V1, CONTINUATION_V2, 1)
    else:
        print("ERROR: v1 continuation block not found for v2 upgrade", file=sys.stderr)
        sys.exit(1)

    if CONTINUATION_V1_CI in text:
        text = text.replace(CONTINUATION_V1_CI, CONTINUATION_V2_CI, 1)

    MIDDLEWARE.write_text(text, encoding="utf-8")
    print("patched v2", MIDDLEWARE)


if __name__ == "__main__":
    main()
