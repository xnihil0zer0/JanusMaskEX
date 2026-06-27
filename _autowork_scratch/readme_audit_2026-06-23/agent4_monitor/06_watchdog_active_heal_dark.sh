#!/usr/bin/env bash
# Prove: a NEW per-task stall healer (detect_and_heal_stalls) landed since baseline,
# ACTIVELY kills+requeues (not diagnosis-only), but is DEFAULT-OFF (dark): emits
# NO ledger event, and its live call site passes config=None so only JM_WATCHDOG_ENABLED arms it.
set -u
cd /home/xnihil0zer0/JanusMaskJR
echo "=== NEW since baseline? ==="
echo -n "baseline detect_and_heal_stalls def: "; git show e5c0f9fb:harness/state_reconciler.py 2>/dev/null | grep -c "def detect_and_heal_stalls"
echo -n "current  detect_and_heal_stalls def: "; grep -c "def detect_and_heal_stalls" harness/state_reconciler.py
echo
echo "=== it ACTIVELY heals (SIGKILL wedged worker + clear pidfile), not diagnosis-only ==="
grep -n "os.kill(pid, signal.SIGKILL)\|entry.unlink()\|result\['healed'\]" harness/state_reconciler.py | head
echo
echo "=== but DEFAULT-OFF: armed only by JM_WATCHDOG_ENABLED env or config watchdog.enabled ==="
grep -n "JM_WATCHDOG_ENABLED\|_watchdog_enabled" harness/state_reconciler.py | head -4
echo -n "config.yaml has a 'watchdog:' section?  "; grep -c "watchdog" harness/config.yaml
echo "(0 = no config section => only the env var could ever arm it)"
echo
echo "=== the live call site passes NO config (config=None) -> config flag can't even arm it here ==="
grep -n "detect_and_heal_stalls(root" harness/state_reconciler.py
echo
echo "=== it writes NO ledger event (only escalation markers under state/control/.../watchdog/) ==="
echo -n "ledger writes inside detect_and_heal_stalls: "
awk '/def detect_and_heal_stalls/{f=1} f&&/impl_progress|write_jsonl|_emit_telemetry/{print; n++} /^def reap_spent_briefs/{f=0} END{if(!n)print "NONE"}' harness/state_reconciler.py
echo
echo "=== empirically: 0 stall_detected/stall_healed live rows (it is dark) ==="
for ev in stall_detected stall_healed; do echo -n "$ev live rows: "; grep -c "\"event\": \"$ev\"" state/impl_progress.jsonl 2>/dev/null || echo 0; done
echo
echo "=== the SEPARATE always-on inactivity watchdog DOES fire (README §7 row is accurate) ==="
echo -n "inactivity_watchdog_triggered live rows: "; grep -c '"event": "inactivity_watchdog_triggered"' state/impl_progress.jsonl 2>/dev/null
