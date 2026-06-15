---
interfaces: "exposes `materialize_oracle_result(repo, cwe, severity, *, bounties=None, submissions=0, last_audit_days=None, fp_patterns=None) -> dict` returning EXACTLY the four keys source_qualify_gate.qualify reads: expected_payout(int), open_submissions(int), days_since_audit(int|float), fp_risk(False|list); plus the module constant ORACLE_RESULT_FIELDS."
working_dir: "/home/xnihil0zer0/NobleGreedv2"
---

# Title

oracle_result materializer (ngv2/oracle_materializer.py): per-repo computation of the exact dict source_qualify_gate.qualify consumes

# Scope

Build a NEW pure, stdlib+ngv2-only module ngv2/oracle_materializer.py that computes the `oracle_result` dict the live ngv2.source_qualify_gate.qualify consumes, replacing the hand-faked stub at _e2e_run/drive_one.py:254-258. It exposes `materialize_oracle_result(repo, cwe, severity, *, bounties=None, submissions=0, last_audit_days=None, fp_patterns=None) -> dict` returning EXACTLY the four keys qualify reads -- expected_payout (int, via ngv2.bounty_gate.gate), open_submissions (int, the injected saturation count), days_since_audit (int|float, the injected audit age; never-audited -> a large stale value), and fp_risk (literal False when no FP pattern matches the CWE, else the list of matched patterns -- a truthy value that makes qualify SKIP). All external facts arrive through injected data seams so the function is pure, total, deterministic, and hermetic (no network, subprocess, real-clock, filesystem, or randomness). Emit the whole file verbatim from the Deliverables block. Name the committed oracle tests/test_oracle_materializer_wired.py in the verification_command.

# Non-Goals

Do NOT scrape or read any file (the bounty snapshot, saturation count, audit age, and fp_patterns are all injected arguments). Do NOT re-implement the economic decision -- call ngv2.bounty_gate.gate. Do NOT change source_qualify_gate, bounty_gate, target_qualify, or _e2e_run/drive_one.py. No network, subprocess, LLM, wall-clock, or randomness. This is a single new file; do not touch any other module.

# Inputs

Consumes ngv2.bounty_gate.gate(owner_repo, cwe, severity, *, bounties=None) -> {"decision","expected_payout","tier","reasoning"} (expected_payout may be int|0|None). The produced dict is consumed by ngv2.source_qualify_gate.qualify(target, oracle_result, *, saturation_cap=50, freshness_min=7), whose REQUIRED_FIELDS are exactly ('expected_payout','open_submissions','days_since_audit','fp_risk') and which (a) SKIPs when expected_payout<=0, (b) SKIPs when open_submissions>=saturation_cap, (c) SKIPs when days_since_audit<freshness_min, (d) SKIPs when fp_risk is not False. fp_patterns records look like {"cwe":"CWE-352", ...}; match by CWE case-insensitively.

# Deliverables

ngv2/oracle_materializer.py with EXACTLY this content:

```python
"""Materialize the ``oracle_result`` dict consumed by source_qualify_gate.qualify.

Pure + stdlib-only: every external fact -- the bounty economics decision, the
saturation count, the audit clock, and the false-positive patterns -- arrives
through an injected data seam, so this function performs no network, subprocess,
real-clock, or filesystem access of its own. Identical inputs always yield
identical outputs.

The produced dict has EXACTLY the four keys source_qualify_gate.qualify reads:
``expected_payout`` (int), ``open_submissions`` (int), ``days_since_audit``
(int|float), and ``fp_risk`` (literally ``False`` when no FP pattern matches the
CWE, else the list of matched patterns -- a truthy value that makes qualify SKIP).
"""
from __future__ import annotations
from typing import Any, Dict, Mapping, Optional, Sequence

from ngv2.bounty_gate import gate as _bounty_gate

ORACLE_RESULT_FIELDS = ('expected_payout', 'open_submissions', 'days_since_audit', 'fp_risk')

# A days_since_audit value used when there is no prior audit record. It is large
# enough to always clear any sane freshness floor (a never-audited repo is
# maximally fresh-to-hunt).
NEVER_AUDITED_DAYS = 10 ** 6


def _expected_payout(repo: str, cwe: str, severity: str, bounties: Optional[Mapping[str, Any]]) -> int:
    """Run the economic gate and coerce its payout to a non-negative int."""
    decision = _bounty_gate(repo, cwe, severity, bounties=bounties)
    payout = decision.get('expected_payout')
    if isinstance(payout, bool) or not isinstance(payout, (int, float)):
        return 0
    return int(payout) if payout > 0 else 0


def _days_since_audit(last_audit_days: Optional[Any]) -> Any:
    """Return the injected audit age in days; never-audited -> NEVER_AUDITED_DAYS."""
    if last_audit_days is None:
        return NEVER_AUDITED_DAYS
    try:
        value = float(last_audit_days)
    except (TypeError, ValueError):
        return NEVER_AUDITED_DAYS
    return value if value >= 0 else 0.0


def _fp_risk(cwe: str, fp_patterns: Optional[Sequence[Mapping[str, Any]]]):
    """Return ``False`` when no FP pattern matches the CWE, else the matched list."""
    records = fp_patterns or []
    cwe_norm = str(cwe or '').strip().lower()
    matched = [r for r in records if str(r.get('cwe', '')).strip().lower() == cwe_norm]
    return matched if matched else False


def materialize_oracle_result(repo: str, cwe: str, severity: str, *,
                              bounties: Optional[Mapping[str, Any]] = None,
                              submissions: int = 0,
                              last_audit_days: Optional[Any] = None,
                              fp_patterns: Optional[Sequence[Mapping[str, Any]]] = None) -> Dict[str, Any]:
    """Compute the oracle_result dict source_qualify_gate.qualify consumes.

    All external facts are injected, keeping the function pure and hermetic.
    """
    try:
        open_submissions = int(submissions)
    except (TypeError, ValueError):
        open_submissions = 0
    if open_submissions < 0:
        open_submissions = 0
    return {
        'expected_payout': _expected_payout(repo, cwe, severity, bounties),
        'open_submissions': open_submissions,
        'days_since_audit': _days_since_audit(last_audit_days),
        'fp_risk': _fp_risk(cwe, fp_patterns),
    }
```

Verification: `cd /home/xnihil0zer0/NobleGreedv2 && .venv/bin/python -m pytest tests/test_oracle_materializer_wired.py -q`
