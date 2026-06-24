"""Thin adapters over the external agent-execution tools."""

from automate.adapters.base import AdapterError, CommandResult, CommandRunner
from automate.adapters.direct import DirectCrewAdapter
from automate.adapters.firstmate import FirstmateAdapter
from automate.adapters.no_mistakes import NoMistakesAdapter
from automate.adapters.treehouse import TreehouseAdapter

__all__ = [
    "AdapterError",
    "CommandResult",
    "CommandRunner",
    "DirectCrewAdapter",
    "FirstmateAdapter",
    "NoMistakesAdapter",
    "TreehouseAdapter",
]
