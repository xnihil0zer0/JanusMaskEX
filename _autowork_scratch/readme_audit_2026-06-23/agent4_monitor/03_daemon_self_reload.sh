#!/usr/bin/env bash
# Prove the daemon self-reload mechanism exists NOW and postdates the README baseline.
set -u
cd /home/xnihil0zer0/JanusMaskJR
echo "=== README baseline e5c0f9fb committed at ==="
git show -s --format='%ci  %s' e5c0f9fb
echo
echo "=== self-reload absent at baseline, present now? ==="
echo -n "baseline _should_reload_daemon hits: "; git show e5c0f9fb:harness/autowork_daemon.py 2>/dev/null | grep -c "_should_reload_daemon"
echo -n "current  _should_reload_daemon hits: "; grep -c "_should_reload_daemon" harness/autowork_daemon.py
echo
echo "=== the loop-top reload check + clean exit + ledger row ==="
grep -n "_should_reload_daemon(state_dir, startup_sha)\|daemon_source_changed\|return 0" harness/autowork_daemon.py | sed -n '1,6p'
echo
echo "=== which modules the reload-hash watches (self-reload SCOPE) ==="
.venv/bin/python - <<'PY'
import sys; sys.path.insert(0,'.')
import re, pathlib
src = pathlib.Path('harness/autowork_daemon.py').read_text()
# the tuple is identical in _should_reload_daemon and run_daemon
m = re.search(r"for _name in \(([^)]*)\):", src)
print("watched modules:", m.group(1).replace("\n","").strip() if m else "<not found>")
PY
echo
echo "=== is harness.brief_status (README §12 'B1') in the self-reload set? ==="
grep -q "'harness.brief_status'" harness/autowork_daemon.py && echo "YES -- brief_status self-reloads; the §12 'B1 needs restart' Note is stale" || echo "NO"
echo
echo "=== config knobs still read ONCE at startup (NOT self-reloaded) ==="
grep -n "config = load_config\|load_config()" harness/autowork_daemon.py | head -3
echo "(self-reload triggers on .py SOURCE sha change of those modules; a config.yaml VALUE change is NOT a source-file change in those modules -> still needs restart)"
