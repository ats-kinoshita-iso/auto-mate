"""auto-mate: the agent-execution layer of the stack.

Composes isolated worktrees (treehouse), agent crews (firstmate), governance and
codegen/eval harnesses (henkaten-council, trine-eval), and a safe-push gate
(no-mistakes) into a single programmatic execution lifecycle.
"""

from automate.config import Settings, get_settings
from automate.models import (
    CrewResult,
    GateResult,
    RunRecord,
    RunStatus,
    Task,
    Verdict,
    Worktree,
)
from automate.orchestrator import Orchestrator

__version__ = "0.1.0"

__all__ = [
    "Settings",
    "get_settings",
    "Task",
    "Worktree",
    "CrewResult",
    "Verdict",
    "GateResult",
    "RunRecord",
    "RunStatus",
    "Orchestrator",
    "__version__",
]
