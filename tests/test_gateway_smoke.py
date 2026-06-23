"""Smoke tests for the FastAPI gateway (no live vLLM)."""

from __future__ import annotations

import base64
from unittest.mock import AsyncMock, patch

import httpx
import pytest
from fastapi.testclient import TestClient

def test_health(client: TestClient) -> None:
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


def test_list_modes(client: TestClient) -> None:
    r = client.get("/v1/modes")
    assert r.status_code == 200
    data = r.json()
    assert "chat" in data["modes"]
    assert "telegram" in data["channels"]
    assert "routes" in data and isinstance(data["routes"], dict)


def test_chat_internal_summarize_skips_logic_gate(client: TestClient) -> None:
    with patch("gateway.app.chat_completion", new_callable=AsyncMock) as m:
        m.return_value = ("summary", {})
        r = client.post(
            "/v1/task",
            json={
                "mode": "chat",
                "channel": "internal",
                "message": "請以 100-300 字總結…",
                "client_request_id": "summarize-123",
            },
        )
    assert r.status_code == 200
    msgs = m.call_args.kwargs["messages"]
    assert len(msgs) == 1
    assert msgs[0]["role"] == "user"
    assert r.json()["meta"].get("logic_gate") == "off"


def test_chat_mode_mocked_llm(client: TestClient) -> None:
    with patch("gateway.app.chat_completion", new_callable=AsyncMock) as m:
        m.return_value = ("mock-reply", {})
        r = client.post(
            "/v1/task",
            json={"mode": "chat", "channel": "web", "message": "請簡述緣起"},
        )
    assert r.status_code == 200
    body = r.json()
    assert body["output"]["reply"] == "mock-reply"
    msgs = m.call_args.kwargs["messages"]
    assert msgs[0]["role"] == "system"
    assert "<Logic_Gate>" in msgs[0]["content"]
    assert body["meta"].get("logic_gate") == "chat_enforced"


def test_chat_mode_quick_greeting_short_circuit(client: TestClient) -> None:
    with patch("gateway.app.chat_completion", new_callable=AsyncMock) as m:
        r = client.post(
            "/v1/task",
            json={"mode": "chat", "channel": "telegram", "message": "Hi"},
        )
    assert r.status_code == 200
    m.assert_not_called()
    body = r.json()
    assert body["meta"].get("logic_gate") == "chat_quick_reply"
    assert "<Logic_Gate>" in body["output"]["reply"]


def test_chat_mode_uses_short_token_budget_and_no_thinking_prompt(
    client: TestClient,
) -> None:
    with patch("gateway.app.chat_completion", new_callable=AsyncMock) as m:
        m.return_value = ("ok", {})
        r = client.post(
            "/v1/task",
            json={"mode": "chat", "channel": "web", "message": "請介紹中觀"},
        )
    assert r.status_code == 200
    kwargs = m.call_args.kwargs
    assert kwargs["max_tokens"] == 768
    system_prompt = kwargs["messages"][0]["content"]
    assert "不得輸出例如 Here's a thinking process" in system_prompt


def test_chat_mode_llm_connect_error_is_503(client: TestClient) -> None:
    with patch("gateway.app.chat_completion", new_callable=AsyncMock) as m:
        m.side_effect = httpx.ConnectError("connection refused")
        r = client.post(
            "/v1/task",
            json={"mode": "chat", "channel": "web", "message": "請解釋空性"},
        )
    assert r.status_code == 503
    detail = r.json()["detail"]
    assert "unreachable" in detail.lower()


def test_model_admin_requires_token(client: TestClient) -> None:
    r = client.post("/v1/task", json={"mode": "model_admin", "channel": "internal"})
    assert r.status_code == 403


def test_translate_tm_cache_hit(client: TestClient) -> None:
    with patch("gateway.app.tm_store.tm_get", new_callable=AsyncMock) as tg:
        tg.return_value = ("cached-draft", "cached-polished", False)
        with patch("gateway.app.chat_completion", new_callable=AsyncMock) as llm:
            r = client.post(
                "/v1/task",
                json={"mode": "translate", "message": "test segment"},
            )
    assert r.status_code == 200
    llm.assert_not_called()
    body = r.json()
    assert body["output"]["translation_memory_hit"] is True
    assert body["output"]["polished"] == "cached-polished"


def test_ocr_batch_calls_vl_twice(client: TestClient) -> None:
    b64 = base64.b64encode(b"\xff\xd8\xff\xd9").decode("ascii")
    with patch("gateway.app._ocr_qwen_vl_post", new_callable=AsyncMock) as ocr:
        ocr.side_effect = ["page-a", "page-b"]
        r = client.post(
            "/v1/task",
            json={"mode": "ocr", "images_base64": [b64, b64]},
        )
    assert r.status_code == 200
    assert ocr.await_count == 2
    out = r.json()["output"]
    assert out["batch"] is True
    assert len(out["pages"]) == 2


def test_disabled_mode_via_env(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("VAJRA_DISABLED_MODES", "chat")
    with patch("gateway.app.chat_completion", new_callable=AsyncMock):
        r = client.post(
            "/v1/task",
            json={"mode": "chat", "channel": "web", "message": "x"},
        )
    assert r.status_code == 503
    assert "disabled" in r.json()["detail"].lower()


def test_model_admin_vram_json(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("VAJRA_ADMIN_TOKEN", "secret-test")
    fake_rows = [
        {
            "index": 0,
            "name": "GB10",
            "memory_used_mib": 1000,
            "memory_total_mib": 128000,
            "memory_free_mib": 500,
        }
    ]
    with patch(
        "gateway.app.gateway_ops.nvidia_gpu_memory_csv",
        new_callable=AsyncMock,
        return_value=("", fake_rows),
    ):
        r = client.post(
            "/v1/task",
            headers={"X-Admin-Token": "secret-test"},
            json={
                "mode": "model_admin",
                "channel": "internal",
                "ops": {"action": "vram_json"},
            },
        )
    assert r.status_code == 200
    assert "gpus" in r.json()["output"]
