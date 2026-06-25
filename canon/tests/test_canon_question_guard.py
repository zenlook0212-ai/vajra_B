"""Guard for off-topic queries in search_tripitaka."""

import importlib.util
from pathlib import Path

_spec = importlib.util.spec_from_file_location(
    "canon_rag",
    Path(__file__).resolve().parents[1] / "scripts" / "openwebui_canon_rag.py",
)
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)
is_canon_question = _mod.is_canon_question
REFUSAL = _mod.REFUSAL


def test_refuses_chitchat():
    assert not is_canon_question("hihi")
    assert not is_canon_question("你好")
    assert not is_canon_question("test")


def test_accepts_canon_queries():
    assert is_canon_question("長阿含經序提到如來出世的大教有幾種？")
    assert is_canon_question("四諦")
    assert is_canon_question("金剛經 應無所住")
    assert is_canon_question("CBETA T01")


def test_refusal_message():
    assert "不閒聊" in REFUSAL
