---
interfaces: "edits ngv2/session_api.py SessionApi._classify(self, data, phase) -> str to add a phase->kind mapping"
working_dir: "/home/xnihil0zer0/NobleGreedv2"
---

# Title

ngv2/session_api.py — fix SessionApi._classify so a bare LiveTestReport submitted during the 'detonate' (and 'report') phase classifies as 'report', not 'finding'

# Scope

EDIT the EXISTING module ngv2/session_api.py in the external NobleGreedv2 repo (working_dir /home/xnihil0zer0/NobleGreedv2). The only behavioral change is inside the existing method `SessionApi._classify(self, data, phase) -> str`. Today `_classify` derives the contract kind purely by substring-matching the phase STRING against the tokens ('poc'/'exploit', 'report'/'live', 'find'); the pipeline phase name 'detonate' (one of ngv2.state_machine.PHASES = ('hunt','triage','poc','detonate','report','done')) contains NONE of those tokens, so a bare `LiveTestReport.to_dict()` (keys {poc_finding_id, verdict, exit_code, stdout, stderr, duration_ms} — no explicit discriminator key, no intersection with the report key-set {report_id, outcome, live_result}) submitted in the 'detonate' phase is misclassified as 'finding'; `Finding.from_dict` then raises "rebuild failed: 'id'" and the report is rejected, 422-ing the detonate→report transition. ADD an explicit phase→kind map consulted as part of `_classify`: 'hunt'→'finding', 'triage'→'finding', 'poc'→'poc', 'detonate'→'report', 'report'→'report'. The map must apply ONLY when the artifact carries no explicit discriminator key — an explicit key in ('artifact_type','kind','type','contract','_type','category') MUST still win (it is checked first and returns its own mapping). Preserve the existing token heuristic and the structural key-set fallback as the final fallback. Keep the module pure/deterministic, stdlib + ngv2 only; no other method, signature, or import changes. Verify GREEN with `python -m pytest tests/ngv2/test_session_api_classify_phase_wired.py -q`; working_dir is /home/xnihil0zer0/NobleGreedv2.

# Non-Goals

This is an EDIT and integration is out of scope: do NOT add integration/e2e tests. Do NOT author or modify any test — the oracle tests/ngv2/test_session_api_classify_phase_wired.py is committed and authoritative. Do NOT change the `_classify` signature `_classify(self, data, phase) -> str`. Do NOT change any other SessionApi method (submit_artifacts, _validate_artifact, _contract_for, transition, etc.), nor ngv2/contracts.py, ngv2/state_machine.py, ngv2/session_db.py, or any other module — edit ngv2/session_api.py ONLY. Do NOT let the phase→kind map override an explicit artifact discriminator key. No network, no wall-clock, no randomness, no third-party imports, no new module-level symbols beyond what `_classify` needs.

# Inputs

The committed authoritative oracle at tests/ngv2/test_session_api_classify_phase_wired.py (drives the live SessionApi over a real ngv2.session_db.SessionDB; asserts `_classify(report_dict,'detonate')=='report'`, that `submit_artifacts(sid,'detonate',[bare_report_dict])` returns exactly `{'ok':True,'accepted':1,'rejected':[]}`, the same for phase 'report', that an explicit `artifact_type='finding'` key still classifies 'finding' even in the 'detonate' phase, and that the existing 'poc'/'hunt' phase behavior is preserved). The current ngv2/session_api.py (the `_classify` method body is the only thing to change — read it for the existing discriminator-key scan, token heuristic, and key-set fallback to preserve). ngv2/state_machine.py PHASES and ngv2/contracts.py LiveTestReport/Finding/PoC (read-only references for the mapping and the bare-report key set — do NOT modify). stdlib + ngv2 only.

# Deliverables

Edited ngv2/session_api.py whose `SessionApi._classify(self, data, phase) -> str` consults an explicit phase→kind map ('hunt'/'triage'→'finding', 'poc'→'poc', 'detonate'/'report'→'report') so a bare LiveTestReport submitted during the 'detonate' or 'report' phase classifies as 'report' and is accepted, while an explicit artifact discriminator key still wins and all previously-correct classifications are preserved. Verified GREEN by `python -m pytest tests/ngv2/test_session_api_classify_phase_wired.py -q`.
