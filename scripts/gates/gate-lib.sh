#!/usr/bin/env bash
# Shared runner for auto-mate gate scripts. A gate script defines:
#   gate_name     - short name used in diagnostics
#   build_prompt  - function printing the agent prompt; runs after arg parsing
#                   and diff capture, so it may use $task_id, $intent, $branch,
#                   $base_ref, $diff, and $diff_max
# and then sources this file, which does everything else.
#
# Contract (identical for every gate): invoked as
#   <gate>.sh <task-id> <branch> <intent> [<base-ref>]
# with the task's repository as the working directory.
# Exit 0 = VERDICT: PASS, exit 1 = VERDICT: FAIL (or empty diff), exit 2 =
# infrastructure error (agent failed or returned no verdict line).
#
# Output: the agent's review text, ending in its VERDICT line, followed (when the
# agent is Claude Code) by one line `USAGE: {...}` carrying the JSON result's
# session_id, total_cost_usd, usage, modelUsage, durations and turn count. auto-mate's
# CommandGate parses that line into Verdict.usage (ADR-0006 in cloud-catcher).
#
# Configuration (environment):
#   GATE_AGENT_CMD   headless agent command           (default: "claude -p")
#   GATE_BASE_REF    fallback base when argv 4 absent (default: main)
#   GATE_DIFF_MAX    max diff bytes embedded          (default: 60000)
#   GATE_OUTPUT_JSON 1 forces JSON mode, 0 forces plain text; unset = JSON when
#                    the agent command is claude and names no --output-format
set -euo pipefail

task_id="${1:?usage: ${gate_name}.sh <task-id> <branch> <intent> [<base-ref>]}"
branch="${2:?missing branch}"
intent="${3:-"(no intent recorded)"}"
agent_cmd="${GATE_AGENT_CMD:-claude -p}"
base_ref="${4:-${GATE_BASE_REF:-main}}"
diff_max="${GATE_DIFF_MAX:-60000}"

# Truncate in the shell, not via `| head -c`: head closing the pipe early gives
# git SIGPIPE (exit 141), which pipefail turns into a silent gate failure.
diff="$(git diff "${base_ref}...${branch}")"
diff="${diff:0:$diff_max}"
if [ -z "$diff" ]; then
  echo "${gate_name} gate: empty diff for ${branch} vs ${base_ref}" >&2
  exit 1
fi

prompt="$(build_prompt)"

# JSON mode: on for a Claude Code agent that does not already pick a format.
json_mode=0
case " ${agent_cmd} " in
  " claude "*|*" claude "*|*"/claude "*) json_mode=1 ;;
esac
case "$agent_cmd" in *--output-format*) json_mode=0 ;; esac
case "${GATE_OUTPUT_JSON:-}" in 1|true|yes) json_mode=1 ;; 0|false|no) json_mode=0 ;; esac

# "--" ends option parsing so a configured variadic flag cannot swallow the prompt.
# The child must not inherit the orchestrating session's id (it would report it as
# its own and break the session_id join in diagnostics).
if [ "$json_mode" = 1 ]; then
  out_raw="$(env -u CLAUDE_CODE_SESSION_ID ${agent_cmd} --output-format json -- "$prompt" 2>&1)" || {
    printf '%s\n' "$out_raw" | tail -c 400 >&2
    echo "${gate_name} gate: agent command failed" >&2
    exit 2
  }
  # Split the JSON result into the review text (for the verdict grep) and the
  # USAGE line. If the output is not a result object, fall back to it verbatim.
  if parsed="$(printf '%s' "$out_raw" | python3 -c '
import json, sys
raw = sys.stdin.read().strip()
obj = None
try:
    obj = json.loads(raw)
except ValueError:
    for line in reversed(raw.splitlines()):
        line = line.strip()
        if line.startswith("{"):
            try:
                obj = json.loads(line)
                break
            except ValueError:
                pass
if not isinstance(obj, dict) or obj.get("type") != "result":
    sys.exit(3)
text = obj.get("result") if isinstance(obj.get("result"), str) else ""
keep = {k: obj[k] for k in ("type", "subtype", "is_error", "session_id", "total_cost_usd",
        "usage", "modelUsage", "duration_ms", "duration_api_ms", "num_turns",
        "permission_denials", "subagent_stats") if k in obj}
sys.stdout.write(text.rstrip("\n") + "\nUSAGE: " + json.dumps(keep) + "\n")
')"; then
    out="$parsed"
  else
    out="$out_raw"
  fi
else
  out="$(${agent_cmd} -- "$prompt" 2>&1)" || {
    printf '%s\n' "$out" | tail -c 400 >&2
    echo "${gate_name} gate: agent command failed" >&2
    exit 2
  }
fi
printf '%s\n' "$out"

# `|| true`: a reply with no verdict line must reach the diagnostic branch
# below - without it, pipefail + set -e killed the script here and made the
# exit-2 path unreachable.
verdict="$(printf '%s\n' "$out" | grep -E '^VERDICT: (PASS|FAIL)' | tail -1 || true)"
case "$verdict" in
  "VERDICT: PASS"*) exit 0 ;;
  "VERDICT: FAIL"*) printf '%s\n' "$verdict" >&2; exit 1 ;;
  *) echo "${gate_name} gate: agent returned no VERDICT line" >&2; exit 2 ;;
esac
