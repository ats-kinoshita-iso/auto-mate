"""Shared test fixtures."""

from __future__ import annotations

import os

import pytest


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Strip AUTOMATE_* env vars so config tests are deterministic."""
    for key in list(os.environ):
        if key.startswith("AUTOMATE_"):
            monkeypatch.delenv(key, raising=False)
