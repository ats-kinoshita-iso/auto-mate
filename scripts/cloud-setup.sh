#!/bin/bash
# Setup script for a Claude Code cloud environment (claude.ai/code).
#
# Paste this into the environment's "Setup script" field. It runs once per
# environment as root on Ubuntu 24.04, before Claude launches; the container
# filesystem is snapshotted afterward, so installs here are free for every
# later session.
#
# Network: needs github.com, astral.sh (uv bootstrap), and PyPI (pypi.org +
# files.pythonhosted.org, where uv downloads the dependencies). The default
# "Trusted" policy allows all of these; a Custom allowlist must include them.
#
# Result:
#   - the `automate` CLI on PATH in every session of the environment
#   - a checkout at /opt/auto-mate, so the gate scripts are available at a
#     stable ABSOLUTE path. The wheel ships only the `automate` package, and
#     gate commands run with the task's repo as cwd, so a relative
#     scripts/gates/ path would resolve against the wrong repository.
set -euo pipefail

CHECKOUT=/opt/auto-mate

# uv is preinstalled in Claude's cloud containers; bootstrap it if absent.
if ! command -v uv >/dev/null 2>&1; then
  curl -LsSf https://astral.sh/uv/install.sh | sh
  export PATH="$HOME/.local/bin:$PATH"
fi

if [ -d "$CHECKOUT/.git" ]; then
  git -C "$CHECKOUT" pull --ff-only  # re-running the setup script updates it
else
  git clone https://github.com/ats-kinoshita-iso/auto-mate "$CHECKOUT"
fi

# --force: re-running the setup script reinstalls over the existing tool.
uv tool install --force "$CHECKOUT"

# Fail the setup (and surface it in the environment log) if the CLI is broken.
automate --help >/dev/null
echo "auto-mate installed; gates at $CHECKOUT/scripts/gates/"
