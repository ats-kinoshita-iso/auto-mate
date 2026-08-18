# Handoff: rebuild henkaten-council's tool-call audit logger on native hooks

**Status:** ready-to-apply reference implementation. The henkaten-council plugin repo is not
reachable from the session that produced this handoff, so these files are staged here (the
stack's docs home) for manual application to the plugin.

## Why

The plugin's `hook/log-tool-call` is the least reliable component in the stack
(HKP-0003, tracked across HK-0006/0008/0014/0017/0021/0034 in bay-o-net's `.council/`):

1. ~35% of audit entries carry `tool_input_summary=file_path=unknown` — the logger never
   sees the real tool input.
2. The andon counter increments monotonically on the main thread, firing on read-only
   Grep traffic — the counter is a side effect of logging, not a policy.
3. Hook cwd leakage created phantom `.council/.council/` and `.harness/sprint-11-references/.council/`
   directories (HK-0005/HK-0020).
4. The plugin's `run-verification.py` resolves `_REPO_ROOT` to the plugin cache directory,
   so verification commands referencing `.harness/`/`.council/` fail (HK-0027).

Native PostToolUse hooks fix all four by construction: the hook receives structured JSON on
stdin carrying the real `tool_name`, the full `tool_input` (including `file_path`), the
`tool_response`, and the session `cwd`; and `${CLAUDE_PLUGIN_ROOT}` gives the script a
correct path anchor regardless of where the plugin is cached.

## What's here

| File | Purpose |
|---|---|
| `hooks.json` | Drop-in fragment for the plugin's `hooks/hooks.json` — one PostToolUse hook, all tools |
| `log-tool-call.sh` | The logger. Bash-via-Git-Bash compatible; all parsing in one `python -c` (no jq), per the stack's documented hook constraints |

## Behavior

- Appends one JSONL entry per tool call to `<repo-root>/.council/audit-log.jsonl`, where
  repo root is resolved from the **hook input's `cwd`** via `git rev-parse --show-toplevel`
  (never the process cwd — that is the HK-0005 leakage class).
- **Writes only if `.council/` already exists** at that root. A crew worktree or unrelated
  repo without an initialized council gets no phantom directories — the same isolation
  lesson auto-mate encodes with `--setting-sources project,local`.
- Entry schema is kept compatible with the existing `audit-log.jsonl`:
  `entry_id`, `timestamp`, `event_type: "tool-call"`, `agent_id`, `tool_name`,
  `tool_input_summary`, `tool_outcome`, `andon_pull_count`.
  - `tool_input_summary` now always carries a real value: `file_path=…` for file tools,
    `command=…` (truncated) for Bash, `pattern=…` for search tools, else the first
    scalar input field.
  - `andon_pull_count` is always `null`: **andon becomes a policy evaluated over the log**
    (e.g. by the orchestrator at review points), not a counter incremented inside the
    logging hook. This is deliberate — it removes defect (2) rather than reimplementing it.
- The script always exits 0 and swallows its own errors: an audit logger must never block
  or fail a session.

## Open questions that need the plugin source

1. **Agent-identity attribution.** Native hook input does not identify which subagent made
   the call; entries are stamped `agent_id: "session"`. If per-agent attribution is still
   required, the council's forked agents should stamp their identity into entries they
   cause indirectly (e.g. via a session-scoped marker file the script reads), or attribution
   can be reconstructed from the transcript_path the hook input carries.
2. **Andon policy wiring.** Where the plugin currently reads `andon_pull_count`, point it at
   a policy function over the recent log window (distinct-originator and consecutive-count
   thresholds already live in `.council/config.json` → `dynamic_autonomy_thresholds`).
3. **Rotation.** The existing manual archive-and-truncate at 5000 entries can stay; a
   SessionEnd hook is the natural native home for it later.

## Applying

1. Copy `log-tool-call.sh` into the plugin (e.g. `hooks/log-tool-call.sh`), keep LF line
   endings (`.gitattributes eol=lf` — non-negotiable on Windows).
2. Merge the `hooks.json` fragment into the plugin's hook manifest, keeping
   `${CLAUDE_PLUGIN_ROOT}` as the script path anchor.
3. Remove the old `hook/log-tool-call` registration and the in-hook andon increment.
4. Validate on one sprint: expect 0% `file_path=unknown` and no `.council/` directories
   created outside the initialized repo root.
