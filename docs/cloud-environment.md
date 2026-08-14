# auto-mate in a Claude cloud environment

How to make `automate` part of a default [Claude Code cloud environment](https://code.claude.com/docs/en/claude-code-on-the-web), so every web session starts with the CLI installed and configured.

## One-time environment setup

1. On [claude.ai/code](https://claude.ai/code), open the **environment selector** (the cloud icon above the message box) and create or edit an environment.
2. Paste the contents of [`scripts/cloud-setup.sh`](../scripts/cloud-setup.sh) into the environment's **Setup script**. It installs the `automate` CLI with `uv tool install` from this repository; the container snapshot is cached after the script completes, so later sessions start instantly.
3. Add **environment variables** (`.env` format) to preconfigure auto-mate. A useful cloud baseline:

   ```bash
   # Stay in dry-run until the upstream tools are installed (see below).
   AUTOMATE_DRY_RUN=true
   # The direct crew backend needs a headless agent command.
   AUTOMATE_AGENT_CMD=claude -p --permission-mode acceptEdits --setting-sources project,local
   ```

4. Keep the network policy at **Trusted** (the default) or wider: the setup script needs `github.com` and `astral.sh`, and live runs need whatever the agent and gates reach.
5. Pick this environment in the selector to make it the default for new sessions (from the CLI: `/remote-env`).

## What works in the cloud, and what needs more

- **Out of the box** (setup script only): the full lifecycle in `dry_run`, and the `direct` crew backend for real agent runs — cloud sessions have `claude` on PATH.
- **Live gates**: `AUTOMATE_GOVERNANCE_CMD` / `AUTOMATE_CODEGEN_CMD` can point at [`scripts/gates/`](../scripts/gates/) (invoked as `bash <script>`); they only need a headless agent, which the cloud has.
- **Live worktrees and shipping**: `treehouse` and `no-mistakes` are external binaries that must also be installed by the setup script before `AUTOMATE_DRY_RUN=false` makes sense end to end. `no-mistakes` additionally needs its daemon running, so full live shipping from a cloud session is not validated yet — treat the cloud environment as dry-run + direct until it is.
- **firstmate**: needs tmux plus a one-time interactive consent in its pane ([docs/adapters.md](adapters.md)), so it is not suited to unattended cloud sessions.

## Working on this repository in the cloud

Independent of the environment setup above, this repo carries a `SessionStart` hook ([`.claude/hooks/session-start.sh`](../.claude/hooks/session-start.sh)) that runs `uv sync` in remote sessions, so `make check` works from the first turn when auto-mate itself is opened in Claude Code on the web.
