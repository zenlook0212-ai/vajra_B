"""Synthesis prompts with mandatory CBETA coordinate citations."""

from __future__ import annotations

from typing import Any

SYSTEM_PROMPT = """你是佛典研究助手。回答時必須引用原文，格式：
【T01n0001_p0001a05】（大正藏坐標：卷冊頁欄行）
若找不到充分依據，明確說「現有語料不足以確認」。
勿捏造經名、章節或坐標。"""

_NO_THINKING_RULES = (
    "禁止輸出任何內部思考、草稿或規劃步驟；"
    "不得輸出例如 Here's a thinking process、Analyze User Input、"
    "Draft Response、Check Against Constraints、redacted_thinking 等內容。"
    "回覆第一行必須直接是給使用者的繁體中文正文。"
)


def build_canon_synth_prompt(user_message: str, snippets: list[dict[str, Any]]) -> str:
    blocks: list[str] = []
    for i, sn in enumerate(snippets, start=1):
        meta = sn.get("metadata") or {}
        coord = meta.get("coord_start") or meta.get("coord") or ""
        canon = meta.get("canon_id") or ""
        ref = f"【{coord}】({canon})" if coord else f"({canon})" if canon else ""
        excerpt = sn.get("text", "")
        blocks.append(f"[片段{i}]{ref}\n{excerpt}")

    corpus = "\n\n---\n\n".join(blocks).strip()
    return (
        f"使用者問題：\n{user_message.strip()}\n\n"
        f"以下是從 CBETA 語料檢索到的相關片段；請僅在有依據時引用，"
        f"引用時使用片段中的坐標格式。\n\n{corpus}\n\n請以繁體中文作答。"
    )


def build_canon_synth_prompt_d_class(
    user_message: str, snippets: list[dict[str, Any]]
) -> str:
    """One-shot structured synthesis for open doctrine (D-class) questions."""
    blocks: list[str] = []
    for i, sn in enumerate(snippets, start=1):
        meta = sn.get("metadata") or {}
        coord = meta.get("coord_start") or meta.get("coord") or ""
        canon = meta.get("canon_id") or ""
        ref = f"【{coord}】({canon})" if coord else f"({canon})" if canon else ""
        excerpt = sn.get("text", "")
        blocks.append(f"[片段{i}]{ref}\n{excerpt}")

    corpus = "\n\n---\n\n".join(blocks).strip()
    return (
        f"使用者問題：\n{user_message.strip()}\n\n"
        f"以下是從漢文大藏經檢索到的相關段落（附 CBETA 坐標）。\n\n{corpus}\n\n"
        "請在一次回答中完成以下結構（使用繁體中文）：\n"
        "1. 【義理面向】列出 2–4 個面向標籤（如定義、修行、對治煩惱），"
        "每面向用 2–3 句概括，句末標明所依坐標。\n"
        "2. 【綜合回答】整合以上面向，不超過 400 字；各要點後附坐標引用。\n"
        "3. 若不同經典觀點有差異，請如實指出；勿捏造未出現在片段中的內容。\n"
        "4. 勿使用「根據以上段落」等空洞開場。"
    )


def synthesizer_system_message(*, query_type: str = "A") -> str:
    base = SYSTEM_PROMPT + "\n" + _NO_THINKING_RULES
    if query_type == "D":
        return (
            base
            + "\n開放義理題：先分面向再綜合，務必標明 CBETA 坐標；"
            "僅依檢索片段作答。"
        )
    return base
