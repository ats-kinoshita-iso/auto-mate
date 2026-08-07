"""Shared subprocess plumbing for tool adapters."""

from __future__ import annotations

import shlex
import subprocess
from dataclasses import dataclass


class AdapterError(RuntimeError):
    """Raised when an external command exits non-zero."""


@dataclass(frozen=True)
class CommandResult:
    """Captured result of a shelled-out command."""

    command: list[str]
    returncode: int
    stdout: str
    stderr: str

    @property
    def ok(self) -> bool:
        return self.returncode == 0


class CommandRunner:
    """Runs external commands, or echoes them under ``dry_run``.

    Every adapter and gate holds one of these (composition) so the subprocess
    boundary lives in exactly one place: trivial to fake in tests, and the single
    spot that becomes live when ``dry_run`` is turned off.
    """

    def __init__(self, *, dry_run: bool = True) -> None:
        self._dry_run = dry_run

    @property
    def dry_run(self) -> bool:
        return self._dry_run

    def run(
        self,
        command: list[str],
        *,
        cwd: str | None = None,
        check: bool = True,
        timeout: float | None = None,
    ) -> CommandResult:
        """Execute ``command``; under dry-run, return a synthetic success instead.

        With ``check=False`` a non-zero exit is returned to the caller instead of
        raised, so gates can turn failures into verdicts. A ``timeout`` (seconds)
        bounds long-running externals such as agent harnesses; expiry raises
        :class:`AdapterError`.
        """
        if self._dry_run:
            return CommandResult(
                command=command,
                returncode=0,
                stdout=f"[dry-run] {shlex.join(command)}",
                stderr="",
            )
        try:
            completed = subprocess.run(
                command,
                cwd=cwd,
                capture_output=True,
                text=True,
                check=False,
                timeout=timeout,
            )
        except subprocess.TimeoutExpired as exc:
            raise AdapterError(
                f"command timed out after {timeout}s: {shlex.join(command)}"
            ) from exc
        result = CommandResult(
            command=command,
            returncode=completed.returncode,
            stdout=completed.stdout,
            stderr=completed.stderr,
        )
        if check and not result.ok:
            raise AdapterError(
                f"command failed ({result.returncode}): {shlex.join(command)}\n{result.stderr}"
            )
        return result
