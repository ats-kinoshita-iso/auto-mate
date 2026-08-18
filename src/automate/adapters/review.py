"""A read-only deep-review agent: explores a PR checkout, writes the review.

Implements the ``Reviewer`` port. Structurally a read-only sibling of
``DirectCrewAdapter``: it launches a headless agent in the worktree (checked out
at the PR head) with a prompt carrying the PR's intent and base ref. The agent
explores the real code - so review depth is not limited by an embedded-diff cap
- and returns a markdown review on stdout.

Read-only-ness is enforced by the configured command's tool allowlist (see
``AUTOMATE_REVIEW_AGENT_CMD``), not by this adapter; the blast radius of a
misconfigured command is a pooled worktree that ``treehouse return --force``
resets.
"""

from __future__ import annotations

import shlex

from automate.adapters.base import CommandRunner
from automate.models import Task, Worktree

_PROMPT = """You are reviewing a pull request. The PR's head is checked out at HEAD in this \
directory, and the full diff is available via: git diff {base_ref}...HEAD

PR intent (title and description - the contract this change should satisfy):
{intent}

Explore the checkout and the diff, then write a substantive markdown review:
1. A two-to-three sentence summary of what the change actually does.
2. Strengths worth keeping.
3. Issues ordered by severity, each with a file:line reference and a concrete suggestion. \
Cover correctness, unmet intent, and maintainability; skip pure style nits.
4. A final one-line recommendation.

Rules: you are read-only - never edit files. Do not output a PASS/FAIL verdict; separate \
gates own that. Output ONLY the markdown review, no preamble."""

# The native-skill engine: /code-review runs a multi-pass review (parallel finders,
# then a verification step that filters false positives) and takes a target + effort
# level. Validated headless (2026-08-18): with the read-only allowlist it reviews
# `<base-ref>...HEAD` in the checkout and prints prose + a JSON findings block, which
# lands in the persisted report like any other review body. The PR intent cannot be
# threaded into the skill invocation - intent conformance stays with the gates.
_CODE_REVIEW_PROMPT = "/code-review {base_ref} high"


class AgentReviewAdapter:
    """Run a headless read-only agent over a PR checkout and return its review."""

    def __init__(
        self,
        *,
        agent_cmd: str,
        engine: str = "prompt",
        dry_run: bool = True,
        runner: CommandRunner | None = None,
        timeout: float | None = None,
    ) -> None:
        self._agent_cmd = agent_cmd
        self._engine = engine
        self._runner = runner or CommandRunner(dry_run=dry_run)
        self._timeout = timeout

    def review(self, task: Task, worktree: Worktree) -> str:
        """Review the checked-out PR head in ``worktree``; return the markdown body."""
        if self._engine == "code-review":
            prompt = _CODE_REVIEW_PROMPT.format(base_ref=task.base_ref)
        else:
            prompt = _PROMPT.format(base_ref=task.base_ref, intent=task.prompt)
        # "--" ends option parsing: variadic flags (e.g. claude's --allowedTools)
        # would otherwise swallow the prompt as more flag values.
        result = self._runner.run(
            [*shlex.split(self._agent_cmd), "--", prompt],
            cwd=worktree.path,
            timeout=self._timeout,
        )
        if self._runner.dry_run:
            return f"[dry-run] deep review of {task.id} would run here"
        return result.stdout.strip()
