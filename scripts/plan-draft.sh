#!/usr/bin/env bash
set -e

if [ -f "venv/bin/activate" ]; then
    source venv/bin/activate
fi

exec python -m harness.planner.cli "$@"
