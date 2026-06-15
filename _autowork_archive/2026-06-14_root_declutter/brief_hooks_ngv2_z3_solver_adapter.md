---
interfaces: "creates NEW module ngv2/z3_solver_adapter.py exposing make_z3_solver() -> Optional[SolverFn] — a factory with a GUARDED IN-BODY `import z3` (returns None when z3 is absent) that translates the two committed ngv2.z3_bridge constraint sets ('grounding': (codeql_found OR joern_found) -> confidence >= HIGH; 'gate': (submitting AND live_test_required) -> live_test_passed) into z3 Bool/Implies assertions and returns a SolverFn callable `(constraint_set: str, state: Mapping[str, object]) -> bool` compatible with Z3Bridge(solver_fn=...), stateless per call (fresh z3.Solver per invocation, no push/pop), whose verdict differentially matches the stdlib rule fallback on every one of the 24 reachable constraint states"
working_dir: "/home/xnihil0zer0/NobleGreedv2"
---

# Title

NEW ngv2/z3_solver_adapter.py — an optional real-z3 SolverFn factory `make_z3_solver() -> Optional[SolverFn]` that plugs into the EXISTING injected solver seam `Z3Bridge(solver_fn=...)` in ngv2/z3_bridge.py, translating the two committed constraint sets into z3 Bool/Implies assertions, with a guarded in-body `import z3` so the factory returns None (and the system degrades to the stdlib rule fallback) when z3 is absent

# Scope

CREATE the NEW module ngv2/z3_solver_adapter.py in the external NobleGreedv2 repo (working_dir /home/xnihil0zer0/NobleGreedv2). ngv2/z3_bridge.py is stdlib-only BY DESIGN and is NOT touched — it already exposes the injected seam: `Z3Bridge(solver_fn=...)` routes every `check_invariants` call exclusively through the injected callable and reports `z3_used=True` on that path. This new module is the OTHER side of that seam: the only place in NGv2 allowed to import the real `z3` package (z3-solver 4.16.0.0 is installed in the NGv2 venv at /home/xnihil0zer0/NobleGreedv2/.venv — verified live).

THE MODULE'S ENTIRE PUBLIC SURFACE is one function:

    def make_z3_solver() -> Optional[SolverFn]:

REQUIRED STRUCTURE (all verified against ngv2/z3_bridge.py at HEAD):

1. GUARDED IN-BODY IMPORT — `import z3` must live INSIDE the body of `make_z3_solver()` (never at module top level), wrapped in `try: import z3 / except ImportError: return None`. Module import of ngv2.z3_solver_adapter must succeed even when z3 is absent; only the factory call returns None then. The committed oracle blocks the z3 import via a sys.meta_path finder and asserts `make_z3_solver() is None` deterministically on repeated calls — so the guard must re-attempt the import per call (or otherwise behave identically when z3 is blocked), not cache a module-level result captured at import time.

2. RETURNED SolverFn — when z3 imports, return a closure `_solver(constraint_set: str, state: Mapping[str, object]) -> bool` matching the bridge's `SolverFn = Callable[[str, Mapping[str, object]], object]` alias. The bridge passes the constraint-set name ALREADY LOWERCASED and coerces the return value with `bool(...)`; still, normalize defensively with `cs = str(constraint_set).lower()` and return a real Python bool.

3. STATELESS PER CALL — construct a FRESH `z3.Solver()` inside every `_solver` invocation. NO push/pop incrementality, no solver reuse across calls, no assertion accumulation. Repeated calls with different states must be independent (the oracle asserts repeat-invocation stability on one solver instance).

4. THE z3 ENCODING (write exactly this logic; booleans are derived from the state dict THE SAME WAY the rule fallback does — bool() coercions, identical key names, identical defaults, confidence ranked via the bridge's own `_CONFIDENCE_RANK` table; the constraint is asserted and `s.check() == z3.sat` is the verdict, which on ground BoolVal instantiations is exactly the truth value of the implication):

    For cs == 'grounding'   # (codeql_found OR joern_found) -> confidence >= HIGH
        codeql       = z3.BoolVal(bool(state.get('codeql_found', False)))
        joern        = z3.BoolVal(bool(state.get('joern_found', False)))
        rank         = _CONFIDENCE_RANK.get(str(state.get('confidence', 'LOW')).upper(), 0)
        conf_ge_high = z3.BoolVal(rank >= _CONFIDENCE_RANK['HIGH'])
        s = z3.Solver()
        s.add(z3.Implies(z3.Or(codeql, joern), conf_ge_high))
        return s.check() == z3.sat

    For cs == 'gate'        # (submitting AND live_test_required) -> live_test_passed
        submitting = z3.BoolVal(bool(state.get('submitting', False)))
        required   = z3.BoolVal(bool(state.get('live_test_required', True)))   # NOTE: default True, mirroring _check_gate
        passed     = z3.BoolVal(bool(state.get('live_test_passed', False)))
        s = z3.Solver()
        s.add(z3.Implies(z3.And(submitting, required), passed))
        return s.check() == z3.sat

    For any other cs: return True   # unknown sets are vacuously satisfied, mirroring the bridge

    Import `_CONFIDENCE_RANK` from ngv2.z3_bridge (it is in the bridge's __all__) — do NOT redeclare the rank table. You MAY also import the `SolverFn` alias for typing.

This encoding has been validated live against the rule fallback across all 24 reachable states (16 grounding + 8 gate) with zero mismatches — reproduce it faithfully and the committed oracle goes GREEN. Verify GREEN with `python -m pytest tests/ngv2/test_z3_solver_adapter_wired.py -q`; working_dir is /home/xnihil0zer0/NobleGreedv2.

DISPATCH DIRECTIVE — WHOLE-FILE FORMAT (NEW module — the canonical safe shape for a file that does not exist at HEAD): emit the COMPLETE module source for ngv2/z3_solver_adapter.py as a SINGLE WHOLE FILE. NEVER emit a `__JANUSMASK_PATCHES__` list for a new module — a NEW-file + patches-symbol emission deterministically produces auto_commit_failed; there is no existing symbol to anchor against. One file, whole contents, nothing else. POST-EMIT SELF-CHECK (mandatory): your emission is the full module text starting with a module docstring; it contains NO top-level `import z3` (the z3 import appears ONLY inside the body of `make_z3_solver`); it defines exactly one public function `make_z3_solver`; it touches no other file.

# Required plan shape

EXACTLY ONE impl task. Use this task_id VERBATIM (the committed oracle is keyed to this brief): `task_id`: `ngv2-z3-solver-adapter`. meta_task_type=`data_model` (external NGv2 target — the diff-fuzzer cannot resolve external imports, so use a fuzzer-bypassed, smoke-gated meta-type per META_TASK_POLICY; data_model is bypass_fuzzer). priority: high. dependencies: []. working_dir: `/home/xnihil0zer0/NobleGreedv2`. files_touched: `["ngv2/z3_solver_adapter.py"]` ONLY. partial_edit semantics: NONE — this is a NEW module; single-file WHOLE-FILE dispatch (emit the complete module source; NEVER `__JANUSMASK_PATCHES__` for a new module — see the DISPATCH DIRECTIVE above, which MUST be copied VERBATIM into the task's `implementation_notes` so the blind worker sees it). verification_command: `python -m pytest tests/ngv2/test_z3_solver_adapter_wired.py -q`. The committed RED oracle tests/ngv2/test_z3_solver_adapter_wired.py (NGv2 commit 69e8c4e) is the authoritative acceptance contract — make it GREEN; do NOT author new tests. `spec.functional_requirements` MUST be CONSOLIDATED to at most 5 entries, and `test_spec.unit_tests` MUST enumerate AT LEAST as many entries as `spec.functional_requirements` (validator floor: len(unit_tests) >= len(functional_requirements)); unit_tests entries are descriptors NAMING committed-oracle test cases (this does NOT authorize authoring new tests). `test_spec.regression_tests` MUST list at least two entries that NAME existing test cases from the committed oracle `tests/ngv2/test_z3_solver_adapter_wired.py` (plan descriptors referencing committed/landed tests — this does NOT authorize authoring new tests), so every `spec.edge_cases` entry is reflected per the validator's edge-case rule (e.g. `test_grounding_differential_matches_rule_fallback`, `test_gate_differential_matches_rule_fallback`, `test_make_z3_solver_returns_none_when_z3_absent`).

# Non-Goals

This is a NEW leaf module and integration is out of scope: the task's non_goals MUST declare integration testing out of scope — do NOT add integration/e2e tests; this build is verified solely by the committed unit oracle tests/ngv2/test_z3_solver_adapter_wired.py. Do NOT author or modify any test — that oracle is committed and authoritative. Do NOT touch ngv2/z3_bridge.py (stdlib-only by contract — it must NEVER import z3), ngv2/backtrack.py (its Optional injected verifier seam already exists; wiring this adapter into it is a SEPARATE future leaf), or any other production module or test. NO new live composition points — nothing imports ngv2.z3_solver_adapter at module scope anywhere else; the adapter is composed only by future callers passing `make_z3_solver()` output into `Z3Bridge(solver_fn=...)`. No push/pop incrementality, no solver caching/reuse across calls, no `z3.Optimize`, no tactics/goals. No pySMT, no cvc5, no other SMT backend — stdlib + the `z3` package only. No subprocess, no network, no wall-clock dependence, no randomness, no environment-variable switches, no logging side effects. Do NOT redeclare `_CONFIDENCE_RANK` or the constraint semantics — import the rank table from ngv2.z3_bridge and mirror the fallback's bool/default derivations exactly. Do NOT add a module-level `import z3` (the guarded in-body import is the entire point). Do NOT add a CLI, `__main__` block, or config knobs.

# Inputs

The committed authoritative oracle at tests/ngv2/test_z3_solver_adapter_wired.py (NGv2 commit 69e8c4e; currently RED with `ModuleNotFoundError: No module named 'ngv2.z3_solver_adapter'` at collection — clean single-file collection error, the expected RED shape). Its key assertions:

- `test_make_z3_solver_returns_callable_when_z3_present`: `solver = make_z3_solver()`; asserts `solver is not None` and `callable(solver)` (z3 IS installed — no skip).
- `test_grounding_differential_matches_rule_fallback` (16 parametrized states: codeql_found x joern_found x all four `_CONFIDENCE_RANK` ranks): for every state asserts `Z3Bridge(solver_fn=make_z3_solver()).check_invariants('grounding', state).satisfied == Z3Bridge().check_invariants('grounding', state).satisfied`, `isinstance(injected.satisfied, bool)`, `injected.z3_used is True`, `reference.z3_used is False`.
- `test_gate_differential_matches_rule_fallback` (8 parametrized states: submitting x live_test_required x live_test_passed): same differential law and z3_used assertions for 'gate'.
- `test_solver_is_stateless_per_call_repeat_invocations_stable`: ONE solver instance in ONE bridge, 3 repeated rounds alternating a violating grounding state ({'codeql_found': True, 'confidence': 'LOW'} -> False) and a holding one ({'codeql_found': True, 'confidence': 'HIGH'} -> True) — verdicts must not drift (no leaked assertions).
- `test_make_z3_solver_returns_none_when_z3_absent`: evicts every `z3`/`z3.*` entry from sys.modules and prepends a sys.meta_path finder that raises ImportError for `z3` and `z3.*`; asserts `make_z3_solver() is None` TWICE (deterministic under absence).
- `test_constraint_sets_contract_unchanged`: pins `tuple(CONSTRAINT_SETS) == ('grounding', 'gate')` and `_CONFIDENCE_RANK == {'LOW': 0, 'MEDIUM': 1, 'HIGH': 2, 'CONFIRMED': 3}`.

The EXACT committed constraint-set source from ngv2/z3_bridge.py at HEAD (read-only context — do NOT edit; this is the reference semantics your z3 encoding must match):

    _CONFIDENCE_RANK: Dict[str, int] = {'LOW': 0, 'MEDIUM': 1, 'HIGH': 2, 'CONFIRMED': 3}
    CONSTRAINT_SETS = ('grounding', 'gate')

    @staticmethod
    def _check_grounding(state: Mapping[str, object]) -> 'tuple[bool, str]':
        """(codeql_found OR joern_found) -> confidence >= HIGH."""
        taint = bool(state.get('codeql_found', False)) or bool(state.get('joern_found', False))
        if not taint:
            return (True, 'grounding vacuously satisfied: no static-analysis taint')
        confidence = str(state.get('confidence', 'LOW')).upper()
        rank = _CONFIDENCE_RANK.get(confidence, 0)
        if rank >= _CONFIDENCE_RANK['HIGH']:
            return (True, 'grounding satisfied: taint backed by confidence %r' % confidence)
        return (False, 'grounding violated: taint with insufficient confidence %r' % confidence)

    @staticmethod
    def _check_gate(state: Mapping[str, object]) -> 'tuple[bool, str]':
        """(submitting AND live_test_required) -> live_test_passed."""
        submitting = bool(state.get('submitting', False))
        required = bool(state.get('live_test_required', True))
        passed = bool(state.get('live_test_passed', False))
        if submitting and required:
            if passed:
                return (True, 'gate satisfied: live test passed before submission')
            return (False, 'gate violated: submitting with required live test not passed')
        return (True, 'gate vacuously satisfied: live test not required for this action')

The EXACT SolverFn calling convention as the bridge invokes and consumes it (from ngv2/z3_bridge.py at HEAD — read-only):

    SolverFn = Callable[[str, Mapping[str, object]], object]

    # inside Z3Bridge.check_invariants, after cs = str(constraint_set).lower():
    if self._solver_fn is not None:
        verdict = bool(self._solver_fn(cs, st))
        reason = 'injected solver verdict for %r: %s' % (cs, verdict)
        return Z3Result(satisfied=verdict, reason=reason, z3_used=True, elapsed_ms=_elapsed_ms(start))

i.e. your callable receives `(constraint_set: str (already lowercased), state: Mapping[str, object])` positionally and its return value is coerced with `bool(...)` into `Z3Result.satisfied`; the bridge — not your adapter — sets `z3_used=True` and composes the reason string. `Z3Result` fields are `satisfied: bool, reason: str, z3_used: bool, elapsed_ms: float`. Also available read-only for shape reference: `make_mock_solver` / `make_scripted_solver` in ngv2/z3_bridge.py return exactly this callable shape. z3-solver 4.16.0.0 is installed in the NGv2 venv (`import z3; z3.get_version_string()` -> '4.16.0' — verified live). stdlib + z3 + ngv2.z3_bridge imports only.

# Deliverables

NEW ngv2/z3_solver_adapter.py whose single public function `make_z3_solver() -> Optional[SolverFn]` (a) returns None deterministically when `import z3` fails (guarded IN-BODY import — module import itself never requires z3), and (b) when z3 is importable returns a stateless-per-call SolverFn closure that builds a fresh `z3.Solver()` per invocation, encodes 'grounding' as `Implies(Or(codeql, joern), conf_ge_high)` and 'gate' as `Implies(And(submitting, required), passed)` over `z3.BoolVal` ground booleans derived from the state dict exactly as the rule fallback derives them (same keys, same bool() coercions, same defaults including `live_test_required` defaulting True, confidence ranked via the imported `_CONFIDENCE_RANK`), returns `s.check() == z3.sat` as a real bool, and treats unknown constraint sets as vacuously True — so that `Z3Bridge(solver_fn=make_z3_solver()).check_invariants(cs, state).satisfied` matches `Z3Bridge().check_invariants(cs, state).satisfied` on every one of the 24 reachable constraint states with `z3_used is True`, while ngv2/z3_bridge.py and ngv2/backtrack.py remain byte-identical. Verified GREEN by `python -m pytest tests/ngv2/test_z3_solver_adapter_wired.py -q`.
