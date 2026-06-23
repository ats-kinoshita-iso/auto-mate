"""Adapter over ``no-mistakes``, the safe-push gate.

no-mistakes installs a local git-remote proxy: after ``no-mistakes init``, pushing
to the ``no-mistakes`` remote runs an AI validation pipeline
(review -> test -> docs -> lint) and only forwards the branch to the real target
and opens a PR once every check is green. This adapter initializes the gate and
pushes a worktree's branch through it.
"""

from __future__ import annotations

import re

from automate.adapters.base import CommandRunner
from automate.models import GateResult, Worktree

_PR_URL = re.compile(r"https://\S+/pull/\d+")


class NoMistakesAdapter:
    """Ship a branch through the no-mistakes safe-push pipeline."""

    def __init__(
        self,
        binary: str = "no-mistakes",
        *,
        dry_run: bool = True,
        runner: CommandRunner | None = None,
    ) -> None:
        self._binary = binary
        self._runner = runner or CommandRunner(dry_run=dry_run)

    def init(self, repo_path: str) -> None:
        """Install the gate in ``repo_path`` (idempotent)."""
        self._runner.run([self._binary, "init"], cwd=repo_path)

    def gate(self, worktree: Worktree) -> GateResult:
        """Push the worktree's branch through the gate; a PR opens only when green."""
        result = self._runner.run(
            ["git", "push", "no-mistakes", worktree.branch], cwd=worktree.path
        )
        match = _PR_URL.search(result.stdout)
        return GateResult(
            task_id=worktree.task_id,
            pushed=result.ok,
            pr_url=match.group(0) if match else None,
        )
