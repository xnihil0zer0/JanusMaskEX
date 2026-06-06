---
epic: true
working_dir: "/home/xnihil0zer0/NobleGreedv2"
---

# Title

NobleGreedv2 Epic-1: substrate beachhead — artifact contract, state machine, detonation chamber.

# Scope

Decompose this epic into EXACTLY THREE independent child briefs that build the
deterministic substrate of NobleGreedv2 into the external repo (its own git +
venv). All three are pure, deterministic, stdlib-only Python modules under the
`ngv2/` package, each pinned by a HAND-AUTHORED ORACLE THAT IS ALREADY COMMITTED
to the NobleGreedv2 repo — so every child is IMPL-ONLY (it must NOT author tests).
Each child is a NEW single module file submitted WHOLE-FILE.

Produce these three children with these exact slugs and contracts:

## Child 1 — slug `ngv2-artifact-contract` (L0, no dependencies)
Builds NEW file `ngv2/contracts.py`. Pure dataclasses + JSON dict (de)serialization
+ validation, importing only `dataclasses`/`typing` (no I/O, globals, randomness).
- Module constants: `SEVERITIES = ('low','medium','high','critical')` and
  `VERDICTS = ('confirmed','refuted','error','inconclusive')`.
- `@dataclass Finding` with fields in order: `id:str, target:str, category:str,
  severity:str, title:str, description:str, evidence:list` (evidence defaults to
  an empty list via `field(default_factory=list)`).
- `@dataclass PoC` with fields: `finding_id:str, language:str, code:str, entrypoint:str`.
- `@dataclass LiveTestReport` with fields: `poc_finding_id:str, verdict:str,
  exit_code` (int or None)`, stdout:str, stderr:str, duration_ms:int`.
- Each class has `to_dict() -> dict` keyed EXACTLY by its field names, a
  classmethod `from_dict(d)` reconstructing an equal instance (Finding.from_dict
  defaults evidence to `[]` when the key is absent), and `validate() -> None`.
- `Finding.validate`: raise `ValueError` if severity not in SEVERITIES, or if any
  of id/target/category/title is not a non-empty str. `PoC.validate`: raise
  ValueError if any of the four fields is not a non-empty str. `LiveTestReport.validate`:
  raise ValueError if verdict not in VERDICTS, or duration_ms < 0, or poc_finding_id
  is not a non-empty str (exit_code may be int or None).
- Dataclasses use default `__eq__` so `from_dict(to_dict(x)) == x`.
- Verification: `python -m pytest tests/test_contracts.py -q` (the oracle is
  already committed in the repo).

## Child 2 — slug `ngv2-state-machine` (L1, depends on `ngv2-artifact-contract`)
Builds NEW file `ngv2/state_machine.py`. A deterministic
hunt->triage->poc->detonate->report->done phase machine with a serializable state.
- `PHASES = ('hunt','triage','poc','detonate','report','done')`.
- `ALLOWED_TRANSITIONS: dict[str, tuple[str,...]] = {'hunt':('triage','done'),
  'triage':('poc','done'), 'poc':('detonate','done'), 'detonate':('report','done'),
  'report':('done',), 'done':()}`.
- `@dataclass HuntState`: `phase:str='hunt'`; `findings:list = field(default_factory=list)`.
- `class HuntStateMachine`: `__init__(self, state: HuntState | None = None)` sets
  `self.state = state or HuntState()`; `can_transition(self, to) -> bool` returns
  `to in ALLOWED_TRANSITIONS.get(self.state.phase, ())`; `transition(self, to)`
  raises ValueError if not can_transition else sets `self.state.phase = to`;
  `add_finding(self, finding)` appends to `self.state.findings`;
  `to_dict(self) -> {'phase': self.state.phase, 'findings': [f.to_dict() for f in
  self.state.findings]}`; classmethod `from_dict(cls, d) -> cls(HuntState(
  phase=d['phase'], findings=[Finding.from_dict(x) for x in d.get('findings', [])]))`.
- MUST import `from ngv2.contracts import Finding` (the dependency edge). Do NOT
  redefine Finding.
- Verification: `python -m pytest tests/test_state_machine.py -q` (oracle committed).

## Child 3 — slug `ngv2-detonation-chamber` (L1, depends on `ngv2-artifact-contract`)
Builds NEW file `ngv2/detonation.py`. Deterministic ORCHESTRATION of a PoC
detonation over an INJECTED runner (the exploit is data; no real subprocess/network).
- `class DetonationChamber` with `__init__(self, success_marker: str = 'VULNERABLE')`
  storing `self.success_marker`.
- `detonate(self, poc, target_spec, runner) -> LiveTestReport`. Call
  `runner(poc, target_spec)` inside try/except; on ANY exception return
  `LiveTestReport(poc.finding_id, 'error', None, '', repr(exc), 0)`. On success
  unpack `(exit_code, stdout, stderr, duration_ms)`; verdict is `'confirmed'` if
  `exit_code == 0 and self.success_marker in stdout`; elif `exit_code not in (0, None)`
  -> `'refuted'`; else `'inconclusive'`. Return
  `LiveTestReport(poc.finding_id, verdict, exit_code, stdout, stderr, duration_ms)`.
- MUST import `from ngv2.contracts import PoC, LiveTestReport`. Do NOT redefine them.
- Verification: `python -m pytest tests/test_detonation.py -q` (oracle committed).

# Non-Goals

- Do NOT author, create, or modify ANY test file. The three oracles
  (`tests/test_contracts.py`, `tests/test_state_machine.py`,
  `tests/test_detonation.py`) are ALREADY COMMITTED in the NobleGreedv2 repo;
  every child is IMPL-ONLY and must emit NO `test_authoring` task. Each child's
  verification_command runs ONLY its own already-committed oracle.
- Do NOT use eval, exec, or `__import__`.
- Do NOT add fields, methods, or symbols beyond those specified, and do NOT change
  field names or order.
- Do NOT add I/O, file access, network, globals, or randomness; stdlib only
  (`dataclasses`/`typing`).
- Do NOT collapse the three modules into one, and do NOT add a fourth child.
- Children 2 and 3 must NOT redefine the contract dataclasses — they import them
  from `ngv2.contracts`.

# Inputs

- The external NobleGreedv2 repo at the epic `working_dir`
  (`/home/xnihil0zer0/NobleGreedv2`), which already contains the committed oracles
  `tests/test_contracts.py`, `tests/test_state_machine.py`, `tests/test_detonation.py`
  and an empty `ngv2/` package to fill.
- Child 2 and Child 3 consume `ngv2.contracts`: `Finding` (child 2), and
  `PoC`/`LiveTestReport` (child 3), each with `to_dict()`/`from_dict()` exactly as
  produced by Child 1.

# Deliverables

- Child `ngv2-artifact-contract` produces NEW `ngv2/contracts.py` exposing
  `SEVERITIES`, `VERDICTS`, and dataclasses `Finding`, `PoC`, `LiveTestReport`,
  each with `to_dict() -> dict`, classmethod `from_dict(d)`, and `validate() -> None`
  as specified above. Verified by the committed `tests/test_contracts.py`.
- Child `ngv2-state-machine` produces NEW `ngv2/state_machine.py` exposing
  `PHASES`, `ALLOWED_TRANSITIONS`, `HuntState`, and `HuntStateMachine`
  (`can_transition`/`transition`/`add_finding`/`to_dict`/classmethod `from_dict`),
  importing `Finding` from `ngv2.contracts`. Verified by `tests/test_state_machine.py`.
- Child `ngv2-detonation-chamber` produces NEW `ngv2/detonation.py` exposing
  `DetonationChamber` with `detonate(self, poc, target_spec, runner) -> LiveTestReport`
  and the deterministic verdict mapping above, importing `PoC, LiveTestReport`
  from `ngv2.contracts`. Verified by `tests/test_detonation.py`.
