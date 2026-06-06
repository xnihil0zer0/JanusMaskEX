---
interfaces: "from ngv2.contracts import PoC; RUNNER_RESULT_FIELDS = ('exit_code', 'stdout', 'stderr', 'duration_ms'); make_mock_runner(exit_code: int = 0, stdout: str = '', stderr: str = '', duration_ms: int = 0) -> Callable[[poc, target_spec], tuple]; make_scripted_runner(script: dict) -> Callable[[poc, target_spec], tuple]  # runner returns (exit_code, stdout, stderr, duration_ms); unmapped finding_id -> (None, '', '', 0)"
working_dir: "/home/xnihil0zer0/NobleGreedv2"
---

# Title

ngv2/poc_runner.py — deterministic runner-adapter factories

# Scope

Build NEW file ngv2/poc_runner.py: the deterministic runner-adapter contract consumed by the DetonationChamber, plus deterministic mock/scripted runner factories for tests. The REAL subprocess/bwrap runner is NOT built here — runners are injected at NGv2 runtime. IMPL-ONLY (oracle tests/test_poc_runner.py already committed). Must `from ngv2.contracts import PoC` (documented runner input type). Expose module constant `RUNNER_RESULT_FIELDS = ('exit_code', 'stdout', 'stderr', 'duration_ms')` (the exact order DetonationChamber unpacks). Expose `make_mock_runner(exit_code: int = 0, stdout: str = '', stderr: str = '', duration_ms: int = 0)`: returns a callable runner(poc, target_spec) that ignores its arguments and returns the fixed tuple (exit_code, stdout, stderr, duration_ms). Expose `make_scripted_runner(script: dict)`: script maps a poc.finding_id (str) to a 4-tuple (exit_code, stdout, stderr, duration_ms); returns a callable runner(poc, target_spec) that looks up poc.finding_id in script and returns its tuple; for an UNMAPPED finding_id returns the deterministic default (None, '', '', 0) and never raises.

# Non-Goals

Do NOT author, create, or modify any test file — tests/test_poc_runner.py is already committed; emit NO test_authoring task. Do NOT run a real subprocess, open a socket, touch the network, or execute exploit code; the only 'execution' is calling an injected callable. Do NOT use eval, exec, or __import__. No I/O, file access, globals, or randomness; stdlib only. Do NOT redefine PoC or any substrate dataclass — import PoC from ngv2.contracts. Do NOT add fields, public functions, or symbols beyond RUNNER_RESULT_FIELDS, make_mock_runner, and make_scripted_runner; do NOT change their names, signatures, or return shapes. Do NOT depend on or import any other Epic-2 child module (grounding, report, pipeline).

# Inputs

The already-committed Epic-1 substrate module ngv2.contracts, consumed via `from ngv2.contracts import PoC`. PoC(finding_id, language, code, entrypoint) — only poc.finding_id is read by make_scripted_runner. The runner contract must match what DetonationChamber.detonate expects: an injected callable runner(poc, target_spec) -> (exit_code, stdout, stderr, duration_ms). The committed oracle tests/test_poc_runner.py pins behavior.

# Deliverables

NEW file ngv2/poc_runner.py exposing constant `RUNNER_RESULT_FIELDS = ('exit_code', 'stdout', 'stderr', 'duration_ms')`, `make_mock_runner(exit_code=0, stdout='', stderr='', duration_ms=0)` returning a callable runner(poc, target_spec) -> fixed (exit_code, stdout, stderr, duration_ms), and `make_scripted_runner(script)` returning a callable runner(poc, target_spec) that returns script[poc.finding_id] or the default (None, '', '', 0) for unmapped ids without raising; imports PoC from ngv2.contracts. Verified by the committed tests/test_poc_runner.py via `python -m pytest tests/test_poc_runner.py -q`.
