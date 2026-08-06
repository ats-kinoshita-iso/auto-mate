"""Adapter over ``treehouse``, the worktree-pool manager.

treehouse hands out reusable, isolated git worktrees from a per-repo pool. It
operates on the repository in the current working directory (there is no ``--repo``
flag), and pooled worktrees come back on a detached HEAD - so this adapter cuts the
task's working branch in the acquired worktree itself.

CLI surface confirmed from source (kunchenguid/treehouse):
- ``treehouse get --lease [--lease-holder LABEL]`` acquires a worktree and prints
  ONLY its absolute path to stdout (cmd/get.go); the lease persists until return.
- ``treehouse return <path> [--force]`` releases a worktree (cmd/return_cmd.go).
- ``treehouse status`` prints a human-readable pool table (cmd/status.go).
"""

from __future__ import annotations

from automate.adapters.base import CommandRunner
from automate.models import Task, Worktree


class TreehouseAdapter:
    """Acquire and release pooled worktrees via treehouse."""

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
        """Acquire a leased worktree for ``task`` and cut its working branch."""
        result = self._runner.run(
            [self._binary, "get", "--lease", "--lease-holder", task.id], cwd=task.repo
        )
        path = self._acquired_path(result.stdout, task)
        branch = f"automate/{task.id}"
        # treehouse returns a worktree on a detached HEAD; create the task branch in it.
        self._runner.run(["git", "-C", path, "switch", "-c", branch])
        return Worktree(task_id=task.id, path=path, branch=branch)

    def release(self, worktree: Worktree) -> None:
        """Return a leased worktree to the pool."""
        self._runner.run([self._binary, "return", worktree.path, "--force"])

    def status(self, repo: str) -> str:
        """Return treehouse's pool status table for ``repo`` (human-readable)."""
        return self._runner.run([self._binary, "status"], cwd=repo).stdout

    def _acquired_path(self, stdout: str, task: Task) -> str:
        # `treehouse get --lease` prints only the path (get.go); synthesize under dry-run.
        if self._runner.dry_run:
            return f"~/.treehouse/{task.id}"
        return stdout.strip()
