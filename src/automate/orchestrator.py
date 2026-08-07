"""The agent-execution lifecycle: worktree -> crew -> gates -> ship."""

from __future__ import annotations

from automate.adapters import (
    DirectCrewAdapter,
    FirstmateAdapter,
    NoMistakesAdapter,
    TreehouseAdapter,
)
from automate.config import Settings
from automate.harnesses import CommandGate
from automate.models import RunRecord, RunStatus, Task, Verdict, Worktree
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
        crew: CrewRunner,
        no_mistakes: ShipGate,
        gates: list[Gate],
    ) -> None:
        self._treehouse = treehouse
        self._crew = crew
        self._no_mistakes = no_mistakes
        self._gates = gates

    @classmethod
    def from_settings(cls, settings: Settings) -> Orchestrator:
        """Build an orchestrator with the bundled adapters wired from config."""
        dry = settings.dry_run
        crew: CrewRunner
        if settings.crew_backend == "firstmate":
            crew = FirstmateAdapter(home=settings.firstmate_home, dry_run=dry)
        else:
            crew = DirectCrewAdapter(
                agent_cmd=settings.agent_cmd,
                dry_run=dry,
                agent_timeout=settings.agent_timeout_s,
            )
        return cls(
            treehouse=TreehouseAdapter(settings.treehouse_bin, dry_run=dry),
            crew=crew,
            no_mistakes=NoMistakesAdapter(
                settings.no_mistakes_bin, dry_run=dry, timeout=settings.ship_timeout_s
            ),
            gates=[
                CommandGate(
                    "henkaten-council",
                    settings.governance_cmd,
                    dry_run=dry,
                    timeout=settings.gate_timeout_s,
                ),
                CommandGate(
                    "trine-eval",
                    settings.codegen_cmd,
                    dry_run=dry,
                    timeout=settings.gate_timeout_s,
                ),
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

        crew = self._crew.run(task, worktree)
        record.crew = crew
        record.log.append(crew.summary)

        if not crew.changed:
            record.status = RunStatus.NO_CHANGES
            self._release(worktree, record)
            return

        record.verdicts = [gate.evaluate(crew) for gate in self._gates]
        for verdict in record.verdicts:
            record.log.append(self._format_verdict(verdict))

        if not all(v.passed for v in record.verdicts):
            record.status = RunStatus.GATED
            record.log.append("one or more gates failed; not shipping")
            self._release(worktree, record)
            return

        ship = self._no_mistakes.gate(task, worktree)
        record.gate = ship
        if ship.pushed:
            record.status = RunStatus.SHIPPED
            record.log.append(f"shipped via no-mistakes (pr={ship.pr_url or 'pending'})")
        else:
            record.status = RunStatus.GATED
            record.log.append("no-mistakes gate blocked the push")
        self._release(worktree, record)

    def _release(self, worktree: Worktree, record: RunRecord) -> None:
        """Return the pooled worktree on every terminal state except FAILED.

        The task branch lives in the shared repo and survives the return
        (validated against treehouse), so releasing loses nothing - the record
        keeps the branch name for inspection. A release failure is logged rather
        than raised so it cannot overwrite the run's real outcome. Crashed
        (FAILED) runs skip release in ``run()``'s handler by never reaching here,
        keeping the worktree for an autopsy.
        """
        try:
            self._treehouse.release(worktree)
            record.log.append(f"worktree returned to pool (branch {worktree.branch} kept)")
        except Exception as exc:  # boundary: release must not mask the run outcome
            record.log.append(f"worktree release failed (lease left open): {exc}")

    @staticmethod
    def _format_verdict(verdict: Verdict) -> str:
        state = "passed" if verdict.passed else "failed"
        suffix = f" ({'; '.join(verdict.findings)})" if verdict.findings else ""
        return f"gate {verdict.gate} {state}{suffix}"
