"""Parse what a headless ``claude -p --output-format json`` run reports about itself.

The ``result`` object carries ``session_id``, ``total_cost_usd`` (a client-side
estimate), ``usage`` (Messages API field names), ``modelUsage`` (camelCase, per
model), ``duration_ms``, ``duration_api_ms``, ``num_turns``, ``subtype`` and
``permission_denials``. This module turns it into :class:`AgentUsage` and owns
the two command-line conventions around it: asking for JSON output and not
handing the child the parent's Claude Code session id.
"""

from __future__ import annotations

import json
import os
from collections.abc import Mapping
from pathlib import PurePath
from typing import Any, Literal

from automate.models import AgentUsage, TokenUsage

SESSION_ENV = "CLAUDE_CODE_SESSION_ID"
USAGE_PREFIX = "USAGE: "
_MODEL_USAGE_KEYS = {
    "inputTokens": "input_tokens",
    "outputTokens": "output_tokens",
    "cacheReadInputTokens": "cache_read_input_tokens",
    "cacheCreationInputTokens": "cache_creation_input_tokens",
}
_USAGE_KEYS = {key: key for key in TokenUsage.model_fields}
_CAP_BY_SUBTYPE: dict[str, Literal["turns", "budget"]] = {
    "error_max_turns": "turns",
    "error_max_budget_usd": "budget",
}


def is_claude_command(command: list[str]) -> bool:
    """True when the agent executable is Claude Code (``claude`` or a path to it)."""
    return bool(command) and PurePath(command[0]).name in ("claude", "claude.exe", "claude.cmd")


def with_json_output(command: list[str]) -> list[str]:
    """Ask a Claude Code command for its JSON result unless it already picks a format.

    Non-claude agents are returned untouched: the flag is Claude Code's.
    """
    if not is_claude_command(command):
        return list(command)
    if "--output-format" in command or any(a.startswith("--output-format=") for a in command):
        return list(command)
    return [*command, "--output-format", "json"]


def agent_env(base: Mapping[str, str] | None = None) -> dict[str, str]:
    """Environment for a child agent: the parent's, minus its own session id.

    A child Claude Code run must not report the orchestrating session's id as
    its own, or the id stops being a join key for diagnostics.
    """
    env = dict(os.environ if base is None else base)
    env.pop(SESSION_ENV, None)
    return env


def result_object(stdout: str) -> dict[str, Any] | None:
    """The ``result`` JSON object in ``stdout``, or None when there is none."""
    text = stdout.strip()
    if not text:
        return None
    candidate: Any = None
    try:
        candidate = json.loads(text)
    except ValueError:
        for line in reversed(text.splitlines()):
            line = line.strip()
            if not line.startswith("{"):
                continue
            try:
                candidate = json.loads(line)
            except ValueError:
                continue
            if isinstance(candidate, dict):
                break
    if not isinstance(candidate, dict):
        return None
    if candidate.get("type") == "result" or "total_cost_usd" in candidate or "usage" in candidate:
        return candidate
    return None


def _int(value: Any) -> int | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return int(value)


def _tokens(raw: Any, keymap: Mapping[str, str]) -> TokenUsage:
    if not isinstance(raw, dict):
        return TokenUsage()
    values: dict[str, int] = {}
    for source, target in keymap.items():
        number = _int(raw.get(source))
        if number is not None:
            values[target] = number
    return TokenUsage(**values)


def parse_agent_usage(stdout: str, *, parent_session_id: str | None = None) -> AgentUsage | None:
    """Build an :class:`AgentUsage` from a Claude Code JSON result; None if absent."""
    obj = result_object(stdout)
    if obj is None:
        return None
    model_usage = obj.get("modelUsage")
    by_model = (
        {str(model): _tokens(usage, _MODEL_USAGE_KEYS) for model, usage in model_usage.items()}
        if isinstance(model_usage, dict)
        else {}
    )
    raw_cost = obj.get("total_cost_usd")
    cost_usd: float | None = (
        float(raw_cost)
        if isinstance(raw_cost, (int, float)) and not isinstance(raw_cost, bool)
        else None
    )
    subtype = obj.get("subtype") if isinstance(obj.get("subtype"), str) else None
    session_id = obj.get("session_id") if isinstance(obj.get("session_id"), str) else None
    stats = obj.get("subagent_stats")
    spawned = _int(stats.get("spawned")) if isinstance(stats, dict) else None
    denials = obj.get("permission_denials")
    return AgentUsage(
        session_id=session_id,
        session_id_inherited=bool(session_id and session_id == parent_session_id),
        usage=_tokens(obj.get("usage"), _USAGE_KEYS),
        usage_by_model=by_model,
        cost_usd=cost_usd,
        cost_source="claude-code-estimate" if cost_usd is not None else None,
        duration_ms=_int(obj.get("duration_ms")),
        api_duration_ms=_int(obj.get("duration_api_ms")),
        num_turns=_int(obj.get("num_turns")),
        subagents_spawned=spawned,
        permission_denials=len(denials) if isinstance(denials, list) else None,
        subtype=subtype,
        cap_hit=_CAP_BY_SUBTYPE.get(subtype or ""),
    )


def parse_usage_line(stdout: str, *, parent_session_id: str | None = None) -> AgentUsage | None:
    """Parse the ``USAGE: {...}`` line a gate script prints after its verdict."""
    for line in reversed(stdout.splitlines()):
        if line.startswith(USAGE_PREFIX):
            return parse_agent_usage(line[len(USAGE_PREFIX) :], parent_session_id=parent_session_id)
    return None
