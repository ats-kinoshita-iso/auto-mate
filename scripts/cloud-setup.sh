#!/bin/bash
# Setup script for a Claude Code cloud environment (claude.ai/code).
#
# Paste this into the environment's "Setup script" field (or fetch and run it).
# It runs once per environment as root on Ubuntu 24.04, before Claude launches;
# the container filesystem is snapshotted afterward, so installs here are free
# for every later session. The default "Trusted" network policy allows
# github.com and astral.sh, which is all this script needs.
#
# Result: the `automate` CLI on PATH in every session of the environment.
set -euo pipefail

# uv is preinstalled in Claude's cloud containers; bootstrap it if absent.
if ! command -v uv >/dev/null 2>&1; then
  curl -LsSf https://astral.sh/uv/install.sh | sh
  export PATH="$HOME/.local/bin:$PATH"
fi

# --force: re-running the setup script upgrades an existing install in place.
uv tool install --force git+https://github.com/ats-kinoshita-iso/auto-mate

# Fail the setup (and surface it in the environment log) if the CLI is broken.
automate --help >/dev/null
echo "auto-mate installed: $(automate status 2>&1 | head -1)"
