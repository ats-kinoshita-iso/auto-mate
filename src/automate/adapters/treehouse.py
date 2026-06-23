"""Adapter over ``treehouse``, the worktree-pool manager.

treehouse manages a pool of reusable, isolated git worktrees. Its documented
default invocation is interactive (it drops the caller into a subshell), so the
non-interactive provisioning surface used below is provisional and runs only
under dry-run until confirmed against the installed CLI.
"""

from __future__ import annotations

from automate.adapters.base import CommandRunner
from automate.models import Task, Worktree


class TreehouseAdapter:
    """Provision and release isolated worktrees via the treehouse pool."""

    def __init__(
        self,
        binary: str = "treehouse",
        *,
        dry_run: bool = True,
        runner: CommandRunner | None = None,
    ) -> None:
        self._binary = binary
        self._runner = runner or CommandRunner(dry_run=dry_run)

    def create(self, task: Task) -> Worktree:
        """Provision an isolated worktree for ``task`` from its base ref."""
        branch = f"automate/{task.id}"
        # TODO: confirm against the treehouse CLI. The README documents an
        # interactive `treehouse` subshell; this non-interactive form is provisional.
        self._runner.run([self._binary, "new", "--repo", task.repo, "--branch", branch])
        # TODO: parse the real worktree path from treehouse output; synthesized for now.
        path = f"~/.treehouse/{task.id}"
        return Worktree(task_id=task.id, path=path, branch=branch)

    def release(self, worktree: Worktree) -> None:
        """Return a worktree to the pool for reuse."""
        # TODO: confirm the release subcommand name against the treehouse CLI.
        self._runner.run([self._binary, "release", worktree.path])
