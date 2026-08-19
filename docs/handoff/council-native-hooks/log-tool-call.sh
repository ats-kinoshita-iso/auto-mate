#!/usr/bin/env bash
# henkaten-council tool-call audit logger — native PostToolUse hook.
#
# Reads the hook payload from stdin (JSON: tool_name, tool_input, tool_response, cwd)
# and appends one entry to <repo-root>/.council/audit-log.jsonl, schema-compatible with
# the plugin's existing log. All parsing happens in one python -c (jq is not assumed;
# bash runs via Git Bash on Windows — keep LF endings).
#
# Invariants:
#   - repo root comes from the HOOK INPUT's cwd (git rev-parse), never the process cwd
#     (HK-0005/HK-0020: process-cwd resolution created phantom .council/ directories);
#   - writes only when .council/ already exists at that root (no phantom initialization
#     in crew worktrees or unrelated repos);
#   - andon_pull_count is always null — andon is a policy over the log, not a counter
#     incremented while logging (HKP-0003 defect 2);
#   - always exits 0: an audit logger must never block or fail the session.

python -c '
import json, os, subprocess, sys, uuid
from datetime import datetime, timezone

try:
    payload = json.load(sys.stdin)

    hook_cwd = payload.get("cwd") or os.getcwd()
    try:
        root = subprocess.run(
            ["git", "-C", hook_cwd, "rev-parse", "--show-toplevel"],
            capture_output=True, text=True, timeout=5,
        ).stdout.strip() or hook_cwd
    except Exception:
        root = hook_cwd

    council = os.path.join(root, ".council")
    if not os.path.isdir(council):
        sys.exit(0)  # council not initialized here: log nothing, create nothing

    tool_name = payload.get("tool_name", "unknown")
    tool_input = payload.get("tool_input") or {}

    summary = "no-input"
    for key in ("file_path", "command", "pattern", "path", "url", "prompt"):
        value = tool_input.get(key)
        if isinstance(value, str) and value:
            summary = f"{key}={value[:160]}"
            break
    else:
        for key, value in tool_input.items():
            if isinstance(value, (str, int, float, bool)):
                summary = f"{key}={str(value)[:160]}"
                break

    response = payload.get("tool_response")
    outcome = "success"
    if isinstance(response, dict) and (
        response.get("is_error") or response.get("error") or response.get("success") is False
    ):
        outcome = "error"

    entry = {
        "entry_id": str(uuid.uuid4()),
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "event_type": "tool-call",
        "agent_id": "session",  # open question 1 in README: per-agent attribution
        "tool_name": tool_name,
        "tool_input_summary": summary,
        "tool_outcome": outcome,
        "andon_pull_count": None,  # policy over the log, not a hook-side counter
    }
    with open(os.path.join(council, "audit-log.jsonl"), "a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
except Exception:
    pass  # never block the session on audit failure
' 2>/dev/null

exit 0
