"""Structural interfaces (ports) the orchestrator depends on.

Defining these as Protocols keeps the orchestrator decoupled from concrete
adapters (composition over inheritance): the user's forks, the bundled adapters,
or lightweight test fakes all satisfy them structurally, with no base class to
inherit.
"""

from __future__ import annotations

from typing import Protocol

from automate.models import CrewResult, GateResult, Task, Verdict, Worktree


class WorktreeProvider(Protocol):
    """Provisions and releases isolated worktrees (implemented by treehouse)."""

    def create(self, task: Task) -> Worktree: ...

    def release(self, worktree: Worktree) -> None: ...


class CrewRunner(Protocol):
    """Runs an agent crew against a worktree (implemented by firstmate)."""

    def run(self, task: Task, worktree: Worktree) -> CrewResult: ...


class Gate(Protocol):
    """A governance or evaluation gate over a crew's output.

    Receives the task as well: gate commands run inside the task's repo and
    judge the crew's branch against the task's intent.
    """

    def evaluate(self, task: Task, crew: CrewResult) -> Verdict: ...


class ShipGate(Protocol):
    """The safe-push gate that ships work (implemented by no-mistakes).

    Receives the task as well as the worktree: the pipeline wants the task's
    intent (the goal behind the change), and gate initialization is anchored to
    the task's repository.
    """

    def gate(self, task: Task, worktree: Worktree) -> GateResult: ...
