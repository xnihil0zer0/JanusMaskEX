"""RED wiring oracle for autocompiler/js/js_fork_policy.py (leaf ac-js-fork-policy wire proof).

Proves the module is WIRED per harness.wire_up.check_wired: present in the
discovered module set AND reachable from a live root OR registered for dynamic
wiring under config/** (config/autocompiler.yaml). RED while the module does
not exist; GREEN once the leaf lands alongside the committed registration.
"""
from pathlib import Path

from harness.wire_up import check_wired


def test_js_fork_policy_module_is_wired():
    repo_root = Path(__file__).resolve().parents[2]
    res = check_wired(repo_root, 'autocompiler/js/js_fork_policy.py')
    assert res.wired, res.reason
