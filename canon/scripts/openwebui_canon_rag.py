"""
Open WebUI Function: CBETA Canon RAG
Copy to Open WebUI Admin → Functions, or mount this file.
"""
import os
import re

import requests

_BOLD_RE = re.compile(r"\*\*(.+?)\*\*", re.DOTALL)
_ITALIC_UNDERSCORE_RE = re.compile(r"(?<!\w)_(.+?)_(?!\w)", re.DOTALL)
_ATX_HEADING_RE = re.compile(r"^#{1,6}\s+", re.MULTILINE)
_HR_RE = re.compile(r"^\s*---+\s*$", re.MULTILINE)


def _sanitize_display_markdown(text: str) -> str:
    if not text:
        return text
    out = text
    for _ in range(8):
        nxt = _BOLD_RE.sub(r"\1", out)
        if nxt == out:
            break
        out = nxt
    for _ in range(8):
        nxt = _ITALIC_UNDERSCORE_RE.sub(r"\1", out)
        if nxt == out:
            break
        out = nxt
    out = _ATX_HEADING_RE.sub("", out)
    out = _HR_RE.sub("", out)
    return re.sub(r"\n{3,}", "\n\n", out).strip()

GATEWAY = os.environ.get("VAJRA_GATEWAY_URL", "http://127.0.0.1:8081")

REFUSAL = "我是佛典助理，不閒聊。請問大藏經、CBETA 或某部經的內容／出處／義理。"

# Obvious greetings / small talk — never worth a gateway round-trip.
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

# Enough signal that the user is asking about canon / Buddhist texts.
_CANON_SIGNAL_RE = re.compile(
    r"CBETA|cbeta|大藏|大正|T\d{2}|"
    r"佛經|佛经|佛典|藏經|藏经|經文|经藏|律藏|論藏|论藏|契經|"
    r"阿含|般若|金剛|金刚|楞嚴|楞严|華嚴|华严|法華|法华|"
    r"唯識|唯识|八識|八识|四諦|四谛|八正道|十二因緣|十二因缘|十二有支|十二緣起|緣起|因緣|"
    r"涅槃|菩薩|菩萨|如來|如来|羅漢|罗汉|比丘|"
    r"戒律|禁律|法相|法眼|禪|禅|定|慧|"
    r"序品|序|卷|品|章|"
    r"《[^》]{1,20}》|"  # sutra title in book quotes
    r"[\u4e00-\u9fff]{2,}經|[\u4e00-\u9fff]{1,3}經",
    re.I,
)

_COORD_CITE_RE = re.compile(r"【([A-Z]{1,3}\d+n\d+_[^】]+)】", re.I)
# Trailing junk after valid p####[abc]## (e.g. p0195b14P -> p0195b14)
_COORD_TAIL_RE = re.compile(
    r"^(T\d+n\d+_p\d+)([abc])(\d+)([^abc\d_].*)$",
    re.I,
)


def _sanitize_coord(inner: str) -> str:
    m = _COORD_TAIL_RE.match(inner.strip())
    if m:
        return f"{m.group(1)}{m.group(2)}{m.group(3)}"
    return inner.rstrip("_")


def sanitize_citations(text: str) -> str:
    def repl(match: re.Match[str]) -> str:
        return f"【{_sanitize_coord(match.group(1))}】"

    return _COORD_CITE_RE.sub(repl, text)


def is_canon_question(question: str) -> bool:
    q = (question or "").strip()
    if not q:
        return False
    if _CHITCHAT_RE.match(q):
        return False
    if _CANON_SIGNAL_RE.search(q):
        return True
    if re.match(
        r"^(?:十二因緣|十二因缘|十二有支|十二緣起|四諦|四谛|八正道|緣起|因緣)$",
        q,
        re.I,
    ):
        return True
    # Short non-signal utterances (e.g. "hihi", "嗯") — not canon.
    if len(q) < 6 and not re.search(r"[\u4e00-\u9fff]{2,}", q):
        return False
    # Longer text without any canon cue — treat as off-topic for this tool.
    return False



class Tools:
    def search_tripitaka(self, question: str) -> str:
        """查詢 CBETA 大藏經語料，返回答案與 CBETA 連結。"""
        if not is_canon_question(question):
            return REFUSAL
        r = requests.post(
            f"{GATEWAY}/v1/task",
            json={
                "mode": "canon_rag",
                "channel": "web",
                "message": question,
            },
            timeout=300,
        )
        r.raise_for_status()
        data = r.json()
        out = data.get("output", {})
        answer = sanitize_citations(out.get("answer", ""))
        teaser = out.get("survey_teaser", "")
        links = out.get("similar_sutra_links", [])
        link_txt = "\n".join(f"- [{x['label']}]({x['url']})" for x in links[:5])
        body = answer
        if teaser:
            body = f"{answer}{teaser}"
        if link_txt:
            body = f"{body}\n\n【CBETA 連結】\n{link_txt}"
        return sanitize_citations(_sanitize_display_markdown(body))

    def list_tripitaka_occurrences(self, keyword: str, page: int = 1) -> str:
        """列出已匯入語料中含某關鍵詞的經典（全藏出處表，附 CBETA 連結）。page 從 1 起算。"""
        kw = (keyword or "").strip()
        if not kw:
            return "請提供關鍵詞，例如：十二因緣、四諦、般若。"
        page = max(1, int(page or 1))
        r = requests.post(
            f"{GATEWAY}/v1/task",
            json={
                "mode": "canon_survey",
                "channel": "web",
                "message": kw,
                "survey_page": page,
                "survey_page_size": 15,
            },
            timeout=120,
        )
        r.raise_for_status()
        out = r.json().get("output", {})
        return sanitize_citations(out.get("answer", ""))
