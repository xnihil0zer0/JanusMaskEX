#!/usr/bin/env bash
# scripts/impl_dispatch_once.sh — run orchestrator until a target task lands, then exit cleanly.
#
# Usage:
#   scripts/impl_dispatch_once.sh <task_id> [<state_dir>] [<max_seconds>]
#
# Defaults: state_dir=state, max_seconds=1800.
#
# Behavior:
#   1. Verifies state/tasks/<task_id>.json exists (canonical scan path per
#      harness/orchestrator.py:533) and processed/<task_id>.json absent.
#      Auto-promotes from legacy state/tasks/queued/<task_id>.json if found.
#   2. Spawns python -m harness.orchestrator --state-dir <state_dir> in the background,
#      capturing pid + setsid so we can kill the whole process group cleanly.
#   3. Polls every 2s for state/tasks/processed/<task_id>.json (orchestrator atomically
#      moves the task on accept OR reject — both are terminal).
#   4. After detection, waits 5s for any final ledger writes, then SIGTERM the orchestrator
#      process group (SIGKILL fallback after 10s).
#   5. Verification: greps state/impl_progress.jsonl for event=auto_commit + matching task_id
#      and prints any new git commit on the task's files_touched paths.
#   6. Exit codes: 0=task processed (regardless of accept/reject), 1=timeout, 2=preflight failed.

set -u

PROJECT_DIR="${CLAUDE_PROJECT_DIR:-$(cd "$(dirname "$0")/.." && pwd)}"
cd "${PROJECT_DIR}"

TASK_ID="${1:?usage: impl_dispatch_once.sh <task_id> [state_dir] [max_seconds]}"
STATE_DIR="${2:-state}"
MAX_SECONDS="${3:-1800}"

CANONICAL_PATH="${STATE_DIR}/tasks/${TASK_ID}.json"
LEGACY_QUEUED_PATH="${STATE_DIR}/tasks/queued/${TASK_ID}.json"
PROCESSED_PATH="${STATE_DIR}/tasks/processed/${TASK_ID}.json"
LEDGER="${STATE_DIR}/impl_progress.jsonl"

# Orchestrator scans state/tasks/*.json (top-level) per harness/orchestrator.py:533.
# Auto-promote from legacy state/tasks/queued/ subdir if found there.
if [[ ! -f "${CANONICAL_PATH}" && -f "${LEGACY_QUEUED_PATH}" ]]; then
  echo "preflight: promoting ${LEGACY_QUEUED_PATH} -> ${CANONICAL_PATH} (canonical scan path)"
  mv "${LEGACY_QUEUED_PATH}" "${CANONICAL_PATH}"
fi

if [[ ! -f "${CANONICAL_PATH}" ]]; then
  echo "preflight: ${CANONICAL_PATH} not found (also checked ${LEGACY_QUEUED_PATH})" >&2
  exit 2
fi
if [[ -f "${PROCESSED_PATH}" ]]; then
  echo "preflight: ${PROCESSED_PATH} already exists — task already processed (mv it back to ${CANONICAL_PATH} to re-dispatch)" >&2
  exit 2
fi

LEDGER_PRELEN=0
if [[ -f "${LEDGER}" ]]; then
  LEDGER_PRELEN=$(wc -l < "${LEDGER}")
fi
HEAD_PRE=$(git rev-parse HEAD)

echo "dispatch: launching orchestrator (state=${STATE_DIR}, target=${TASK_ID}, max=${MAX_SECONDS}s)"
setsid python -m harness.orchestrator --state-dir "${STATE_DIR}" \
  > "${STATE_DIR}/dispatch_once.stdout.log" \
  2> "${STATE_DIR}/dispatch_once.stderr.log" &
ORCH_PID=$!
echo "dispatch: orchestrator pgid=${ORCH_PID} pid=${ORCH_PID} (logs: ${STATE_DIR}/dispatch_once.std{out,err}.log)"

cleanup() {
  if kill -0 "${ORCH_PID}" 2>/dev/null; then
    echo "dispatch: SIGTERM to orchestrator pgid=${ORCH_PID}"
    kill -TERM "-${ORCH_PID}" 2>/dev/null || true
    for _ in $(seq 1 10); do
      kill -0 "${ORCH_PID}" 2>/dev/null || break
      sleep 1
    done
    if kill -0 "${ORCH_PID}" 2>/dev/null; then
      echo "dispatch: SIGKILL fallback for orchestrator pgid=${ORCH_PID}"
      kill -KILL "-${ORCH_PID}" 2>/dev/null || true
    fi
  fi
}
trap cleanup EXIT

ELAPSED=0
INTERVAL=2
while [[ ${ELAPSED} -lt ${MAX_SECONDS} ]]; do
  if [[ -f "${PROCESSED_PATH}" ]]; then
    echo "dispatch: ${TASK_ID} reached processed/ after ${ELAPSED}s"
    break
  fi
  if ! kill -0 "${ORCH_PID}" 2>/dev/null; then
    echo "dispatch: orchestrator exited prematurely (pid=${ORCH_PID})" >&2
    echo "--- stderr tail ---" >&2
    tail -20 "${STATE_DIR}/dispatch_once.stderr.log" >&2 || true
    exit 1
  fi
  sleep ${INTERVAL}
  ELAPSED=$((ELAPSED + INTERVAL))
done

if [[ ! -f "${PROCESSED_PATH}" ]]; then
  echo "dispatch: timeout after ${MAX_SECONDS}s — ${TASK_ID} did not reach processed/" >&2
  exit 1
fi

# Allow ledger writes + auto_commit to flush before tearing down.
sleep 5

cleanup
trap - EXIT

echo
echo "=== verification ==="
echo "ledger rows added: $(($(wc -l < "${LEDGER}") - LEDGER_PRELEN))"
echo "--- new ledger rows for ${TASK_ID} ---"
grep "\"task_id\": \"${TASK_ID}\"" "${LEDGER}" | tail -10 || true
echo
echo "--- auto_commit row (if any) ---"
grep "\"task_id\": \"${TASK_ID}\"" "${LEDGER}" | grep '"event": "auto_commit"' || echo "(no auto_commit row — task may have been rejected)"
echo
HEAD_POST=$(git rev-parse HEAD)
if [[ "${HEAD_PRE}" != "${HEAD_POST}" ]]; then
  echo "--- new commits ---"
  git log --oneline "${HEAD_PRE}..${HEAD_POST}"
else
  echo "--- HEAD unchanged (no auto_commit landed) ---"
fi

exit 0
