# Architecture

auto-mate is an orchestration layer, not a tool.
Its job is to sequence other tools - and my own harnesses - into one repeatable, inspectable execution lifecycle, and to expose that lifecycle as typed Python plus a CLI.

## Design principles

- Orchestrate, do not reimplement.
  Worktrees, crews, and push gating are solved by `treehouse`, `firstmate`, and `no-mistakes`.
  auto-mate composes them; it owns the sequencing, the gates, and the run record.
- Composition over inheritance.
  The orchestrator depends on small structural interfaces (ports), not concrete classes.
  Adapters and gates each hold a `CommandRunner` rather than subclassing one.
- Dry-run by default.
  The subprocess boundary lives in exactly one place ([`CommandRunner`](../src/automate/adapters/base.py)).
  Under `dry_run` it echoes commands and returns synthetic success, so the whole lifecycle is testable before any external tool exists.
- Every run is a record.
  `run()` never throws; it returns a [`RunRecord`](../src/automate/models.py) whose status is one of `shipped`, `gated`, `no_changes`, or `failed`.

## The ports

The orchestrator is wired against four structural interfaces in [`ports.py`](../src/automate/ports.py).
Any object with the right methods satisfies them - the bundled adapters, my forks, or test fakes - with no base class to inherit:

| Port | Method | Implemented by |
|---|---|---|
| `WorktreeProvider` | `create`, `release` | `TreehouseAdapter` |
| `CrewRunner` | `run` | `FirstmateAdapter` |
| `Gate` | `evaluate` | `CommandGate` (henkaten-council, trine-eval) |
| `ShipGate` | `gate` | `NoMistakesAdapter` |

## The lifecycle

[`Orchestrator.run`](../src/automate/orchestrator.py) executes a [`Task`](../src/automate/models.py) through these stages:

1. Provision - `treehouse` creates an isolated worktree on branch `automate/<task-id>`.
2. Crew - `firstmate` runs a crew of agents in that worktree and reports a `CrewResult`.
3. Short-circuit - if the crew produced no changes, release the worktree and finish as `no_changes`.
4. Gates - run every `Gate` (governance, then codegen/eval); collect a `Verdict` from each.
5. Decide - if any gate fails, finish as `gated` without shipping.
6. Ship - `no-mistakes` pushes the branch through its safe-push pipeline; finish as `shipped` (with a PR URL) or `gated` if the push is blocked.

Any exception raised by a stage is caught at the `run()` boundary, recorded in the log, and surfaced as a `failed` status, so a run always yields an inspectable record.

## Wiring

[`Orchestrator.from_settings`](../src/automate/orchestrator.py) builds the bundled adapters from [`Settings`](../src/automate/config.py).
`Settings` reads `AUTOMATE_`-prefixed environment variables and an optional `.env`.
Swapping in a fork is a config change (point a `*_bin` at the new binary), not a code change.

## What this scaffold is not

- It does not yet drive the real CLIs of `treehouse` / `firstmate` / `no-mistakes`.
  The adapter command surfaces are provisional and gated behind `dry_run` (see [adapters.md](adapters.md)).
- It ships no orchestration features beyond the lifecycle skeleton.
  Following the project's eval-first convention, each real feature lands with its own eval.
