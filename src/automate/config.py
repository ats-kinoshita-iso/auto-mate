"""Runtime configuration for auto-mate, loaded from the environment and ``.env``."""

from __future__ import annotations

from typing import Any, Literal

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
    # Crew engine.
    crew_backend: Literal["direct", "firstmate"] = Field(
        "direct", description="Crew engine: 'direct' (one agent in the worktree) or 'firstmate'."
    )
    agent_cmd: str = Field("claude", description="Agent harness for the 'direct' crew backend.")
    firstmate_home: str = Field(
        "", description="firstmate home directory (bin/ scripts); used when crew_backend=firstmate."
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

    # PR review (gh-backed).
    gh_bin: str = Field("gh", description="GitHub CLI binary (PATH or absolute).")
    review_clone_root: str = Field(
        "~/.auto-mate/repos", description="Where review clones of remote repos are created."
    )
    review_agent_cmd: str = Field(
        'claude -p --setting-sources project,local --allowedTools "Read,Glob,Grep,'
        'Bash(git diff:*),Bash(git log:*),Bash(git show:*)"',
        description="Headless read-only agent command for the deep PR review.",
    )
    review_timeout_s: float = Field(
        1800.0, description="Upper bound for one deep-review agent run."
    )

    # Timeouts (seconds) for long-running externals.
    agent_timeout_s: float = Field(
        3600.0, description="Upper bound for one direct-backend agent run."
    )
    ship_timeout_s: float = Field(
        3600.0, description="Upper bound for one no-mistakes pipeline run (axi run blocks)."
    )
    gate_timeout_s: float = Field(
        1800.0, description="Upper bound for one governance/eval gate command."
    )

    # Safety.
    dry_run: bool = Field(
        True, description="When true, adapters echo commands instead of executing them."
    )


def get_settings(**overrides: Any) -> Settings:
    """Build a :class:`Settings`, applying explicit overrides over env and ``.env``."""
    return Settings(**overrides)
