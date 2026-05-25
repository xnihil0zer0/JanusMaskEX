#!/bin/sh
set -e

MARKER_ATTEMPTS="# DEFERRED_WIRING: attempts_not_consumed"
MARKER_AMBIGUOUS="# DEFERRED_WIRING: ambiguous_folded_into_failures"
MODE="strict"

if [ "$1" = "--list" ]; then
    MODE="list"
fi

if [ ! -d "harness" ]; then
    echo "Error: harness/ directory does not exist." >&2
    exit 1
fi

# Find all .py and .sh files in harness/, scripts/, tests/ and grep for markers
HITS=$(find harness scripts tests -type f \( -name "*.py" -o -name "*.sh" \) | grep -vE "check[-_]deferred[-_]wiring" | grep -v "test_track_record_handlers.py" | xargs grep -Hn -F -e "$MARKER_ATTEMPTS" -e "$MARKER_AMBIGUOUS" 2>/dev/null || true)

COUNT_ATTEMPTS=$(echo "$HITS" | grep -F "$MARKER_ATTEMPTS" | wc -l)
COUNT_AMBIGUOUS=$(echo "$HITS" | grep -F "$MARKER_AMBIGUOUS" | wc -l)

if [ -n "$HITS" ]; then
    echo "$HITS"
fi

echo "Summary: $COUNT_ATTEMPTS attempts_not_consumed, $COUNT_AMBIGUOUS ambiguous_folded_into_failures"

if [ "$MODE" = "list" ]; then
    exit 0
fi

# Strict mode: BOTH markers must appear AT LEAST ONCE in harness/track_record.py
ANCHOR_ATTEMPTS=$(echo "$HITS" | grep -F "harness/track_record.py" | grep -F "$MARKER_ATTEMPTS" | wc -l)
ANCHOR_AMBIGUOUS=$(echo "$HITS" | grep -F "harness/track_record.py" | grep -F "$MARKER_AMBIGUOUS" | wc -l)

if [ "$ANCHOR_ATTEMPTS" -eq 0 ] || [ "$ANCHOR_AMBIGUOUS" -eq 0 ]; then
    echo "Error: Strict mode anchor failed. Missing markers in harness/track_record.py." >&2
    exit 1
fi

exit 0
