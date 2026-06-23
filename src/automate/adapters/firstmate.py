"""Adapter over ``firstmate``, the AGENTS.md-driven crew orchestrator.

firstmate is not a flag-driven binary: it is a directory whose ``AGENTS.md`` an
agent harness (claude / codex / opencode / pi) follows, spawning crewmates in
tmux + treehouse worktrees and reporting finished work back. This adapter drives
it by launching the configured harness inside the firstmate home with the task
prompt. The exact prompt-passing convention is harness-specific and runs only
under dry-run until confirmed.
"""

from __future__ import annotations

from automate.adapters.base import CommandRunner
from automate.models import CrewResult, Task, Worktree


class FirstmateAdapter:
    """Dispatch an agent crew for a task via firstmate."""

    def __init__(
        self,
        *,
        home: str,
        agent_cmd: str = "claude",
        dry_run: bool = True,
        runner: CommandRunner | None = None,
    ) -> None:
        self._home = home
        self._agent_cmd = agent_cmd
        self._runner = runner or CommandRunner(dry_run=dry_run)

    def run(self, task: Task, worktree: Worktree) -> CrewResult:
        """Dispatch a crew for ``task`` and wait for it to finish."""
        if not self._home and not self._runner.dry_run:
            raise ValueError("firstmate home is not configured (AUTOMATE_FIRSTMATE_HOME)")
        # TODO: confirm the non-interactive prompt convention for the chosen harness;
        # firstmate's AGENTS.md takes over once the harness launches in its home.
        self._runner.run([self._agent_cmd, "-p", task.prompt], cwd=self._home or None)
        # TODO: parse the real crew outcome (branch, PR, summary) from firstmate's report.
        return CrewResult(
            task_id=task.id,
            branch=worktree.branch,
            changed=True,
            summary=f"crew dispatched for task {task.id!r} via firstmate",
        )
