#!/usr/bin/env bash
# plan-validate.sh

if [ -z "$1" ]; then
    echo "Usage: $0 <plan.json>"
    exit 1
fi

PLAN_FILE="$1"

if [ ! -f "$PLAN_FILE" ]; then
    echo "Error: File not found: $PLAN_FILE"
    exit 1
fi

PYTHONPATH="$(cd "$(dirname "$0")/.." && pwd)" python3 -c "
import sys
import json
from harness.planner.plan_validator import validate_plan

try:
    violations = validate_plan('$PLAN_FILE')
    if not violations:
        print('Plan is valid.')
        sys.exit(0)
    else:
        for v in violations:
            print(f'[{v.severity.upper()}] {v.code} at {v.path}: {v.message}')
        sys.exit(1)
except Exception as e:
    print(f'Validation failed: {e}')
    sys.exit(1)
"
