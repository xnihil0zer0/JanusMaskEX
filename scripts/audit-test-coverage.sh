#!/usr/bin/env bash
set -e

# Default to running the script directly without arguments,
# the python script will handle finding the correct plan files.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
python3 "$SCRIPT_DIR/_audit_test_coverage.py" "$@"
