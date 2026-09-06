#!/usr/bin/env bash
# Lint, typecheck and test. CI runs this same script; so does the commit gate.
set -euo pipefail
cd "$(dirname "$0")/.."

if [[ -x .venv/bin/python ]]; then
    export PATH="$PWD/.venv/bin:$PATH"
fi

ruff check .
ruff format --check .
mypy
pytest -q
