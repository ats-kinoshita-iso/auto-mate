#!/usr/bin/env bash
# henkaten-council governance gate for auto-mate.
#
# Invoked by auto-mate's CommandGate as:
#   governance.sh <task-id> <branch> <intent> [<base-ref>]
# with the task's repository as the working directory. Exit 0 = pass; any other
# exit fails the gate and the last stderr text becomes the verdict's findings.
#
# The review is change-point / scope governance: does the diff stay inside the
# task's intent, with no unexplained or destructive changes? The diff is embedded
# in the prompt so the gate agent needs no tool permissions.
#
# Configuration (environment):
#   GATE_AGENT_CMD  headless agent command      (default: "claude -p")
#   GATE_BASE_REF   ref the branch is judged against (default: main)
#   GATE_DIFF_MAX   max diff bytes embedded     (default: 60000)
set -euo pipefail

task_id="${1:?usage: governance.sh <task-id> <branch> <intent> [<base-ref>]}"
branch="${2:?missing branch}"
intent="${3:-"(no intent recorded)"}"
agent_cmd="${GATE_AGENT_CMD:-claude -p}"
base_ref="${4:-${GATE_BASE_REF:-main}}"
diff_max="${GATE_DIFF_MAX:-60000}"

diff="$(git diff "${base_ref}...${branch}" | head -c "$diff_max")"
if [ -z "$diff" ]; then
  echo "governance gate: empty diff for ${branch} vs ${base_ref}" >&2
  exit 1
fi

prompt="You are the henkaten-council governance gate reviewing one task branch.

Task id: ${task_id}
Task intent (what the change is supposed to accomplish):
${intent}

Review the diff below STRICTLY for governance concerns, through the 4M change-point lens (Man/Machine/Material/Method):
- scope drift: changes unrelated to the stated intent
- unexpected surface: files or areas the intent gives no reason to touch
- destructive or hard-to-reverse operations (deletions, force pushes, config/credential changes)
- policy smells: secrets, disabled checks, silenced errors

Do NOT judge implementation quality or style; that is another gate's job.

End your reply with exactly one final line:
VERDICT: PASS
or
VERDICT: FAIL - <one-line reason>

Diff (may be truncated at ${diff_max} bytes):
${diff}"

out="$(${agent_cmd} "$prompt" 2>&1)" || {
  printf '%s\n' "$out" | tail -c 400 >&2
  echo "governance gate: agent command failed" >&2
  exit 2
}
printf '%s\n' "$out"

verdict="$(printf '%s\n' "$out" | grep -E '^VERDICT: (PASS|FAIL)' | tail -1)"
case "$verdict" in
  "VERDICT: PASS"*) exit 0 ;;
  "VERDICT: FAIL"*) printf '%s\n' "$verdict" >&2; exit 1 ;;
  *) echo "governance gate: agent returned no VERDICT line" >&2; exit 2 ;;
esac
