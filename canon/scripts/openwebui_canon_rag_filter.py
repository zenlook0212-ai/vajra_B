"""
title: Canon RAG Guard
author: vajra
version: 0.2.0
description: Block parametric canon answers without CBETA coords
"""
import re

from pydantic import BaseModel, Field

_CHITCHAT_RE = re.compile(
    r"^(?:"
    r"h+i+h*i|hi+|hello+|hey+|yo+|test+|ok+|okay+|"
    r"你好|您好|嗨|哈[喽囉]|在嗎|在吗|谢谢|謝謝|多谢|多謝|"
    r"再见|再見|拜拜|bye+|good\s*(?:morning|night|bye)|"
    r"你是誰|你是谁|who\s*are\s*you|"
    r"[\U0001F300-\U0001FAFF\s]+"
    r")$",
    re.I,
)

_CANON_SIGNAL_RE = re.compile(
    r"CBETA|cbeta|大藏|大正|T\d{2}|"
    r"佛經|佛经|佛典|藏經|藏经|經文|经藏|律藏|論藏|论藏|契經|"
    r"阿含|般若|金剛|金刚|楞嚴|楞严|華嚴|华严|法華|法华|"
    r"唯識|唯识|八識|八识|四諦|四谛|八正道|"
    r"十二因緣|十二因缘|十二有支|十二緣起|緣起|因緣|"
    r"涅槃|菩薩|菩萨|如來|如来|羅漢|罗汉|比丘|"
    r"戒律|禁律|法相|法眼|禪|禅|定|慧|"
    r"序品|序|卷|品|章|"
    r"《[^》]{1,20}》|"
    r"[\u4e00-\u9fff]{2,}經|[\u4e00-\u9fff]{1,3}經",
    re.I,
)

_SHORT_DOCTRINE_RE = re.compile(
    r"^(?:十二因緣|十二因缘|十二有支|十二緣起|四諦|四谛|八正道|緣起|因緣|涅槃|般若)$",
    re.I,
)

_HALLUCINATION_RE = re.compile(
    r"Nidānas|Twelve\s+Nid|No\.\s*\d+|T\d{2},\s*No\.|"
    r"Ignorance\s+conditions|volitional\s+formations",
    re.I,
)

_GUARD_MSG = (
    "【系統】此回覆未經 CBETA 語料檢索（無【T…】坐標），可能為模型記憶生成，不作考據依據。\n\n"
    "請確認已選 qwen35b · 佛典RAG，並重新發送原問題；"
    "助理將呼叫 search_tripitaka，返回含【義理面向】／【綜合回答】與 CBETA 坐標的內容。"
)


def _is_canon_question(question: str) -> bool:
    q = (question or "").strip()
    if not q:
        return False
    if _CHITCHAT_RE.match(q):
        return False
    if _SHORT_DOCTRINE_RE.match(q):
        return True
    if _CANON_SIGNAL_RE.search(q):
        return True
    if len(q) < 6 and not re.search(r"[\u4e00-\u9fff]{2,}", q):
        return False
    return False


def _message_text(msg: dict) -> str:
    content = msg.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(
            str(x.get("text", "")) for x in content if isinstance(x, dict)
        )
    return ""


def _has_canon_evidence(text: str) -> bool:
    t = text or ""
    if "【T" in t or "cbetaonline.dila.edu.tw" in t.lower():
        return True
    if "我是佛典助理，不閒聊" in t:
        return True
    if "【系統】此回覆未經 CBETA" in t:
        return True
    if "檢視來自 search_tripitaka" in t:
        return True
    return False


def _looks_like_parametric_canon(text: str) -> bool:
    t = text or ""
    if _HALLUCINATION_RE.search(t):
        return True
    if "十二有支" in t and "【T" not in t:
        return True
    if re.search(r"^\d+\.\s*\*\*", t, re.M) and "【T" not in t:
        return True
    if "Twelve" in t or "Nidānas" in t:
        return True
    return False


class Filter:
    class Valves(BaseModel):
        priority: int = Field(default=10, description="Run after other filters")
        enabled: bool = Field(default=True, description="Enable canon outlet guard")

    def __init__(self):
        self.valves = self.Valves()

    def inlet(self, body: dict, __user__: dict | None = None) -> dict:
        return body

    def outlet(self, body: dict, __user__: dict | None = None) -> dict:
        if not self.valves.enabled:
            return body
        messages = body.get("messages") or []
        if not messages:
            return body

        last_user = ""
        for msg in reversed(messages):
            if msg.get("role") == "user":
                last_user = _message_text(msg)
                break
        if not _is_canon_question(last_user):
            return body

        for msg in reversed(messages):
            if msg.get("role") != "assistant":
                continue
            text = _message_text(msg)
            if not text.strip():
                continue
            if _has_canon_evidence(text):
                break
            if _looks_like_parametric_canon(text) or not _has_canon_evidence(text):
                msg["content"] = _GUARD_MSG
            break
        return body
