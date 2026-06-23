"""
可選 Hermes 審核：翻譯（translate）與經藏 RAG（canon_rag）。

以環境變數控制，預設關閉，避免改變既有延遲與行為；需要時再於部署層開啟。
"""

from __future__ import annotations

import os


def _norm_flag(raw: str) -> str:
    return raw.strip().lower()


def should_hermes_after_translate(*, used_monlam: bool) -> bool:
    """
    是否在 ``translate`` 主鏈完成後呼叫 Hermes。

    ``VAJRA_HERMES_TRANSLATE``：

    - ``0`` / ``false`` / ``off`` / 空：關閉（預設）
    - ``1`` / ``true`` / ``always``：每次非 TM 快取路徑皆審
    - ``monlam_only``：僅 ``used_monlam`` 為真時審（藏文主路徑）
    """
    flag = _norm_flag(os.environ.get("VAJRA_HERMES_TRANSLATE", "0"))
    if flag in ("0", "false", "no", "off", ""):
        return False
    if flag in ("1", "true", "yes", "on", "always"):
        return True
    if flag in ("monlam_only", "monlam"):
        return bool(used_monlam)
    return False


def should_hermes_after_canon_rag(*, rag_hits: int) -> bool:
    """
    是否在 ``canon_rag`` 合成後呼叫 Hermes。

    ``VAJRA_HERMES_CANON_RAG``：

    - ``0`` / ``false`` / ``off`` / 空：關閉（預設）
    - ``1`` / ``true`` / ``always``：每次皆審
    - ``hits`` / ``auto``：僅當 ``rag_hits > 0``（有向量片段）時審
    """
    flag = _norm_flag(os.environ.get("VAJRA_HERMES_CANON_RAG", "0"))
    if flag in ("0", "false", "no", "off", ""):
        return False
    if flag in ("1", "true", "yes", "on", "always"):
        return True
    if flag in ("hits", "auto", "on_demand"):
        return rag_hits > 0
    return False
