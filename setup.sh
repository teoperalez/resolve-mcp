#!/usr/bin/env bash
# First-time setup for resolve-mcp: install Python deps and register the MCP server.
# Called automatically by bootstrap.sh after cloning. Idempotent.
#
# Usage: ./setup.sh [/path/to/resolve-mcp]

set -euo pipefail
DEST="${1:-$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)}"

# ── 1. Ensure uv is available ─────────────────────────────────────────────────
if ! command -v uv >/dev/null 2>&1; then
  UV_CANDIDATES=(
    "$HOME/.local/bin/uv"
    "$HOME/.cargo/bin/uv"
  )
  UV_BIN=""
  for c in "${UV_CANDIDATES[@]}"; do
    if [[ -x "$c" ]]; then UV_BIN="$c"; break; fi
  done
  if [[ -n "$UV_BIN" ]]; then
    export PATH="$(dirname "$UV_BIN"):$PATH"
    echo "  [resolve-mcp] uv found at $UV_BIN"
  else
    echo "  [resolve-mcp] uv not found — installing..."
    curl -LsSf https://astral.sh/uv/install.sh | sh
    export PATH="$HOME/.local/bin:$PATH"
  fi
fi
UV_EXE="$(command -v uv)"

# ── 2. Install Python deps ────────────────────────────────────────────────────
echo "  [resolve-mcp] Installing Python dependencies..."
cd "$DEST"
"$UV_EXE" sync --extra transcription

# ── 3. Register MCP server (user scope = available in all projects) ───────────
echo "  [resolve-mcp] Registering MCP server with Claude Code..."
claude mcp remove resolve 2>/dev/null || true
claude mcp add --scope user resolve \
    -- "$UV_EXE" --directory "$DEST" run resolve-mcp

echo "  [resolve-mcp] Setup complete."
echo "  [resolve-mcp] Start a new Claude Code session to activate the 'resolve' MCP server."
