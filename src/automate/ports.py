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
    """A governance or evaluation gate over a crew's output."""

    def evaluate(self, crew: CrewResult) -> Verdict: ...


class ShipGate(Protocol):
    """The safe-push gate that ships work (implemented by no-mistakes)."""

    def gate(self, worktree: Worktree) -> GateResult: ...
