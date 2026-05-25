#!/usr/bin/env bash
# scripts/run-webui.sh — unified launcher for the JanusMask orchestrator daemon
# and the read-only WebUI sidecar (tools/webui_server.py).
#
# Usage:
#   scripts/run-webui.sh [options]
#
# Default behavior: launches BOTH `python -m harness.orchestrator` and
# `python -m tools.webui_server` as background processes, streams their logs
# to logs/{orchestrator,webui}.log, and traps SIGINT/SIGTERM to tear them
# down cleanly. Stdout shows a one-line status summary; tail the log files
# for live activity.
#
# Options:
#   --webui-only          Launch only the WebUI sidecar (skip the orchestrator)
#   --orchestrator-only   Launch only the orchestrator daemon (skip the WebUI)
#   --port <N>            WebUI bind port (default: 8765)
#   --host <addr>         WebUI bind host (default: 127.0.0.1)
#   --state-dir <path>    state directory (default: state)
#   --logs-dir <path>     logs directory (default: logs)
#   --foreground          Don't background — run the orchestrator in the
#                         foreground (Ctrl-C tears both down)
#   -h | --help           Show this help and exit
#
# Notes:
#   - Loopback bind (127.0.0.1) is the only access boundary for the WebUI.
#     Do not expose to non-loopback addresses; see
#     docs/runbooks/webui-sidecar.md "Non-coverage notice".
#   - The orchestrator may already be running in another terminal; in that
#     case use --webui-only to launch just the sidecar.
#   - Logs are appended (>>), not truncated, so historical activity is
#     preserved across restarts.

set -u

PROJECT_DIR="${CLAUDE_PROJECT_DIR:-$(cd "$(dirname "$0")/.." && pwd)}"
cd "${PROJECT_DIR}"

LAUNCH_ORCHESTRATOR=1
LAUNCH_WEBUI=1
PORT=8765
HOST=127.0.0.1
STATE_DIR=state
LOGS_DIR=logs
FOREGROUND=0

usage() {
  sed -n '2,33p' "$0"
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --webui-only) LAUNCH_ORCHESTRATOR=0; shift ;;
    --orchestrator-only) LAUNCH_WEBUI=0; shift ;;
    --port) PORT="$2"; shift 2 ;;
    --host) HOST="$2"; shift 2 ;;
    --state-dir) STATE_DIR="$2"; shift 2 ;;
    --logs-dir) LOGS_DIR="$2"; shift 2 ;;
    --foreground) FOREGROUND=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "unknown option: $1" >&2; usage; exit 2 ;;
  esac
done

mkdir -p "${LOGS_DIR}"

ORCH_PID=""
WEBUI_PID=""

cleanup() {
  local rc=$?
  echo
  if [[ -n "${ORCH_PID}" ]] && kill -0 "${ORCH_PID}" 2>/dev/null; then
    echo "run-webui: SIGTERM orchestrator pgid=${ORCH_PID}"
    kill -TERM "-${ORCH_PID}" 2>/dev/null || true
  fi
  if [[ -n "${WEBUI_PID}" ]] && kill -0 "${WEBUI_PID}" 2>/dev/null; then
    echo "run-webui: SIGTERM webui pgid=${WEBUI_PID}"
    kill -TERM "-${WEBUI_PID}" 2>/dev/null || true
  fi
  # Give them up to 5s to exit gracefully, then SIGKILL.
  for _ in 1 2 3 4 5; do
    local alive=0
    [[ -n "${ORCH_PID}" ]] && kill -0 "${ORCH_PID}" 2>/dev/null && alive=1
    [[ -n "${WEBUI_PID}" ]] && kill -0 "${WEBUI_PID}" 2>/dev/null && alive=1
    [[ ${alive} -eq 0 ]] && break
    sleep 1
  done
  [[ -n "${ORCH_PID}" ]] && kill -0 "${ORCH_PID}" 2>/dev/null && kill -KILL "-${ORCH_PID}" 2>/dev/null || true
  [[ -n "${WEBUI_PID}" ]] && kill -0 "${WEBUI_PID}" 2>/dev/null && kill -KILL "-${WEBUI_PID}" 2>/dev/null || true
  exit ${rc}
}
trap cleanup INT TERM EXIT

if [[ ${LAUNCH_ORCHESTRATOR} -eq 1 ]]; then
  echo "run-webui: launching orchestrator (state=${STATE_DIR}, log=${LOGS_DIR}/orchestrator.log)"
  setsid python -m harness.orchestrator --state-dir "${STATE_DIR}" \
    >> "${LOGS_DIR}/orchestrator.log" 2>&1 &
  ORCH_PID=$!
  echo "  orchestrator pgid=${ORCH_PID}"
fi

if [[ ${LAUNCH_WEBUI} -eq 1 ]]; then
  echo "run-webui: launching sidecar (http://${HOST}:${PORT}, log=${LOGS_DIR}/webui.log)"
  setsid python -m tools.webui_server \
    --host "${HOST}" --port "${PORT}" \
    --state-dir "${STATE_DIR}" --logs-dir "${LOGS_DIR}" \
    >> "${LOGS_DIR}/webui.log" 2>&1 &
  WEBUI_PID=$!
  echo "  webui pgid=${WEBUI_PID}"
fi

if [[ -z "${ORCH_PID}" && -z "${WEBUI_PID}" ]]; then
  echo "run-webui: nothing to launch (--webui-only and --orchestrator-only both unset?)" >&2
  trap - INT TERM EXIT
  exit 2
fi

echo
echo "run-webui: ready. Tail logs with:"
[[ -n "${ORCH_PID}" ]] && echo "    tail -f ${LOGS_DIR}/orchestrator.log"
[[ -n "${WEBUI_PID}" ]] && echo "    tail -f ${LOGS_DIR}/webui.log"
[[ -n "${WEBUI_PID}" ]] && echo "    curl -fsS http://${HOST}:${PORT}/api/health"
# E8: surface the operator token URL so the operator does not have to grep
# the webui log to find it. Wait briefly for E2's load_or_mint_token to
# settle the file, then read it.
if [[ -n "${WEBUI_PID}" ]]; then
  TOKEN_FILE="${STATE_DIR}/control/operator_token"
  for _ in 1 2 3 4 5 6 7 8 9 10; do
    [[ -s "${TOKEN_FILE}" ]] && break
    sleep 0.2
  done
  if [[ -s "${TOKEN_FILE}" ]]; then
    TOKEN="$(cat "${TOKEN_FILE}")"
    echo
    echo "    WebUI ready at http://${HOST}:${PORT}/?token=${TOKEN}"
  else
    echo
    echo "    (operator token not yet written; check ${TOKEN_FILE})"
  fi
fi
echo "Press Ctrl-C to stop."

# Wait for either process to exit; if one dies, tear down the other.
while true; do
  if [[ -n "${ORCH_PID}" ]] && ! kill -0 "${ORCH_PID}" 2>/dev/null; then
    echo "run-webui: orchestrator exited unexpectedly; tearing down" >&2
    exit 1
  fi
  if [[ -n "${WEBUI_PID}" ]] && ! kill -0 "${WEBUI_PID}" 2>/dev/null; then
    echo "run-webui: webui exited unexpectedly; tearing down" >&2
    exit 1
  fi
  sleep 2
done
