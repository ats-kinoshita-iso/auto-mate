"""Adapter over ``treehouse``, the worktree-pool manager.

treehouse hands out reusable, isolated git worktrees from a per-repo pool. It
operates on the repository in the current working directory (there is no ``--repo``
flag), and pooled worktrees come back on a detached HEAD - so this adapter cuts the
task's working branch in the acquired worktree itself.

CLI surface confirmed from source (kunchenguid/treehouse) and validated live against
treehouse v2.1.1 on Linux (2026-08-06; re-checked against v2.1.1 releases 2026-08-17):
- ``treehouse get --lease [--lease-holder LABEL] --json`` acquires a worktree and
  prints the lease allocation as JSON to stdout (``path``, ``lease_id``,
  ``lease_holder``, ``leased_at``); human chatter goes to stderr in either output
  mode. Without ``--json`` only the absolute path is printed - this adapter uses
  the JSON mode as the robust contract. No ``treehouse init`` is required first,
  and a fresh get tracks the repo's current default-branch head.
- Pooled worktrees are *linked* git worktrees (``.git`` file -> the repo's
  ``.git/worktrees/...``), so remotes, refs, and config are shared with the repo:
  branches cut here survive release, and remotes added in the repo (e.g. the
  ``no-mistakes`` gate remote) are usable from the worktree.
- ``treehouse return <path> --force [--if-lease-id ID | --if-lease-holder H]``
  cleans, resets, and returns a worktree without prompting. ``--if-lease-id``
  (v2.1.0 stable lease identities) guards on the specific acquisition, which is
  tighter than the holder label - a re-run of the same task id cannot release a
  lease a newer run now owns. The holder guard remains the fallback when no
  lease id was captured.
- ``treehouse status`` prints a human-readable pool table (no JSON mode).
"""

from __future__ import annotations

import json

from automate.adapters.base import AdapterError, CommandRunner
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
            [self._binary, "get", "--lease", "--lease-holder", task.id, "--json"],
            cwd=task.repo,
        )
        path, lease_id = self._allocation(result.stdout, task)
        branch = f"automate/{task.id}"
        # treehouse returns a worktree on a detached HEAD; create the task branch in it.
        # -C (not -c): a re-run of the same task id resets its branch instead of failing.
        self._runner.run(["git", "-C", path, "switch", "-C", branch])
        return Worktree(task_id=task.id, path=path, branch=branch, lease_id=lease_id)

    def release(self, worktree: Worktree) -> None:
        """Return a leased worktree to the pool (only if this task still holds it)."""
        # Prefer the per-acquisition lease-id guard; fall back to the holder label
        # for worktrees acquired before the JSON mode. `is not None` (not truthiness):
        # a manually-built empty-string lease_id should fail loudly at treehouse
        # rather than silently downgrade to the weaker holder guard.
        guard = (
            ["--if-lease-id", worktree.lease_id]
            if worktree.lease_id is not None
            else ["--if-lease-holder", worktree.task_id]
        )
        self._runner.run([self._binary, "return", worktree.path, "--force", *guard])

    def status(self, repo: str) -> str:
        """Return treehouse's pool status table for ``repo`` (human-readable)."""
        return self._runner.run([self._binary, "status"], cwd=repo).stdout

    def _allocation(self, stdout: str, task: Task) -> tuple[str, str | None]:
        # `treehouse get --lease --json` prints the allocation object; synthesize
        # a plausible one under dry-run so the lifecycle stays walkable.
        if self._runner.dry_run:
            return f"~/.treehouse/{task.id}", f"dry-{task.id}"
        try:
            allocation = json.loads(stdout)
            path = allocation["path"]
        except (json.JSONDecodeError, TypeError, KeyError) as exc:
            raise AdapterError(
                f"treehouse get --json printed an unparseable allocation: {stdout!r}"
            ) from exc
        if not isinstance(path, str) or not path:
            # A granted lease with no usable path would otherwise crash later in
            # git and orphan the lease; fail loudly at the boundary instead.
            raise AdapterError(f"treehouse get --json allocation has no usable path: {stdout!r}")
        lease_id = allocation.get("lease_id")
        # Normalize absent/null/empty to None so release() falls back to the holder guard.
        if not isinstance(lease_id, str) or not lease_id:
            lease_id = None
        return path, lease_id
