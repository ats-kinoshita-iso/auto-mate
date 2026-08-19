"""The review lifecycle: gh adapter, deep reviewer, and orchestrator records."""

from __future__ import annotations

from pathlib import Path

from automate.adapters import AgentReviewAdapter, GhAdapter, TreehouseAdapter
from automate.adapters.base import CommandRunner
from automate.models import (
    CrewResult,
    PullRequest,
    ReviewStatus,
    Task,
    Verdict,
    Worktree,
)
from automate.review import ReviewOrchestrator
from test_adapters import RecordingRunner

_PR_JSON = (
    '{"number": 10, "title": "WS-2: explainers", "body": "Adds glosses.",'
    ' "baseRefName": "ws/copy-voice", "headRefName": "ws/chakra-explainers",'
    ' "headRefOid": "abc123", "isDraft": true,'
    ' "url": "https://github.com/me/repo/pull/10", "additions": 3650, "deletions": 1545}'
)

_TASK = Task(id="pr-10", prompt="intent", repo="/clone", base_ref="origin/ws/copy-voice")
_WORKTREE = Worktree(task_id="pr-10", path="/wt", branch="automate/pr-10")


# --- GhAdapter -----------------------------------------------------------------


def test_gh_view_parses_gh_json_aliases() -> None:
    runner = RecordingRunner(stdout=_PR_JSON)
    adapter = GhAdapter(clone_root="/tmp/repos", runner=runner)
    pr = adapter.view("/clone", 10)
    assert pr.number == 10
    assert pr.base_ref == "ws/copy-voice"  # stacked base, not main
    assert pr.head_ref == "ws/chakra-explainers"
    assert pr.draft is True
    assert runner.calls[0][:3] == ["gh", "pr", "view"]
    assert runner.cwds == ["/clone"]


def test_gh_list_open_parses_a_list() -> None:
    runner = RecordingRunner(stdout=f"[{_PR_JSON}]")
    adapter = GhAdapter(clone_root="/tmp/repos", runner=runner)
    prs = adapter.list_open("/clone")
    assert [pr.number for pr in prs] == [10]


def test_gh_ensure_clone_skips_existing_dir(tmp_path: Path) -> None:
    runner = RecordingRunner()
    adapter = GhAdapter(clone_root=str(tmp_path / "repos"), runner=runner)
    existing = tmp_path / "already-here"
    existing.mkdir()
    assert adapter.ensure_clone(str(existing)) == str(existing)
    assert runner.calls == []  # no clone command for a local path


def test_gh_ensure_clone_keys_clones_by_full_slug(tmp_path: Path) -> None:
    # Same-named repos of different owners must never share a clone directory.
    runner = RecordingRunner()
    root = tmp_path / "repos"
    adapter = GhAdapter(clone_root=str(root), runner=runner)
    assert adapter.ensure_clone("alice/tools") == str(root / "alice" / "tools")
    assert adapter.ensure_clone("bob/tools") == str(root / "bob" / "tools")
    assert runner.calls == [
        ["gh", "repo", "clone", "alice/tools", str(root / "alice" / "tools")],
        ["gh", "repo", "clone", "bob/tools", str(root / "bob" / "tools")],
    ]


def test_gh_fetch_pr_fetches_head_and_the_prs_own_base() -> None:
    # An explicit refspec suppresses opportunistic remote-tracking updates, so
    # the base must be fetched explicitly or stacked-PR diffs go stale.
    runner = RecordingRunner()
    adapter = GhAdapter(clone_root="/tmp/repos", runner=runner, timeout=321.0)
    pr = PullRequest(number=10, title="t", base_ref="ws/copy-voice")
    ref = adapter.fetch_pr("/clone", pr)
    assert ref == "refs/automate/pr/10"
    assert runner.calls == [
        [
            "git",
            "-C",
            "/clone",
            "fetch",
            "origin",
            "+refs/pull/10/head:refs/automate/pr/10",
            "+refs/heads/ws/copy-voice:refs/remotes/origin/ws/copy-voice",
        ]
    ]
    assert runner.timeouts == [321.0]  # the fetch is bounded like every other call


def test_gh_checkout_resets_worktree_to_ref() -> None:
    runner = RecordingRunner()
    adapter = GhAdapter(clone_root="/tmp/repos", runner=runner)
    adapter.checkout(_WORKTREE, "refs/automate/pr/10")
    assert runner.calls == [["git", "-C", "/wt", "reset", "--hard", "refs/automate/pr/10"]]


def test_gh_comment_posts_body_and_returns_url() -> None:
    runner = RecordingRunner(stdout="https://github.com/me/repo/pull/10#issuecomment-1\n")
    adapter = GhAdapter(clone_root="/tmp/repos", runner=runner)
    url = adapter.comment("/clone", 10, "review body")
    assert url == "https://github.com/me/repo/pull/10#issuecomment-1"
    assert runner.calls == [["gh", "pr", "comment", "10", "--body", "review body"]]
    assert runner.cwds == ["/clone"]


def test_gh_comment_truncates_over_the_github_cap() -> None:
    runner = RecordingRunner(stdout="url")
    adapter = GhAdapter(clone_root="/tmp/repos", runner=runner)
    adapter.comment("/clone", 10, "x" * 70_000)
    body = runner.calls[0][-1]
    assert len(body) < 65_536
    assert body.endswith("*[review truncated to fit the comment limit]*")


# --- AgentReviewAdapter --------------------------------------------------------


def test_review_agent_runs_in_worktree_with_intent_and_base() -> None:
    runner = RecordingRunner(stdout="## Review\nLooks solid.\n")
    adapter = AgentReviewAdapter(agent_cmd="claude -p --flag", runner=runner, timeout=1800.0)
    body = adapter.review(_TASK, _WORKTREE)
    assert body == "## Review\nLooks solid."
    # "--" shields the prompt from variadic flags like claude's --allowedTools.
    assert runner.calls[0][:4] == ["claude", "-p", "--flag", "--"]
    prompt = runner.calls[0][-1]
    assert "intent" in prompt and "origin/ws/copy-voice" in prompt
    assert runner.cwds == ["/wt"]
    assert runner.timeouts == [1800.0]


def test_review_agent_code_review_engine_invokes_native_skill() -> None:
    runner = RecordingRunner(stdout="## Review findings\n...")
    adapter = AgentReviewAdapter(agent_cmd="claude -p --flag", engine="code-review", runner=runner)
    adapter.review(_TASK, _WORKTREE)
    assert runner.calls[0][:4] == ["claude", "-p", "--flag", "--"]
    # The native skill takes the base ref + effort level; intent stays with the gates.
    assert runner.calls[0][-1] == f"/code-review {_TASK.base_ref} high"


# --- ReviewOrchestrator --------------------------------------------------------


class FakeHost:
    def __init__(self) -> None:
        self.comments: list[tuple[int, str]] = []
        self.checkouts: list[str] = []
        self.prs = [
            PullRequest(
                number=10,
                title="WS-2: explainers",
                body="Adds glosses.",
                base_ref="ws/copy-voice",
                head_ref="ws/chakra-explainers",
                url="https://github.com/me/repo/pull/10",
                additions=3650,
                deletions=1545,
            ),
            PullRequest(number=8, title="Design loop v2", base_ref="main"),
        ]

    def ensure_clone(self, repo: str) -> str:
        return "/clone"

    def list_open(self, clone: str) -> list[PullRequest]:
        return list(self.prs)

    def view(self, clone: str, number: int) -> PullRequest:
        return next(pr for pr in self.prs if pr.number == number)

    def fetch_pr(self, clone: str, pr: PullRequest) -> str:
        return f"refs/automate/pr/{pr.number}"

    def checkout(self, worktree: Worktree, ref: str) -> None:
        self.checkouts.append(ref)

    def comment(self, clone: str, number: int, body: str) -> str:
        self.comments.append((number, body))
        return f"https://github.com/me/repo/pull/{number}#issuecomment-9"


class FakeTreehouse:
    def __init__(self) -> None:
        self.released: list[str] = []

    def create(self, task: Task) -> Worktree:
        return Worktree(task_id=task.id, path=f"/wt/{task.id}", branch=f"automate/{task.id}")

    def release(self, worktree: Worktree) -> None:
        self.released.append(worktree.task_id)


class FakeReviewer:
    def __init__(self, *, body: str = "Deep review body.", boom: bool = False) -> None:
        self._body = body
        self._boom = boom
        self.tasks: list[Task] = []

    def review(self, task: Task, worktree: Worktree) -> str:
        self.tasks.append(task)
        if self._boom:
            raise RuntimeError("reviewer crashed")
        return self._body


class FakeGate:
    def __init__(self, name: str, *, passed: bool = True) -> None:
        self._name = name
        self._passed = passed
        self.bases: list[str] = []

    def evaluate(self, task: Task, crew: CrewResult) -> Verdict:
        self.bases.append(task.base_ref)
        findings = [] if self._passed else ["VERDICT: FAIL - scope drift"]
        return Verdict(gate=self._name, passed=self._passed, findings=findings)


def _build(
    tmp_path: Path, *, gate_passes: bool = True, boom: bool = False
) -> tuple[ReviewOrchestrator, FakeHost, FakeTreehouse, FakeReviewer]:
    host = FakeHost()
    treehouse = FakeTreehouse()
    reviewer = FakeReviewer(boom=boom)
    orchestrator = ReviewOrchestrator(
        host=host,
        treehouse=treehouse,
        reviewer=reviewer,
        gates=[FakeGate("henkaten-council", passed=gate_passes), FakeGate("trine-eval")],
        reports_dir=str(tmp_path / "reviews"),
    )
    return orchestrator, host, treehouse, reviewer


def test_review_happy_path_saves_report_and_does_not_post(tmp_path: Path) -> None:
    orchestrator, host, treehouse, reviewer = _build(tmp_path)
    record = orchestrator.review_pr("me/repo", 10)
    assert record.status is ReviewStatus.REVIEWED
    assert record.posted is False and host.comments == []
    assert [v.passed for v in record.verdicts] == [True, True]
    assert record.review == "Deep review body."
    assert treehouse.released == ["pr-10"]
    assert host.checkouts == ["refs/automate/pr/10"]
    # The gates judged against the PR's own (stacked) base, and the report has it all.
    assert reviewer.tasks[0].base_ref == "origin/ws/copy-voice"
    assert record.report_path is not None
    report = Path(record.report_path).read_text(encoding="utf-8")
    assert "PR #10" in report and "henkaten-council" in report and "Deep review body." in report


def test_review_post_flag_comments_the_report(tmp_path: Path) -> None:
    orchestrator, host, _, _ = _build(tmp_path)
    record = orchestrator.review_pr("me/repo", 10, post=True)
    assert record.status is ReviewStatus.POSTED
    assert record.posted is True
    assert record.comment_url == "https://github.com/me/repo/pull/10#issuecomment-9"
    number, body = host.comments[0]
    assert number == 10 and "Deep review body." in body


def test_review_failing_gate_is_content_not_failure(tmp_path: Path) -> None:
    orchestrator, _, treehouse, _ = _build(tmp_path, gate_passes=False)
    record = orchestrator.review_pr("me/repo", 10)
    assert record.status is ReviewStatus.REVIEWED
    assert record.verdicts[0].passed is False
    assert record.report_path is not None
    assert "FAIL" in Path(record.report_path).read_text(encoding="utf-8")
    assert treehouse.released == ["pr-10"]


def test_review_crash_yields_failed_record_and_releases_worktree(tmp_path: Path) -> None:
    orchestrator, _, treehouse, _ = _build(tmp_path, boom=True)
    record = orchestrator.review_pr("me/repo", 10)
    assert record.status is ReviewStatus.FAILED
    assert any("reviewer crashed" in line for line in record.log)
    assert treehouse.released == ["pr-10"]  # released even on failure


def test_review_open_reviews_every_open_pr(tmp_path: Path) -> None:
    orchestrator, _, _, _ = _build(tmp_path)
    records = orchestrator.review_open("me/repo")
    assert [record.pr.number for record in records] == [10, 8]
    assert all(record.status is ReviewStatus.REVIEWED for record in records)


def test_review_open_yields_a_failed_record_when_listing_crashes(tmp_path: Path) -> None:
    class DownHost(FakeHost):
        def list_open(self, clone: str) -> list[PullRequest]:
            raise RuntimeError("gh not authenticated")

    orchestrator = ReviewOrchestrator(
        host=DownHost(),
        treehouse=FakeTreehouse(),
        reviewer=FakeReviewer(),
        gates=[],
        reports_dir=str(tmp_path / "reviews"),
    )
    records = orchestrator.review_open("me/repo")
    assert len(records) == 1
    assert records[0].status is ReviewStatus.FAILED
    assert any("gh not authenticated" in line for line in records[0].log)


def test_review_from_settings_wires_bundled_adapters() -> None:
    from automate.config import Settings

    orchestrator = ReviewOrchestrator.from_settings(Settings(_env_file=None))
    assert isinstance(orchestrator._host, GhAdapter)
    assert isinstance(orchestrator._treehouse, TreehouseAdapter)
    assert isinstance(orchestrator._reviewer, AgentReviewAdapter)


def test_dry_run_walks_the_whole_review_lifecycle(tmp_path: Path) -> None:
    runner = CommandRunner(dry_run=True)
    host = GhAdapter(clone_root=str(tmp_path / "repos"), runner=runner)
    orchestrator = ReviewOrchestrator(
        host=host,
        treehouse=TreehouseAdapter(runner=runner),
        reviewer=AgentReviewAdapter(agent_cmd="claude -p", runner=runner),
        gates=[],
        reports_dir=str(tmp_path / "reviews"),
    )
    record = orchestrator.review_pr("me/repo", 7)
    assert record.status is ReviewStatus.REVIEWED
    assert record.pr.number == 7
    assert "[dry-run]" in record.review
    assert record.report_path is not None


def test_review_from_settings_selects_cloud_runnable_backends() -> None:
    from automate.adapters import GitHost, GitWorktreeProvider
    from automate.config import Settings

    orchestrator = ReviewOrchestrator.from_settings(
        Settings(_env_file=None, review_host="git", worktree_backend="git")
    )
    assert isinstance(orchestrator._host, GitHost)
    assert isinstance(orchestrator._treehouse, GitWorktreeProvider)
