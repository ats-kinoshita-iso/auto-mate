"""The agent-execution lifecycle: worktree -> crew -> gates -> ship."""

from __future__ import annotations

from automate.adapters import FirstmateAdapter, NoMistakesAdapter, TreehouseAdapter
from automate.config import Settings
from automate.harnesses import CommandGate
from automate.models import RunRecord, RunStatus, Task, Verdict
from automate.ports import CrewRunner, Gate, ShipGate, WorktreeProvider


class Orchestrator:
    """Drives a task through the full execution lifecycle and records the run.

    The lifecycle stages are injected as ports (composition), so each is
    independently testable and the user's forks swap in without touching this
    class. :meth:`from_settings` wires the bundled adapters from configuration.
    """

    def __init__(
        self,
        *,
        treehouse: WorktreeProvider,
        firstmate: CrewRunner,
        no_mistakes: ShipGate,
        gates: list[Gate],
    ) -> None:
        self._treehouse = treehouse
        self._firstmate = firstmate
        self._no_mistakes = no_mistakes
        self._gates = gates

    @classmethod
    def from_settings(cls, settings: Settings) -> Orchestrator:
        """Build an orchestrator with the bundled adapters wired from config."""
        dry = settings.dry_run
        return cls(
            treehouse=TreehouseAdapter(settings.treehouse_bin, dry_run=dry),
            firstmate=FirstmateAdapter(home=settings.firstmate_home, dry_run=dry),
            no_mistakes=NoMistakesAdapter(settings.no_mistakes_bin, dry_run=dry),
            gates=[
                CommandGate("henkaten-council", settings.governance_cmd, dry_run=dry),
                CommandGate("trine-eval", settings.codegen_cmd, dry_run=dry),
            ],
        )

    def run(self, task: Task) -> RunRecord:
        """Execute ``task`` end to end, returning a structured record.

        Any exception from a stage is captured into the record as a FAILED run
        rather than propagated, so a run always yields an inspectable record.
        """
        record = RunRecord(task=task, status=RunStatus.FAILED)
        try:
            self._execute(task, record)
        except Exception as exc:  # boundary: surface failures in the record
            record.status = RunStatus.FAILED
            record.log.append(f"run failed: {exc}")
        return record

    def _execute(self, task: Task, record: RunRecord) -> None:
        worktree = self._treehouse.create(task)
        record.worktree = worktree
        record.log.append(f"provisioned worktree at {worktree.path} on {worktree.branch}")

        crew = self._firstmate.run(task, worktree)
        record.crew = crew
        record.log.append(crew.summary)

        if not crew.changed:
            record.status = RunStatus.NO_CHANGES
            record.log.append("crew produced no changes; releasing worktree")
            self._treehouse.release(worktree)
            return

        record.verdicts = [gate.evaluate(crew) for gate in self._gates]
        for verdict in record.verdicts:
            record.log.append(self._format_verdict(verdict))

        if not all(v.passed for v in record.verdicts):
            record.status = RunStatus.GATED
            record.log.append("one or more gates failed; not shipping")
            return

        ship = self._no_mistakes.gate(worktree)
        record.gate = ship
        if ship.pushed:
            record.status = RunStatus.SHIPPED
            record.log.append(f"shipped via no-mistakes (pr={ship.pr_url or 'pending'})")
        else:
            record.status = RunStatus.GATED
            record.log.append("no-mistakes gate blocked the push")

    @staticmethod
    def _format_verdict(verdict: Verdict) -> str:
        state = "passed" if verdict.passed else "failed"
        suffix = f" ({'; '.join(verdict.findings)})" if verdict.findings else ""
        return f"gate {verdict.gate} {state}{suffix}"
