---
interfaces: "from ngv2.contracts import Finding, SEVERITIES; normalize_severity(raw: str) -> str; parse_semgrep(report: dict, target: str) -> list[Finding]"
working_dir: "/home/xnihil0zer0/NobleGreedv2"
---

# Title

ngv2/grounding.py — semgrep-shaped report -> Finding adapter

# Scope

Build NEW file ngv2/grounding.py: a pure, deterministic, stdlib-only adapter that normalizes a semgrep-shaped static-analysis JSON report (passed in as a dict; NO tool is invoked) into ngv2.contracts.Finding objects. IMPL-ONLY (the oracle tests/test_grounding.py is already committed). Must `from ngv2.contracts import Finding, SEVERITIES`. Expose `normalize_severity(raw: str) -> str`: case-insensitive map CRITICAL->'critical', ERROR->'high', WARNING->'medium', INFO->'low', any unknown -> safe default 'low'; the returned value is ALWAYS a member of SEVERITIES. Expose `parse_semgrep(report: dict, target: str) -> list[Finding]`: read report.get('results', []); for each result at 0-based index i build a Finding with id=f"{result['check_id']}-{i}", target=target, category= the first CWE in result['extra']['metadata']['cwe'] if that list is present and non-empty else result['check_id'] (always a non-empty str, accessed via .get defensively so a missing metadata/cwe falls back to check_id without raising), severity=normalize_severity(result['extra']['severity']), title=result['extra']['message'], description=result['extra']['message'], evidence=[f"{result['path']}:{result['start']['line']}-{result['end']['line']}"]. Every returned Finding must satisfy Finding.validate(). An empty or missing results list returns [].

# Non-Goals

Do NOT author, create, or modify any test file — tests/test_grounding.py is already committed; emit NO test_authoring task. Do NOT invoke any static-analysis tool, run a subprocess, open a socket, touch the network, or do any I/O/file access. Do NOT use eval, exec, or __import__. No globals or randomness; stdlib only. Do NOT redefine Finding or SEVERITIES — import them from ngv2.contracts. Do NOT add fields, public functions, or symbols beyond normalize_severity and parse_semgrep; do NOT change their names, signatures, or return shapes. Do NOT depend on or import any other Epic-2 child module (poc_runner, report, pipeline).

# Inputs

The already-committed Epic-1 substrate module ngv2.contracts, consumed via `from ngv2.contracts import Finding, SEVERITIES`. Finding(id, target, category, severity, title, description, evidence=[]) has to_dict(), classmethod from_dict(d), and validate(). SEVERITIES = ('low','medium','high','critical'). The semgrep-shaped input is a dict with shape report['results'] -> list of results, each result having keys 'check_id', 'path', 'start'['line'], 'end'['line'], and 'extra' with 'severity', 'message', and optional 'metadata'['cwe'] (a list). The committed oracle tests/test_grounding.py pins behavior.

# Deliverables

NEW file ngv2/grounding.py exposing `normalize_severity(raw) -> str` (case-insensitive CRITICAL->'critical', ERROR->'high', WARNING->'medium', INFO->'low', unknown->'low'; result always in SEVERITIES) and `parse_semgrep(report, target) -> list[Finding]` as specified, importing `Finding, SEVERITIES` from ngv2.contracts. Verified by the committed tests/test_grounding.py via `python -m pytest tests/test_grounding.py -q`.
