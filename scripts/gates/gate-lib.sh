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
# Configuration (environment):
#   GATE_AGENT_CMD  headless agent command           (default: "claude -p")
#   GATE_BASE_REF   fallback base when argv 4 absent (default: main)
#   GATE_DIFF_MAX   max diff bytes embedded          (default: 60000)
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

# "--" ends option parsing so a configured variadic flag cannot swallow the prompt.
out="$(${agent_cmd} -- "$prompt" 2>&1)" || {
  printf '%s\n' "$out" | tail -c 400 >&2
  echo "${gate_name} gate: agent command failed" >&2
  exit 2
}
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
