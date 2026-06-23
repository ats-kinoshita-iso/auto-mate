# auto-mate

The agent-execution layer of my stack.

auto-mate is the programmatic spine that turns a task into shipped work.
It composes a set of focused external tools and my own harnesses into one execution lifecycle, exposed as a typed Python API and a CLI.
You hand it a task; it provisions an isolated workspace, runs a crew of agents, gates the result through governance and evaluation, and ships it behind a safe-push gate - recording a structured run the whole way.

> Status: scaffold. Every external integration runs in `dry_run` mode by default (commands are echoed, not executed), so the full lifecycle is exercisable today, before the upstream tools are installed or forked.

## Where it sits in the stack

auto-mate does not reimplement worktrees, crews, or push gating.
It orchestrates tools that already do those well, and layers my governance and codegen harnesses on top as quality gates.

| Layer | Tool | Role |
|---|---|---|
| Isolation | [`treehouse`](https://github.com/kunchenguid/treehouse) | A pool of reusable, isolated git worktrees, one per task |
| Crew | [`firstmate`](https://github.com/kunchenguid/firstmate) | Talk to one agent; it runs a crew of agents to do the work |
| Governance gate | `henkaten-council` | Change-point / governance review of the crew's output |
| Codegen / eval gate | `trine-eval` | Contract and quality evaluation of the result |
| Ship gate | [`no-mistakes`](https://github.com/kunchenguid/no-mistakes) | Safe-push proxy: review -> test -> lint -> PR, only when green |

The three upstream tools are external dependencies, referenced by command path.
They are **not** vendored or forked here; my forks drop in later by pointing the config at them.

## The execution lifecycle

```
task
  │
  ▼  treehouse
provision an isolated worktree
  │
  ▼  firstmate
run a crew of agents in the worktree
  │
  ▼  henkaten-council + trine-eval
governance + evaluation gates
  │  (all pass)
  ▼  no-mistakes
safe-push gate -> clean PR
  │
  ▼
RunRecord  { status, worktree, crew, verdicts, gate, log }
```

A run stops early - without shipping - if the crew made no changes or any gate fails.
Every run returns a [`RunRecord`](src/automate/models.py), so outcomes are inspectable and machine-readable.

## Getting started

Prerequisites: Python 3.12+ and [uv](https://docs.astral.sh/uv/).

```bash
git clone https://github.com/ats-kinoshita-iso/auto-mate.git
cd auto-mate
uv sync
cp .env.example .env   # adjust tool paths and gate commands as needed
```

Walk the full lifecycle without any external tools installed (dry-run is the default):

```bash
uv run automate run "add dark mode" --repo /path/to/project --id dark-mode
```

This prints a `RunRecord` showing each stage - the exact commands each adapter would have run, the gate verdicts, and the final status.

Other commands:

```bash
uv run automate status        # resolved dry-run state + which tools/gates are configured
uv run automate config show   # full resolved configuration as JSON
uv run automate worktrees ls  # (placeholder until the treehouse list command is wired)
```

## Configuration

All settings load from environment variables prefixed `AUTOMATE_` (and an optional `.env`).
See [.env.example](.env.example) for the full list.
Key knobs:

- `AUTOMATE_DRY_RUN` - when `true` (default), adapters echo commands instead of executing them.
- `AUTOMATE_TREEHOUSE_BIN`, `AUTOMATE_NO_MISTAKES_BIN` - paths to those binaries (or your forks).
- `AUTOMATE_FIRSTMATE_HOME`, `AUTOMATE_FIRSTMATE_AGENT_CMD` - firstmate's AGENTS.md directory and the harness that drives it.
- `AUTOMATE_GOVERNANCE_CMD`, `AUTOMATE_CODEGEN_CMD` - commands for the henkaten-council and trine-eval gates; empty disables a gate.

## Development

```bash
make check   # ruff lint + format check + mypy + pytest
make test    # pytest only
make format  # apply ruff formatting
```

See [docs/architecture.md](docs/architecture.md) for the design and [docs/adapters.md](docs/adapters.md) for how each tool integrates and what is still provisional.

## License

MIT. See [LICENSE](LICENSE).
