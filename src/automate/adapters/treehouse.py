"""Adapter over ``treehouse``, the worktree-pool manager.

treehouse hands out reusable, isolated git worktrees from a per-repo pool. It
operates on the repository in the current working directory (there is no ``--repo``
flag), and pooled worktrees come back on a detached HEAD - so this adapter cuts the
task's working branch in the acquired worktree itself.

CLI surface confirmed from source (kunchenguid/treehouse) and validated live against
treehouse v2.1.1 on Linux (2026-08-06):
- ``treehouse get --lease [--lease-holder LABEL]`` acquires a worktree and prints
  ONLY its absolute path to stdout (human chatter goes to stderr); the lease
  persists until return. No ``treehouse init`` is required first, and a fresh get
  tracks the repo's current default-branch head.
- Pooled worktrees are *linked* git worktrees (``.git`` file -> the repo's
  ``.git/worktrees/...``), so remotes, refs, and config are shared with the repo:
  branches cut here survive release, and remotes added in the repo (e.g. the
  ``no-mistakes`` gate remote) are usable from the worktree.
- ``treehouse return <path> --force [--if-lease-holder H]`` cleans, resets, and
  returns a worktree without prompting; the holder guard prevents releasing a
  lease this task does not own.
- ``treehouse status`` prints a human-readable pool table (no JSON mode).
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
        # -C (not -c): a re-run of the same task id resets its branch instead of failing.
        self._runner.run(["git", "-C", path, "switch", "-C", branch])
        return Worktree(task_id=task.id, path=path, branch=branch)

    def release(self, worktree: Worktree) -> None:
        """Return a leased worktree to the pool (only if this task still holds it)."""
        self._runner.run(
            [
                self._binary,
                "return",
                worktree.path,
                "--force",
                "--if-lease-holder",
                worktree.task_id,
            ]
        )

    def status(self, repo: str) -> str:
        """Return treehouse's pool status table for ``repo`` (human-readable)."""
        return self._runner.run([self._binary, "status"], cwd=repo).stdout

    def _acquired_path(self, stdout: str, task: Task) -> str:
        # `treehouse get --lease` prints only the path (get.go); synthesize under dry-run.
        if self._runner.dry_run:
            return f"~/.treehouse/{task.id}"
        return stdout.strip()
