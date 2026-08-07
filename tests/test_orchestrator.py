"""The orchestrator walks the lifecycle and records each outcome correctly."""

from __future__ import annotations

from automate.adapters import DirectCrewAdapter, FirstmateAdapter
from automate.config import Settings
from automate.models import CrewResult, GateResult, RunStatus, Task, Verdict, Worktree
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
    def __init__(self, *, changed: bool = True) -> None:
        self._changed = changed

    def run(self, task: Task, worktree: Worktree) -> CrewResult:
        return CrewResult(
            task_id=task.id, branch=worktree.branch, changed=self._changed, summary="crew ran"
        )


class FakeGate:
    def __init__(self, name: str, *, passed: bool = True) -> None:
        self._name = name
        self._passed = passed

    def evaluate(self, crew: CrewResult) -> Verdict:
        return Verdict(gate=self._name, passed=self._passed)


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
