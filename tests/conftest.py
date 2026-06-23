"""Pytest defaults: avoid nvidia-smi during TestClient lifespan in CPU-only CI."""

from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient

from gateway.app import app


def pytest_configure() -> None:
    os.environ.setdefault("VAJRA_VRAM_LOG_ON_START", "0")


@pytest.fixture
def client() -> TestClient:
    with TestClient(app) as c:
        yield c
