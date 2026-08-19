"""Thin adapters over the external agent-execution tools."""

from automate.adapters.base import AdapterError, CommandResult, CommandRunner
from automate.adapters.direct import DirectCrewAdapter
from automate.adapters.firstmate import FirstmateAdapter
from automate.adapters.gh import GhAdapter
from automate.adapters.githost import GitHost
from automate.adapters.gitworktree import GitWorktreeProvider
from automate.adapters.no_mistakes import NoMistakesAdapter
from automate.adapters.review import AgentReviewAdapter
from automate.adapters.treehouse import TreehouseAdapter

__all__ = [
    "AdapterError",
    "AgentReviewAdapter",
    "CommandResult",
    "CommandRunner",
    "DirectCrewAdapter",
    "FirstmateAdapter",
    "GhAdapter",
    "GitHost",
    "GitWorktreeProvider",
    "NoMistakesAdapter",
    "TreehouseAdapter",
]
