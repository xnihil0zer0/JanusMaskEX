#!/usr/bin/env bash
# Finding 5: new control files/dirs under state/control/autowork/ not in README §13 tree.
set -euo pipefail
cd /home/xnihil0zer0/JanusMaskJR
echo "=== NEW: watchdog/ dir + attempts.json + escalation_<id>.json ==="
grep -nE "watchdog_dir = |attempts.json|escalation_%s.json|escalation_" harness/state_reconciler.py | head
echo
echo "=== README §13 currently lists under autowork/ ==="
sed -n '609,620p' README.md
echo
echo "=== Does README mention 'watchdog' anywhere? ==="
grep -niE "watchdog" README.md || echo "(README does NOT mention watchdog at all)"
