#!/usr/bin/env bash
# trine-eval codegen/evaluation gate for auto-mate.
#
# Invoked by auto-mate's CommandGate as:
#   codegen.sh <task-id> <branch> <intent> [<base-ref>]
# with the task's repository as the working directory. Exit 0 = pass; any other
# exit fails the gate and the last stderr text becomes the verdict's findings.
#
# The review is implementation quality against the task's intent: does the diff
# actually deliver what was asked, correctly and cleanly? The diff is embedded
# in the prompt so the gate agent needs no tool permissions.
#
# Configuration (environment):
#   GATE_AGENT_CMD  headless agent command      (default: "claude -p")
#   GATE_BASE_REF   ref the branch is judged against (default: main)
#   GATE_DIFF_MAX   max diff bytes embedded     (default: 60000)
set -euo pipefail

task_id="${1:?usage: codegen.sh <task-id> <branch> <intent> [<base-ref>]}"
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
  echo "codegen gate: empty diff for ${branch} vs ${base_ref}" >&2
  exit 1
fi

prompt="You are the trine-eval evaluation gate reviewing one task branch as an adversarial evaluator.

Task id: ${task_id}
Task intent (the contract this change must satisfy):
${intent}

Evaluate the diff below STRICTLY for delivery against the intent:
- completeness: does the change actually do what the intent asks, fully?
- correctness: bugs, broken edge cases, wrong behavior
- craft: dead code, leftover debug artifacts, files that should not ship
- fit: does it respect the conventions visible in the surrounding diff context?

Do NOT judge scope or governance; that is another gate's job.
Minor style nits alone do not fail the gate; unmet intent or defects do.

End your reply with exactly one final line:
VERDICT: PASS
or
VERDICT: FAIL - <one-line reason>

Diff (may be truncated at ${diff_max} bytes):
${diff}"

out="$(${agent_cmd} "$prompt" 2>&1)" || {
  printf '%s\n' "$out" | tail -c 400 >&2
  echo "codegen gate: agent command failed" >&2
  exit 2
}
printf '%s\n' "$out"

verdict="$(printf '%s\n' "$out" | grep -E '^VERDICT: (PASS|FAIL)' | tail -1)"
case "$verdict" in
  "VERDICT: PASS"*) exit 0 ;;
  "VERDICT: FAIL"*) printf '%s\n' "$verdict" >&2; exit 1 ;;
  *) echo "codegen gate: agent returned no VERDICT line" >&2; exit 2 ;;
esac
