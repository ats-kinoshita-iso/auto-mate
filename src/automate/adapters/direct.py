"""A minimal crew backend: run one agent harness directly in the worktree.

This is the default crew backend. It launches the configured agent command in the
task's worktree with the prompt, then reports whether the agent left changes
(uncommitted work or commits beyond the base ref). It needs only an agent harness
on PATH, so auto-mate runs anywhere - without firstmate's macOS/Linux + tmux stack.
"""

from __future__ import annotations

import shlex

from automate.adapters.base import CommandRunner
from automate.models import CrewResult, Task, Worktree


class DirectCrewAdapter:
    """Run a single agent harness directly in the worktree."""

    def __init__(
        self,
        *,
        agent_cmd: str = "claude",
        dry_run: bool = True,
        runner: CommandRunner | None = None,
    ) -> None:
        self._agent_cmd = agent_cmd
        self._runner = runner or CommandRunner(dry_run=dry_run)

    def run(self, task: Task, worktree: Worktree) -> CrewResult:
        """Launch the agent in the worktree and report whether it produced changes."""
        self._runner.run([*shlex.split(self._agent_cmd), task.prompt], cwd=worktree.path)
        return CrewResult(
            task_id=task.id,
            branch=worktree.branch,
            changed=self._produced_changes(worktree, task.base_ref),
            summary=f"agent {self._agent_cmd!r} ran in {worktree.path}",
        )

    def _produced_changes(self, worktree: Worktree, base_ref: str) -> bool:
        # Under dry-run nothing actually ran; assume work so the lifecycle demos fully.
        if self._runner.dry_run:
            return True
        dirty = self._runner.run(
            ["git", "-C", worktree.path, "status", "--porcelain"]
        ).stdout.strip()
        ahead = self._runner.run(
            ["git", "-C", worktree.path, "rev-list", "--count", f"{base_ref}..HEAD"]
        ).stdout.strip()
        return bool(dirty) or ahead not in ("", "0")
