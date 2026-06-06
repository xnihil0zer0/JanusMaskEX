---
interfaces: "from ngv2.state_machine import HuntStateMachine; from ngv2.detonation import DetonationChamber; run_pipeline(handlers: dict, *, success_marker: str = 'VULNERABLE') -> dict  # {'phase': 'done', 'reports': [LiveTestReport.to_dict() in poc order], 'report': handlers['report'](sm.state, reports) or None}"
working_dir: "/home/xnihil0zer0/NobleGreedv2"
---

# Title

ngv2/pipeline.py — hunt->triage->poc->detonate->report->done orchestrator

# Scope

Build NEW file ngv2/pipeline.py: a pure, deterministic, stdlib-only, mock-testable orchestrator that drives a HuntStateMachine through hunt -> triage -> poc -> detonate -> report -> done over INJECTED phase handlers (callables); detonation runs through the injected runner via a DetonationChamber (no real subprocess/network). IMPL-ONLY (oracle tests/test_pipeline.py already committed). Must `from ngv2.state_machine import HuntStateMachine` and `from ngv2.detonation import DetonationChamber`. Expose `run_pipeline(handlers: dict, *, success_marker: str = 'VULNERABLE') -> dict`: (1) sm = HuntStateMachine(); (2) for each finding returned by handlers['hunt']() call sm.add_finding(f); (3) sm.transition('triage'); kept = handlers['triage'](list(sm.state.findings)); sm.state.findings = list(kept) (triage may DROP findings); (4) sm.transition('poc'); pocs = handlers['poc'](list(sm.state.findings)); (5) sm.transition('detonate'); chamber = DetonationChamber(success_marker=success_marker); for each poc in pocs compute chamber.detonate(poc, handlers.get('target_spec'), handlers['runner']) and collect the LiveTestReports in order; (6) sm.transition('report'); if 'report' in handlers call report = handlers['report'](sm.state, reports) else report = None; (7) sm.transition('done'); (8) return {'phase': sm.state.phase, 'reports': [r.to_dict() for r in reports], 'report': report}. An empty findings list still walks every transition to 'done' with reports == [].

# Non-Goals

Do NOT author, create, or modify any test file — tests/test_pipeline.py is already committed; emit NO test_authoring task. Do NOT run a real subprocess, open a socket, touch the network, or execute exploit code; the only 'execution' is calling the injected runner callable through DetonationChamber. Do NOT use eval, exec, or __import__. No I/O, file access, globals, or randomness; stdlib only. Do NOT redefine HuntStateMachine, DetonationChamber, or the substrate dataclasses — import HuntStateMachine from ngv2.state_machine and DetonationChamber from ngv2.detonation. Do NOT add public functions or symbols beyond run_pipeline; do NOT change its name, signature, dict keys, or return shape. Do NOT depend on or import any other Epic-2 child module (grounding, poc_runner, report) — handlers (including the report handler and runner) are injected by the caller.

# Inputs

The already-committed Epic-1 substrate modules, consumed via `from ngv2.state_machine import HuntStateMachine` and `from ngv2.detonation import DetonationChamber`. HuntStateMachine() exposes add_finding, transition(phase), and .state with .phase and .findings; PHASES = ('hunt','triage','poc','detonate','report','done'). DetonationChamber(success_marker='VULNERABLE').detonate(poc, target_spec, runner) -> LiveTestReport, where runner is an injected callable runner(poc, target_spec) -> (exit_code, stdout, stderr, duration_ms). The handlers dict supplies callables 'hunt'() -> findings, 'triage'(findings) -> kept, 'poc'(findings) -> pocs, 'runner' (the injected runner), optional 'target_spec', and optional 'report'(state, reports) -> object. Each LiveTestReport has .to_dict(). The committed oracle tests/test_pipeline.py pins behavior.

# Deliverables

NEW file ngv2/pipeline.py exposing `run_pipeline(handlers, *, success_marker='VULNERABLE') -> dict` that drives HuntStateMachine hunt->triage->poc->detonate->report->done over injected handlers, detonates each poc via DetonationChamber(success_marker=success_marker).detonate(poc, handlers.get('target_spec'), handlers['runner']) collecting LiveTestReports in poc order, calls handlers['report'](sm.state, reports) when present (else None), and returns {'phase': 'done', 'reports': [r.to_dict() for r in reports], 'report': report}; imports HuntStateMachine from ngv2.state_machine and DetonationChamber from ngv2.detonation. An empty findings list still reaches phase 'done' with reports == []. Verified by the committed tests/test_pipeline.py via `python -m pytest tests/test_pipeline.py -q`.
