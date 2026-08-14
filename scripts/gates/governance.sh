#!/usr/bin/env bash
# henkaten-council governance gate for auto-mate.
#
# Invoked as: governance.sh <task-id> <branch> <intent> [<base-ref>], with the
# task's repository as the working directory. All mechanics (arg parsing, diff
# capture, agent invocation, verdict handling, exit codes, GATE_* env knobs)
# live in gate-lib.sh; this file owns only the governance review lens.
gate_name="governance"

build_prompt() {
  cat <<PROMPT
You are the henkaten-council governance gate reviewing one task branch.

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
${diff}
PROMPT
}

. "$(dirname "${BASH_SOURCE[0]}")/gate-lib.sh"
