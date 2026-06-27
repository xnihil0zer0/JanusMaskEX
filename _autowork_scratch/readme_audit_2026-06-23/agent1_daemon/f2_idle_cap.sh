#!/usr/bin/env bash
# Finding 2: idle-sleep cap by soonest blocked-retry deadline.
set -euo pipefail
cd /home/xnihil0zer0/JanusMaskJR
echo "=== _soonest_blocked_retry_deadline exists ==="
grep -nE "def _soonest_blocked_retry_deadline" harness/autowork_daemon.py
echo
echo "=== run_daemon caps sleep_target when idle ==="
sed -n '2991,3002p' harness/autowork_daemon.py
echo
echo "=== heartbeat default still 1800 (config) ==="
grep -nE "heartbeat_sec" harness/config.yaml
echo
echo "=== commit ==="
git log --oneline e5c0f9fb..HEAD -- harness/autowork_daemon.py | grep -iE "idle-sleep-cap|idle_sleep" || echo "(see 06833ea daemon-idle-sleep-cap-impl)"
