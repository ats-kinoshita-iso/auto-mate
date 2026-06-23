# Adapters and gates

Each external tool is wrapped by a thin adapter in [`src/automate/adapters/`](../src/automate/adapters/), and each harness by a [`CommandGate`](../src/automate/harnesses/gate.py).
Every adapter holds a [`CommandRunner`](../src/automate/adapters/base.py); the runner is the only code that touches `subprocess`.

The command surfaces below were read from each tool's source (the `kunchenguid` upstreams; the user's forks at `ats-kinoshita-iso/*` are identical at fork time).
What is verified-from-source is marked as such; what still needs a running binary to confirm is marked `TODO` and only ever runs under `dry_run`.

## treehouse - `WorktreeProvider`

[`TreehouseAdapter`](../src/automate/adapters/treehouse.py)

- What it is: a manager for a per-repo pool of reusable, isolated git worktrees. It operates on the repo in the current directory (no `--repo` flag) and hands back a worktree on a detached HEAD.
- Verified CLI surface (`cmd/*.go`):
  - `treehouse get --lease [--lease-holder LABEL]` acquires a worktree and prints **only its absolute path** to stdout; the lease persists until return.
  - `treehouse return <path> [--force]` releases a worktree back to the pool.
  - `treehouse status` prints a human-readable pool table (no JSON mode).
  - Other subcommands: `init`, `prune`, `destroy`, `update`.
- How the adapter drives it: `create()` runs `get --lease --lease-holder <task-id>` in the repo, reads the path from stdout, then cuts the working branch with `git -C <path> switch -c automate/<task-id>` (treehouse leaves a detached HEAD). `release()` runs `return <path> --force`. `status()` backs `automate worktrees ls`.
- Provisional: path parsing assumes `get --lease` prints exactly the path (true in source); under dry-run the path is synthesized. `task.repo` is assumed to be a local path (treehouse needs to run inside the repo).

## no-mistakes - `ShipGate`

[`NoMistakesAdapter`](../src/automate/adapters/no_mistakes.py)

- What it is: a local git-remote proxy. `no-mistakes init` creates a bare repo and adds a remote literally named `no-mistakes`; pushing to it runs a background-daemon pipeline (review -> test -> document -> lint -> push -> PR) that forwards to the real target and opens a PR only when every check is green.
- Verified CLI surface: pushing to the `no-mistakes` remote is the **only** way to invoke the gate - there is no `no-mistakes push`/`gate`/`run` ship subcommand. A headless, agent-facing surface does exist: `no-mistakes axi run --intent <goal> --yes` (plus `axi status`, `axi respond`, `axi logs`). The gate needs the daemon running (`no-mistakes daemon`).
- How the adapter drives it: `init()` runs `no-mistakes init`; `gate()` runs `git push no-mistakes <branch>` in the worktree.
- Provisional: the PR URL is **not** reliably on the push stdout (the daemon opens it asynchronously); the authoritative source is `no-mistakes axi status` (TOON output). The regex scrape is best-effort. Wiring `axi run`/`axi status` for a fully headless, PR-URL-accurate flow is a follow-up.

## firstmate - `CrewRunner`

[`FirstmateAdapter`](../src/automate/adapters/firstmate.py)

- What it is: not a flag CLI and not a dispatch API. firstmate is a conversational supervisor - you *talk* to a first-mate agent (launch claude/codex/opencode/pi in the firstmate home) and its `AGENTS.md` runs a crew of agents in tmux + treehouse worktrees. There is no `-p`/prompt flag; harnesses are launched by firstmate itself with the brief as a positional argument.
- The programmatic surface is firstmate's `bin/` scripts: `bin/fm-brief.sh <id> <repo>` scaffolds a task brief, `bin/fm-spawn.sh <id> projects/<repo>` spawns a crewmate, `bin/fm-watch.sh` supervises, and crew status lands in `state/<id>.status` / `data/<id>/report.md`.
- **Design fork (needs a decision):**
  - **(A) Drive the firstmate agent** - hand a high-level instruction to a first-mate agent and let it supervise. Matches firstmate's intended "talk to one agent" model, but is conversational, not cleanly headless.
  - **(B) Drive the `bin/` scripts directly** - treat firstmate as a crew-execution library and let auto-mate be the supervisor. Headless and fits auto-mate's role, but bypasses the first-mate agent's judgment (effectively a different system built on firstmate's machinery).
  - This adapter currently stubs toward **(B)** (`fm-brief.sh` + `fm-spawn.sh`), since auto-mate is itself the programmatic orchestrator. Revisit if you'd rather auto-mate delegate to a real first-mate agent.
- Provisional / platform: firstmate is **macOS/Linux only** and needs tmux + a detected harness, so this path cannot be validated on Windows. Writing `task.prompt` into the brief, mapping `task.repo` to a `projects/` entry, and supervising to completion remain `TODO`.

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
