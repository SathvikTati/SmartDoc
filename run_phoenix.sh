#!/usr/bin/env bash
#
# Runs the Phoenix observability server as ONE persistent process, separate
# from the FastAPI app.
#
# Not from .venv: that environment has `arize-phoenix-otel`, which only
# *emits* spans, and the server package does not import on the 3.11 the
# app pins. uvx fetches the server into its own 3.12 environment instead,
# so the UI never becomes a dependency of the API.
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$SCRIPT_DIR"

export PHOENIX_WORKING_DIR="$REPO_ROOT/.phoenix"

echo "Starting Phoenix"
echo "  data dir : $PHOENIX_WORKING_DIR"
echo "  UI       : http://localhost:6006  (project: port6)"
echo
echo "The API only emits spans when PHOENIX_ENABLED=true, so start it with:"
echo "  PHOENIX_ENABLED=true uv run uvicorn port6.main:app --reload"

exec uvx --python 3.12 --from arize-phoenix phoenix serve
