# Adapters and gates

Each external tool is wrapped by a thin adapter in [`src/automate/adapters/`](../src/automate/adapters/), and each harness by a [`CommandGate`](../src/automate/harnesses/gate.py).
Every adapter holds a [`CommandRunner`](../src/automate/adapters/base.py); the runner is the only code that touches `subprocess`.

## Provisional by design

The exact command-line surface of the three upstream tools is not yet pinned down in code.
Where an adapter assumes a command, it is marked `TODO: confirm against <tool> CLI` and only ever runs under `dry_run`.
The notes below capture what is known from each tool's README; the `TODO`s are resolved when my forks are wired in, by checking each command against the installed binary and adjusting the adapter and its tests together.

## treehouse - `WorktreeProvider`

[`TreehouseAdapter`](../src/automate/adapters/treehouse.py)

- What it is: a manager for a pool of reusable, isolated git worktrees, one ready environment per agent.
- Known surface: the documented entrypoint is interactive - `treehouse` drops you into a subshell in a fresh worktree, and `exit` returns it to the pool.
- Provisional: `create()` assumes a non-interactive provisioning command and synthesizes the worktree path; `release()` assumes a release subcommand. Both need confirmation against the real CLI, and the returned path must be parsed from actual output.

## firstmate - `CrewRunner`

[`FirstmateAdapter`](../src/automate/adapters/firstmate.py)

- What it is: not a binary at all. firstmate is a directory whose `AGENTS.md` an agent harness (claude / codex / opencode / pi) follows, spawning crewmates in tmux + treehouse worktrees and handing back finished PRs or reports.
- How the adapter drives it: launch the configured `AUTOMATE_FIRSTMATE_AGENT_CMD` inside `AUTOMATE_FIRSTMATE_HOME`, passing the task prompt; the AGENTS.md takes over from there.
- Provisional: the non-interactive prompt-passing convention is harness-specific (the default assumes `claude -p <prompt>`), and the crew outcome (branch, PR, summary) must be parsed from firstmate's report rather than assumed.

## no-mistakes - `ShipGate`

[`NoMistakesAdapter`](../src/automate/adapters/no_mistakes.py)

- What it is: a local git-remote proxy. After `no-mistakes init`, pushing to the `no-mistakes` remote runs an AI validation pipeline (review -> test -> docs -> lint) and only forwards the branch to the real target and opens a PR once every check is green.
- How the adapter drives it: `init()` installs the gate; `gate()` runs `git push no-mistakes <branch>` and scrapes the resulting PR URL.
- Provisional: PR-URL scraping is a regex over stdout; finding-level detail (which check failed, what was auto-fixed) is not yet parsed.

## Harness gates - `Gate`

[`CommandGate`](../src/automate/harnesses/gate.py)

Both governance and codegen/eval reuse one gate type, differing only by name and configured command:

- `henkaten-council` via `AUTOMATE_GOVERNANCE_CMD` - governance / change-point review.
- `trine-eval` via `AUTOMATE_CODEGEN_CMD` - contract and quality evaluation.

The configured command is invoked as `<command> <task-id> <branch>`; a zero exit is a pass.
An empty command disables the gate (auto-pass), so the lifecycle runs standalone before the harnesses are connected.

## Adding or replacing a tool

1. Implement the relevant port from [`ports.py`](../src/automate/ports.py) (a plain class with the right methods - no base class required).
2. Hold a `CommandRunner` and build commands through it, so dry-run and error handling come for free.
3. Wire it in [`Orchestrator.from_settings`](../src/automate/orchestrator.py) and add the config knob to [`Settings`](../src/automate/config.py).
4. Add a test that asserts the constructed command and the parsed result.
