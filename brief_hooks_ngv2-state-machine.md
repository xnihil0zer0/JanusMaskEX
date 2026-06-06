---
dependencies:
  - "ngv2-artifact-contract"
interfaces: "from ngv2.contracts import Finding (Finding.from_dict(d) -> Finding, Finding.to_dict() -> dict keyed exactly by field names); PHASES = ('hunt','triage','poc','detonate','report','done'); ALLOWED_TRANSITIONS: dict[str, tuple[str,...]] = {'hunt':('triage','done'),'triage':('poc','done'),'poc':('detonate','done'),'detonate':('report','done'),'report':('done',),'done':()}; @dataclass HuntState(phase:str='hunt', findings:list=field(default_factory=list)); class HuntStateMachine: __init__(self, state: HuntState | None = None); can_transition(self, to) -> bool; transition(self, to); add_finding(self, finding); to_dict(self) -> dict; classmethod from_dict(cls, d)."
working_dir: "/home/xnihil0zer0/NobleGreedv2"
---

# Title

ngv2 state machine: deterministic hunt phase machine over Finding

# Scope

Build NEW file ngv2/state_machine.py: a deterministic hunt->triage->poc->detonate->report->done phase machine with serializable state, stdlib only (dataclasses/typing). Define PHASES = ('hunt','triage','poc','detonate','report','done') and ALLOWED_TRANSITIONS: dict[str, tuple[str,...]] = {'hunt':('triage','done'), 'triage':('poc','done'), 'poc':('detonate','done'), 'detonate':('report','done'), 'report':('done',), 'done':()}. Define @dataclass HuntState with phase:str='hunt' and findings:list = field(default_factory=list). Define class HuntStateMachine: __init__(self, state: HuntState | None = None) sets self.state = state or HuntState(); can_transition(self, to) -> bool returns to in ALLOWED_TRANSITIONS.get(self.state.phase, ()); transition(self, to) raises ValueError if not can_transition else sets self.state.phase = to; add_finding(self, finding) appends to self.state.findings; to_dict(self) returns {'phase': self.state.phase, 'findings': [f.to_dict() for f in self.state.findings]}; classmethod from_dict(cls, d) returns cls(HuntState(phase=d['phase'], findings=[Finding.from_dict(x) for x in d.get('findings', [])])). MUST import 'from ngv2.contracts import Finding' (the dependency edge); do NOT redefine Finding. IMPL-ONLY: oracle tests/test_state_machine.py is already committed. Verification: python -m pytest tests/test_state_machine.py -q.

# Non-Goals

Do NOT author, create, or modify ANY test file (tests/test_state_machine.py is already committed); emit NO test_authoring task. Do NOT redefine the Finding contract dataclass — import it from ngv2.contracts. Do NOT use eval, exec, or __import__. Do NOT add fields, methods, or symbols beyond those specified, and do NOT change field names or order. Do NOT add I/O, file access, network, globals, or randomness; stdlib only (dataclasses/typing plus the ngv2.contracts import). Do NOT collapse modules or build the detonation chamber here.

# Inputs

The external NobleGreedv2 repo at working_dir /home/xnihil0zer0/NobleGreedv2, with committed oracle tests/test_state_machine.py and the ngv2/ package. Consumes sibling ngv2-artifact-contract: imports Finding from ngv2.contracts, a dataclass with classmethod from_dict(d) -> Finding and to_dict() -> dict keyed exactly by its field names (id, target, category, severity, title, description, evidence), exactly as produced by ngv2-artifact-contract.

# Deliverables

NEW file ngv2/state_machine.py exposing PHASES = ('hunt','triage','poc','detonate','report','done'); ALLOWED_TRANSITIONS: dict[str, tuple[str,...]] = {'hunt':('triage','done'), 'triage':('poc','done'), 'poc':('detonate','done'), 'detonate':('report','done'), 'report':('done',), 'done':()}; @dataclass HuntState(phase:str='hunt', findings:list=field(default_factory=list)); class HuntStateMachine with __init__(self, state: HuntState | None = None), can_transition(self, to) -> bool, transition(self, to), add_finding(self, finding), to_dict(self) -> dict, and classmethod from_dict(cls, d). Imports Finding from ngv2.contracts. Verified by the committed tests/test_state_machine.py.
