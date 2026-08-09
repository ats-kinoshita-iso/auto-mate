"""Configuration loading and overrides."""

from __future__ import annotations

import pytest

from automate.config import Settings, get_settings


def test_defaults_are_safe() -> None:
    settings = Settings(_env_file=None)
    assert settings.dry_run is True
    assert settings.treehouse_bin == "treehouse"
    assert settings.no_mistakes_bin == "no-mistakes"
    assert settings.governance_cmd == ""


def test_review_defaults() -> None:
    settings = Settings(_env_file=None)
    assert settings.gh_bin == "gh"
    assert settings.review_clone_root == "~/.auto-mate/repos"
    assert settings.review_agent_cmd.startswith("claude -p")
    assert "--allowedTools" in settings.review_agent_cmd  # read-only enforcement lives here
    assert settings.review_timeout_s == 1800.0


def test_env_overrides(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AUTOMATE_DRY_RUN", "false")
    monkeypatch.setenv("AUTOMATE_TREEHOUSE_BIN", "/opt/treehouse")
    monkeypatch.setenv("AUTOMATE_REVIEW_CLONE_ROOT", "/srv/reviews")
    settings = Settings(_env_file=None)
    assert settings.dry_run is False
    assert settings.treehouse_bin == "/opt/treehouse"
    assert settings.review_clone_root == "/srv/reviews"


def test_explicit_overrides_win() -> None:
    settings = get_settings(dry_run=False, codegen_cmd="trine-eval run")
    assert settings.dry_run is False
    assert settings.codegen_cmd == "trine-eval run"
