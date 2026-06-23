"""Runtime configuration for auto-mate, loaded from the environment and ``.env``."""

from __future__ import annotations

from typing import Any

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Configuration for the agent-execution layer.

    Values load from environment variables prefixed ``AUTOMATE_`` and an optional
    ``.env`` file. External tools are referenced by command, so the user's forks of
    treehouse / firstmate / no-mistakes drop in by adjusting a path.
    """

    model_config = SettingsConfigDict(
        env_prefix="AUTOMATE_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # External tool entrypoints.
    treehouse_bin: str = Field("treehouse", description="treehouse binary (PATH or absolute).")
    no_mistakes_bin: str = Field(
        "no-mistakes", description="no-mistakes binary (PATH or absolute)."
    )
    firstmate_home: str = Field("", description="Path to a firstmate AGENTS.md home directory.")
    firstmate_agent_cmd: str = Field(
        "claude", description="Agent harness that follows firstmate's AGENTS.md."
    )

    # Workspace + delivery.
    workspace_root: str = Field("~/.auto-mate", description="Root for run artifacts and logs.")
    default_base_ref: str = Field("main", description="Default base ref for new worktrees.")

    # Harness gate commands (optional; an empty command disables the gate).
    governance_cmd: str = Field(
        "", description="Command invoked as the henkaten-council governance gate."
    )
    codegen_cmd: str = Field(
        "", description="Command invoked as the trine-eval codegen/evaluation gate."
    )

    # Safety.
    dry_run: bool = Field(
        True, description="When true, adapters echo commands instead of executing them."
    )


def get_settings(**overrides: Any) -> Settings:
    """Build a :class:`Settings`, applying explicit overrides over env and ``.env``."""
    return Settings(**overrides)
