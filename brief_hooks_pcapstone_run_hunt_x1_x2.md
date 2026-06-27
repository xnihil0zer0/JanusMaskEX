---
slug: pcapstone_run_hunt_x1_x2
working_dir: "/home/xnihil0zer0/NobleGreedv2"
complexity_score: high
operator_decision_required: false
auto_approve_requested: true
required_task_ids:
  - pcapstone-health-guard-oracle
  - pcapstone-health-guard-impl
  - pcapstone-evidence-nonce-impl
  - pcapstone-run-hunt-x1-x2-oracle
---

# Title

P-CAPSTONE — close acceptance criteria X1 (autonomous nonce-bound `confirmed` through a
CONTINUOUS `run_hunt`) and X2 (safe-twin typed-terminal `refuted` at detonate) in the
NobleGreedv2 hunt engine. Two minimal engine fixes (A: health-probe path-entry guard;
B: thread the buried detonation nonce into evidence) + a committed CWE-78 twin fixture +
a `test_acceptance` oracle that drives the REAL continuous conductor over both twins
through the REAL bwrap jail, reaching `verdict=confirmed` (vuln, nonce in stdout ∧
fs-diff ∧ `ev['detonation_nonce']`, parked at `awaiting_submission`) and `verdict=refuted`
(safe twin, blocked at the typed terminal `detonation_evidence`).

This capstone is ALREADY PROVEN ACHIEVABLE in scratch (the X5 nonce-bound detonate is
live on HEAD; the offline `poc_writer` + jailed detonate were driven over this exact
fixture and reached confirmed/refuted — see Inputs §"Scratch evidence"). This brief lands
the minimal change set that makes that continuous traversal real on the committed tree.

# Scope

FOUR tasks in ONE flat, strictly serial plan (NOT an epic). Dep chain
1 -> 2 -> 3 -> 4. `required_task_ids` (frontmatter) lists all four in serial order.

- Task 1 `pcapstone-health-guard-oracle` (`test_authoring`, mutation_target
  `ngv2.health_producer`) — RED behavioral oracle for engine fix A. deps: [].
- Task 2 `pcapstone-health-guard-impl` (`io_adapter`, `ngv2/health_producer.py`) — engine
  fix A; turns task 1 GREEN. deps: [pcapstone-health-guard-oracle].
- Task 3 `pcapstone-evidence-nonce-impl` (`io_adapter`, `ngv2/conductor_seams.py`) —
  engine fix B; self-contained `python -c` smoke vcmd. deps: [pcapstone-health-guard-impl].
- Task 4 `pcapstone-run-hunt-x1-x2-oracle` (`test_acceptance`) — bundles the committed
  CWE-78 twin fixture (under `tests/`) + the X1/X2 acceptance test. THE TERMINAL
  RED-PAIR: RED before A+B+fixture land (the continuous run stalls at `health_probe`
  and `ev['detonation_nonce']` is `None`), GREEN after. deps:
  [pcapstone-evidence-nonce-impl].

EXTERNAL working_dir = `/home/xnihil0zer0/NobleGreedv2` (in external_roots.allow).
`ngv2/**` is EXTERNAL and NOT trust-core (NOT in `_NEVER_AUTO_APPROVE`; NOT
`harness_self_fix`): the two engine-fix impls are auto-approve-eligible
(`operator_decision_required: false`, `auto_approve_requested: true`) and need NO
operator decision file. RE-READ each target file before pinning patches — verify the
current line numbers; the line anchors below are from HEAD 53a97b1.

`_INITIAL_PHASE = 'detect'` is ALREADY landed (c7 env-FSM front-half); this capstone
builds on it. Do NOT re-author c7, the cP producers, the c1-c6 handlers, or the X5
detonate seam — they are landed; this leaf CALLS them.

# Non-Goals

- **integration**: this leaf IS the live-integration capstone; the literal word
  `integration` appears here AND in EVERY task's `non_goals` so the planner routes it
  correctly. OUT OF SCOPE: any integration with EXTERNAL corpus targets (`targets/*`),
  real-network provisioning, or host-network pip. The fixture is a hermetic, stdlib-only,
  in-repo CWE-78 twin (no real venv build, no network). NEVER point the oracle at
  `targets/*`.
- **HONESTY (REQUIRED).** This capstone exercises the OFFLINE LLM FLOOR (the deterministic
  no-creds production path: `pattern_scanner` for detection, `poc_writer.write_poc(client=
  None)` for the PoC) with the REAL jailed, per-run-CSPRNG-nonce-bound detonation as the
  TRUST ANCHOR (NEVER stubbed). It does NOT claim the fully-autonomous REAL-LLM
  hunt->poc path is closed — that is a documented FOLLOW-ON. SPECIFICALLY DEFERRED
  (state these in the oracle task's non_goals): (a) the LLM-driven `ngv2/workers/hunt.py`
  worker (it requires a live `llm_client` lead-generator and returns `[]` offline, so the
  offline hunt floor is `ngv2.pattern_scanner.scan_directory`, not the hunt worker);
  (b) the `pattern_scanner`-finding -> `poc_writer`-grounding-input adapter (the raw
  scanner finding lacks `evidence`/`sink_name`/`call_sites`/`category`, so the oracle
  bridges those minimal grounding fields — identical for both twins — into the finding
  before `write_poc`); (c) the genuinely-network-bound `ngv2.poc_repair_loop` (DISABLED:
  do NOT inject the `repair` seam). Do NOT overclaim full autonomy.
- Do NOT touch the X5 detonate seam (`ngv2/workers/_runner.py::_make_detonation_seam`,
  `ngv2/poc_runner_live.py`), the cP producers, the c1-c6 handlers, `fsm_evidence.py`,
  `transition_planner.py`, `gate_executor.py`, `run_hunt.py`, `stage_command_map.py`, or
  any `ngv2/workers/**` body. Fix A touches ONLY `ngv2/health_producer.py`; fix B touches
  ONLY the nested `build_evidence` closure in `ngv2/conductor_seams.py`.
- No clock/uuid/random/`os.urandom` in ANY oracle SOURCE (inject deterministic values).
  NOTE: the engine's `secrets`-based per-run nonce runs INSIDE the real code under test
  (the jailed detonate seam) — that is fine and REQUIRED; the ban is only on banned RNG
  in the oracle's own source.

# Inputs

LIVE FILES (working_dir `/home/xnihil0zer0/NobleGreedv2`, HEAD 53a97b1):

ENGINE FIX A — `ngv2/health_producer.py::produce_health_input` (~line 38; the guard
edit is at ~line 248-250).
- Blocker: the live `env_phase` health seam (`conductor_seams.py:393-394`) passes
  `entry_point = state.get('entry_point') or state.get('target')`. When the capstone
  drives `run_hunt` with `target_path = <fixture repo PATH>`, that entry_point is a
  filesystem PATH. In the jailed-run branch, `produce_health_input` UNCONDITIONALLY
  prepends `entry_point` to `modules_to_probe` (line ~248-250), so it runs
  `python -c "import /tmp/.../repo"` -> `SyntaxError` -> `genuine_import_error` ->
  `import_ok=False`, poisoning the result even though the discovered module (`svc`)
  imports clean. This stalls the continuous run at `health_probe`.
- THE FIX (verify against current code; the nested helper `is_valid_identifier(s)` is
  already defined at ~line 65, IN SCOPE at line 249):
  ```
  -    if entry_point:
  +    if entry_point and is_valid_identifier(entry_point):
           modules_to_probe.append(entry_point)
  ```
- RED on HEAD: `produce_health_input(entry_point=<repo_path>, is_service=False,
  repo_root=<repo with svc.py>, language='python')` -> `import_ok=False`,
  `classification='genuine_import_error'`. GREEN after: path entry_point ignored, only
  `svc` probed -> `import_ok=True`, `classification='clean'`. This is a GENERAL
  all-targets wiring bug (any path-shaped target), NOT fixture-specific.

ENGINE FIX B — the nested `build_evidence` closure inside `ngv2/conductor_seams.py::
build_default_seams` (the nonce block is at ~lines 181-190 on HEAD).
- Blocker: the REAL detonate worker buries the seam's per-run nonce at
  `report['raw_result']['nonce']` (CONFIRMED: `ngv2/workers/detonate.py::_build_report`
  + the committed X5 oracle `tests/ngv2/test_detonation_nonce_bound_confirm.py::
  test_detonation_nonce_persisted_in_evidence` asserts `art['report']['raw_result']
  ['nonce']`). But `build_evidence` reads `raw['nonce']` TOP-LEVEL only, so in the
  continuous run `ev['detonation_nonce']` stays `None`.
- THE FIX (verify against current lines 181-190; reproduce the rest of `build_evidence`
  VERBATIM):
  ```
           raw = ev.get('detonation_report_raw')
  +        raw_nonce = None
           if isinstance(raw, dict):
  -            if 'nonce' in raw:
  -                ev['detonation_nonce'] = raw['nonce']
  +            raw_nonce = raw.get('nonce')
  +            if raw_nonce is None and isinstance(raw.get('raw_result'), dict):
  +                raw_nonce = raw['raw_result'].get('nonce')
  +            if raw_nonce is not None:
  +                ev['detonation_nonce'] = raw_nonce
           if isinstance(raw, dict) and 'detonation_report' not in ev:
               ev['detonation_report'] = _gate_detonation(raw)
  -        if isinstance(raw, dict) and 'nonce' in raw and 'detonation_report' in ev:
  +        if isinstance(raw, dict) and raw_nonce is not None and 'detonation_report' in ev:
               det_rep = ev['detonation_report']
               if isinstance(det_rep, dict):
  -                det_rep['nonce'] = raw['nonce']
  +                det_rep['nonce'] = raw_nonce
  ```
- RED on HEAD (VERIFIED by scratch): a state with `evidence.detonation_report_raw =
  {'raw_result': {'nonce': 'jm...'}}` (no top-level nonce) -> `build_evidence(state)
  ['detonation_nonce']` is `None`. GREEN after: `== 'jm...'`. PRESERVE the top-level-nonce
  path (read `raw.get('nonce')` FIRST) so the committed X5 nonce oracle does NOT regress.

KEY EXISTING TESTS to MIRROR (read them; do NOT edit them):
- `tests/ngv2/test_c7_complete_fsm_live.py` — the continuous-`run_hunt` drive harness:
  hermetic `tmp_path` git repo + build files + `.python-version`, `monkeypatch.
  syspath_prepend(repo)`, `mock_which` so `bwrap -> /usr/bin/bwrap`, `mock_install_fn`
  (smoke_import_ok True, no host pip), the env-FSM front-half traversal + `advance_gate`
  hash checks, and the safe-twin pattern. (Its safe twin refuses EARLY at
  `reachability_probe`; the capstone's X2 refuses DEEPER at `detonate`.)
- `tests/ngv2/test_p11_crossprocess_middle_phase.py::test_fsm_traverses_middle_phases_
  without_respawn` — the `run_conductor_step` loop with `seams['spawn']=fake_spawn` +
  `seams['harvest']=fake_harvest` returning per-phase HARVEST-ROLLUP-shaped artifacts
  (`{'kind':'report','data':{'phase':P,'n_artifacts':1,'artifacts':[{'filename':...,
  'content':<json>,'phase':P}]}}`). The capstone REPLACES the FAKE harvest with a
  REAL-worker offline-floor harvest for hunt/poc/detonate.
- `tests/ngv2/test_detonation_nonce_bound_confirm.py` — the X5 trust anchor:
  `@pytest.mark.skipif(not bwrap_available())`, `_make_detonation_seam`, `<<NONCE>>` PoC,
  `verdict=='confirmed'`/`'refuted'`, and `art['report']['raw_result']['nonce']`.

OFFLINE FLOOR FACTS (read the modules):
- `ngv2.pattern_scanner.scan_directory(repo) -> {'findings':[...], ...}` is the REAL
  deterministic no-creds hunt floor. SCRATCH-VERIFIED: over BOTH twins it emits ONE
  `command_injection` finding (`{'id':'command_injection','file':'svc.py','line':5,
  'cwe':'CWE-78',...}`) — identical shape for both (the safe twin's `subprocess.run` is
  flagged too), so the floor is identical and the safe twin REACHES detonate.
- `ngv2.poc_writer.write_poc(finding, target, 'python', client=None)` is the REAL
  deterministic no-creds PoC floor. SCRATCH-VERIFIED: given a grounding-ready finding
  (add `category='command_injection'` + `evidence=['svc.py:5']` to the raw scanner
  finding; `target` carries `repo_root=<repo>`), the CWE-78 floor (`_py_command_
  injection`) renders a PoC that `from svc import lookup_host` AND carries `<<NONCE>>`
  (in `echo VULNERABLE <<NONCE>>` and `: > pwned_marker_<<NONCE>>`), marker `VULNERABLE`,
  fs_signature `pwned_marker`. (Without the `category`/`evidence` enrichment, write_poc
  raises `KeyError 'cannot resolve a CWE template'` — that adapter gap is a deferred
  Non-Goal.)
- `ngv2.workers.detonate.run_stage(context, {'detonation': _make_detonation_seam()})` is
  the REAL detonate worker; `context['parked_package'] = {'poc': <PoC>,
  'expected_fs_signature':'pwned_marker','success_marker':'VULNERABLE'}`. The seam
  substitutes `<<NONCE>>` with a fresh `secrets`-based per-run nonce and confirms iff the
  nonce appears in stdout/stderr AND fs-diff.
- `ngv2.workers.poc.run_stage(context, {'poc_writer': write_poc})` (NO `repair`, NO
  `llm`) is the REAL poc worker over the offline writer floor; `context['prior_findings']
  = [<enriched finding>]`, `context['target']`/`context['repo']` carry the repo.

SCRATCH EVIDENCE (the maximally-real-offline composition was driven by the brief author;
this is why the oracle uses the REAL `poc_writer`, NOT a hand-grounded floor PoC):
- `write_poc(client=None)` over `vuln/svc.py` -> PoC: `from svc import lookup_host`,
  `<<NONCE>>` present. (real grounding via AST over svc.py)
- VULN twin: real write_poc -> `_make_detonation_seam` (real bwrap) -> `verdict=confirmed`,
  `success=True`, `reproduced=True`, the per-run CSPRNG nonce (`jm...`, 34 chars) IN
  stdout AND IN fs-diff.
- SAFE twin (IDENTICAL real write_poc floor; only svc.py differs — `subprocess.run(
  ["getent","hosts",host])`, shell=False, injection inert): `verdict=refuted`,
  `success=False`, `reproduced=False`, nonce NOT reflected.
- Real `detonate.run_stage` report has NO top-level `nonce` (it is at
  `report['raw_result']['nonce']`), and on HEAD `persist(detonate)` + `build_evidence`
  yields `ev['detonation_nonce']=None` (RED — exactly what fix B closes).

INTERPRETER: `.python-version` is pinned to `3.10` because `/usr/bin/python3.10` EXISTS
on the host (verified) and the bwrap detonation jail `--ro-bind / /` exposes it; the
stdlib-only `svc.py` imports clean under 3.10. Use `3.10`.

# Deliverables

Author EXACTLY FOUR tasks, ONE plan, strictly serial. Every task's `non_goals` MUST
contain the literal word `integration`. All `working_dir = /home/xnihil0zer0/
NobleGreedv2`. Engine-fix impls: `meta_task_type: io_adapter`, `priority: high`, ONE
file, a single `__JANUSMASK_PATCHES__` SYMBOL recipe (one entry per modified symbol;
verbatim reproduction apart from the noted change), OMIT `mutation_target`, NO operator
decision file. `ngv2/**` is external — NOT `harness_self_fix`, NOT trust-core.

## TASK 1 — `pcapstone-health-guard-oracle` (`test_authoring`; mutation_target `ngv2.health_producer`)
- `files_touched: ["tests/ngv2/test_pcapstone_health_guard.py"]`. deps: `[]`.
  Ordinary Python test source (NOT a manifest); import the generated module via
  `importlib` (exec/eval/`__import__` are AST-banned).
- A RED behavioral oracle for engine fix A. It MUST be NON-VACUOUS under the mutation
  gate (kill mutants of `ngv2.health_producer`) AND prove the fix RED->GREEN, and MUST
  stay runnable WITHOUT bwrap (the mutation gate may lack bwrap). Required assertions
  (derive expectations from the REAL `produce_health_input` behavior; do NOT paste impl
  source, do NOT assert a frozen body literal):
  1. FIX-A GUARD (bwrap-FREE, the load-bearing RED case). Monkeypatch
     `ngv2.poc_runner_live.build_detonation_jail_argv` to a no-op (`lambda cmd, **kw:
     list(cmd)`) — `produce_health_input` imports it at call time, so the patch lands —
     and inject `sandbox_run_fn` that RECORDS each `argv` and returns `(0, '', '')`.
     Build a `tmp_path` repo with `svc.py` (`import os\n`). Call
     `produce_health_input(entry_point=str(tmp_repo), is_service=False,
     repo_root=str(tmp_repo), language='python', sandbox_run_fn=recorder)`. Assert that
     the RECORDED probe commands include `import svc` but DO NOT include
     `import <tmp_repo path>`. RED on HEAD (the path entry_point IS probed); GREEN after
     fix A (only `svc` is probed). This is bwrap-free, deterministic, and fix-A-specific.
  2. REAL-JAIL INTEGRATION (`@pytest.mark.skipif(not bwrap_available())`, mirror the X5
     oracle): real `produce_health_input(entry_point=str(tmp_repo), is_service=False,
     repo_root=str(tmp_repo), language='python')` over a `tmp_path` repo with `svc.py`
     -> assert `import_ok is True` and `classification == 'clean'` (GREEN after fix;
     RED on HEAD = `import_ok False`/`genuine_import_error`).
  3. regression (>= 2): (a) a VALID-identifier entry_point (e.g. `'svc'`) is STILL
     probed (the guard does not drop legal module names); (b) the non-jailed path
     (e.g. `language='node'` or `is_service=True` with an injected `import_fn`) is
     UNCHANGED by the fix.
  4. property/edge (>= 1): a path-shaped entry_point containing a dot (e.g. an absolute
     path) is rejected by the guard (NOT probed), while a legal dotted module name
     (`pkg.mod`) is accepted — exercise `is_valid_identifier`'s dotted-segment rule via
     observable probe membership.
- `verification_command` (bare, no `cd`):
  `python -m pytest tests/ngv2/test_pcapstone_health_guard.py -q`. `regression_tests >= 2`.

## TASK 2 — `pcapstone-health-guard-impl` (`io_adapter`; `ngv2/health_producer.py`)
- `files_touched: ["ngv2/health_producer.py"]`. deps:
  `["pcapstone-health-guard-oracle"]` (RED oracle first; this impl turns it GREEN —
  red-pair).
- A single `__JANUSMASK_PATCHES__` SYMBOL recipe, ONE entry `{'kind':'symbol',
  'name':'produce_health_input', 'code': r'''...'''}` reproducing `produce_health_input`
  VERBATIM except the one-line guard change above (`if entry_point:` ->
  `if entry_point and is_valid_identifier(entry_point):`). `produce_health_input` is a
  pre-existing top-level symbol — NO R-anchor. Do NOT emit a manifest.
- The fix is GENERAL (any path-shaped entry_point), driven by `is_valid_identifier`, NOT
  fixture-specific. OMIT `mutation_target`. Auto-approve-eligible; NO operator decision
  file.
- `verification_command` (bare): `python -m pytest tests/ngv2/test_pcapstone_health_guard.py -q`
  (the task-1 oracle, now GREEN). `regression_tests >= 2`.

## TASK 3 — `pcapstone-evidence-nonce-impl` (`io_adapter`; `ngv2/conductor_seams.py`)
- `files_touched: ["ngv2/conductor_seams.py"]`. deps:
  `["pcapstone-health-guard-impl"]`.
- A single `__JANUSMASK_PATCHES__` SYMBOL recipe targeting the NESTED `build_evidence`
  closure via the DOTTED name `{'kind':'symbol', 'name':'build_default_seams.
  build_evidence', 'code': r'''...'''}` (per the "patch a nested closure via DOTTED
  Enclosing.nested" rule — a 1-part bare `build_evidence` is rejected). Reproduce
  `build_evidence` VERBATIM apart from the fix B nonce-fallback diff above. (If the
  dotted-nested patch is not honored, FALL BACK to a single `build_default_seams` symbol
  patch carrying the whole function with `build_evidence` changed — verbatim apart from
  fix B.) Preserve the top-level-nonce path (no X5 regression). OMIT `mutation_target`.
  Auto-approve-eligible; NO operator decision file.
- `verification_command` — SELF-CONTAINED `python -c` smoke (no `.py`/`cd`/pytest),
  VERIFIED RED on HEAD by the brief author:
  `python -c "from ngv2.conductor_seams import build_default_seams as b; s=b('s',None,None,{}); be=s['build_evidence']; ev=be({'evidence':{'detonation_report_raw':{'raw_result':{'nonce':'jmTESTNONCE'}}}}); assert ev.get('detonation_nonce')=='jmTESTNONCE', ev.get('detonation_nonce')"`
  (RED on HEAD -> AssertionError None; GREEN after fix B). `regression_tests >= 2` (the
  impl test_spec, if any, covers: top-level-nonce path preserved; `raw_result.nonce`
  fallback threaded).

## TASK 4 — `pcapstone-run-hunt-x1-x2-oracle` (`test_acceptance`)
THE CAPSTONE / TERMINAL RED-PAIR. deps: `["pcapstone-evidence-nonce-impl"]`.
- `files_touched` — ALL UNDER `tests/` (so neither the wire-up `orphan_unwired` gate NOR
  the planner's `_split_multifile_module_tasks` multi-new-module split fires — both
  exclude `tests/**`; a non-`tests/` fixture path with two new `svc.py` modules WOULD be
  split and break `required_task_ids`):
  - `tests/ngv2/test_pcapstone_run_hunt_x1_x2.py`
  - `tests/ngv2/_pcapstone_fixtures/vuln/svc.py`
  - `tests/ngv2/_pcapstone_fixtures/vuln/.python-version`
  - `tests/ngv2/_pcapstone_fixtures/vuln/requirements.txt`
  - `tests/ngv2/_pcapstone_fixtures/safe/svc.py`
  - `tests/ngv2/_pcapstone_fixtures/safe/.python-version`
  - `tests/ngv2/_pcapstone_fixtures/safe/requirements.txt`
- Submission is a `__JANUSMASK_MANIFEST__` whole-file manifest carrying ALL of the above
  (the 6 fixture files + the test). FIXTURE CONTENT:
  - `vuln/svc.py`: `import os` then `def lookup_host(host):\n    return os.system("getent
    hosts " + host)` (the externally-influenced shell sink — CWE-78).
  - `safe/svc.py`: `import subprocess` then `def lookup_host(host):\n    return
    subprocess.run(["getent", "hosts", host], capture_output=True).returncode`
    (list-arg, shell=False — injection inert).
  - each `.python-version` = `3.10\n` (LOAD-BEARING: `.python-version` in
    PYTHON_BUILD_FILES sets language=python AND resolves `resolved_python_bin=
    /usr/bin/python3.10`).
  - each `requirements.txt` = a comment-only line (stdlib target -> provision installs
    nothing, no host pip).
- THE TEST (ordinary Python; importlib only; `@pytest.mark.skipif(not bwrap_available())`
  mirroring the X5 oracle): for EACH twin, copy
  `Path(__file__).parent/'_pcapstone_fixtures'/<twin>` into a `tmp_path` repo (so
  detonation side-effects never touch the committed tree), `git init`+commit it (a real
  `head_commit`; pinned==head), `monkeypatch.syspath_prepend(repo)`, `mock_which` so
  `bwrap -> /usr/bin/bwrap` (mirror c7), and DRIVE THE REAL CONTINUOUS conductor with
  `target_path = <repo PATH>` (NOT a bare module name — this is what exercises fix A at
  `health_probe`).
- DRIVE MECHANISM (choose either; both are "the REAL continuous run_hunt/run_conductor_
  step"): (i) build `seams = build_default_seams(session_id, db, None, ctx)` and drive
  `seams['run_conductor_step']` in a loop to a terminal step (mirror p11), OR (ii)
  `monkeypatch` `ngv2.conductor_seams.build_default_seams` to wrap the real seams and
  call `run_hunt(...)` (mirror c7's `mock_seams_and_git`). The ENV front-half
  (detect..baseline_capture) runs REAL via the live `env_phase` seam (this is where fix A
  is exercised — the path `entry_point` reaches `produce_health_input`). For the
  back-half, OVERRIDE `seams['spawn']` + `seams['harvest']` so each phase returns a
  HARVEST-ROLLUP-shaped artifact (the p11 shape) built from the OFFLINE FLOOR:
  - `hunt`: run REAL `ngv2.pattern_scanner.scan_directory(repo)`; take the
    `command_injection` finding, ENRICH it (the deferred scanner->grounding adapter,
    applied IDENTICALLY for BOTH twins) with ALL of:
    `category='command_injection'` + `evidence=['svc.py:5']` + `target='svc'` +
    `sink_name='os.system'` + `call_sites=['os.system("getent hosts " + host)']`.
    The `call_sites` value MUST be a LIST OF CODE-SNIPPET STRINGS (NEVER a list of
    dicts — `assess_sink_reachability(sink_name: str, call_sites: List[str])` hashes
    them; a dict raises `TypeError: unhashable type: 'dict'`), and the snippet MUST call
    the sink with a NON-CONSTANT arg (the `+ host` concatenation above). Do NOT add
    `expected_signature` — `build_evidence` derives it from `sink_name`
    (conductor_seams.py:159; VERIFIED: sink_name + string `call_sites` alone ->
    `expected_signature='os.system'` and the VULN twin advances detonate->novelty).
    WHY ALL FIVE (VERIFIED empirically): the `detonate` from-phase has THREE gates
    (`gate_executor.py:114`) — `detonation_evidence` (needs `detonation_report`),
    `sink_presence` (needs `target_source` + `expected_signature`), and
    `sink_reachability` (needs `sink_name` + `call_sites`). With only category/evidence/
    target, `sink_name`/`call_sites` stay unset and the VULN twin BLOCKS at
    detonate->novelty with `blocked_by=['sink_presence:missing_evidence',
    'sink_reachability:missing_evidence']` -> it NEVER reaches `awaiting_submission` ->
    X1 can never confirm. Emit the enriched finding as the hunt finding rollup so
    `persist` threads it into `prior_findings`. (NEVER stub the detection — it is the
    real scanner.)
  - NON-VACUITY INVARIANT (state this in the oracle task's non_goals/docstring): the
    sink bridge (`sink_name`/`call_sites`/`evidence`/`category`/`target`) is IDENTICAL
    for both twins, so the `sink_presence` and `sink_reachability` gates evaluate
    IDENTICALLY for both — ONLY `detonation_evidence` (the REAL bwrap-jailed detonation
    of the differing `svc.py`) differs between the twins. That is precisely what makes
    the safe-twin refutation GENUINE and non-vacuous: the structural gates are
    deliberately non-discriminating; the live jailed detonation is the sole arbiter.
  - `poc`: run REAL `ngv2.workers.poc.run_stage(poc_context, {'poc_writer': write_poc})`
    (NO `repair`, NO `llm`) -> REAL offline `write_poc` PoC (carries `<<NONCE>>`); emit
    its rollup so `persist` threads `parked_package['poc']`.
  - `detonate`: run REAL `ngv2.workers.detonate.run_stage(det_context, {'detonation':
    _make_detonation_seam()})` with `parked_package={'poc':<PoC>,'expected_fs_signature':
    'pwned_marker','success_marker':'VULNERABLE'}`; emit a detonate rollup whose `content`
    is the REAL worker report (carrying `report['raw_result']['nonce']`) so `persist`
    (detonate) sets `ev['detonation_report_raw']` and fix B's `build_evidence` threads
    `ev['detonation_nonce']`. THIS IS THE TRUST ANCHOR — NEVER stub the jail/verdict/nonce.
  - `triage`/`verify`/`novelty`/`report`: minimal deterministic pass-through rollups
    (`{"triage_result": true}` etc.) — NOT security-substantive for X1/X2; hand-injected.
VERDICT SOURCE (read the X1/X2 PASS/FAIL adjudication from the CONDUCTOR/GATE level, NOT
the raw detonate-worker `report['verdict']`): the worker report's TOP-LEVEL `verdict` is
`'success'`/`'failure'` (outcome), so do NOT assert against it. The nonce-bound
`'confirmed'`/`'refuted'` SEAM verdict is at `report['raw_result']['verdict']` (the X5
seam value); the CONDUCTOR-LEVEL X1/X2 outcome is the run trajectory — VULN ADVANCES past
detonate and PARKS at `awaiting_submission`; SAFE BLOCKS at detonate with
`'detonation_evidence' in blocked_by` (the `gate_executor` adjudication). Assert on those,
plus the nonce binding below.
- ASSERT X1 (VULN twin): the continuous run ADVANCES through `detonate`
  (`report['raw_result']['verdict'] == 'confirmed'`) and PARKS at `awaiting_submission`
  (terminal). The per-run nonce N (read from `report['raw_result']['nonce']`; a fresh
  `jm...` CSPRNG token, NOT finding-id-derived) is the SAME value end-to-end and
  satisfies: N ∈ stdout ∧ N ∈ fs_snapshot_diff ∧
  `final_state['evidence']['detonation_nonce'] == N`. (Without fix B, `detonation_nonce`
  is `None` -> RED; without fix A, the run stalls at `health_probe` and never reaches
  detonate -> RED.)
- ASSERT X2 (SAFE twin, IDENTICAL floor — only `svc.py` differs): the `detonate` step
  BLOCKS with `'detonation_evidence' in blocked_by`
  (`report['raw_result']['verdict'] == 'refuted'`), and the run NEVER reaches
  `awaiting_submission`/a confirmed detonation. (This is a DEEPER refutation than c7's
  reachability `sink_patched` — the safe twin passes the env-FSM AND the identical
  `sink_presence`/`sink_reachability` gates, reaching the dynamic detonate arbiter, which
  refutes because the injection is inert.)
- `verification_command` (bare): `python -m pytest tests/ngv2/test_pcapstone_run_hunt_x1_x2.py -q`.

# Required plan shape

FOUR tasks, ONE plan, strictly serial: 1 -> 2 -> 3 -> 4. NOT an epic. Do not add or drop
a task (`required_task_ids` lists all four). Tasks 2 & 3: `meta_task_type: io_adapter`,
`priority: high`, single-file `__JANUSMASK_PATCHES__` SYMBOL recipe, OMIT
`mutation_target`, auto-approve-eligible (NO operator decision file). Task 1:
`meta_task_type: test_authoring`, `mutation_target: ngv2.health_producer`, ordinary test
source via importlib, the 4 assertion groups + `regression_tests >= 2`. Task 4:
`meta_task_type: test_acceptance`, `__JANUSMASK_MANIFEST__` whole-file (6 fixture files +
the test, ALL under `tests/`), OMIT `mutation_target`, the X1+X2 assertions, real jailed
detonate as the NEVER-stubbed trust anchor. Every task's `non_goals` contains the literal
`integration`. Dep edges: `pcapstone-health-guard-impl <- pcapstone-health-guard-oracle`;
`pcapstone-evidence-nonce-impl <- pcapstone-health-guard-impl`;
`pcapstone-run-hunt-x1-x2-oracle <- pcapstone-evidence-nonce-impl`.
`ngv2/**` is external (NOT sensitive -> no decision file; NOT `harness_self_fix`).
