# Validation evidence — every reference impl proven against its oracle

Per mandatory design element #3 ("validate each reference impl against its oracle
in a scratch run before writing the brief — Phase II proved this kills paraphrase
rejects"), every NEW module + EDITed module in `_reference/` was run against its
committed RED oracle, and the EDITs were run against the UNION of all existing
oracles touching the shared symbol (anti-seesaw).

## Scratch scaffold (no production tree write)
A namespace-package shim at `/tmp/p3_validate/ngv2/__init__.py` does
`__path__.append('/home/xnihil0zer0/NobleGreedv2/ngv2')`, so the NEW/EDITed
reference modules shadow the real NGv2 package while every other `ngv2.*` import
resolves to the real tree. Reproduce:

```bash
# (recreate the shim: new modules + *.EDITED.py copied to /tmp/p3_validate/ngv2/,
#  reference data to /tmp/p3_validate/data, bundled taint_specs copied too)
cd /tmp/p3_validate
PYTHONPATH=/tmp/p3_validate:/home/xnihil0zer0/NobleGreedv2 \
  python3 -m pytest -q /home/xnihil0zer0/JanusMaskJR/_phase_prep/phase3/build/oracles/
```

## Results
- **61 / 61 new oracles PASS** (all 11 dispatched leaves).
- **Anti-seesaw UNION: 160 / 160 existing oracles PASS** against the three edited
  modules (codeql_runner, confidence_signals, session_gate), incl.
  tests/test_codeql_runner.py, the three confidence_signals oracles, and the full
  session_gate / session_api / state_machine / lifecycle suite.
- **Zero new regressions in the full NGv2 suite.** Baseline (no shim) and with
  the edited-module shim are IDENTICAL: `45 failed, 1434 passed, 14 errors`. The
  45 fails + 14 collection errors are pre-existing in-flight Phase-I/II modules
  (verdict_store, candidate_builder, ssrf_detect, pathtrav_detect, the huntr/osv
  fetchers, …) — none touched by this build.

## Host CodeQL (read-only, no DB built)
- `codeql version` → 2.25.1; `python-security-extended.qls` + python-queries
  1.7.11 resolve locally (offline). See `research/codeql_host_capability.md`.

## What was deliberately NOT validated here
- No CodeQL database was built (minutes/GB — deferred to the Stage-2 leaf / D1
  smoke run, as instructed).
- The hand-authored driver `_e2e_run/drive_reachability.py` has no unit oracle
  (it is wiring); its imports were smoke-checked clean against the shim.
