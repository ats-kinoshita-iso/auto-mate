"""Adapter over ``firstmate``, the crew orchestrator.

firstmate is not a flag CLI and has no headless prompt flag. Used as intended you
*talk* to a first-mate agent (launch claude / codex / opencode / pi inside the
firstmate home, and its ``AGENTS.md`` supervises a crew). For programmatic use,
firstmate's ``bin/`` scripts are the real surface: ``bin/fm-brief.sh`` scaffolds a
task brief and ``bin/fm-spawn.sh <id> projects/<repo>`` spawns a crewmate in a
tmux + treehouse worktree (confirmed from source). This adapter drives those
scripts - the programmatic path that fits auto-mate's role as the supervisor.

Caveats (still provisional): firstmate is macOS/Linux only and needs tmux plus a
detected agent harness, so this path can only be validated in that environment.
Writing ``task.prompt`` into the brief, mapping ``task.repo`` to a ``projects/``
entry, and supervising to completion (``bin/fm-watch.sh`` + ``state/<id>.status``)
remain TODO.
"""

from __future__ import annotations

from automate.adapters.base import CommandRunner
from automate.models import CrewResult, Task, Worktree


class FirstmateAdapter:
    """Dispatch a crewmate for a task via firstmate's bin/ scripts."""

    def __init__(
        self,
        *,
        home: str,
        dry_run: bool = True,
        runner: CommandRunner | None = None,
    ) -> None:
        self._home = home
        self._runner = runner or CommandRunner(dry_run=dry_run)

    def run(self, task: Task, worktree: Worktree) -> CrewResult:
        """Scaffold a brief and spawn a crewmate for ``task``."""
        if not self._home and not self._runner.dry_run:
            raise ValueError("firstmate home is not configured (AUTOMATE_FIRSTMATE_HOME)")
        brief = f"{self._home}/bin/fm-brief.sh" if self._home else "bin/fm-brief.sh"
        spawn = f"{self._home}/bin/fm-spawn.sh" if self._home else "bin/fm-spawn.sh"
        cwd = self._home or None
        # TODO: write task.prompt into the scaffolded brief (data/<id>/brief.md) before spawn.
        self._runner.run(["bash", brief, task.id, task.repo], cwd=cwd)
        self._runner.run(["bash", spawn, task.id, f"projects/{task.repo}"], cwd=cwd)
        # TODO: supervise to completion (bin/fm-watch.sh) and parse state/<id>.status.
        return CrewResult(
            task_id=task.id,
            branch=worktree.branch,
            changed=True,
            summary=f"crewmate spawned for task {task.id!r} via firstmate bin/fm-spawn.sh",
        )
