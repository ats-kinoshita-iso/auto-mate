#!/bin/bash
# SessionStart hook: make auto-mate runnable in Claude Code on the web.
#
# Installs the project and its dev group (pytest, ruff, mypy) into .venv so
# `make check` works from the first turn of a web session. Local sessions are
# untouched: developers manage their own environment there.
set -euo pipefail

if [ "${CLAUDE_CODE_REMOTE:-}" != "true" ]; then
  exit 0
fi

cd "$CLAUDE_PROJECT_DIR"

# uv is preinstalled in Claude's cloud containers; bootstrap it if absent.
if ! command -v uv >/dev/null 2>&1; then
  curl -LsSf https://astral.sh/uv/install.sh | sh
  export PATH="$HOME/.local/bin:$PATH"
  echo 'export PATH="$HOME/.local/bin:$PATH"' >> "$CLAUDE_ENV_FILE"
fi

# Idempotent: resolves against uv.lock and reuses .venv on re-runs.
uv sync
