"""Quality gates backed by the user's harnesses.

A :class:`CommandGate` delegates to an external command - henkaten-council for
governance, trine-eval for codegen/evaluation. An empty command disables the gate
(auto-pass) so the execution layer runs standalone until a harness is wired in.
"""

from __future__ import annotations

import shlex
from typing import TYPE_CHECKING

from automate.adapters.base import CommandRunner
from automate.models import CrewResult, Task, Verdict

if TYPE_CHECKING:
    from automate.config import Settings


class CommandGate:
    """A governance/evaluation gate that delegates to an external harness command."""

    def __init__(
        self,
        gate: str,
        command: str = "",
        *,
        dry_run: bool = True,
        runner: CommandRunner | None = None,
        timeout: float | None = None,
    ) -> None:
        self._gate = gate
        self._command = command
        self._runner = runner or CommandRunner(dry_run=dry_run)
        self._timeout = timeout

    @property
    def name(self) -> str:
        return self._gate

    def evaluate(self, task: Task, crew: CrewResult) -> Verdict:
        """Run the gate over ``crew``'s output, returning a pass/fail verdict.

        The command is invoked as ``<command> <task-id> <branch> <intent>
        <base-ref>`` with the task's repo as working directory, so gate scripts
        can diff the branch against the task's own base (PRs may target a branch
        other than main) and judge it against what the task set out to do. It
        runs with ``check=False``: a non-zero exit is this gate's "fail" signal
        and must surface as a failed verdict (a GATED run), not as an exception
        (a FAILED run).
        """
        if not self._command:
            return Verdict(gate=self._gate, passed=True, findings=["gate disabled"])
        result = self._runner.run(
            [*shlex.split(self._command), crew.task_id, crew.branch, task.prompt, task.base_ref],
            cwd=task.repo,
            check=False,
            timeout=self._timeout,
        )
        if result.ok:
            return Verdict(gate=self._gate, passed=True)
        return Verdict(
            gate=self._gate,
            passed=False,
            findings=[result.stderr.strip() or "gate reported failure"],
        )


def harness_gates(settings: Settings) -> list[CommandGate]:
    """The two bundled harness gates, wired from settings.

    Shared by the run and review lifecycles so gate wiring lives in one place.
    """
    return [
        CommandGate(
            "henkaten-council",
            settings.governance_cmd,
            dry_run=settings.dry_run,
            timeout=settings.gate_timeout_s,
        ),
        CommandGate(
            "trine-eval",
            settings.codegen_cmd,
            dry_run=settings.dry_run,
            timeout=settings.gate_timeout_s,
        ),
    ]
