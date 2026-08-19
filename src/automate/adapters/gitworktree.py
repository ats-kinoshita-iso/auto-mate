"""A plain ``git worktree`` WorktreeProvider for environments without treehouse.

treehouse adds pooling, cached dependencies, and lease guards - none of which
plain git provides - but it is a separate binary that Claude Code cloud
containers and most CI images do not ship. This provider covers the same port
with git alone: one linked worktree per task under a configurable root,
branch cut in the worktree exactly like the treehouse adapter, removed with
``--force`` on release (a review checkout holds no unique state).

Linked worktrees share refs and remotes with the parent clone, so the
``refs/automate/pr/<N>`` namespace fetched by the PR host is visible inside
the worktree - the property the review lifecycle depends on.
"""

from __future__ import annotations

from pathlib import Path

from automate.adapters.base import CommandRunner
from automate.models import Task, Worktree


class GitWorktreeProvider:
    """Provision one plain git worktree per task; no pooling, no leases."""

    def __init__(
        self,
        *,
        worktree_root: str,
        dry_run: bool = True,
        runner: CommandRunner | None = None,
    ) -> None:
        self._root = Path(worktree_root).expanduser()
        self._runner = runner or CommandRunner(dry_run=dry_run)

    def create(self, task: Task) -> Worktree:
        """Add a detached worktree for ``task`` and cut its working branch."""
        path = self._root / f"{Path(task.repo).name}-{task.id}"
        if path.is_dir() and not self._runner.dry_run:
            # A leftover worktree from a crashed run: remove it so add succeeds.
            self._runner.run(["git", "-C", task.repo, "worktree", "remove", "--force", str(path)])
        if not self._runner.dry_run:
            # Keep dry-run side-effect-free like every other adapter: the only
            # filesystem mutation not routed through the runner stays gated too.
            self._root.mkdir(parents=True, exist_ok=True)
        self._runner.run(["git", "-C", task.repo, "worktree", "add", "--detach", str(path)])
        branch = f"automate/{task.id}"
        # Same convention as the treehouse adapter: -C resets the branch on re-runs.
        self._runner.run(["git", "-C", str(path), "switch", "-C", branch])
        return Worktree(task_id=task.id, path=str(path), branch=branch, lease_id=None)

    def release(self, worktree: Worktree) -> None:
        """Remove the worktree (and its checkout) from the parent clone.

        The parent repo is resolved from the worktree itself via
        ``--git-common-dir``, so release needs no extra state on ``Worktree``.
        """
        if self._runner.dry_run:
            self._runner.run(["git", "worktree", "remove", "--force", worktree.path])
            return
        common = self._runner.run(
            ["git", "-C", worktree.path, "rev-parse", "--path-format=absolute", "--git-common-dir"]
        ).stdout.strip()
        repo = str(Path(common).parent)
        self._runner.run(["git", "-C", repo, "worktree", "remove", "--force", worktree.path])

    def status(self, repo: str) -> str:
        """The parent clone's worktree table (git's own listing)."""
        return self._runner.run(["git", "-C", repo, "worktree", "list"], cwd=repo).stdout
