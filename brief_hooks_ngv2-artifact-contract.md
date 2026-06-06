---
interfaces: "SEVERITIES = ('low','medium','high','critical'); VERDICTS = ('confirmed','refuted','error','inconclusive'); @dataclass Finding(id:str, target:str, category:str, severity:str, title:str, description:str, evidence:list=field(default_factory=list)) with to_dict()->dict, classmethod from_dict(d)->Finding, validate()->None; @dataclass PoC(finding_id:str, language:str, code:str, entrypoint:str) with to_dict()->dict, classmethod from_dict(d)->PoC, validate()->None; @dataclass LiveTestReport(poc_finding_id:str, verdict:str, exit_code, stdout:str, stderr:str, duration_ms:int) with to_dict()->dict, classmethod from_dict(d)->LiveTestReport, validate()->None."
working_dir: "/home/xnihil0zer0/NobleGreedv2"
---

# Title

ngv2 artifact contract: Finding / PoC / LiveTestReport dataclasses

# Scope

Build NEW file ngv2/contracts.py: pure, deterministic, stdlib-only (dataclasses/typing only). Define module constants SEVERITIES = ('low','medium','high','critical') and VERDICTS = ('confirmed','refuted','error','inconclusive'). Define three dataclasses using default __eq__ so that from_dict(to_dict(x)) == x. Finding has fields IN ORDER: id:str, target:str, category:str, severity:str, title:str, description:str, evidence:list where evidence defaults to an empty list via field(default_factory=list). PoC has fields: finding_id:str, language:str, code:str, entrypoint:str. LiveTestReport has fields: poc_finding_id:str, verdict:str, exit_code (int or None), stdout:str, stderr:str, duration_ms:int. Each class provides to_dict() -> dict keyed EXACTLY by its field names, a classmethod from_dict(d) reconstructing an equal instance (Finding.from_dict defaults evidence to [] when the key is absent), and validate() -> None. Finding.validate raises ValueError if severity not in SEVERITIES, or if any of id/target/category/title is not a non-empty str. PoC.validate raises ValueError if any of the four fields is not a non-empty str. LiveTestReport.validate raises ValueError if verdict not in VERDICTS, or duration_ms < 0, or poc_finding_id is not a non-empty str (exit_code may be int or None). IMPL-ONLY: the oracle tests/test_contracts.py is already committed. Verification: python -m pytest tests/test_contracts.py -q.

# Non-Goals

Do NOT author, create, or modify ANY test file (tests/test_contracts.py is already committed); emit NO test_authoring task. Do NOT use eval, exec, or __import__. Do NOT add fields, methods, or symbols beyond those specified, and do NOT change field names or order. Do NOT add I/O, file access, network, globals, or randomness; import only dataclasses/typing. Do NOT define the state machine or detonation chamber here, and do NOT collapse modules.

# Inputs

The external NobleGreedv2 repo at working_dir /home/xnihil0zer0/NobleGreedv2, which already contains the committed oracle tests/test_contracts.py and an empty ngv2/ package to fill. No sibling outputs are consumed (this is the L0 root).

# Deliverables

NEW file ngv2/contracts.py exposing module constants SEVERITIES = ('low','medium','high','critical') and VERDICTS = ('confirmed','refuted','error','inconclusive'); dataclass Finding(id:str, target:str, category:str, severity:str, title:str, description:str, evidence:list=field(default_factory=list)); dataclass PoC(finding_id:str, language:str, code:str, entrypoint:str); dataclass LiveTestReport(poc_finding_id:str, verdict:str, exit_code, stdout:str, stderr:str, duration_ms:int). Each class exposes to_dict() -> dict (keyed exactly by field names), classmethod from_dict(d) (Finding.from_dict defaults evidence to [] when absent; from_dict(to_dict(x)) == x via default __eq__), and validate() -> None with the specified ValueError rules. Verified by the committed tests/test_contracts.py.
