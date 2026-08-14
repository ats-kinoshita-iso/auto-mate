"""Adapter over ``firstmate``, the crew orchestrator.

firstmate is a conversational supervisor, but its ``bin/`` scripts are a real
programmatic surface (contract read from source, firstmate main, 2026-08-06):

- ``bin/fm-brief.sh <task-id> <repo-name> --mode <mode>`` scaffolds a brief at
  ``data/<task-id>/brief.md`` containing a literal ``{TASK}`` placeholder the
  caller fills with the task description. Ship briefs REQUIRE a delivery mode.
- ``bin/fm-spawn.sh <task-id> projects/<repo-name> --mode <mode> --yolo <on|off>``
  launches a crewmate in the configured session backend (tmux by default). The
  spawn provisions its OWN treehouse worktree inside ``projects/<repo-name>`` -
  a local clone of the target repo that must exist before spawning - and records
  it as ``worktree=`` in ``state/<task-id>.meta``.
- The crew reports through ``state/<task-id>.status``; the last line's verb is
  the signal (``done:`` terminal success, ``blocked:`` needs the supervisor,
  ``paused`` declared external wait).

auto-mate uses ``--mode local-only`` deliberately: the crew implements on a
branch and STOPS - no push, no PR - so auto-mate's governance/eval gates and its
no-mistakes ship stage keep sole shipping authority. Because the crew works in a
clone, its result is adopted back by fetching the crew worktree's branch into the
task's own worktree/branch once the status reports done.

Validated live: brief scaffolding and the {TASK} fill. Spawning a real crew and
the status protocol end-to-end still need a supervised live run (tmux + a
harness), so this backend remains second to ``direct`` until then.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from pathlib import Path

from automate.adapters.base import AdapterError, CommandRunner
from automate.models import CrewResult, Task, Worktree

_TERMINAL_DONE = "done:"
_TERMINAL_BLOCKED = "blocked:"


class FirstmateAdapter:
    """Dispatch a crewmate for a task via firstmate's bin/ scripts."""

    def __init__(
        self,
        *,
        home: str,
        dry_run: bool = True,
        runner: CommandRunner | None = None,
        crew_timeout: float = 3600.0,
        poll_interval: float = 15.0,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._home = home
        self._runner = runner or CommandRunner(dry_run=dry_run)
        self._crew_timeout = crew_timeout
        self._poll_interval = poll_interval
        self._sleep = sleep
        self._clock = clock

    def run(self, task: Task, worktree: Worktree) -> CrewResult:
        """Brief, spawn, and supervise a crewmate; adopt its branch when done."""
        if not self._home and not self._runner.dry_run:
            raise ValueError("firstmate home is not configured (AUTOMATE_FIRSTMATE_HOME)")
        home = Path(self._home) if self._home else Path()
        repo_name = Path(task.repo).name

        self._ensure_project_clone(home, repo_name, task.repo)
        self._runner.run(
            ["bash", str(home / "bin" / "fm-brief.sh"), task.id, repo_name, "--mode", "local-only"],
            cwd=self._home or None,
        )
        self._fill_brief(home, task)
        self._clear_stale_state(home, task)
        self._runner.run(
            [
                "bash",
                str(home / "bin" / "fm-spawn.sh"),
                task.id,
                f"projects/{repo_name}",
                "--mode",
                "local-only",
                "--yolo",
                "off",
            ],
            cwd=self._home or None,
        )

        if self._runner.dry_run:
            return CrewResult(
                task_id=task.id,
                branch=worktree.branch,
                changed=True,
                summary=f"crewmate spawned for task {task.id!r} via firstmate bin/fm-spawn.sh",
            )

        status = self._supervise(home, task)
        self._adopt_crew_branch(home, task, worktree)
        return CrewResult(
            task_id=task.id,
            branch=worktree.branch,
            changed=self._produced_changes(worktree, task.base_ref),
            summary=f"firstmate crew finished: {status}",
        )

    def _ensure_project_clone(self, home: Path, repo_name: str, repo: str) -> None:
        """firstmate crews work in a local clone under ``projects/``; keep it fresh.

        An existing clone is fetched and fast-forwarded rather than reused as-is:
        a frozen clone would have every later crew implement against the base as
        it stood when the clone was first created.
        """
        if self._runner.dry_run:
            return
        clone = home / "projects" / repo_name
        if not clone.exists():
            self._runner.run(["git", "clone", repo, str(clone)], cwd=self._home)
            return
        self._runner.run(["git", "-C", str(clone), "fetch", "origin", "--prune"])
        self._runner.run(["git", "-C", str(clone), "pull", "--ff-only"])

    def _clear_stale_state(self, home: Path, task: Task) -> None:
        """Drop a previous run's status/meta so it cannot be adopted as this run's.

        ``fm-spawn.sh`` launches the crew asynchronously; a leftover terminal
        ``done:`` line from an earlier run of the same task id would otherwise
        satisfy the first supervision poll and ship the OLD crew's branch.
        """
        if self._runner.dry_run:
            return
        (home / "state" / f"{task.id}.status").unlink(missing_ok=True)
        (home / "state" / f"{task.id}.meta").unlink(missing_ok=True)

    def _fill_brief(self, home: Path, task: Task) -> None:
        """Replace the scaffolded brief's ``{TASK}`` placeholder with the prompt."""
        if self._runner.dry_run:
            return
        brief = home / "data" / task.id / "brief.md"
        text = brief.read_text(encoding="utf-8")
        if "{TASK}" not in text:
            raise AdapterError(f"brief at {brief} has no {{TASK}} placeholder to fill")
        brief.write_text(text.replace("{TASK}", task.prompt), encoding="utf-8")

    def _supervise(self, home: Path, task: Task) -> str:
        """Poll ``state/<id>.status`` until a terminal verb, or time out."""
        status_file = home / "state" / f"{task.id}.status"
        deadline = self._clock() + self._crew_timeout
        while self._clock() < deadline:
            last = self._last_status_line(status_file)
            if last.startswith(_TERMINAL_DONE):
                return last
            if last.startswith(_TERMINAL_BLOCKED):
                raise AdapterError(f"firstmate crew blocked for task {task.id!r}: {last}")
            self._sleep(self._poll_interval)
        raise AdapterError(
            f"firstmate crew for task {task.id!r} did not finish within {self._crew_timeout}s"
        )

    @staticmethod
    def _last_status_line(status_file: Path) -> str:
        if not status_file.exists():
            return ""
        lines = [line.strip() for line in status_file.read_text(encoding="utf-8").splitlines()]
        return next((line for line in reversed(lines) if line), "")

    def _adopt_crew_branch(self, home: Path, task: Task, worktree: Worktree) -> None:
        """Fetch the crew's branch from its clone worktree into the task's branch.

        The crew worked in its own worktree (a treehouse slot inside the
        ``projects/`` clone, recorded as ``worktree=`` in ``state/<id>.meta``);
        its commits live there, not in the task repo. Fetch them and point the
        task's ``automate/<id>`` branch at the result.
        """
        crew_worktree = self._crew_worktree(home, task)
        crew_branch = self._runner.run(
            ["git", "-C", crew_worktree, "branch", "--show-current"]
        ).stdout.strip()
        if not crew_branch:
            raise AdapterError(f"crew worktree {crew_worktree} is not on a branch; cannot adopt")
        self._runner.run(["git", "-C", worktree.path, "fetch", crew_worktree, crew_branch])
        self._runner.run(
            ["git", "-C", worktree.path, "switch", "-C", worktree.branch, "FETCH_HEAD"]
        )

    def _crew_worktree(self, home: Path, task: Task) -> str:
        meta = home / "state" / f"{task.id}.meta"
        if not meta.exists():
            raise AdapterError(f"no crew metadata at {meta}; was the spawn successful?")
        for line in meta.read_text(encoding="utf-8").splitlines():
            if line.startswith("worktree="):
                return line.removeprefix("worktree=").strip()
        raise AdapterError(f"crew metadata {meta} records no worktree= entry")

    def _produced_changes(self, worktree: Worktree, base_ref: str) -> bool:
        ahead = self._runner.run(
            ["git", "-C", worktree.path, "rev-list", "--count", f"{base_ref}..HEAD"]
        ).stdout.strip()
        return ahead not in ("", "0")
