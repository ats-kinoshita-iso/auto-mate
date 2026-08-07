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

For real (non-dry) runs the agent command must be headless and allowed to edit files - e.g. `claude -p --permission-mode acceptEdits` - because an interactive command blocks forever waiting for a TTY; `AUTOMATE_AGENT_TIMEOUT_S` bounds the run.
Work the agent leaves uncommitted is committed by the adapter (`automate/<task-id>: <prompt title>`): the ship gate pushes the branch, and only commits travel.

### firstmate - [`FirstmateAdapter`](../src/automate/adapters/firstmate.py)

- What it is: not a flag CLI and not a dispatch API. firstmate is a conversational supervisor - you *talk* to a first-mate agent (launch claude/codex/opencode/pi in the firstmate home) and its `AGENTS.md` runs a crew in tmux + treehouse worktrees. There is no `-p` flag; harnesses are launched by firstmate with the brief as a positional argument.
- Programmatic surface: firstmate's `bin/` scripts - `bin/fm-brief.sh <id> <repo>` scaffolds a brief, `bin/fm-spawn.sh <id> projects/<repo>` spawns a crewmate, `bin/fm-watch.sh` supervises, and crew status lands in `state/<id>.status` / `data/<id>/report.md`.
- **Decision: drive the `bin/` scripts (option B).** firstmate already supervises *and ships* (it has no-mistakes built into its delivery modes), so delegating the whole task to a first-mate agent (option A) would ship work before auto-mate's governance/eval gates could run - defeating auto-mate's purpose. So auto-mate stays the single supervisor and uses firstmate as a crew-execution library. Trade-off: this bypasses the first-mate agent's own intake/supervision judgment.
- Provisional / platform: firstmate is **macOS/Linux only** and needs tmux + a detected harness, so this path cannot be validated on Windows. Writing `task.prompt` into the brief, mapping `task.repo` to a `projects/` entry, and supervising to completion remain `TODO`.

## Harness gates - `Gate`

[`CommandGate`](../src/automate/harnesses/gate.py)

Both governance and codegen/eval reuse one gate type, differing only by name and configured command:

- `henkaten-council` via `AUTOMATE_GOVERNANCE_CMD` - governance / change-point review.
- `trine-eval` via `AUTOMATE_CODEGEN_CMD` - contract and quality evaluation.

The configured command is invoked as `<command> <task-id> <branch>`; a zero exit is a pass.
A non-zero exit is the gate's fail signal and surfaces as a failed verdict (a `gated` run), never as an exception (a `failed` run); `AUTOMATE_GATE_TIMEOUT_S` bounds each gate.
An empty command disables the gate (auto-pass), so the lifecycle runs standalone before the harnesses are connected.

## Adding or replacing a tool

1. Implement the relevant port from [`ports.py`](../src/automate/ports.py) (a plain class with the right methods - no base class required).
2. Hold a `CommandRunner` and build commands through it, so dry-run and error handling come for free.
3. Wire it in [`Orchestrator.from_settings`](../src/automate/orchestrator.py) and add the config knob to [`Settings`](../src/automate/config.py).
4. Add a test that asserts the constructed command and the parsed result.
