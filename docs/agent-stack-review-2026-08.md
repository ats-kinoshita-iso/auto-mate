# Agent Stack vs. Native Claude Code — Full Review (2026-08)

**Scope:** the three-repo agent stack — **trine-eval** (Planner/Generator/Evaluator eval-driven harness + `trine_eval` Python library), **henkaten-council** (governance plugin, observed through its `.council/` state in bay-o-net), and **auto-mate** (outer orchestration CLI over Kun Chen's treehouse / no-mistakes / firstmate) — reviewed against native Claude Code capabilities as of August 2026.

**Verdict posture:** evidence-weighted. A custom component is only marked for deprecation where a native feature demonstrably covers the *specific failure modes documented in 28 production sprints* of bay-o-net (2026-05-13 → 2026-06-30). Anything load-bearing for auditability stays.

**Bottom line:** the stack's *methodology* layers (contracts, regression graduation, governance ledgers, safe-push) have no native equivalent and should stay. The stack's *plumbing* layers — subagent trial dispatch, tool-call audit logging, structured verdict capture — are exactly where the documented reliability failures live, and native features (Workflows with structured output and resume, native hooks) now cover those failure modes directly. The Kun Chen dependencies are healthy and should be kept, except firstmate. Two quick wins were applied during this review (see §8).

---

## 1. Method

Four parallel investigations, each independently sourced:

1. Full functional inventory of trine-eval (plugin v0.4.0 + library v0.1.0) and auto-mate (v0.1.0).
2. Operational review of bay-o-net's `.harness/` + `.council/` state — 28 sprints, 108 eval files, 62 henka records, 36 council decisions — to ground every verdict in what actually failed or held.
3. Native-feature inventory against current official docs (code.claude.com), followed by a **second, adversarial verification pass** of every load-bearing claim. Claims that failed verification are flagged below rather than silently used.
4. Current-state check of the Kun Chen dependencies (releases, changelogs, contract stability) and a deep-read of Anthropic's 2025–2026 publications on agent reliability.

Native-claim corrections that came out of the verification pass (these would otherwise have skewed verdicts):

- **No native `/batch` fan-out-to-PRs skill** is documented, contrary to an initial inventory. Worktree isolation for subagents exists (`isolation: worktree`), but nothing native replicates treehouse-style pooling or auto-mate's ship pipeline.
- **No documented OpenTelemetry export from Claude Code itself.** OTel observability remains the `trine_eval` library's own job.
- **No PR-event subscription in the local CLI.** Session-waking PR monitoring (CI failures, review comments) exists only on Claude Code on the web / remote sessions.
- `--setting-sources` is absent from current docs but **still present and working in the shipped CLI** (verified against `claude --help` this session), alongside the newer `--bare`.
- Subagent frontmatter documents `tools`, `disallowedTools`, `model`, `permissionMode`, `maxTurns`, `memory`, `isolation` — but **not** `context: fork` or `thinking:`/effort fields, which trine-eval's agents rely on. These may still work (undocumented) but should be re-validated; effort inheritance is documented at the session level.
- Hook events verified: PreToolUse, PostToolUse, SessionStart, SessionEnd, UserPromptSubmit, Stop, PermissionRequest, plus experimental agent-team events (TaskCreated, TaskCompleted, TeammateIdle). Exit code 2 blocks on PreToolUse/PostToolUse/Stop. Prompt-based and agent-based hooks exist alongside command/HTTP/MCP hooks.

## 2. The stack, and why each piece exists

| Layer | What it is | The instability it was built against |
|---|---|---|
| trine-eval plugin | Contract → build → eval sprints; 3 subagents; pass^3 trials; append-only regression suite | Ungoverned single-session drift; unverifiable "done" claims; grader fabrication |
| trine_eval library | Inspect-style eval runner: scorers, judge calibration, docker sandbox, Batch API, OTel→Langfuse | Need for statistically valid, replayable, cost-capped evals |
| henkaten-council | Change-point detection (4M axis), decision/henka/standard-work ledgers, Cynefin prebriefs, nemawashi, direction-check CI | The 2026-05 wrong-direction incident: three sprints compounded on a killed workstream before anyone noticed |
| auto-mate | Task → worktree → crew → gates → safe-push, all headless `claude -p`; PR-review lifecycle | No native outer loop: one-shot sessions with no independent shipping decision |

The single most important operational fact from bay-o-net: **the forked-Evaluator trial mechanism — the heart of pass^3 — failed three distinct ways across the sprint history** (HK-0035 family):

- **S18:** all three trial subagents did real verification (55–69 tool calls each) but exhausted their dispatch turn budget *before writing verdicts*, leaving `pending` scaffolds. Fallback to main-thread grading collapsed the trials into deterministic replicas.
- **S20:** all three forked evaluators died on a session limit before doing any grading — pass^3 silently became pass^1.
- **S24/S25/S27:** generator and reviewer subagents truncated mid-report on large sprints (scale-correlated, corroborated from both directions per HK-0051).

The mitigation that finally worked (zero fallbacks across S21–S28, HK-0035 resolved at S28) was *procedural*: re-dispatch before falling back, plus main-thread corroboration. That is precisely the mitigation the native Workflow runtime now automates (§4.3).

A second key fact: the council's own tool-call audit hook is the least reliable part of the stack — ~35% of audit entries log `file_path=unknown`, the andon counter increments monotonically on read-only traffic, hook cwd leakage created phantom `.council/.council/` directories (HK-0005/0020), and the plugin's verification runner resolves paths against its cache directory instead of the repo (HK-0027). The custom machinery meant to guarantee auditability is itself the biggest source of audit noise (HKP-0003).

## 3. Decision matrix

| # | Component | Native overlap | Verdict | Rationale (evidence) |
|---|---|---|---|---|
| 1 | Planner/Generator/Evaluator agent definitions | `.claude/agents/*.md` is native | **KEEP** (already native) | Re-validate undocumented `context: fork` / `thinking:` frontmatter (§1) |
| 2 | Contract negotiation, tasks.json, 6-trap authoring checklist, `verified_via_command` hygiene | none | **KEEP** | Repeatedly the highest-value step: R1 contract review caught defects pre-implementation in S11/S18/S21/S24; DEC-0035 made it the catching layer for HKP-0004 |
| 3 | pass^3 trial dispatch via forked subagents | **Workflows**: `agent()` loops, JSON-schema structured output, resume/re-dispatch from cache, background execution | **UPGRADE** | Directly targets all three documented failure modes (S18/S20/S24 family). Structured output makes "verdict never written" impossible-by-construction; resume automates re-dispatch-before-fallback |
| 4 | Transcript trailer (JSON parsed from evaluator prose) | Workflow/subagent structured output; headless `--json-schema` | **DEPRECATE → structured output** | The trailer exists because subagent output was unstructured; schema-validated returns remove the fabrication surface the audit scripts patrol |
| 5 | Regression graduation (`regression.json` + runs/ evidence) | none | **KEEP** | Append-only, exit-code-faithful; nothing native does saturation → graduation |
| 6 | pass@k / pass^k math, saturation analysis, ACI self-optimization | none | **KEEP** | Native gives binary results only |
| 7 | Harness hooks (SessionStart state injection, Stop marker, PostToolUse debounced touch) | Native hooks (they already are) | **KEEP** | Correctly built on native surface |
| 8 | Docker sandbox (`--network=none`), tmpdir isolation | none in local CLI | **KEEP** | Local CLI runs in your shell; no native container sandbox |
| 9 | Batch API eval mode | none | **KEEP** | 50% cost discount still unmatched |
| 10 | `trine_eval` Anthropic wrapper + pricing | n/a (API client) | **UPGRADED in this review** | Was sending removed `budget_tokens` params (400s on Opus 4.7+); see §8 |
| 11 | `trine_eval` OTel → Langfuse | none native | **KEEP + fix drift** | Locked langfuse 4.6.1 vs v2-era client code and `langfuse:2` compose pin — reconcile |
| 12 | Council ledgers (DEC/HK/HKP/SW/YK), Cynefin prebriefs, nemawashi, autonomy levels | none | **KEEP** | Nothing native holds cross-sprint governance state; this is the auditable change-management the stack exists for |
| 13 | Council `hook/log-tool-call` audit logger | **Native PostToolUse hooks** (structured JSON input incl. tool input + cwd; `${CLAUDE_PLUGIN_ROOT}` for path resolution) | **REPLACE** | The plugin logger is demonstrably broken (HKP-0003: 35% unknown paths, monotone andon counter; HK-0005/0020 cwd leakage; HK-0027 plugin-cache path bug). Native hooks receive exactly the fields it fails to capture |
| 14 | direction-check CI (Layer A) | plain CI already | **KEEP** | Vendored, stdlib-only, tested after its own coverage incident |
| 15 | Council 4-agent fan-out (architect / scope-guardian / henkaten-detector / retrospective) | Workflows (parallel + structured findings) | **KEEP, optionally UPGRADE dispatch** | Content is bespoke; only the dispatch mechanics benefit from Workflow reliability |
| 16 | auto-mate orchestrator + RunRecord | Workflow tool (session-scoped) | **KEEP** | RunRecord is a typed, CI-tested, dry-runnable contract; Workflows don't produce machine-readable run records for external consumers |
| 17 | auto-mate crew (`claude -p` + `--setting-sources`) | `--bare`; Agent SDK | **KEEP + harden** | `--setting-sources project,local` remains correct for crews (documented tradeoff added to docs/adapters.md this review); Agent SDK is the structured upgrade path if/when subprocess parsing becomes limiting |
| 18 | auto-mate gates (governance + codegen, diff-embedded, exit-code verdicts) | subagents, /code-review | **KEEP** | Independent-verdict-by-construction has no native equivalent; `--bare` hardening documented |
| 19 | auto-mate review lifecycle (`automate review --all`, persisted reports) | `/code-review` (multi-pass, false-positive verification, `--fix`/`--comment`, PR targeting) | **HYBRID** | Adopt `/code-review` as the review *engine* inside the lifecycle; keep batch mode, persisted timestamped reports, and independent gate verdicts. Native PR-event monitoring is remote-only, so the local batch reviewer stays valuable |
| 20 | treehouse (worktree pool + leases) | native worktrees, `isolation: worktree` | **KEEP** | v2.1.1 is current (no releases since); both invoked surfaces documented-stable. Pooling + cached deps + lease guards have no native equivalent. Harden: `--json` output, `--if-lease-id` |
| 21 | no-mistakes (safe-push gate) | none | **KEEP; pin v1.48.0** | No TOON/`axi run` breakage v1.45.4→v1.53.0, but ≥v1.49.0 are pre-releases and the TOON contract has no stability guarantee — pin to the last stable (v1.48.0), watch releases, note the new `\xNN` C0-escape rendering for the parser |
| 22 | firstmate (crew backend) | agent teams (experimental) | **PARK / candidate DEPRECATE** | No releases, no tags, ~2 commits/day, `--dangerously-skip-permissions`, tmux-bound. Not the default backend anyway. Native agent teams aren't a replacement yet (experimental, not resumable) — keep the `AUTOMATE_CREW_BACKEND` seam and revisit |
| 23 | Checkpoint/rewind discipline (git checkpoints per sprint) | native `/rewind` checkpoints | **KEEP** | Native checkpoints don't track bash-side changes and don't survive as auditable artifacts; git checkpoints remain the record. Use native rewind as a convenience, not a replacement |

Completeness check against the failure-pattern ledger: HKP-0001 (strategic-doc drift) → rows 12/14 keep the guard; HKP-0002 (grep-precision blockers) and HKP-0004 (literal-verification-vs-prose-intent) → row 2 keeps the catching layer, and row 4's structured verdicts enforce the per-sub-condition table shape mechanically; HKP-0003 (council infrastructure degradation) → row 13 replaces the defective component; HKP-0005 (untested execution surface) → unaffected by this review, the S25 executed-bundle smoke discipline stands. Open watches HK-0051/HK-0059 (fork truncation at scale) → row 3; HK-0062 (resume-from-partial) → row 23 + SW-0006 unchanged.

## 4. The three structural recommendations

### 4.1 Re-platform the evaluator trial loop on Workflows (highest value)

The pass^3 mechanism is the stack's core measurement and its most failure-prone plumbing. A Workflow script (`.claude/workflows/`) replaces hand-dispatched forked subagents with:

- `agent(prompt, {schema})` trials returning **schema-validated verdict objects** — the S18 "did the work, never wrote the verdict" failure becomes structurally impossible; the per-sub-condition verdict table (Lesson 10 / HK-0050) becomes a schema, not a prose convention.
- **Resume from cache**: a truncated or killed trial re-runs from the journal without re-paying completed trials — the automated form of the re-dispatch-before-fallback procedure that resolved HK-0035.
- Deterministic trial-loop control flow in JS instead of orchestration prose in SKILL.md.

Keep unchanged: the `.harness/` file formats as the durable audit record (the workflow writes them), trial-vs-retry semantics, the contract layer, and the regression gate. This is a plumbing swap, not a methodology change. Validation: replay one closed sprint (e.g. S26) through the workflow and diff the produced eval files against the historical ones.

### 4.2 Rebuild the council's audit logger on native PostToolUse hooks

Keep the ledgers, the taxonomy, and the andon *policy* — replace the broken *sensor*. A native PostToolUse (+ PostToolUseFailure where available) command hook receives structured JSON with the real tool input and cwd, writes the same `audit-log.jsonl` schema, and uses `${CLAUDE_PLUGIN_ROOT}` so the HK-0027 path-resolution class disappears. This directly retires HKP-0003's three defect families. The andon counter moves from "increment per tool call on the main thread" to a policy evaluated over the log.

### 4.3 Adopt `/code-review` inside `automate review`

`/code-review` is now a multi-pass reviewer with adversarial false-positive verification, effort levels, `--fix`/`--comment`, and PR targeting — a strictly stronger review engine than a single read-only `claude -p` pass. auto-mate keeps what native lacks: batch `--all` over open PRs, persisted timestamped reports in the workspace, and the independent governance/codegen gate verdicts alongside the prose review.

## 5. Kun Chen dependency assessment (verified 2026-08-17)

All three repos are public, actively maintained, and part of one composed stack; no deprecation signals anywhere.

| Tool | Pinned | Latest | Status | Action |
|---|---|---|---|---|
| treehouse | v2.1.1 (validated 2026-07-31 release) | v2.1.1 | Stable, maturing (~10 commits/30d); `get --lease` stdout contract and `return --force --if-lease-holder` both documented on main | Keep. Harden with `--json` (typed lease allocation) and `--if-lease-id` (per-acquisition guard, tighter than holder-name) |
| no-mistakes | v1.45.4 | v1.48.0 stable; v1.49.0–v1.53.0 pre-release | Very high velocity; changelog shows **no** changes to `axi run` flags, TOON format, `outcome:` field, or exit codes since the pin; `axi` stdout/stderr/exit-code contract is documented (but not *guaranteed*) | Upgrade pin to v1.48.0; stay off pre-releases (they're an eval-toolkit arc); parser note: unsupported C0 control bytes now render as `\xNN` escapes |
| firstmate | none (no tags exist) | n/a | ~2 commits/day, 680 open PRs, no releases, no stability contract | Keep parked as provisional; per-SHA integration tests if ever promoted |

Notable adjacent prior art from the same author: **gnhf** (overnight autonomous agent-loop orchestrator over worktrees — overlaps auto-mate's own territory) and **axi** (the agent-native CLI design principles behind no-mistakes' TOON surface; the most citable artifact on why auto-mate's exit-code/stdout contracts are shaped the way they are).

## 6. What Anthropic's current guidance says about this stack

*(Sourced from the 2025–2026 publications sweep; direct fetches of anthropic.com/engineering are egress-blocked from this environment, so access method is noted per citation in §9 — several key claims were verified via directly-fetched docs pages and GitHub mirrors.)*

### 6.1 Where the stack matches published doctrine

1. **The three-agent contract shape is now Anthropic's own published architecture.** *Harness Design for Long-Running Application Development* (Anthropic Labs, March 2026) describes a Planner/Generator/Evaluator harness communicating through files and **negotiating sprint contracts before implementation** — near-isomorphic to trine-eval, built independently a year after this stack's design. The contract as the bridge "between high-level specs and testable implementations without over-specification" is exactly the role trine-eval's contracts play.
2. **Forked, fresh-context evaluation is doctrine.** "Agents tend to respond by confidently praising the work" (harness-design); "a fresh context improves code review since Claude won't be biased toward code it just wrote" and the verification-subagent escalation rung ("a fresh model tries to refute the result, so the agent doing the work isn't the one grading it") are in the current best-practices docs, fetched direct.
3. **pass^k is the named consistency metric.** *Demystifying evals for AI agents* draws precisely trine-eval's pass@k-vs-pass^k distinction ("does it eventually succeed?" vs "does it succeed consistently?") and mandates repeated trials because agent behavior is stochastic. The trial-vs-retry split that makes the harness's pass^k statistically valid has no counterpart in the docs — it's ahead of them.
4. **File-based state as system of record.** *Effective harnesses for long-running agents* prescribes structured files + git as the memory between sessions, and specifically notes agents corrupt Markdown state files but respect JSON's structure — the harness's JSON-for-structure/markdown-for-prose convention, independently derived.
5. **Append-only regression gates** match Demystifying evals' capability-vs-regression split ("one measures frontier ability, the other protects behavior that already works") and the evals-as-CI framing; bay-o-net's parity floors are the textbook implementation.
6. **Single-call LLM judge, deterministic-first, human calibration** — the multi-agent research post's strongest empirical finding (a single judge call with a single rubric beat multi-judge architectures) matches the harness's three-tier grader hierarchy and its bias toward deterministic verification commands.
7. **Headless `claude -p` through worktrees with scoped `--allowedTools` and human gates at plan/ship** is verbatim the official automation playbook — auto-mate is a typed, tested implementation of it. The ~400k-session usage study (June 2026) empirically supports the stack's human-plans/agent-executes split and shows verification-and-recovery habits are what separate 33% from 15% verified success.

### 6.2 Where the guidance pushes back

1. **"Every component in a harness encodes an assumption about what the model can't do on its own"** — the sharpest critique in the corpus, from Anthropic's own harness team, who *deleted* sprint decomposition and context resets from their harness between Opus 4.5 and 4.6 (cutting cost ~40% at equal quality) because the model no longer needed them. Ceremony calibrated on 2026-Q2 models is presumptively carrying dead weight on current ones. bay-o-net has in fact already begun this organically — SW-0007 sanctions pass^1 for build-heavy sprints — but as an exception, not a policy. **Recommendation: make trial count risk-tiered by policy** (pass^3 for parity/inference-core changes; pass^1-with-fork for routine sprints), and put a "re-justify against current model" check into every PDCA cycle.
2. **Cost multipliers are real and published:** Anthropic's own harness ran ~20× a solo run; multi-agent ≈ 15× chat tokens. Uniform pass^3 plus a 4-agent council fan-out on every sprint is expensive measurement used as a universal gate. "Only increase complexity when needed" (*Building Effective Agents*).
3. **A standing autonomous governance council has no support in the corpus** — and the docs actively warn about its failure mode: "a reviewer prompted to find gaps will usually report some, even when the work is sound... chasing every finding leads to over-engineering." The council's *ledgers, monitoring, and audit trail* are well-supported (production tracing, evals-as-CI); the *per-sprint autonomous fan-out* is the part the guidance would trim. Counter-evidence from bay-o-net is genuine, though: the prebrief blocked S24 on an unlocked strategic gate, the scope-guardian caught repeated status drift, and HKP-0004's inward turn was caught by the council's own machinery. Verdict stays KEEP for the ledgers and gates; consider dialing fan-out frequency to cycle boundaries rather than every sprint, and keep the human at the nemawashi gate (the usage study's ~70%-human-planning split argues for exactly that placement).
4. **End-state over trajectory:** both the multi-agent post and Demystifying evals warn that path-scoring fails for non-deterministic agents. Most SN gates are genuine invariants (frozen-boundary diffs) and stand; any criterion that pins procedure rather than outcome should be rewritten at contract time.
5. **Platform-native churn is real and continuing** — checkpointing, `/goal` + Stop hooks, verification subagents, `/code-review`, agent teams, Managed Agents (a hosted harness, Apr 2026 beta), multi-agent orchestration threads (May 2026 beta). The custom stack's defensible core is what the platform still doesn't do: the contract format, append-only eval journal + regression gates, governance ledgers, parity floors, and the safe-push policy. Everything else should be treated as candidate plumbing to shed at each platform release — which is §4 of this review in practice.

## 7. Migration roadmap

**Phase 0 — applied in this review** (see §8).

**Phase 1 — low risk, immediate:**
1. Council audit logger → native PostToolUse hooks (§4.2). Success test: 0% `file_path=unknown` over a full sprint; andon counter fires only on its policy conditions.
2. Pin no-mistakes at v1.48.0; adopt treehouse `--json` + `--if-lease-id` in `adapters/treehouse.py`/`no_mistakes.py` (small, tested command-string changes).
3. Reconcile the langfuse drift in trine_eval (v2-era client calls vs locked 4.6.1 vs `langfuse:2` compose): either migrate the client to the v4 API or pin the dependency to `<3`.
4. Re-validate the undocumented agent frontmatter (`context: fork`, `thinking:`) against the current runtime before the next harness sprint relies on it.

**Phase 2 — medium risk, high value:**
5. Workflow-based trial loop (§4.1), validated by replaying a closed sprint and diffing eval artifacts.
6. Same treatment for the council fan-out dispatch (content unchanged).
7. `/code-review` as the engine inside `automate review` (§4.3).

**Phase 2b — ceremony re-audit (per §6.2):**
- Make trial count risk-tiered by policy: pass^3 reserved for sprints touching parity floors / inference core; pass^1-with-forked-evaluator for routine sprints (generalizes SW-0007 from exception to policy).
- Consider moving the council 4-agent fan-out from every-sprint to cycle boundaries (`cycle_length=5`), keeping per-sprint henka detection passive (log-derived) and the nemawashi human gate unchanged.
- Add a standing PDCA question: "which harness component has the current model generation made unnecessary?" — Anthropic's harness team cut ~40% of cost this way between model releases.

**Phase 3 — watch and revisit:**
8. Agent teams for contract negotiation once stable and resumable (TaskCreated/TaskCompleted/TeammateIdle exit-code-2 gates map naturally onto contract-approval semantics).
9. Agent SDK as an alternative crew backend for auto-mate (typed sessions, cost tracking, retries) — worthwhile only when subprocess-parsing becomes the limiting factor.
10. Decide firstmate's fate at the next auto-mate milestone; the seam makes this a config change.

**Explicitly not migrating:** contracts, regression graduation, council ledgers/nemawashi/prebriefs, direction-check CI, docker sandboxing, Batch API evals, treehouse, no-mistakes, RunRecord, git-checkpoint discipline. bay-o-net's live `.harness/`/`.council/` state was not touched by this review (sprint 29 remains HALTED on its user gate).

## 8. Quick wins applied during this review

1. **trine-eval `fix(models)`** — `AnthropicModel` was sending `thinking: {type: "enabled", budget_tokens: N}` plus an invalid `betas=` kwarg; `budget_tokens` is removed on Opus 4.7+ (400), so the live-API path was broken, and the pricing constants understated Opus output cost by 40% ($15 vs $25/1M). Migrated to adaptive thinking + `output_config.effort` (the library's effort tiers map 1:1 onto the API's), defaulted to `claude-opus-5` (same price point), corrected pricing. 108 tests pass; no new lint/type findings.
2. **auto-mate `docs(adapters)`** — documented the `--bare` vs `--setting-sources project,local` isolation tradeoff (verified against the shipped CLI), including `--bare` as the hermetic-by-construction option for gate agents.

Also surfaced, not fixed (report-only): trine-eval's pre-existing toolchain drift — `ruff`/`mypy` report 30/15 findings on the untouched tree against the README's "exit 0" claims, almost certainly because the unpinned dev toolchain resolved to much newer versions (ruff 0.15, mypy 2.1) than the library was built against.

## 9. Bibliography

Anthropic publications (access method from this review's environment in parentheses; anthropic.com/engineering is egress-blocked here, so several were read via search summaries or directly-fetched mirrors):

- *Building Effective Agents* (Dec 2024) — https://www.anthropic.com/engineering/building-effective-agents (search summary). Workflows-vs-agents; five workflow patterns; "simplest solution first."
- *Claude Code: Best practices for agentic coding* (Apr 2025) + living docs successor — https://code.claude.com/docs/en/best-practices (**fetched direct**). Context as the master constraint; give Claude a check it can run; evidence over assertions; worktree multi-Claude; adversarial-review over-engineering warning.
- *How we built our multi-agent research system* (Jun 2025) — https://www.anthropic.com/engineering/multi-agent-research-system (search summary). Orchestrator-worker; single-call LLM judge; end-state grading; 15× token economics; production tracing.
- *Effective context engineering for AI agents* (Sep 2025) — https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents (search summary). Compaction vs structured note-taking vs sub-agents; note-taking named best fit for milestone-driven development.
- *Effective harnesses for long-running agents* (Nov 2025) — https://www.anthropic.com/engineering/effective-harnesses-for-long-running-agents (search summary + mirror). Initializer/coding-agent split; structured files + git as memory; JSON constrains agent drift; forced end-to-end self-verification.
- *Demystifying evals for AI agents* (early 2026) — https://www.anthropic.com/engineering/demystifying-evals-for-ai-agents (search summary). pass@k vs pass^k; outcome vs transcript grading; capability vs regression suites; 20–50 tasks from real failures.
- *Harness Design for Long-Running Application Development* (Mar 2026, Anthropic Labs) — https://www.anthropic.com/engineering/harness-design-long-running-apps (via GitHub research-note mirror, **fetched direct**; companion repo `anthropics/cwc-long-running-agents`). Planner/Generator/Evaluator + sprint contracts; "every component encodes an assumption about what the model can't do"; harness cost multipliers and per-model-generation pruning.
- *Agentic Coding and Persistent Returns to Expertise* ("How Claude Code is used in practice", Jun 2026) — https://www.anthropic.com/research/claude-code-expertise (search summary). ~400k sessions; humans plan (~70%) / agents execute (~80%); problem expertise doubles verified success; abandonment-under-trouble failure mode.
- Claude Agent SDK + Managed Agents / multi-agent orchestration docs — https://platform.claude.com/docs/en/managed-agents/multiagent-orchestration (**fetched direct**). Hosted harness (Apr 2026 beta); context-isolated session threads (May 2026 beta).

Native Claude Code documentation verified direct this session: sub-agents, hooks, workflows, checkpointing, headless, plugins-reference, code-review, agent-teams, worktrees, env-vars (all at code.claude.com/docs/en/), plus the locally installed CLI's `--help` for `--bare` / `--setting-sources`.

Kun Chen ecosystem (all fetched direct on github.com, 2026-08-17): treehouse v2.1.1 + releases; no-mistakes v1.45.4→v1.53.0 changelog + `axi` CLI reference; firstmate (no releases); axi design principles; gnhf. Blog ("Kun's Field Notes") and interview coverage via search.

---

*Review conducted 2026-08-17 in a Claude Code remote session; all native-feature claims verified against code.claude.com documentation or the locally installed CLI during the session.*
