#!/usr/bin/env bash
# scripts/run-autowork.sh — supervisor for the JanusMask autowork daemon
# (harness/autowork_daemon.py). Provides self-START + self-SUSTAIN: launches
# the daemon under setsid, writes its pidfile, and respawns it with capped
# exponential backoff if it dies. Mirrors run-webui.sh's trap/kill structure.
#
# CRITICAL: the daemon launched here runs run_daemon() (NOT --once), which emits
# a `daemon_start` ledger row from this NON-INTERACTIVE parent — the telemetry
# self-build criterion 7 depends on.
#
# Usage:
#   scripts/run-autowork.sh [options]
#
# Options:
#   --state-dir <path>    state directory (default: state)
#   --logs-dir <path>     logs directory (default: logs)
#   --config <path>       harness config (default: harness/config.yaml)
#   --max-backoff <sec>   cap on respawn backoff (default: 60)
#   --once                run a single daemon iteration (no respawn) and exit
#   -h | --help           show this help and exit
#
# Notes:
#   - Writes its supervised pid to state/control/autowork.pid (the same path
#     tools/webui_control.py reads), so the WebUI Stop button can SIGTERM it.
#   - The daemon installs its own SIGTERM handler (graceful drain on shutdown,
#     see G-DRAINEXIT). This supervisor forwards SIGINT/SIGTERM to the daemon
#     process group and stops respawning once it receives one.
#   - Logs are appended (>>), not truncated.

set -u

PROJECT_DIR="${CLAUDE_PROJECT_DIR:-$(cd "$(dirname "$0")/.." && pwd)}"
cd "${PROJECT_DIR}"

STATE_DIR=state
LOGS_DIR=logs
CONFIG=harness/config.yaml
MAX_BACKOFF=60
RUN_ONCE=0

usage() {
  sed -n '2,33p' "$0"
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --state-dir) STATE_DIR="$2"; shift 2 ;;
    --logs-dir) LOGS_DIR="$2"; shift 2 ;;
    --config) CONFIG="$2"; shift 2 ;;
    --max-backoff) MAX_BACKOFF="$2"; shift 2 ;;
    --once) RUN_ONCE=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "unknown option: $1" >&2; usage; exit 2 ;;
  esac
done

mkdir -p "${LOGS_DIR}"
mkdir -p "${STATE_DIR}/control/autowork"

PIDFILE="${STATE_DIR}/control/autowork.pid"
STOP_SENTINEL="${STATE_DIR}/control/autowork/supervisor.stop"
FULL_STOP_SENTINEL="${STATE_DIR}/control/autowork/full_stop"
LOGFILE="${LOGS_DIR}/autowork.log"
DAEMON_PID=""
STOP_REQUESTED=0

# Clear a stale supervisor.stop sentinel left by a prior WebUI Stop so a fresh
# start runs (G-SUPERVISOR-WUI). full_stop is operator-persistent and is NOT
# auto-cleared here (G-FULLSTOP) — the operator removes it to resume.
rm -f "${STOP_SENTINEL}" 2>/dev/null || true

cleanup() {
  local rc=$?
  STOP_REQUESTED=1
  echo
  if [[ -n "${DAEMON_PID}" ]] && kill -0 "${DAEMON_PID}" 2>/dev/null; then
    echo "run-autowork: SIGTERM daemon pgid=${DAEMON_PID}"
    kill -TERM "-${DAEMON_PID}" 2>/dev/null || true
    # Give the daemon up to 35s to drain its workers (G-DRAINEXIT grace=30s).
    for _ in $(seq 1 35); do
      kill -0 "${DAEMON_PID}" 2>/dev/null || break
      sleep 1
    done
    kill -0 "${DAEMON_PID}" 2>/dev/null && kill -KILL "-${DAEMON_PID}" 2>/dev/null || true
  fi
  rm -f "${PIDFILE}" 2>/dev/null || true
  # Clear the supervisor.stop sentinel on a clean exit so a later Start works
  # (G-SUPERVISOR-WUI). full_stop is intentionally left in place.
  rm -f "${STOP_SENTINEL}" 2>/dev/null || true
  exit ${rc}
}
trap cleanup INT TERM EXIT

if [[ ${RUN_ONCE} -eq 1 ]]; then
  echo "run-autowork: single iteration (state=${STATE_DIR}, log=${LOGFILE})"
  setsid python -m harness.autowork_daemon \
    --state-dir "${STATE_DIR}" --config "${CONFIG}" --once \
    >> "${LOGFILE}" 2>&1 &
  DAEMON_PID=$!
  echo "${DAEMON_PID}" > "${PIDFILE}"
  wait "${DAEMON_PID}"
  rc=$?
  trap - INT TERM EXIT
  rm -f "${PIDFILE}" 2>/dev/null || true
  exit ${rc}
fi

echo "run-autowork: supervising daemon (state=${STATE_DIR}, config=${CONFIG}, log=${LOGFILE})"
echo "  respawn backoff cap: ${MAX_BACKOFF}s"
echo "  Press Ctrl-C to stop (forwards SIGTERM for graceful drain)."

backoff=1
while [[ ${STOP_REQUESTED} -eq 0 ]]; do
  # WebUI Stop (or operator) writes supervisor.stop to halt the supervisor
  # itself, not just the daemon child — without it, Stop kills the daemon and we
  # respawn (G-SUPERVISOR-WUI). full_stop (G-FULLSTOP) likewise halts respawn.
  if [[ -e "${STOP_SENTINEL}" || -e "${FULL_STOP_SENTINEL}" ]]; then
    echo "run-autowork: stop/full_stop sentinel present; not respawning"
    break
  fi
  start_ts=$(date +%s)
  setsid python -m harness.autowork_daemon \
    --state-dir "${STATE_DIR}" --config "${CONFIG}" \
    >> "${LOGFILE}" 2>&1 &
  DAEMON_PID=$!
  echo "${DAEMON_PID}" > "${PIDFILE}"
  echo "run-autowork: daemon launched pgid=${DAEMON_PID} (backoff reset)"

  wait "${DAEMON_PID}"
  rc=$?
  DAEMON_PID=""
  rm -f "${PIDFILE}" 2>/dev/null || true

  [[ ${STOP_REQUESTED} -eq 1 ]] && break
  if [[ -e "${STOP_SENTINEL}" || -e "${FULL_STOP_SENTINEL}" ]]; then
    echo "run-autowork: stop/full_stop sentinel present after daemon exit; not respawning"
    break
  fi

  now_ts=$(date +%s)
  ran_for=$(( now_ts - start_ts ))
  if [[ ${ran_for} -ge 60 ]]; then
    backoff=1   # healthy run -> reset backoff
  fi
  echo "run-autowork: daemon exited rc=${rc} after ${ran_for}s; respawning in ${backoff}s" >&2
  for _ in $(seq 1 "${backoff}"); do
    [[ ${STOP_REQUESTED} -eq 1 ]] && break
    [[ -e "${STOP_SENTINEL}" || -e "${FULL_STOP_SENTINEL}" ]] && break
    sleep 1
  done
  backoff=$(( backoff * 2 ))
  [[ ${backoff} -gt ${MAX_BACKOFF} ]] && backoff=${MAX_BACKOFF}
done

# Belt-and-suspenders: clear supervisor.stop on loop exit (the trap also does
# this). full_stop is left in place — operator-persistent.
rm -f "${STOP_SENTINEL}" 2>/dev/null || true
