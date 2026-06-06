---
dependencies:
  - "ngv2-artifact-contract"
interfaces: "from ngv2.contracts import PoC, LiveTestReport (PoC has attribute finding_id; LiveTestReport(poc_finding_id:str, verdict:str, exit_code, stdout:str, stderr:str, duration_ms:int) constructed positionally); class DetonationChamber: __init__(self, success_marker: str = 'VULNERABLE'); detonate(self, poc, target_spec, runner) -> LiveTestReport."
working_dir: "/home/xnihil0zer0/NobleGreedv2"
---

# Title

ngv2 detonation chamber: deterministic PoC orchestration over injected runner

# Scope

Build NEW file ngv2/detonation.py: deterministic ORCHESTRATION of a PoC detonation over an INJECTED runner (the exploit is data; no real subprocess/network), stdlib only. Define class DetonationChamber with __init__(self, success_marker: str = 'VULNERABLE') storing self.success_marker. Define detonate(self, poc, target_spec, runner) -> LiveTestReport: call runner(poc, target_spec) inside try/except; on ANY exception return LiveTestReport(poc.finding_id, 'error', None, '', repr(exc), 0). On success unpack (exit_code, stdout, stderr, duration_ms); verdict is 'confirmed' if exit_code == 0 and self.success_marker in stdout; elif exit_code not in (0, None) -> 'refuted'; else 'inconclusive'. Return LiveTestReport(poc.finding_id, verdict, exit_code, stdout, stderr, duration_ms). MUST import 'from ngv2.contracts import PoC, LiveTestReport'; do NOT redefine them. IMPL-ONLY: oracle tests/test_detonation.py is already committed. Verification: python -m pytest tests/test_detonation.py -q.

# Non-Goals

Do NOT author, create, or modify ANY test file (tests/test_detonation.py is already committed); emit NO test_authoring task. Do NOT redefine the PoC or LiveTestReport contract dataclasses — import them from ngv2.contracts. Do NOT use eval, exec, or __import__. Do NOT run a real subprocess or network; the runner is injected and treated as data. Do NOT add fields, methods, or symbols beyond those specified, and do NOT change field names or order. Do NOT add I/O, file access, globals, or randomness; stdlib only (plus the ngv2.contracts import). Do NOT collapse modules or build the state machine here.

# Inputs

The external NobleGreedv2 repo at working_dir /home/xnihil0zer0/NobleGreedv2, with committed oracle tests/test_detonation.py and the ngv2/ package. Consumes sibling ngv2-artifact-contract: imports PoC and LiveTestReport from ngv2.contracts. PoC exposes attribute finding_id. LiveTestReport is constructed positionally as LiveTestReport(poc_finding_id, verdict, exit_code, stdout, stderr, duration_ms), with to_dict()/from_dict() exactly as produced by ngv2-artifact-contract.

# Deliverables

NEW file ngv2/detonation.py exposing class DetonationChamber with __init__(self, success_marker: str = 'VULNERABLE') storing self.success_marker, and detonate(self, poc, target_spec, runner) -> LiveTestReport implementing the deterministic verdict mapping: exception -> LiveTestReport(poc.finding_id, 'error', None, '', repr(exc), 0); success unpacks (exit_code, stdout, stderr, duration_ms); 'confirmed' if exit_code == 0 and success_marker in stdout; elif exit_code not in (0, None) -> 'refuted'; else 'inconclusive'; returning LiveTestReport(poc.finding_id, verdict, exit_code, stdout, stderr, duration_ms). Imports PoC, LiveTestReport from ngv2.contracts. Verified by the committed tests/test_detonation.py.
