# auto-mate in a Claude cloud environment

How to make `automate` part of a default [Claude Code cloud environment](https://code.claude.com/docs/en/claude-code-on-the-web), so every web session starts with the CLI installed and configured.

## One-time environment setup

1. On [claude.ai/code](https://claude.ai/code), open the **environment selector** (the cloud icon above the message box) and create or edit an environment.
2. Paste the contents of [`scripts/cloud-setup.sh`](../scripts/cloud-setup.sh) into the environment's **Setup script**. It keeps a checkout of this repository at `/opt/auto-mate`, installs the `automate` CLI from it with `uv tool install`, and verifies the install. The checkout matters beyond the install: the wheel ships only the `automate` package, so the [gate scripts](../scripts/gates/) exist in the environment only through that checkout, at a stable absolute path. The container snapshot is cached after the script completes, so later sessions start instantly.
3. Add **environment variables** (`.env` format) to preconfigure auto-mate. A useful cloud baseline:

   ```bash
   # Dry-run lifecycle (also the default); see below before flipping this off.
   AUTOMATE_DRY_RUN=true
   # The direct crew backend needs a headless agent command.
   AUTOMATE_AGENT_CMD=claude -p --permission-mode acceptEdits --setting-sources project,local
   # Gates, by ABSOLUTE path: gate commands run with the task's repo as their
   # working directory, so a relative path would resolve against that repo.
   AUTOMATE_GOVERNANCE_CMD=bash /opt/auto-mate/scripts/gates/governance.sh
   AUTOMATE_CODEGEN_CMD=bash /opt/auto-mate/scripts/gates/codegen.sh
   ```

4. Network policy: the setup script needs `github.com`, `astral.sh` (uv bootstrap), and PyPI (`pypi.org` and `files.pythonhosted.org`, where uv downloads the dependencies). The default **Trusted** policy covers all of these; a **Custom** allowlist must include them explicitly.
5. Pick this environment in the selector to make it the default for new sessions (from the CLI: `/remote-env`).

## What works in the cloud, and what needs more

`AUTOMATE_DRY_RUN` is a single global switch: every adapter and gate either echoes its commands or executes them. There is no per-stage mix, so going live is all-or-nothing:

- **Setup script only (`AUTOMATE_DRY_RUN=true`)**: the full lifecycle and CLI work in dry-run — each stage prints the exact commands it would run, including the agent command. Nothing executes for real.
- **Going live (`AUTOMATE_DRY_RUN=false`) needs the upstream binaries too.** The first live stage is worktree provisioning, so `treehouse` must also be installed by the setup script or every run fails before the crew starts; shipping additionally needs `no-mistakes` plus its daemon, which has not been validated inside cloud containers. Install both per their own repositories before flipping the flag. Once they are present, the pieces the cloud does provide line up: sessions have `claude` on PATH for the `direct` crew backend, and the gate scripts sit at `/opt/auto-mate/scripts/gates/` from the setup checkout.
- **firstmate**: needs tmux plus a one-time interactive consent in its pane ([docs/adapters.md](adapters.md)), so it is not suited to unattended cloud sessions.

## Working on this repository in the cloud

Independent of the environment setup above, this repo carries a `SessionStart` hook ([`.claude/hooks/session-start.sh`](../.claude/hooks/session-start.sh)) that runs `uv sync` in remote sessions, so `make check` works from the first turn when auto-mate itself is opened in Claude Code on the web.
