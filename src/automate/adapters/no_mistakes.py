"""Adapter over ``no-mistakes``, the safe-push gate.

no-mistakes installs a local git-remote proxy: ``no-mistakes init`` registers a bare
gate repo as a remote named ``no-mistakes`` and detects the real target remote.
Validated live against no-mistakes v1.45.4 on Linux (2026-08-06):

- ``no-mistakes axi run --intent <goal> --yes`` is the agent-facing entrypoint: it
  drives the full pipeline (intent -> rebase -> review -> test -> document -> lint ->
  push -> pr -> ci) for the current branch, BLOCKS until the outcome, auto-resolves
  approval gates, and prints token-efficient TOON to stdout (progress streams to
  stderr). ``outcome: passed`` is the authoritative success signal; the pipeline may
  land fix commits, and the pushed head is forwarded to the real remote. The ``pr``
  step is auto-skipped for non-GitHub remotes.
- This replaces the earlier raw ``git push no-mistakes <branch>`` + stdout-scrape
  design: the push trigger is asynchronous and its stdout does not reliably carry
  the PR URL, while ``axi run`` is synchronous and structured.
- The daemon must be running (installed as a managed service by the installer);
  ``axi run`` fails fast with a clear error when it is not.
"""

from __future__ import annotations

import re

from automate.adapters.base import CommandRunner
from automate.models import GateResult, Task, Worktree

_PR_URL = re.compile(r"https://\S+/pull/\d+")
_OUTCOME = re.compile(r"^outcome:\s*(\S+)", re.MULTILINE)
_FIX_ROW = re.compile(r"^\s{2}(\w+),(.+)$", re.MULTILINE)


class NoMistakesAdapter:
    """Ship a branch through the no-mistakes safe-push pipeline."""

    def __init__(
        self,
        binary: str = "no-mistakes",
        *,
        dry_run: bool = True,
        runner: CommandRunner | None = None,
        timeout: float | None = None,
    ) -> None:
        self._binary = binary
        self._runner = runner or CommandRunner(dry_run=dry_run)
        self._timeout = timeout

    def init(self, repo_path: str) -> None:
        """Install the gate in ``repo_path`` (idempotent)."""
        self._runner.run([self._binary, "init"], cwd=repo_path)

    def gate(self, task: Task, worktree: Worktree) -> GateResult:
        """Run the branch through the pipeline; ship only when the outcome passes.

        The gate is (re-)initialized in the task's repo first - init is idempotent
        and the pooled worktree shares the repo's remotes, so the gate remote is
        visible from the worktree where ``axi run`` executes.
        """
        self.init(task.repo)
        result = self._runner.run(
            [self._binary, "axi", "run", "--intent", task.prompt, "--yes"],
            cwd=worktree.path,
            check=False,
            timeout=self._timeout,
        )
        if self._runner.dry_run:
            return GateResult(task_id=worktree.task_id, pushed=True, findings=["dry-run"])
        return self._parse(worktree, result.stdout, result.stderr)

    def _parse(self, worktree: Worktree, stdout: str, stderr: str) -> GateResult:
        outcome_match = _OUTCOME.search(stdout)
        outcome = outcome_match.group(1) if outcome_match else "unknown"
        findings = [f"outcome: {outcome}"]
        findings.extend(self._fixes(stdout))
        if outcome != "passed":
            detail = stderr.strip().splitlines()[-3:] or stdout.strip().splitlines()[-3:]
            findings.extend(line.strip() for line in detail if line.strip())
        pr = _PR_URL.search(stdout)
        return GateResult(
            task_id=worktree.task_id,
            pushed=outcome == "passed",
            pr_url=pr.group(0) if pr else None,
            findings=findings,
        )

    def _fixes(self, stdout: str) -> list[str]:
        """Extract pipeline fix commits from the ``fixes[N]{step,summary}`` block."""
        block = re.search(r"^fixes\[\d+\][^\n]*\n((?:^\s{2}.+\n?)+)", stdout, re.MULTILINE)
        if not block:
            return []
        return [
            f"pipeline fix ({m.group(1)}): {m.group(2).strip()}"
            for m in _FIX_ROW.finditer(block.group(1))
        ]
