"""Adapters build the right commands and parse results at the subprocess boundary."""

from __future__ import annotations

from pathlib import Path

import pytest

from automate.adapters import (
    DirectCrewAdapter,
    FirstmateAdapter,
    NoMistakesAdapter,
    TreehouseAdapter,
)
from automate.adapters.base import AdapterError, CommandResult, CommandRunner
from automate.harnesses import CommandGate
from automate.models import CrewResult, Task, Worktree


class RecordingRunner(CommandRunner):
    """A CommandRunner that records commands and returns canned output."""

    def __init__(self, *, stdout: str = "", returncode: int = 0, dry_run: bool = False) -> None:
        super().__init__(dry_run=dry_run)
        self.calls: list[list[str]] = []
        self.cwds: list[str | None] = []
        self.timeouts: list[float | None] = []
        self._stdout = stdout
        self._returncode = returncode

    def run(
        self,
        command: list[str],
        *,
        cwd: str | None = None,
        check: bool = True,
        timeout: float | None = None,
    ) -> CommandResult:
        self.calls.append(command)
        self.cwds.append(cwd)
        self.timeouts.append(timeout)
        return CommandResult(
            command=command, returncode=self._returncode, stdout=self._stdout, stderr=""
        )


def test_treehouse_create_acquires_lease_and_cuts_branch() -> None:
    allocation = (
        '{"path": "/home/u/.treehouse/abc/1/repo", "lease_id": "lease-01XYZ",'
        ' "lease_holder": "abc", "leased_at": "2026-08-17T00:00:00Z"}'
    )
    runner = RecordingRunner(stdout=allocation)
    adapter = TreehouseAdapter("treehouse", runner=runner)
    worktree = adapter.create(Task(id="abc", prompt="do it", repo="/repo"))
    assert worktree.path == "/home/u/.treehouse/abc/1/repo"
    assert worktree.branch == "automate/abc"
    assert worktree.lease_id == "lease-01XYZ"
    assert runner.calls == [
        ["treehouse", "get", "--lease", "--lease-holder", "abc", "--json"],
        # -C, not -c: re-running a task id resets its branch instead of failing.
        ["git", "-C", "/home/u/.treehouse/abc/1/repo", "switch", "-C", "automate/abc"],
    ]


def test_treehouse_create_rejects_unparseable_allocation() -> None:
    runner = RecordingRunner(stdout="not json")
    adapter = TreehouseAdapter("treehouse", runner=runner)
    with pytest.raises(AdapterError, match="unparseable allocation"):
        adapter.create(Task(id="abc", prompt="do it", repo="/repo"))


def test_treehouse_create_rejects_null_path_and_normalizes_empty_lease_id() -> None:
    runner = RecordingRunner(stdout='{"path": null, "lease_id": "x"}')
    adapter = TreehouseAdapter("treehouse", runner=runner)
    with pytest.raises(AdapterError, match="no usable path"):
        adapter.create(Task(id="abc", prompt="do it", repo="/repo"))

    runner = RecordingRunner(stdout='{"path": "/wt", "lease_id": ""}')
    adapter = TreehouseAdapter("treehouse", runner=runner)
    worktree = adapter.create(Task(id="abc", prompt="do it", repo="/repo"))
    assert worktree.lease_id is None  # empty string normalized: release uses holder guard


def test_treehouse_release_prefers_lease_id_guard() -> None:
    runner = RecordingRunner()
    adapter = TreehouseAdapter("treehouse", runner=runner)
    adapter.release(
        Worktree(task_id="abc", path="/wt", branch="automate/abc", lease_id="lease-01XYZ")
    )
    assert runner.calls == [
        ["treehouse", "return", "/wt", "--force", "--if-lease-id", "lease-01XYZ"]
    ]


def test_treehouse_release_falls_back_to_holder_guard_without_lease_id() -> None:
    runner = RecordingRunner()
    adapter = TreehouseAdapter("treehouse", runner=runner)
    adapter.release(Worktree(task_id="abc", path="/wt", branch="automate/abc"))
    assert runner.calls == [["treehouse", "return", "/wt", "--force", "--if-lease-holder", "abc"]]


def test_treehouse_release_passes_empty_lease_id_through_loudly() -> None:
    # A manually-built empty-string lease_id must NOT silently downgrade to the
    # holder guard - it goes through as --if-lease-id "" and fails at treehouse.
    runner = RecordingRunner()
    adapter = TreehouseAdapter("treehouse", runner=runner)
    adapter.release(Worktree(task_id="abc", path="/wt", branch="automate/abc", lease_id=""))
    assert runner.calls == [["treehouse", "return", "/wt", "--force", "--if-lease-id", ""]]


_PASSED_TOON = """run:
  id: "01KZD0017H49TFKZXBFDQK6FRM"
  branch: automate/abc
  status: completed
  steps[9]{step,status,findings,duration_ms}:
    intent,completed,0,4
    review,completed,2,165846
    push,completed,0,78
    pr,skipped,0,6
outcome: passed
fixes[2]{step,summary}:
  rebase,fix applied (no summary recorded)
  review,drop out-of-scope files
help[1]: "Summarize this pipeline run."
"""

_TASK = Task(id="abc", prompt="add dark mode", repo="/repo")
_WORKTREE = Worktree(task_id="abc", path="/wt", branch="automate/abc")


def test_no_mistakes_gate_inits_then_drives_axi_run() -> None:
    runner = RecordingRunner(stdout=_PASSED_TOON)
    adapter = NoMistakesAdapter(runner=runner, timeout=1234.0)
    result = adapter.gate(_TASK, _WORKTREE)
    assert runner.calls == [
        ["no-mistakes", "init"],
        ["no-mistakes", "axi", "run", "--intent", "add dark mode", "--yes"],
    ]
    assert runner.cwds == ["/repo", "/wt"]  # init in the repo, run in the worktree
    assert runner.timeouts[1] == 1234.0
    assert result.pushed is True
    assert result.pr_url is None  # pr step skipped for non-GitHub remotes
    assert "outcome: passed" in result.findings
    assert any("drop out-of-scope files" in f for f in result.findings)


def test_no_mistakes_gate_parses_pr_url_when_present() -> None:
    toon = _PASSED_TOON + '\npr: "https://github.com/me/repo/pull/7"\n'
    runner = RecordingRunner(stdout=toon)
    adapter = NoMistakesAdapter(runner=runner)
    result = adapter.gate(_TASK, _WORKTREE)
    assert result.pushed is True
    assert result.pr_url == "https://github.com/me/repo/pull/7"


def test_no_mistakes_gate_failed_outcome_blocks_push() -> None:
    runner = RecordingRunner(stdout="run:\n  status: completed\noutcome: failed\n")
    adapter = NoMistakesAdapter(runner=runner)
    result = adapter.gate(_TASK, _WORKTREE)
    assert result.pushed is False
    assert "outcome: failed" in result.findings


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


def test_firstmate_dry_run_drives_the_real_brief_and_spawn_contract() -> None:
    runner = RecordingRunner(dry_run=True)
    adapter = FirstmateAdapter(home="/fm", runner=runner)
    crew = adapter.run(
        Task(id="abc", prompt="x", repo="/repos/myrepo"),
        Worktree(task_id="abc", path="/wt", branch="automate/abc"),
    )
    assert crew.changed is True
    # Path rendering is platform-dependent; the adapter builds these the same way.
    brief_script = str(Path("/fm") / "bin" / "fm-brief.sh")
    spawn_script = str(Path("/fm") / "bin" / "fm-spawn.sh")
    assert runner.calls == [
        ["bash", brief_script, "abc", "myrepo", "--mode", "local-only"],
        ["bash", spawn_script, "abc", "projects/myrepo", "--mode", "local-only", "--yolo", "off"],
    ]


def _firstmate_home(tmp_path: Path, *, status: str, meta: str | None = "worktree=/crew/wt") -> Path:
    home = tmp_path / "fm"
    (home / "data" / "abc").mkdir(parents=True)
    (home / "data" / "abc" / "brief.md").write_text("## Task\n{TASK}\n", encoding="utf-8")
    (home / "state").mkdir()
    if status:
        (home / "state" / "abc.status").write_text(status, encoding="utf-8")
    if meta is not None:
        (home / "state" / "abc.meta").write_text(meta + "\n", encoding="utf-8")
    return home


def test_firstmate_supervises_to_done_and_adopts_the_crew_branch(tmp_path: Path) -> None:
    # Stale state from a previous run is pre-created; the adapter must clear it,
    # then adopt only what "the crew" (our sleep hook) writes after the spawn.
    home = _firstmate_home(tmp_path, status="done: STALE previous-run line\n")

    def crew_reports(_seconds: float) -> None:
        (home / "state" / "abc.status").write_text(
            "spawned\ndone: ready in branch crew/abc\n", encoding="utf-8"
        )
        (home / "state" / "abc.meta").write_text("worktree=/crew/wt\n", encoding="utf-8")

    runner = RecordingRunner(stdout="crew/abc")
    adapter = FirstmateAdapter(home=str(home), runner=runner, sleep=crew_reports)
    crew = adapter.run(
        Task(id="abc", prompt="add dark mode", repo="/repos/myrepo"),
        Worktree(task_id="abc", path="/wt", branch="automate/abc"),
    )
    assert crew.changed is True
    assert "done: ready in branch" in crew.summary  # the fresh line, not the stale one
    brief = (home / "data" / "abc" / "brief.md").read_text(encoding="utf-8")
    assert "{TASK}" not in brief and "add dark mode" in brief
    assert ["git", "clone", "/repos/myrepo", str(home / "projects" / "myrepo")] in runner.calls
    assert ["git", "-C", "/wt", "fetch", "/crew/wt", "crew/abc"] in runner.calls
    assert ["git", "-C", "/wt", "switch", "-C", "automate/abc", "FETCH_HEAD"] in runner.calls


def test_firstmate_refreshes_an_existing_project_clone(tmp_path: Path) -> None:
    # A frozen clone would have every later crew implement against a stale base.
    home = _firstmate_home(tmp_path, status="")
    clone = home / "projects" / "myrepo"
    clone.mkdir(parents=True)

    def crew_reports(_seconds: float) -> None:
        (home / "state" / "abc.status").write_text("done: ready\n", encoding="utf-8")
        (home / "state" / "abc.meta").write_text("worktree=/crew/wt\n", encoding="utf-8")

    runner = RecordingRunner(stdout="crew/abc")
    adapter = FirstmateAdapter(home=str(home), runner=runner, sleep=crew_reports)
    adapter.run(
        Task(id="abc", prompt="x", repo="/repos/myrepo"),
        Worktree(task_id="abc", path="/wt", branch="automate/abc"),
    )
    assert ["git", "-C", str(clone), "fetch", "origin", "--prune"] in runner.calls
    assert ["git", "-C", str(clone), "pull", "--ff-only"] in runner.calls
    assert not any(call[:2] == ["git", "clone"] for call in runner.calls)


def test_firstmate_blocked_crew_raises(tmp_path: Path) -> None:
    home = _firstmate_home(tmp_path, status="")

    def crew_blocks(_seconds: float) -> None:
        (home / "state" / "abc.status").write_text("blocked: needs a decision\n", encoding="utf-8")

    adapter = FirstmateAdapter(home=str(home), runner=RecordingRunner(), sleep=crew_blocks)
    with pytest.raises(AdapterError, match="blocked"):
        adapter.run(
            Task(id="abc", prompt="x", repo="/repos/myrepo"),
            Worktree(task_id="abc", path="/wt", branch="automate/abc"),
        )


def test_firstmate_supervision_times_out(tmp_path: Path) -> None:
    home = _firstmate_home(tmp_path, status="")  # crew never reports
    ticks = iter(range(0, 100, 10))
    adapter = FirstmateAdapter(
        home=str(home),
        runner=RecordingRunner(),
        crew_timeout=25.0,
        sleep=lambda _s: None,
        clock=lambda: float(next(ticks)),
    )
    with pytest.raises(AdapterError, match="did not finish"):
        adapter.run(
            Task(id="abc", prompt="x", repo="/repos/myrepo"),
            Worktree(task_id="abc", path="/wt", branch="automate/abc"),
        )


def test_direct_crew_runs_agent_and_reports_no_changes() -> None:
    runner = RecordingRunner()  # empty stdout -> clean worktree, not ahead -> no changes
    adapter = DirectCrewAdapter(agent_cmd="claude --print", runner=runner, agent_timeout=900.0)
    crew = adapter.run(
        Task(id="abc", prompt="add dark mode", repo="/repo"),
        Worktree(task_id="abc", path="/wt", branch="automate/abc"),
    )
    assert runner.calls[0] == ["claude", "--print", "--", "add dark mode"]
    assert runner.timeouts[0] == 900.0
    assert crew.changed is False
    assert ["git", "-C", "/wt", "add", "-A"] not in runner.calls  # clean -> no commit


def test_direct_crew_commits_leftover_work_so_it_can_ship() -> None:
    runner = RecordingRunner(stdout="M src/app.py")
    adapter = DirectCrewAdapter(runner=runner)
    crew = adapter.run(
        Task(id="abc", prompt="add dark mode\nwith details", repo="/repo"),
        Worktree(task_id="abc", path="/wt", branch="automate/abc"),
    )
    assert crew.changed is True
    assert ["git", "-C", "/wt", "add", "-A"] in runner.calls
    commit = next(c for c in runner.calls if "commit" in c)
    assert commit == ["git", "-C", "/wt", "commit", "-m", "automate/abc: add dark mode"]


def test_direct_crew_commit_title_survives_an_empty_prompt() -> None:
    runner = RecordingRunner(stdout="M src/app.py")
    adapter = DirectCrewAdapter(runner=runner)
    adapter.run(
        Task(id="abc", prompt="", repo="/repo"),
        Worktree(task_id="abc", path="/wt", branch="automate/abc"),
    )
    commit = next(c for c in runner.calls if "commit" in c)
    assert commit == ["git", "-C", "/wt", "commit", "-m", "automate/abc: task abc"]


_CREW = CrewResult(task_id="abc", branch="automate/abc", changed=True)


def test_command_gate_disabled_when_no_command() -> None:
    runner = RecordingRunner()
    gate = CommandGate("henkaten-council", "", runner=runner)
    verdict = gate.evaluate(_TASK, _CREW)
    assert verdict.passed is True
    assert runner.calls == []  # disabled gate never shells out


def test_command_gate_runs_in_repo_with_task_context() -> None:
    runner = RecordingRunner()
    gate = CommandGate("trine-eval", "bash gates/codegen.sh", runner=runner)
    gate.evaluate(_TASK, _CREW)
    assert runner.calls == [
        ["bash", "gates/codegen.sh", "abc", "automate/abc", "add dark mode", "main"]
    ]
    assert runner.cwds == ["/repo"]  # gate scripts run inside the task's repo


def test_command_gate_passes_the_tasks_own_base_ref() -> None:
    # Stacked PRs target a branch other than main; the gate diff must use it.
    runner = RecordingRunner()
    gate = CommandGate("trine-eval", "review", runner=runner)
    stacked = Task(id="pr-10", prompt="explainers", repo="/repo", base_ref="origin/ws/copy-voice")
    gate.evaluate(stacked, CrewResult(task_id="pr-10", branch="refs/automate/pr/10", changed=True))
    assert runner.calls[0][-1] == "origin/ws/copy-voice"


def test_command_gate_failure_is_a_verdict_not_an_exception() -> None:
    runner = RecordingRunner(returncode=1)
    gate = CommandGate("trine-eval", "trine-eval run", runner=runner)
    verdict = gate.evaluate(_TASK, _CREW)
    assert verdict.passed is False
    assert verdict.findings == ["gate reported failure"]


# --- GitHost (cloud-runnable PR host) ------------------------------------------


def test_githost_clones_by_https_url_keyed_by_full_slug(tmp_path: Path) -> None:
    from automate.adapters import GitHost

    runner = RecordingRunner()
    root = tmp_path / "repos"
    host = GitHost(clone_root=str(root), runner=runner)
    assert host.ensure_clone("alice/tools") == str(root / "alice" / "tools")
    assert runner.calls == [
        ["git", "clone", "https://github.com/alice/tools.git", str(root / "alice" / "tools")],
    ]


def test_githost_view_builds_metadata_from_config() -> None:
    from automate.adapters import GitHost

    host = GitHost(
        clone_root="/tmp/repos",
        base_ref="develop",
        intent="Add dark mode\nUsers asked for it.",
        runner=RecordingRunner(),
    )
    pr = host.view("/clone", 7)
    assert pr.number == 7
    assert pr.title == "Add dark mode"
    assert pr.body == "Users asked for it."
    assert pr.base_ref == "develop"
    assert "Add dark mode" in pr.intent


def test_githost_fetches_pull_head_and_base_like_gh() -> None:
    from automate.adapters import GitHost
    from automate.models import PullRequest

    runner = RecordingRunner()
    host = GitHost(clone_root="/tmp/repos", runner=runner, timeout=123.0)
    pr = PullRequest(number=7, title="t", base_ref="develop")
    ref = host.fetch_pr("/clone", pr)
    assert ref == "refs/automate/pr/7"
    assert runner.calls == [
        [
            "git",
            "-C",
            "/clone",
            "fetch",
            "origin",
            "+refs/pull/7/head:refs/automate/pr/7",
            "+refs/heads/develop:refs/remotes/origin/develop",
        ]
    ]
    assert runner.timeouts == [123.0]


def test_githost_refuses_api_shaped_operations_loudly() -> None:
    from automate.adapters import GitHost

    host = GitHost(clone_root="/tmp/repos", runner=RecordingRunner())
    with pytest.raises(AdapterError, match="gh host"):
        host.list_open("/clone")
    with pytest.raises(AdapterError, match="saved locally"):
        host.comment("/clone", 7, "body")


# --- GitWorktreeProvider (cloud-runnable worktrees) ----------------------------


def test_git_worktree_create_adds_detached_worktree_and_cuts_branch(tmp_path: Path) -> None:
    from automate.adapters import GitWorktreeProvider

    runner = RecordingRunner()
    provider = GitWorktreeProvider(worktree_root=str(tmp_path / "wt"), runner=runner)
    worktree = provider.create(Task(id="abc", prompt="x", repo="/repos/myrepo"))
    expected = str(tmp_path / "wt" / "myrepo-abc")
    assert worktree.path == expected
    assert worktree.branch == "automate/abc"
    assert worktree.lease_id is None  # plain git has no leases
    assert runner.calls == [
        ["git", "-C", "/repos/myrepo", "worktree", "add", "--detach", expected],
        ["git", "-C", expected, "switch", "-C", "automate/abc"],
    ]


def test_git_worktree_release_resolves_parent_repo_from_the_worktree() -> None:
    from automate.adapters import GitWorktreeProvider

    runner = RecordingRunner(stdout="/repos/myrepo/.git\n")
    provider = GitWorktreeProvider(worktree_root="/tmp/wt", runner=runner)
    provider.release(Worktree(task_id="abc", path="/tmp/wt/myrepo-abc", branch="automate/abc"))
    assert runner.calls == [
        [
            "git",
            "-C",
            "/tmp/wt/myrepo-abc",
            "rev-parse",
            "--path-format=absolute",
            "--git-common-dir",
        ],
        ["git", "-C", "/repos/myrepo", "worktree", "remove", "--force", "/tmp/wt/myrepo-abc"],
    ]
