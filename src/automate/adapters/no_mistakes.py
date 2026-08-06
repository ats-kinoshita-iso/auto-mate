"""Adapter over ``no-mistakes``, the safe-push gate.

no-mistakes installs a local git-remote proxy. ``no-mistakes init`` creates a bare
repo and adds a remote literally named ``no-mistakes`` (internal/gate/gate.go);
pushing to it triggers a background-daemon pipeline (review -> test -> document ->
lint -> push -> PR) that forwards to the real target and opens a PR only when every
check is green. Pushing to that remote is the ONLY way to invoke the gate - there is
no dedicated ship subcommand (confirmed from source).

Notes: the gate needs the daemon running (``no-mistakes daemon``). The authoritative
PR URL comes from ``no-mistakes axi status`` (TOON output), not reliably from the
push stdout, so the scrape below is best-effort. A fully headless run can instead use
``no-mistakes axi run --intent <goal> --yes``.
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
        # Pushing to the `no-mistakes` remote is the only trigger; the daemon runs the
        # pipeline and opens the PR asynchronously once every check passes.
        result = self._runner.run(
            ["git", "push", "no-mistakes", worktree.branch], cwd=worktree.path
        )
        match = _PR_URL.search(result.stdout)
        return GateResult(
            task_id=worktree.task_id,
            pushed=result.ok,
            pr_url=match.group(0) if match else None,
        )
