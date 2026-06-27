#!/usr/bin/env bash
# Finding 3: watchdog detect_and_heal_stalls — DEFAULT-OFF; separate from always-on _check_inactivity_watchdog.
set -euo pipefail
cd /home/xnihil0zer0/JanusMaskJR
echo "=== detect_and_heal_stalls is DEFAULT-OFF behind JM_WATCHDOG_ENABLED / autowork.watchdog.enabled ==="
sed -n '1193,1206p' harness/state_reconciler.py
echo
echo "=== config has NO autowork.watchdog section => watchdog OFF ==="
grep -nE "watchdog" harness/config.yaml || echo "(no 'watchdog' key in config.yaml — confirms default-off)"
echo
echo "=== ALWAYS-ON daemon-side _check_inactivity_watchdog is SEPARATE (in autowork_daemon.py) ==="
grep -nE "def _check_inactivity_watchdog|_check_inactivity_watchdog\(" harness/autowork_daemon.py
echo
echo "=== detect_and_heal_stalls only invoked from reconciler reap sweep (contained) ==="
grep -nE "detect_and_heal_stalls\(" harness/state_reconciler.py
echo
echo "=== watchdog control dir path ==="
grep -nE "watchdog_dir = " harness/state_reconciler.py
