"""The Claude Code JSON result is parsed into AgentUsage; command and env conventions hold."""

from __future__ import annotations

import json

import pytest

from automate.claude_output import (
    agent_env,
    is_claude_command,
    parse_agent_usage,
    parse_usage_line,
    result_object,
    with_json_output,
)

# Shape recorded from `claude -p ... --output-format json` (Claude Code 2.1.316).
RESULT = {
    "type": "result",
    "subtype": "success",
    "is_error": False,
    "duration_ms": 3647,
    "duration_api_ms": 2299,
    "num_turns": 1,
    "result": "ok",
    "session_id": "sess-child",
    "total_cost_usd": 0.00354849,
    "usage": {
        "input_tokens": 2,
        "cache_creation_input_tokens": 15800,
        "cache_read_input_tokens": 26159,
        "output_tokens": 4,
        "output_tokens_details": {"thinking_tokens": 0},
        "service_tier": "standard",
    },
    "modelUsage": {
        "claude-haiku-5-5": {
            "inputTokens": 1179,
            "outputTokens": 18,
            "cacheReadInputTokens": 26159,
            "cacheCreationInputTokens": 15800,
            "webSearchRequests": 0,
            "costUSD": 0.00354849,
            "contextWindow": 1000000,
        }
    },
    "permission_denials": [],
    "subagent_stats": {"spawned": 2, "completed": 2},
    "uuid": "u-1",
}


def test_parse_success_result() -> None:
    usage = parse_agent_usage(json.dumps(RESULT))
    assert usage is not None
    assert usage.session_id == "sess-child"
    assert usage.session_id_inherited is False
    # Tokens are the per-model totals (review C09); the top-level usage is the last turn.
    assert usage.usage.input_tokens == 1179 and usage.usage.output_tokens == 18
    assert usage.last_turn_usage is not None
    assert (usage.last_turn_usage.input_tokens, usage.last_turn_usage.output_tokens) == (2, 4)
    assert usage.usage.cache_read_input_tokens == 26159
    assert usage.usage.cache_creation_input_tokens == 15800
    assert usage.usage_by_model["claude-haiku-5-5"].input_tokens == 1179
    assert usage.usage_by_model["claude-haiku-5-5"].cache_read_input_tokens == 26159
    assert usage.cost_usd == pytest.approx(0.00354849)
    assert usage.cost_source == "claude-code-estimate"
    assert (usage.duration_ms, usage.api_duration_ms, usage.num_turns) == (3647, 2299, 1)
    assert usage.subagents_spawned == 2
    assert usage.permission_denials == 0
    assert usage.subtype == "success" and usage.cap_hit is None


@pytest.mark.parametrize(
    ("subtype", "cap"),
    [
        ("error_max_turns", "turns"),
        ("error_max_budget_usd", "budget"),
        ("error_during_execution", None),
    ],
)
def test_error_arm_maps_to_cap_hit(subtype: str, cap: str | None) -> None:
    payload = {**RESULT, "subtype": subtype, "is_error": True, "errors": ["cap"]}
    payload.pop("result")
    usage = parse_agent_usage(json.dumps(payload))
    assert usage is not None and usage.cap_hit == cap and usage.subtype == subtype


def test_result_found_after_leading_noise() -> None:
    stdout = "Warning: something on stdout\n" + json.dumps(RESULT) + "\n"
    assert result_object(stdout) is not None
    usage = parse_agent_usage(stdout)
    assert usage is not None and usage.num_turns == 1


def test_plain_text_and_dry_run_output_yield_no_usage() -> None:
    assert parse_agent_usage("[dry-run] claude -p -- do it") is None
    assert parse_agent_usage("") is None
    assert parse_agent_usage('{"not": "a result"}') is None


def test_inherited_session_id_is_flagged() -> None:
    usage = parse_agent_usage(json.dumps(RESULT), parent_session_id="sess-child")
    assert usage is not None and usage.session_id_inherited is True


def test_with_json_output_only_touches_claude_commands() -> None:
    assert with_json_output(["claude", "-p"]) == ["claude", "-p", "--output-format", "json"]
    assert with_json_output(["/opt/bin/claude", "-p"])[-2:] == ["--output-format", "json"]
    assert with_json_output(["claude", "-p", "--output-format", "text"]) == [
        "claude",
        "-p",
        "--output-format",
        "text",
    ]
    assert with_json_output(["codex", "exec"]) == ["codex", "exec"]
    assert is_claude_command(["claude.exe"]) and not is_claude_command([])


def test_agent_env_drops_the_parent_session_id() -> None:
    env = agent_env({"CLAUDE_CODE_SESSION_ID": "parent", "PATH": "/usr/bin"})
    assert env == {"PATH": "/usr/bin"}


def test_parse_usage_line_reads_the_gate_trailer() -> None:
    stdout = "Review body.\nVERDICT: PASS\nUSAGE: " + json.dumps(RESULT) + "\n"
    usage = parse_usage_line(stdout)
    assert usage is not None and usage.cost_usd == pytest.approx(0.00354849)
    assert parse_usage_line("Review body.\nVERDICT: PASS\n") is None


def _model(inp: int, out: int, cache_read: int = 0, cost: float = 0.0) -> dict[str, object]:
    return {
        "inputTokens": inp,
        "outputTokens": out,
        "cacheReadInputTokens": cache_read,
        "cacheCreationInputTokens": 0,
        "costUSD": cost,
    }


def test_usage_sums_every_model_including_subagents() -> None:
    # A run whose subagent used another model: the top-level usage is the main
    # thread's final turn only, modelUsage covers the whole run (review C09).
    payload = {
        **RESULT,
        "usage": {"input_tokens": 3, "output_tokens": 5},
        "modelUsage": {"model-a": _model(100, 40, 1000, 0.3), "model-b": _model(20, 8, 0, 0.02)},
        "total_cost_usd": 0.32,
    }
    usage = parse_agent_usage(json.dumps(payload))
    assert usage is not None
    assert (usage.usage.input_tokens, usage.usage.output_tokens) == (120, 48)
    assert usage.usage.cache_read_input_tokens == 1000
    assert usage.last_turn_usage is not None and usage.last_turn_usage.output_tokens == 5


def test_budget_capped_result_keeps_its_tokens() -> None:
    # A budget-capped result reports all-zero top-level usage; modelUsage has the spend.
    payload = {
        **RESULT,
        "subtype": "error_max_budget_usd",
        "is_error": True,
        "usage": {"input_tokens": 0, "output_tokens": 0},
        "modelUsage": {"model-a": _model(900, 300, 0, 0.11)},
        "total_cost_usd": 0.11,
    }
    payload.pop("result")
    usage = parse_agent_usage(json.dumps(payload))
    assert usage is not None and usage.cap_hit == "budget"
    assert (usage.usage.input_tokens, usage.usage.output_tokens) == (900, 300)


def test_usage_falls_back_to_the_top_level_without_model_usage() -> None:
    payload = {**RESULT, "usage": {"input_tokens": 7, "output_tokens": 9}}
    payload.pop("modelUsage")
    usage = parse_agent_usage(json.dumps(payload))
    assert usage is not None and (usage.usage.input_tokens, usage.usage.output_tokens) == (7, 9)
