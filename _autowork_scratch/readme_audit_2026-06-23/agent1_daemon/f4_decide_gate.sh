#!/usr/bin/env bash
# Finding 4: pause/full_stop/auto_promote.disabled semantics unchanged.
set -euo pipefail
cd /home/xnihil0zer0/JanusMaskJR
echo "=== _decide paused = pause OR full_stop (matches README snippet) ==="
sed -n '2102,2113p' harness/autowork_daemon.py
echo
echo "=== full_stop breaks loop in run_daemon ==="
sed -n '2950,2953p' harness/autowork_daemon.py
echo
echo "=== auto_promote.disabled gates promotion only ==="
sed -n '1648,1653p' harness/autowork_daemon.py
grep -nE "def _auto_promote_disabled" harness/autowork_daemon.py
echo
echo "=== flag file paths ==="
grep -nE "def _pause_flag_path|def _full_stop_path" harness/autowork_daemon.py
sed -n '316,328p' harness/autowork_daemon.py
