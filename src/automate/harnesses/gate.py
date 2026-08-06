"""Quality gates backed by the user's harnesses.

A :class:`CommandGate` delegates to an external command - henkaten-council for
governance, trine-eval for codegen/evaluation. An empty command disables the gate
(auto-pass) so the execution layer runs standalone until a harness is wired in.
"""

from __future__ import annotations

import shlex

from automate.adapters.base import CommandRunner
from automate.models import CrewResult, Verdict


class CommandGate:
    """A governance/evaluation gate that delegates to an external harness command."""

    def __init__(
        self,
        gate: str,
        command: str = "",
        *,
        dry_run: bool = True,
        runner: CommandRunner | None = None,
    ) -> None:
        self._gate = gate
        self._command = command
        self._runner = runner or CommandRunner(dry_run=dry_run)

    @property
    def name(self) -> str:
        return self._gate

    def evaluate(self, crew: CrewResult) -> Verdict:
        """Run the gate over ``crew``'s output, returning a pass/fail verdict."""
        if not self._command:
            return Verdict(gate=self._gate, passed=True, findings=["gate disabled"])
        result = self._runner.run([*shlex.split(self._command), crew.task_id, crew.branch])
        if result.ok:
            return Verdict(gate=self._gate, passed=True)
        return Verdict(
            gate=self._gate,
            passed=False,
            findings=[result.stderr.strip() or "gate reported failure"],
        )
