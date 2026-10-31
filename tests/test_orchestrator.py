"""The orchestrator walks the lifecycle and records each outcome correctly."""

from __future__ import annotations

from automate.adapters import DirectCrewAdapter, FirstmateAdapter
from automate.config import Settings
from automate.models import (
    AgentUsage,
    CrewResult,
    GateResult,
    RunStatus,
    Task,
    TokenUsage,
    Verdict,
    Worktree,
)
from automate.orchestrator import Orchestrator

TASK = Task(id="t1", prompt="add dark mode", repo="/repo")


class FakeTreehouse:
    def __init__(self) -> None:
        self.released: list[str] = []

    def create(self, task: Task) -> Worktree:
        return Worktree(task_id=task.id, path=f"/wt/{task.id}", branch=f"automate/{task.id}")

    def release(self, worktree: Worktree) -> None:
        self.released.append(worktree.task_id)


class FakeCrew:
    def __init__(self, *, changed: bool = True, usage: AgentUsage | None = None) -> None:
        self._changed = changed
        self._usage = usage

    def run(self, task: Task, worktree: Worktree) -> CrewResult:
        return CrewResult(
            task_id=task.id,
            branch=worktree.branch,
            changed=self._changed,
            summary="crew ran",
            usage=self._usage,
        )


class FakeGate:
    def __init__(self, name: str, *, passed: bool = True, usage: AgentUsage | None = None) -> None:
        self._name = name
        self._passed = passed
        self._usage = usage

    def evaluate(self, task: Task, crew: CrewResult) -> Verdict:
        return Verdict(gate=self._name, passed=self._passed, usage=self._usage)


class FakeShip:
    def __init__(self, *, pushed: bool = True) -> None:
        self._pushed = pushed
        self.intents: list[str] = []

    def gate(self, task: Task, worktree: Worktree) -> GateResult:
        self.intents.append(task.prompt)
        url = "https://github.com/me/repo/pull/1" if self._pushed else None
        return GateResult(task_id=worktree.task_id, pushed=self._pushed, pr_url=url)


def _build(
    *, changed: bool = True, gate_passes: bool = True, pushed: bool = True
) -> tuple[Orchestrator, FakeTreehouse]:
    treehouse = FakeTreehouse()
    orchestrator = Orchestrator(
        treehouse=treehouse,
        crew=FakeCrew(changed=changed),
        no_mistakes=FakeShip(pushed=pushed),
        gates=[FakeGate("henkaten-council", passed=gate_passes), FakeGate("trine-eval")],
    )
    return orchestrator, treehouse


def test_happy_path_ships_and_returns_worktree() -> None:
    orchestrator, treehouse = _build()
    record = orchestrator.run(TASK)
    assert record.status is RunStatus.SHIPPED
    assert record.shipped is True
    assert record.gate is not None and record.gate.pr_url is not None
    assert len(record.verdicts) == 2
    # The branch survives the return (treehouse worktrees share the repo's refs),
    # so the pooled worktree goes back on every terminal state except FAILED.
    assert treehouse.released == ["t1"]


def test_ship_gate_receives_the_task_intent() -> None:
    ship = FakeShip()
    orchestrator = Orchestrator(
        treehouse=FakeTreehouse(), crew=FakeCrew(), no_mistakes=ship, gates=[]
    )
    orchestrator.run(TASK)
    assert ship.intents == ["add dark mode"]


def test_no_changes_releases_worktree_and_skips_gates() -> None:
    orchestrator, treehouse = _build(changed=False)
    record = orchestrator.run(TASK)
    assert record.status is RunStatus.NO_CHANGES
    assert record.verdicts == []
    assert record.gate is None
    assert treehouse.released == ["t1"]


def test_failing_gate_blocks_ship_and_releases() -> None:
    orchestrator, treehouse = _build(gate_passes=False)
    record = orchestrator.run(TASK)
    assert record.status is RunStatus.GATED
    assert record.gate is None  # never reached the ship gate
    assert treehouse.released == ["t1"]


def test_blocked_push_is_gated() -> None:
    orchestrator, treehouse = _build(pushed=False)
    record = orchestrator.run(TASK)
    assert record.status is RunStatus.GATED
    assert record.gate is not None and record.gate.pushed is False
    assert treehouse.released == ["t1"]


def test_release_failure_does_not_mask_the_shipped_outcome() -> None:
    class LeakyTreehouse(FakeTreehouse):
        def release(self, worktree: Worktree) -> None:
            raise RuntimeError("lease already returned")

    orchestrator = Orchestrator(
        treehouse=LeakyTreehouse(), crew=FakeCrew(), no_mistakes=FakeShip(), gates=[]
    )
    record = orchestrator.run(TASK)
    assert record.status is RunStatus.SHIPPED
    assert any("release failed" in line for line in record.log)


def test_run_record_totals_crew_and_gate_usage() -> None:
    crew_usage = AgentUsage(
        usage=TokenUsage(input_tokens=100, output_tokens=10),
        cost_usd=0.5,
        cost_source="claude-code-estimate",
    )
    gate_usage = AgentUsage(
        usage=TokenUsage(input_tokens=5, output_tokens=1, cache_read_input_tokens=50),
        cost_usd=0.1,
        cost_source="claude-code-estimate",
    )
    orchestrator = Orchestrator(
        treehouse=FakeTreehouse(),
        crew=FakeCrew(usage=crew_usage),
        no_mistakes=FakeShip(),
        gates=[
            FakeGate("henkaten-council", usage=gate_usage),
            FakeGate("trine-eval", usage=gate_usage),
        ],
    )
    record = orchestrator.run(TASK)
    assert record.total_usage == TokenUsage(
        input_tokens=110, output_tokens=12, cache_read_input_tokens=100
    )
    assert record.total_cost_usd == 0.7
    assert '"total_cost_usd":0.7' in record.model_dump_json()


def test_run_record_totals_are_none_when_nothing_was_reported() -> None:
    orchestrator, _ = _build()
    record = orchestrator.run(TASK)
    assert record.total_usage is None and record.total_cost_usd is None


def test_stage_exception_is_captured_as_failed_and_keeps_worktree() -> None:
    class Boom:
        def create(self, task: Task) -> Worktree:
            raise RuntimeError("treehouse offline")

        def release(self, worktree: Worktree) -> None: ...

    orchestrator = Orchestrator(
        treehouse=Boom(),
        crew=FakeCrew(),
        no_mistakes=FakeShip(),
        gates=[],
    )
    record = orchestrator.run(TASK)
    assert record.status is RunStatus.FAILED
    assert any("treehouse offline" in line for line in record.log)


def test_from_settings_selects_crew_backend() -> None:
    direct = Orchestrator.from_settings(Settings(_env_file=None, crew_backend="direct"))
    assert isinstance(direct._crew, DirectCrewAdapter)
    firstmate = Orchestrator.from_settings(Settings(_env_file=None, crew_backend="firstmate"))
    assert isinstance(firstmate._crew, FirstmateAdapter)
