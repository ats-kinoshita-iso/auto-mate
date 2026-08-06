"""Adapters build the right commands and parse results at the subprocess boundary."""

from __future__ import annotations

import pytest

from automate.adapters import (
    DirectCrewAdapter,
    FirstmateAdapter,
    NoMistakesAdapter,
    TreehouseAdapter,
)
from automate.adapters.base import CommandResult, CommandRunner
from automate.harnesses import CommandGate
from automate.models import CrewResult, Task, Worktree


class RecordingRunner(CommandRunner):
    """A CommandRunner that records commands and returns canned output."""

    def __init__(self, *, stdout: str = "", returncode: int = 0) -> None:
        super().__init__(dry_run=False)
        self.calls: list[list[str]] = []
        self._stdout = stdout
        self._returncode = returncode

    def run(self, command: list[str], *, cwd: str | None = None) -> CommandResult:
        self.calls.append(command)
        return CommandResult(
            command=command, returncode=self._returncode, stdout=self._stdout, stderr=""
        )


def test_treehouse_create_acquires_lease_and_cuts_branch() -> None:
    runner = RecordingRunner(stdout="/home/u/.treehouse/abc/1/repo")
    adapter = TreehouseAdapter("treehouse", runner=runner)
    worktree = adapter.create(Task(id="abc", prompt="do it", repo="/repo"))
    assert worktree.path == "/home/u/.treehouse/abc/1/repo"
    assert worktree.branch == "automate/abc"
    assert runner.calls == [
        ["treehouse", "get", "--lease", "--lease-holder", "abc"],
        ["git", "-C", "/home/u/.treehouse/abc/1/repo", "switch", "-c", "automate/abc"],
    ]


def test_treehouse_release_returns_worktree() -> None:
    runner = RecordingRunner()
    adapter = TreehouseAdapter("treehouse", runner=runner)
    adapter.release(Worktree(task_id="abc", path="/wt", branch="automate/abc"))
    assert runner.calls == [["treehouse", "return", "/wt", "--force"]]


def test_no_mistakes_gate_parses_pr_url() -> None:
    runner = RecordingRunner(stdout="opened https://github.com/me/repo/pull/7 ready")
    adapter = NoMistakesAdapter(runner=runner)
    result = adapter.gate(Worktree(task_id="abc", path="/wt", branch="automate/abc"))
    assert result.pushed is True
    assert result.pr_url == "https://github.com/me/repo/pull/7"
    assert runner.calls == [["git", "push", "no-mistakes", "automate/abc"]]


def test_firstmate_tolerates_missing_home_only_in_dry_run() -> None:
    task = Task(id="abc", prompt="x", repo="/repo")
    worktree = Worktree(task_id="abc", path="/wt", branch="automate/abc")

    # dry-run: a missing home is fine, the lifecycle can still be walked
    crew = FirstmateAdapter(home="", dry_run=True).run(task, worktree)
    assert crew.changed is True

    # executing for real: a missing home is a hard error
    live = FirstmateAdapter(home="", runner=RecordingRunner())
    with pytest.raises(ValueError, match="firstmate home"):
        live.run(task, worktree)


def test_firstmate_drives_bin_scripts() -> None:
    runner = RecordingRunner()
    adapter = FirstmateAdapter(home="/fm", runner=runner)
    crew = adapter.run(
        Task(id="abc", prompt="x", repo="myrepo"),
        Worktree(task_id="abc", path="/wt", branch="automate/abc"),
    )
    assert crew.changed is True
    assert runner.calls == [
        ["bash", "/fm/bin/fm-brief.sh", "abc", "myrepo"],
        ["bash", "/fm/bin/fm-spawn.sh", "abc", "projects/myrepo"],
    ]


def test_direct_crew_runs_agent_and_reports_no_changes() -> None:
    runner = RecordingRunner()  # empty stdout -> clean worktree, not ahead -> no changes
    adapter = DirectCrewAdapter(agent_cmd="claude --print", runner=runner)
    crew = adapter.run(
        Task(id="abc", prompt="add dark mode", repo="/repo"),
        Worktree(task_id="abc", path="/wt", branch="automate/abc"),
    )
    assert runner.calls[0] == ["claude", "--print", "add dark mode"]
    assert crew.changed is False


def test_direct_crew_detects_dirty_worktree() -> None:
    runner = RecordingRunner(stdout="M src/app.py")
    adapter = DirectCrewAdapter(runner=runner)
    crew = adapter.run(
        Task(id="abc", prompt="x", repo="/repo"),
        Worktree(task_id="abc", path="/wt", branch="automate/abc"),
    )
    assert crew.changed is True


def test_command_gate_disabled_when_no_command() -> None:
    runner = RecordingRunner()
    gate = CommandGate("henkaten-council", "", runner=runner)
    verdict = gate.evaluate(CrewResult(task_id="abc", branch="automate/abc", changed=True))
    assert verdict.passed is True
    assert runner.calls == []  # disabled gate never shells out


def test_command_gate_runs_configured_command() -> None:
    runner = RecordingRunner()
    gate = CommandGate("trine-eval", "trine-eval run", runner=runner)
    gate.evaluate(CrewResult(task_id="abc", branch="automate/abc", changed=True))
    assert runner.calls == [["trine-eval", "run", "abc", "automate/abc"]]
