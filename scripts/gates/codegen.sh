#!/usr/bin/env bash
# trine-eval codegen/evaluation gate for auto-mate.
#
# Invoked as: codegen.sh <task-id> <branch> <intent> [<base-ref>], with the
# task's repository as the working directory. All mechanics (arg parsing, diff
# capture, agent invocation, verdict handling, exit codes, GATE_* env knobs)
# live in gate-lib.sh; this file owns only the evaluation review lens.
gate_name="codegen"

build_prompt() {
  cat <<PROMPT
You are the trine-eval evaluation gate reviewing one task branch as an adversarial evaluator.

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
${diff}
PROMPT
}

. "$(dirname "${BASH_SOURCE[0]}")/gate-lib.sh"
