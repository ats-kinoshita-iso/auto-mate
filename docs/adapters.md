# Adapters and gates

Each external tool is wrapped by a thin adapter in [`src/automate/adapters/`](../src/automate/adapters/), and each harness by a [`CommandGate`](../src/automate/harnesses/gate.py).
Every adapter holds a [`CommandRunner`](../src/automate/adapters/base.py); the runner is the only code that touches `subprocess`.
The runner supports `check=False` (a non-zero exit becomes data instead of an exception - how gates fail soft) and per-call timeouts (a hung external raises instead of blocking forever).

The treehouse and no-mistakes surfaces below are **validated live** (treehouse v2.1.1, no-mistakes v1.45.4, Linux/WSL, 2026-08-06), not just read from source.
The firstmate surface remains provisional and only runs under `dry_run`.

## treehouse - `WorktreeProvider`

[`TreehouseAdapter`](../src/automate/adapters/treehouse.py)

- What it is: a manager for a per-repo pool of reusable, isolated git worktrees. It operates on the repo in the current directory (no `--repo` flag) and hands back a worktree on a detached HEAD.
- Validated live:
  - `treehouse get --lease [--lease-holder LABEL]` prints **exactly the absolute path** to stdout (human chatter goes to stderr); no `treehouse init` is required first, and a fresh get tracks the repo's current default-branch head.
  - Pooled worktrees are **linked git worktrees** (`.git` file pointing into the repo's `.git/worktrees/`), so remotes, refs, and config are shared with the repo.
    Branches cut in a worktree survive its return, and the `no-mistakes` remote added in the repo is usable from the worktree.
  - `treehouse return <path> --force [--if-lease-holder H]` cleans, resets, and returns without prompting; the holder guard refuses to release a lease another task now owns.
- How the adapter drives it: `create()` runs `get --lease --lease-holder <task-id>` in the repo, reads the path from stdout, then cuts the working branch with `git -C <path> switch -C automate/<task-id>` (`-C`, so a re-run of the same task id resets its branch instead of failing).
  `release()` runs `return <path> --force --if-lease-holder <task-id>`.
  `status()` backs `automate worktrees ls`.
- Remaining assumption: `task.repo` is a local path (treehouse runs inside the repo).

## no-mistakes - `ShipGate`

[`NoMistakesAdapter`](../src/automate/adapters/no_mistakes.py)

- What it is: a local git-remote proxy with an agent-facing interface. `no-mistakes init` registers a bare gate repo as a remote named `no-mistakes` and detects the real target remote; the daemon (a managed service installed by the installer) runs the validation pipeline.
- Validated live:
  - `no-mistakes axi run --intent <goal> --yes` drives the full pipeline for the current branch (intent -> rebase -> review -> test -> document -> lint -> push -> pr -> ci), **blocks until the outcome**, auto-resolves approval gates, and prints TOON to stdout with progress on stderr.
    `outcome: passed` is the authoritative success signal.
  - The pipeline may land fix commits on the branch (e.g. dropping out-of-scope files) and forwards the pushed head to the real remote.
  - The `pr` step auto-skips for non-GitHub remotes, so fully local runs (a path remote) work end to end.
- How the adapter drives it: `gate()` re-runs `init` in the task's repo (idempotent), then runs `axi run --intent <task.prompt> --yes` in the worktree with `check=False` and a timeout, and parses the TOON: `outcome` decides `pushed`, `fixes[...]` rows become findings, and a `https://.../pull/N` URL (present for GitHub targets) becomes `pr_url`.
- This replaced the original raw `git push no-mistakes <branch>` + stdout-scrape design: the push trigger is asynchronous and its stdout does not reliably carry the PR URL, while `axi run` is synchronous and structured.

## Crew backends - `CrewRunner`

The crew stage is pluggable: any `CrewRunner` works, and the backend is chosen by `AUTOMATE_CREW_BACKEND`.

### direct (default) - [`DirectCrewAdapter`](../src/automate/adapters/direct.py)

Runs a single agent harness (`AUTOMATE_AGENT_CMD`, default `claude`) directly in the task's worktree with the prompt, then reports whether it left changes (dirty worktree or commits beyond the base ref).
It needs only an agent on PATH, so auto-mate runs anywhere - which is why it is the default.

For real (non-dry) runs the agent command must be headless and allowed to edit files - e.g. `claude -p --permission-mode acceptEdits --setting-sources project,local` - because an interactive command blocks forever waiting for a TTY; `AUTOMATE_AGENT_TIMEOUT_S` bounds the run.
`--setting-sources project,local` keeps user-scope plugins out of crew runs: their hooks otherwise write runtime state (`.harness/`, `.council/`) into the crew worktree, and the commit-leftovers step would sweep it into the task's commit (the governance gate caught exactly this in live validation).
Claude Code also ships a stronger isolation flag, `--bare` (skips hooks, plugin sync, auto-memory, and CLAUDE.md auto-discovery entirely) - but it restricts auth to `ANTHROPIC_API_KEY`/apiKeyHelper (never OAuth or keychain), so it suits hermetic agents that need no project context; crews that should see the repo's CLAUDE.md and project skills while excluding only user-scope plugins are exactly what `--setting-sources project,local` is for.
Work the agent leaves uncommitted is committed by the adapter (`automate/<task-id>: <prompt title>`): the ship gate pushes the branch, and only commits travel.

### firstmate - [`FirstmateAdapter`](../src/automate/adapters/firstmate.py)

- What it is: not a flag CLI and not a dispatch API. firstmate is a conversational supervisor - you *talk* to a first-mate agent (launch claude/codex/opencode/pi in the firstmate home) and its `AGENTS.md` runs a crew in tmux + treehouse worktrees.
- Programmatic surface (contract read from source; brief scaffolding validated live 2026-08-06):
  - `bin/fm-brief.sh <id> <repo-name> --mode <no-mistakes|direct-PR|local-only>` scaffolds `data/<id>/brief.md` with a literal `{TASK}` placeholder and a machine-readable `Delivery contract: mode=...` line; ship briefs require a mode.
  - `bin/fm-spawn.sh <id> projects/<repo-name> --mode <mode> --yolo <on|off>` launches a crewmate in the session backend (tmux by default); the spawn provisions its **own** treehouse worktree inside the `projects/<repo-name>` clone and records it as `worktree=` in `state/<id>.meta`.
  - The crew reports through `state/<id>.status`; the last line's verb is the signal (`done:`, `blocked:`, `paused`).
- **Decision: drive the `bin/` scripts with `--mode local-only`.** In local-only mode the crew implements on a branch and stops - no push, no PR - so auto-mate's governance/eval gates and its no-mistakes stage keep sole shipping authority (firstmate's own no-mistakes delivery mode would ship before the gates run).
- How the adapter drives it: ensure `projects/<repo-name>` exists (a local clone of `task.repo`), scaffold the brief, fill `{TASK}` with `task.prompt`, spawn with `--mode local-only --yolo off`, poll `state/<id>.status` until `done:` (bounded by `AUTOMATE_AGENT_TIMEOUT_S`; `blocked:` and timeout raise), then adopt the crew's result by fetching its worktree's branch into the task's `automate/<id>` branch.
- Home prerequisite: programmatic spawns have no first-mate agent context to detect a harness from, so the firstmate home needs `config/crew-harness` - a bare adapter-name file (e.g. `claude`) - or `fm-spawn.sh` refuses with "no launch template for harness 'unknown'" (observed live).
- One-time environment consent (observed live): firstmate launches claude crews with `--dangerously-skip-permissions`, so the FIRST crew in a fresh environment stops at claude's interactive consent dialogs (folder trust, then bypass-permissions acknowledgment) inside its tmux pane.
  Those acceptances are a human decision: attach once (`tmux attach -t firstmate`), accept, and subsequent crews run unattended.
  An unattended first run otherwise ends at the adapter's supervision timeout with the worktree kept for autopsy.
- Provisional / platform: firstmate is **macOS/Linux only** and needs tmux plus a configured harness. Validated live: brief scaffolding, `{TASK}` fill, project cloning, spawn (tmux window + crew worktree + `state/<id>.meta`), and the supervision timeout path. A full crew round to `done:` awaits the one-time consent above.

## Harness gates - `Gate`

[`CommandGate`](../src/automate/harnesses/gate.py)

Both governance and codegen/eval reuse one gate type, differing only by name and configured command:

- `henkaten-council` via `AUTOMATE_GOVERNANCE_CMD` - governance / change-point review.
- `trine-eval` via `AUTOMATE_CODEGEN_CMD` - contract and quality evaluation.

The configured command is invoked as `<command> <task-id> <branch> <intent>` with the task's repository as working directory; a zero exit is a pass.
A non-zero exit is the gate's fail signal and surfaces as a failed verdict (a `gated` run), never as an exception (a `failed` run); `AUTOMATE_GATE_TIMEOUT_S` bounds each gate.
An empty command disables the gate (auto-pass), so the lifecycle runs standalone before the harnesses are connected.

[`scripts/gates/`](../scripts/gates/) ships reference implementations: each runs a headless agent (`GATE_AGENT_CMD`, default `claude -p`) over the branch's diff vs `GATE_BASE_REF` (default `main`), judged against the task intent, and greps a final `VERDICT: PASS` / `VERDICT: FAIL - reason` line for the exit code.
The diff is embedded in the prompt (capped by `GATE_DIFF_MAX`), so the gate agent needs no tool permissions.
Because a gate agent needs no project context either, `GATE_AGENT_CMD=claude -p --bare` is a good fit when API-key auth is available: it makes the gate hermetic by construction (no hooks, no plugins, no CLAUDE.md) instead of by convention.
`governance.sh` reviews scope drift, unexpected surface, and destructive operations through the 4M change-point lens; `codegen.sh` adversarially evaluates completeness, correctness, and craft against the intent.
The two prompts split responsibilities explicitly so the gates stay independent signals rather than two copies of one review.

## PR review - `PullRequestHost` + `Reviewer`

[`GhAdapter`](../src/automate/adapters/gh.py) and [`AgentReviewAdapter`](../src/automate/adapters/review.py) back `automate review` (see [architecture.md](architecture.md#the-review-lifecycle)).

- `GhAdapter` drives the `gh` CLI with the local clone as cwd (repo inferred from origin; private repos work through the user's authenticated gh).
  PR heads land in `refs/automate/pr/<N>` - a never-checked-out namespace, so forced updates cannot collide with worktree branches - and `--prune` keeps stacked bases fresh.
  Posting uses `gh pr comment`, not `gh pr review`: GitHub rejects formal review events on self-authored PRs, and a comment is the honest shape for an automated report.
- `AgentReviewAdapter` runs `AUTOMATE_REVIEW_AGENT_CMD` in the PR checkout.
  Read-only-ness is enforced by that command's tool allowlist (default: Read/Glob/Grep plus `git diff/log/show`), and `--setting-sources project,local` keeps user-scope plugin hooks out of the checkout - the same crew-isolation lesson as the direct backend.

## Adding or replacing a tool

1. Implement the relevant port from [`ports.py`](../src/automate/ports.py) (a plain class with the right methods - no base class required).
2. Hold a `CommandRunner` and build commands through it, so dry-run and error handling come for free.
3. Wire it in [`Orchestrator.from_settings`](../src/automate/orchestrator.py) and add the config knob to [`Settings`](../src/automate/config.py).
4. Add a test that asserts the constructed command and the parsed result.
