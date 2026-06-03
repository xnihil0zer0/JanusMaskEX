# Title

Method D: Stateful/Rule-Based Differential Property-Based Testing for the JanusMaskJR Validation Harness

## Status / framing (READ FIRST — this brief is a HYPOTHESIS, not ground truth)

This brief describes the **CORRECT END STATE** of the Method D stateful differential
fuzzer. It is a hypothesis to be *verified* against the live tree, not a from-scratch
build order. Each deliverable below carries a **behavioral** `verification_command`
and `acceptance_criteria`; an implementing/planning agent must treat the deliverable as
"reach this asserted behavior" and, if the tree already satisfies the
`verification_command`, the work for that deliverable is a **no-op** (idempotent).

Method D is currently wired end-to-end on the validation pipeline (the six build seams
have landed). Re-deriving these deliverables against the current tree must therefore be
**idempotent**: the behavioral `verification_command`s below are written to PASS against
the integrated tree, so re-planning finds the code already correct and rebuilds none of
the historical defects. In particular, this brief MUST NOT re-introduce the old
comparator bug (comparing stateful step-traces "using `outputs_match`") nor the old
import bug (importing `execute_stateful_trace` from `harness.diff_fuzzer` — it lives in
`harness.sandbox`).

## Scope

Integrate Method D stateful, rule-based differential property-based testing (PBT) into
the JanusMaskJR validation pipeline to verify state-dependent classes (caches, state
machines, transactional models). Tasks of taxonomy type `state_machine` previously
bypassed fuzzing (`bypass_fuzzer: True`); Method D replaces that bypass by modeling the
class under test as a state machine. It:

1. Parses the class interface under test via AST to extract constructor + public-method
   signatures.
2. Generates symbolic action sequences with Hypothesis — `(init_args, list_of_method_calls)`
   where each call is `(method_name, args)`.
3. Replays each generated action sequence step-by-step on both candidate implementations
   (Code A and Code B) inside an isolated sandboxed subprocess, producing a serialized
   list of per-step JSON **step-dicts**.
4. Performs step-by-step trace comparison over those step-dicts (exception dict, then
   authoritative `value_repr`, honoring skipped steps).
5. Shrinks any divergent action sequence using Hypothesis's shrinking engine.
6. Feeds the minimal shrunk trace into the cross-examination system to give precise
   debugging feedback to review agents.

## Non-goals

- Do NOT use native Hypothesis `RuleBasedStateMachine` subclasses (hard to serialize
  across the subprocess jail boundary and fragile to shrink). Generate symbolic command
  lists (action sequences) instead.
- Do NOT break module-level importability of `harness/diff_fuzzer.py` (imported
  module-level by `harness/orchestrator.py` and `harness/orchestrator_worker.py`); all
  additions must be strictly additive, backward-compatible, valid syntax.
- Do NOT refactor or modify existing orchestrator functions in `harness/orchestrator.py`.
- Do NOT alter credential, environment, or nondeterminism gates — they must remain strict.
- Do NOT set a `working_dir` front-matter key; this is a self-build task on this repository.

## Inputs

- `method_d_report.md` — technical report on the stateful mechanism, dynamic command
  sequences, and interface parsing.
- `harness/sandbox.py` — jail execution environment; `Sandbox`, `BatchRunner`, and the
  Method-D trace executor `execute_stateful_trace` (line ~1609) plus its replay driver
  `_STATEFUL_TRACE_DRIVER`.
- `harness/diff_fuzzer.py` — stateless fuzzer: annotation strategy parsers
  `_strategy_for_annotation`, `_ast_node_to_strategy`; output comparator `outputs_match`
  (for STATELESS scalar/return comparison only); `_deep_compare`; `_param_strategies`;
  `_generate_inputs`; and the dataclasses `FuzzResult` and `FuzzFailure` (with the
  stateful fields `action_sequence` / `divergent_step_index`).
- `harness/planner/taxonomies.py` — `META_TASK_POLICY` registry and `BYPASS_FUZZER_TYPES`.
- `harness/cross_examiner.py` — `serialize_failure` and `prepare_exam_packets`.
- `harness/orchestrator.py` — host of `stateful_differential_fuzz` (line ~531), the
  routing helper `_route_stateful_fuzz`, and the class-name resolver
  `_resolve_stateful_class_name`.

## Deliverables

Each deliverable's `verification_command` is a single `python -c`-style snippet (run from
the repo root) and must assert **behavior**, not structure. No `dir()`/membership/policy-
dict-only checks.

1. **`extract_class_interface(code, class_name)` in `harness/diff_fuzzer.py`** — ADDITIVE
   top-level function. Parse the target class via AST and extract parameter annotation
   mappings for the constructor (`__init__`) and public methods, discarding private
   methods (except `__init__`) and reusing the existing AST type parser. Depends on: none.
   - `verification_command`:
     `python -c "from harness.diff_fuzzer import extract_class_interface as f; code='class C:\n    def __init__(self, n: int):\n        self.n=n\n    def inc(self, by: int) -> int:\n        return by\n    def _hidden(self):\n        return 1\n'; i=f(code,'C'); ks=set(); [ks.update(d.keys()) if isinstance(d,dict) else None for d in (i.values() if isinstance(i,dict) else [])]; print(i); assert i, 'empty interface'; s=repr(i); assert 'inc' in s and '_hidden' not in s, 'public methods kept / private dropped'"`
   - `acceptance_criteria`: returns a non-empty interface for class `C` that includes the
     public method `inc` and the constructor, and EXCLUDES the private method `_hidden`.

2. **`build_stateful_strategy(interface)` in `harness/diff_fuzzer.py`** — ADDITIVE strategy
   function. Build a Hypothesis search strategy yielding `(init_args, list_of_method_calls)`
   where `list_of_method_calls` is a sequence of `(method_name, args)`, using
   `_strategy_for_annotation` / `_param_strategies`. Depends on: #1.
   - `verification_command`:
     `python -c "from harness.diff_fuzzer import extract_class_interface as f, build_stateful_strategy as g; code='class C:\n    def __init__(self, n: int):\n        self.n=n\n    def inc(self, by: int) -> int:\n        return by\n'; s=g(f(code,'C')); ex=s.example(); print(ex); init,calls=(ex if isinstance(ex,tuple) and len(ex)==2 else (getattr(ex,'init_args',None),getattr(ex,'method_calls',None))); assert calls is not None, 'no method_calls in produced sequence'; assert isinstance(list(calls),list)"`
   - `acceptance_criteria`: `s.example()` yields a sequence decomposable into
     `(init_args, method_calls)` where `method_calls` is a list of calls; the strategy is a
     real Hypothesis strategy (has `.example()`).

3. **`execute_stateful_trace(code, class_name, init_args, method_calls, ...)` in
   `harness/sandbox.py`** — ADDITIVE function (this is the AUTHORITATIVE location; it is
   NOT in `diff_fuzzer.py`). Replay a trace inside the existing jail (reusing `Sandbox` /
   `BatchRunner` and the `_STATEFUL_TRACE_DRIVER`), instantiating the class with
   `init_args`, replaying the method calls sequentially, and returning a serialized
   `list[dict]` of per-step results. Each step-dict is one of:
   `{'step': i, 'method': name, 'value': <json-or-None>, 'value_repr': <repr>}` (success),
   `{'step': i, 'method': name, 'exception': {'type': ..., 'message': ...}}` (raise), or
   `{'step': i, 'method': name, 'skipped': True, 'reason': ...}` (skipped after an earlier
   construction/lookup failure). Depends on: #2.
   - `verification_command`:
     `python -c "from harness.sandbox import execute_stateful_trace as e; code='class C:\n    def __init__(self, n: int=0):\n        self.n=n\n    def inc(self, by: int=1) -> int:\n        self.n+=by; return self.n\n'; t=e(code,'C',{'args':[0]},[('inc',{'args':[2]}),('inc',{'args':[3]})]); print(t); assert isinstance(t,list) and len(t)>=3; assert t[0]['method']=='__init__'; vals=[s.get('value') for s in t if s.get('method')=='inc']; assert vals==[2,5], vals"`
   - `acceptance_criteria`: returns a `list[dict]` whose step 0 is `__init__` and whose two
     `inc` steps return values `[2, 5]` (state accumulates across the replayed sequence).

4. **`stateful_differential_fuzz(code_a, code_b, class_name, config, session_id)` in
   `harness/orchestrator.py`** — STRICTLY ADDITIVE top-level function (do not touch other
   orchestrator functions; append via a localized patch block). Generate action sequences
   (via #1/#2), replay each against `code_a` and `code_b` using **`execute_stateful_trace`
   imported from `harness.sandbox`** (NOT from `harness.diff_fuzzer` — that import does not
   exist and is the historical defect), and compare the two traces with a **dedicated
   step-dict comparator** — NOT `outputs_match`. `outputs_match` compares stateless
   `ExecutionResult` objects and would be a type mismatch against the JSON step-dicts that
   `execute_stateful_trace` returns. The comparator MUST, per step:
     - classify the step kind (skip / raise / value);
     - if kinds differ ⇒ divergence;
     - for `raise` steps, compare the `exception` dict by `type` then `message`;
     - for `value` steps, treat **`value_repr` as authoritative** (because `value` is
       `None` for non-JSON-serializable returns such as `set`/`bytes`/`Path`), normalizing
       the non-deterministic default object repr `<Cls object at 0x...>` so two
       structurally identical instances are not flagged purely on memory address;
     - a `skipped` step matches iff both sides skipped;
     - unequal trace lengths ⇒ divergence at the first missing index.
   On the first divergent step, shrink the failing action sequence via Hypothesis and
   package the minimal counterexample into a `FuzzFailure` carried by the returned
   `FuzzResult`. A sandbox execution error on exactly one side (or differing exception
   types across sides) is surfaced as a divergence, not silently matched. The function
   never raises: a passing/skipped `FuzzResult` is returned when the class/interface
   cannot be parsed, when Hypothesis is unavailable, or when the example budget is
   exhausted with no divergence. Do not relax credential/nondeterminism gates. Reuse the
   module-level `FuzzResult` import; import `extract_class_interface`,
   `build_stateful_strategy`, `outputs_match` lazily from `harness.diff_fuzzer` and
   `execute_stateful_trace` lazily from `harness.sandbox`. Depends on: #1, #2, #3.
   - `verification_command`:
     `python -c "from harness.orchestrator import stateful_differential_fuzz as s; cfg={'fuzzing':{'stateful':{'max_examples':40}},'sandbox':{'memory_limit_mb':256,'cpu_time_limit_seconds':5,'filesystem_root':'/tmp/jm_md4'}}; a='class C:\n    def __init__(self, limit: int=5):\n        self.n=0; self.limit=limit\n    def inc(self, by: int=1) -> int:\n        self.n=min(self.n+by,self.limit); return self.n\n'; b=a.replace('min(self.n+by,self.limit)','self.n+by'); r=s(a,b,'C',cfg,'md4_div'); print('div', r.equivalent, len(r.failures), r.error); assert r.equivalent is False and len(r.failures)>=1; assert r.error is None; r2=s(a,a,'C',cfg,'md4_eq'); print('eq', r2.equivalent, len(r2.failures)); assert r2.equivalent is True and len(r2.failures)==0"`
   - `acceptance_criteria`: a bounded-vs-unbounded `Counter` pair returns
     `equivalent=False` with ≥1 `FuzzFailure` and no harness `error`; the identical pair
     returns `equivalent=True` with zero failures. (This is the comparator working over
     real step-dicts — the historical `outputs_match` defect would crash or false-match.)

5. **Taxonomy flip in `harness/planner/taxonomies.py`** — edit `META_TASK_POLICY` for
   `'state_machine'` to set `bypass_fuzzer: False` (keep the key so `BYPASS_FUZZER_TYPES`
   resolves) AND `stateful_fuzz: True`, so `state_machine` tasks route through the stateful
   differential fuzz path instead of bypassing. ADDITIVE edit. Depends on: #4.
   - `verification_command`:
     `python -c "from harness.planner.taxonomies import META_TASK_POLICY as P, BYPASS_FUZZER_TYPES as B; pol=P['state_machine']; print(pol); assert pol.get('bypass_fuzzer') is False; assert pol.get('stateful_fuzz') is True; assert 'state_machine' not in B"`
   - `acceptance_criteria`: `state_machine` policy has `bypass_fuzzer is False` and
     `stateful_fuzz is True`, and `state_machine` is no longer in `BYPASS_FUZZER_TYPES`
     (so the routing layer dispatches it to the stateful path).

6. **Stateful cross-examination wiring + `FuzzFailure` shape contract in
   `harness/cross_examiner.py` and `harness/diff_fuzzer.py`** — ADDITIVE. The
   `FuzzFailure` dataclass (`harness/diff_fuzzer.py`) MUST declare `action_sequence` and
   `divergent_step_index` as real fields (defaults `None`), not merely `setattr`-injected
   attributes; for stateful failures `result_a`/`result_b` hold step-dicts (or
   `('error', repr)` tuples / `'ok'` strings), `action_sequence` is the
   `(init_args, method_calls)` pair, and `divergent_step_index` is the first divergent
   step index. `serialize_failure` MUST **detect a stateful failure via
   `action_sequence is not None`** and emit the action sequence (as readable call strings)
   plus the divergent step index, rather than producing the stateless `ExecutionResult`
   summary (which would `AttributeError` on step-dicts). `prepare_exam_packets` MUST thread
   the serialized `action_sequence` + `divergent_step_index` into the feedback packet text
   for the review agents. Depends on: #4, #5.
   - `verification_command`:
     `python -c "from harness.diff_fuzzer import FuzzFailure; from harness.cross_examiner import serialize_failure, prepare_exam_packets; from dataclasses import fields; fn={f.name for f in fields(FuzzFailure)}; assert {'action_sequence','divergent_step_index'} <= fn, fn; f=FuzzFailure(input_args=(0,), input_kwargs={}, result_a={'step':1,'method':'inc','value':5,'value_repr':'5'}, result_b={'step':1,'method':'inc','value':6,'value_repr':'6'}, reason='diverge', action_sequence=((0,),[('inc',(1,))]), divergent_step_index=1); d=serialize_failure(f); print(d); assert d.get('stateful') is True, 'not detected as stateful'; assert d.get('action_sequence'), 'no action_sequence emitted'; assert d.get('divergent_step_index')==1; cp, gp = prepare_exam_packets('class C: pass', 'class C: pass', 'task', [f]); blob=cp.review_prompt + gp.review_prompt; assert 'inc' in blob and 'Divergent step index' in blob, 'action sequence not threaded into packet'"`
   - `acceptance_criteria`: `FuzzFailure` declares `action_sequence`/`divergent_step_index`
     as real fields; `serialize_failure` on a stateful failure emits a populated
     `action_sequence` and the correct `divergent_step_index` (1); `prepare_exam_packets`
     threads the action sequence + divergent step into the packet text. No `AttributeError`.

7. **Integration + behavioral acceptance (the seam check) — `meta_task_type:
   test_integration`.** Depends on: #1, #2, #3, #4, #5, #6. This deliverable owns the
   end-to-end seam that the per-artifact build tasks individually do not: it imports the
   real modules and drives `stateful_differential_fuzz` against a **known-divergent**
   stateful class pair, asserting `equivalent=False` with a *populated* `FuzzFailure`
   (`action_sequence is not None` AND `divergent_step_index is not None`), PLUS an
   **equivalent** pair asserting `equivalent=True` with no failures and no harness error.
   No new code is built here — the harness primitives already exist; the load-bearing
   parts are the `dependencies` (gated on *accepted*, so the task runs against the fully
   integrated post-commit tree) and the behavioral `verification_command` below.
   - `meta_task_type`: `test_integration`
   - `verification_command`:
     `python -c "from harness.orchestrator import stateful_differential_fuzz as s; cfg={'fuzzing':{'stateful':{'max_examples':50},'seed':42},'sandbox':{'memory_limit_mb':256,'cpu_time_limit_seconds':5,'filesystem_root':'/tmp/jm_md7'}}; div_a='class Counter:\n    def __init__(self, limit: int=5):\n        self._n=0; self._limit=limit\n    def inc(self, by: int=1) -> int:\n        self._n=min(self._n+by,self._limit); return self._n\n    def value(self) -> int:\n        return self._n\n'; div_b='class Counter:\n    def __init__(self, limit: int=5):\n        self._n=0; self._limit=limit\n    def inc(self, by: int=1) -> int:\n        self._n=self._n+by; return self._n\n    def value(self) -> int:\n        return self._n\n'; rd=s(div_a,div_b,'Counter',cfg,'md7_div'); print('DIVERGENT equivalent=%s failures=%d error=%s'%(rd.equivalent,len(rd.failures),rd.error)); assert rd.equivalent is False, 'divergent pair must NOT be equivalent'; assert rd.error is None; assert len(rd.failures)>=1; f=rd.failures[0]; assert f.action_sequence is not None, 'FuzzFailure.action_sequence not populated'; assert f.divergent_step_index is not None, 'FuzzFailure.divergent_step_index not populated'; re_=s(div_a,div_a,'Counter',cfg,'md7_eq'); print('EQUIVALENT equivalent=%s failures=%d'%(re_.equivalent,len(re_.failures))); assert re_.equivalent is True, 'identical pair must be equivalent'; assert len(re_.failures)==0; print('SEAM OK')"`
   - `acceptance_criteria`: against the integrated tree, the divergent `Counter` pair
     yields `equivalent=False` with `error is None` and a `FuzzFailure` whose
     `action_sequence` and `divergent_step_index` are both populated; the identical pair
     yields `equivalent=True` with zero failures. Prints `SEAM OK`. This is the
     integration check the original 6-task DAG never had (principle P-I): it fails loudly
     if any seam (import path, comparator, routing, failure shape, cross-exam wiring) is
     broken, and passes idempotently against the already-integrated tree.
