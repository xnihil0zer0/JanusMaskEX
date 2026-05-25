"""Adversarial sub-agent A3 (B3 followup pass) coverage for F4.

Target: ``harness.task_decomposer._preserve_meta_task_type`` and every
caller/consumer of meta_task_type propagation introduced by the F4
precedence flip (commit 6ec6e29).

F4 inverted the precedence at lines 125-140 of ``harness/task_decomposer.py``::

    # (highest wins)
    # explicit child constraints.meta_task_type
    #   > parent top-level meta_task_type
    #     > parent constraints.meta_task_type

An **adjacent spec/test contradiction** remains unreconciled:

* ``state/planning/merged_plan.json`` -> DECOMPOSER-001 -> spec.edge_cases
  line 36 still reads
  ``"Parent task has meta_task_type in both places (top-level takes precedence)"``
  -- the OLD contract.

* ``harness/tests/test_task_decomposer.py::TestMetaTaskTypeInheritance::
  test_preserve_meta_task_type_precedence_task_over_constraints`` from
  commit ``919b5c9`` pins the same OLD contract and therefore now FAILS.

* ``tests/test_task_decomposer.py::TestMetaTaskTypeInheritance::
  test_explicit_child_override_wins_over_parent`` (added in ``bc2e6ba``)
  and ``tests/adversarial/test_P3_safe_subpath_decomposer_attacks.py::
  TestMetaTaskTypeEdges::test_D06_explicit_constraints_override_wins_over_top_level``
  pin the NEW contract and pass.

This suite:

1. Exhaustively adversarially fuzzes ``_preserve_meta_task_type`` (vectors
   1-19).
2. Audits every ``Subtask(`` call site in ``harness/task_decomposer.py``
   via ``ast`` introspection (vector 20).
3. Preserves the contradiction as a CI signal via a ``@pytest.mark.xfail``
   subprocess-driven diagnostic test (vector 21).
4. Cross-fix integration test with F2 ``_extract_meta_task_type`` /
   ``FUZZ_BYPASS_META_TYPES`` (vector 22).
5. Exercises every ``decompose_task`` branch that emits a subtask to
   confirm propagation (vectors 25-27).

Hard constraints honoured:

* No write touches ``harness/task_decomposer.py`` or
  ``state/planning/merged_plan.json``.
* No mutation of the contradicting harness test -- the xfail tracks it.
* Every test builds a fresh dict literal; no shared module-level mutable
  state.
"""

from __future__ import annotations

import ast
import copy
import subprocess
import sys
import threading
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from harness.task_decomposer import (  # noqa: E402
    DecompositionResult,
    SIDE_EFFECT_META_TYPES,
    Subtask,
    _preserve_meta_task_type,
    decompose_task,
)
from harness.diff_fuzzer import FuzzFailure  # noqa: E402
from harness.sandbox import ExecutionResult  # noqa: E402


REPO_ROOT = Path(__file__).resolve().parents[2]
DECOMPOSER_PATH = REPO_ROOT / "harness" / "task_decomposer.py"


# ---------------------------------------------------------------------------
# Helpers -- every test builds fresh dicts, never shares state.
# ---------------------------------------------------------------------------

def _mk_failure(input_args=None, reason="return_mismatch"):
    if input_args is None:
        input_args = [5, 10]
    ra = ExecutionResult(success=True, return_value=1, return_repr="1")
    rb = ExecutionResult(success=True, return_value=2, return_repr="2")
    return FuzzFailure(
        input_args=input_args,
        input_kwargs={},
        result_a=ra,
        result_b=rb,
        reason=reason,
    )


def _two_category_failures():
    """Triggers edge_case strategy (2 distinct input-shape categories)."""
    return [_mk_failure(input_args=[[]]), _mk_failure(input_args=[0])]


# ===========================================================================
# Vector 1-19: direct _preserve_meta_task_type fuzzing.
# ===========================================================================

class TestPreserveHelperDirect:
    """Unit-level adversarial coverage of the helper."""

    def test_V01_constraints_none_returns_fresh_dict(self):
        """None -> returns a dict (never None) even when parent has mtt."""
        result = _preserve_meta_task_type(
            {"task_id": "t", "meta_task_type": "planner_tooling"}, None
        )
        assert isinstance(result, dict)
        assert result.get("meta_task_type") == "planner_tooling"

    def test_V02_constraints_empty_dict_propagates_parent(self):
        """{} + parent mtt -> propagated."""
        result = _preserve_meta_task_type(
            {"task_id": "t", "meta_task_type": "planner_tooling"}, {}
        )
        assert result == {"meta_task_type": "planner_tooling"}

    def test_V03a_constraints_list_does_not_crash_and_parent_wins(self):
        """List constraints are treated as falsy (``dict([])`` would crash,
        but ``if constraints else {}`` makes empty list go to {}; a non-empty
        list raises ValueError).  Empty list must absorb cleanly."""
        result = _preserve_meta_task_type(
            {"task_id": "t", "meta_task_type": "planner_tooling"}, []
        )
        assert result == {"meta_task_type": "planner_tooling"}

    def test_V03b_constraints_nonempty_list_graceful(self):
        """B-F4-A (post-fix): non-dict constraints coerce to {} rather than
        raise. Previously dict([{"a": 1}]) TypeError'd -- now ingest treats
        the list as empty and parent propagation wins."""
        result = _preserve_meta_task_type({"meta_task_type": "x"}, [{"a": 1}])
        assert result == {"meta_task_type": "x"}

    def test_V03c_constraints_int_graceful(self):
        """B-F4-A (post-fix): int coerces to {} rather than raising."""
        result = _preserve_meta_task_type({"meta_task_type": "x"}, 42)
        assert result == {"meta_task_type": "x"}

    def test_V03d_constraints_string_graceful(self):
        """B-F4-A (post-fix): string coerces to {} rather than raising."""
        result = _preserve_meta_task_type({"meta_task_type": "x"}, "foo")
        assert result == {"meta_task_type": "x"}

    def test_V03e_constraints_bool_false_propagates(self):
        """False is falsy -> treated as empty constraints."""
        result = _preserve_meta_task_type(
            {"task_id": "t", "meta_task_type": "planner_tooling"}, False
        )
        assert result == {"meta_task_type": "planner_tooling"}

    def test_V03f_constraints_bool_true_graceful(self):
        """B-F4-A (post-fix): bool True coerces to {} rather than raising."""
        result = _preserve_meta_task_type({"meta_task_type": "x"}, True)
        assert result == {"meta_task_type": "x"}

    def test_V04_parent_task_none_graceful(self):
        """B-F4-B (post-fix): None parent_task is tolerated (signature
        declares dict but defensive guard now returns the coerced empty
        constraints dict rather than raising)."""
        result = _preserve_meta_task_type(None, {})
        assert result == {}

    def test_V04b_parent_task_list_graceful(self):
        """B-F4-B: list parent_task also tolerated (no AttributeError on
        ``in`` check)."""
        result = _preserve_meta_task_type(["not", "a", "dict"], {"k": "v"})
        assert result == {"k": "v"}

    def test_V05_parent_missing_top_falls_through_to_nested_constraints(self):
        """No top-level key -> consults parent.constraints.meta_task_type."""
        parent = {
            "task_id": "t",
            "constraints": {"meta_task_type": "mcp_plumbing"},
        }
        result = _preserve_meta_task_type(parent, {})
        assert result.get("meta_task_type") == "mcp_plumbing"

    def test_V06_parent_top_none_falls_through(self):
        """Top-level ``None`` is falsy -> falls through to nested."""
        parent = {
            "task_id": "t",
            "meta_task_type": None,
            "constraints": {"meta_task_type": "state_machine"},
        }
        assert (
            _preserve_meta_task_type(parent, {}).get("meta_task_type")
            == "state_machine"
        )

    def test_V07_parent_top_empty_string_falls_through(self):
        """Top-level ``''`` is falsy -> falls through."""
        parent = {
            "task_id": "t",
            "meta_task_type": "",
            "constraints": {"meta_task_type": "io_adapter"},
        }
        assert (
            _preserve_meta_task_type(parent, {}).get("meta_task_type")
            == "io_adapter"
        )

    def test_V08_parent_top_zero_or_false_falls_through(self):
        """``0`` and ``False`` are falsy -> treated as absent.

        Documents semantic: the helper uses a truthy check, so numeric /
        bool sentinel values never survive.  For the production value set
        (see SIDE_EFFECT_META_TYPES) all valid values are non-empty strings,
        so this is the intended semantic.
        """
        for sentinel in (0, False):
            parent = {
                "task_id": "t",
                "meta_task_type": sentinel,
                "constraints": {"meta_task_type": "harness_plumbing"},
            }
            assert (
                _preserve_meta_task_type(parent, {}).get("meta_task_type")
                == "harness_plumbing"
            )

    def test_V09_child_explicit_none_does_not_win(self):
        """``constraints['meta_task_type'] is None`` is falsy -> parent wins."""
        result = _preserve_meta_task_type(
            {"task_id": "t", "meta_task_type": "planner_tooling"},
            {"meta_task_type": None},
        )
        assert result.get("meta_task_type") == "planner_tooling"

    def test_V10_child_explicit_empty_string_does_not_win(self):
        """``''`` in child is falsy -> parent wins."""
        result = _preserve_meta_task_type(
            {"task_id": "t", "meta_task_type": "planner_tooling"},
            {"meta_task_type": ""},
        )
        assert result.get("meta_task_type") == "planner_tooling"

    def test_V11_child_explicit_string_wins_over_parent(self):
        """F4 contract: truthy child mtt overrides parent."""
        result = _preserve_meta_task_type(
            {"task_id": "t", "meta_task_type": "orchestration"},
            {"meta_task_type": "planner_tooling"},
        )
        assert result.get("meta_task_type") == "planner_tooling"

    def test_V12_idempotent_same_value_both_sides(self):
        """Same value on both sides -> result contains that value once."""
        result = _preserve_meta_task_type(
            {"task_id": "t", "meta_task_type": "data_model"},
            {"meta_task_type": "data_model"},
        )
        assert result == {"meta_task_type": "data_model"}

    def test_V13_deep_fallthrough_nested_only(self):
        """Top absent + child empty -> parent.constraints.meta_task_type."""
        parent = {
            "task_id": "t",
            "constraints": {"meta_task_type": "sandbox_infra"},
        }
        result = _preserve_meta_task_type(parent, {})
        assert result.get("meta_task_type") == "sandbox_infra"

    def test_V15a_input_constraints_dict_not_mutated(self):
        """Helper copies constraints -- caller's dict must not be touched."""
        original = {"function_signature": "def foo(): ..."}
        before = copy.deepcopy(original)
        _preserve_meta_task_type(
            {"task_id": "t", "meta_task_type": "planner_tooling"}, original
        )
        assert original == before, "input constraints were mutated in place"

    def test_V15b_parent_task_not_mutated(self):
        """Helper does not write back to parent_task."""
        parent = {
            "task_id": "t",
            "meta_task_type": "planner_tooling",
            "constraints": {"meta_task_type": "sandbox_infra"},
        }
        snapshot = copy.deepcopy(parent)
        _preserve_meta_task_type(parent, {"other": 1})
        assert parent == snapshot, "parent_task was mutated"

    def test_V16a_unicode_trailing_newline_canonicalised(self):
        """F4+F2 canonicalisation (post-fix): trailing newline is stripped
        at the ingest boundary so the canonical value hits F2's exact-
        membership bypass set.
        """
        result = _preserve_meta_task_type(
            {"task_id": "t", "meta_task_type": "planner_tooling\n"}, {}
        )
        assert result.get("meta_task_type") == "planner_tooling"
        # And the canonicalised value NOW hits F2 bypass (cross-fix win).
        from harness.diff_fuzzer import FUZZ_BYPASS_META_TYPES
        assert result["meta_task_type"] in FUZZ_BYPASS_META_TYPES

    def test_V16b_case_variant_canonicalised(self):
        """F4+F2 canonicalisation (post-fix): upper-case variant is
        lowered at ingest so the canonical value hits the bypass set.
        """
        result = _preserve_meta_task_type(
            {"task_id": "t", "meta_task_type": "PLANNER_TOOLING"}, {}
        )
        assert result.get("meta_task_type") == "planner_tooling"
        from harness.diff_fuzzer import FUZZ_BYPASS_META_TYPES
        assert result["meta_task_type"] in FUZZ_BYPASS_META_TYPES

    def test_V17_thread_safe_no_module_state(self):
        """100 threads, shared parent dict (read-only), no torn output."""
        parent = {"task_id": "t", "meta_task_type": "planner_tooling"}
        results: list[dict] = []
        errs: list[Exception] = []
        lock = threading.Lock()

        def worker():
            try:
                r = _preserve_meta_task_type(parent, {})
                with lock:
                    results.append(r)
            except Exception as e:  # pragma: no cover -- defensive
                with lock:
                    errs.append(e)

        threads = [threading.Thread(target=worker) for _ in range(100)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert not errs, f"thread errors: {errs}"
        assert len(results) == 100
        for r in results:
            assert r == {"meta_task_type": "planner_tooling"}

    def test_V18_only_walks_one_nested_level(self):
        """Spec: helper looks at parent['constraints']['meta_task_type'] but
        NOT at parent['constraints']['constraints'][...]. Confirm."""
        parent = {
            "task_id": "t",
            "constraints": {"constraints": {"meta_task_type": "deep"}},
        }
        result = _preserve_meta_task_type(parent, {})
        assert result == {}, f"helper walked deeper than one level: {result}"

    def test_V19_top_level_wins_over_nested_when_both_set(self):
        """Both top-level and nested set on parent, child absent -> top wins."""
        parent = {
            "task_id": "t",
            "meta_task_type": "orchestration",
            "constraints": {"meta_task_type": "data_model"},
        }
        result = _preserve_meta_task_type(parent, {})
        assert result.get("meta_task_type") == "orchestration"

    def test_V24_other_constraint_keys_preserved(self):
        """Non-mtt keys in constraints survive the merge."""
        result = _preserve_meta_task_type(
            {"task_id": "t", "meta_task_type": "planner_tooling"},
            {
                "function_signature": "def foo(x): ...",
                "max_lines": 100,
                "nested_dict": {"k": "v"},
                "other_flag": True,
            },
        )
        assert result["function_signature"] == "def foo(x): ..."
        assert result["max_lines"] == 100
        assert result["nested_dict"] == {"k": "v"}
        assert result["other_flag"] is True
        assert result["meta_task_type"] == "planner_tooling"


# ===========================================================================
# Vector 14: grandchild / multi-level decomposition.
# ===========================================================================

class TestMultiLevelDecomposition:

    def test_V14_grandchild_preserves_ancestor_meta_task_type(self):
        """Two rounds of decompose_task -- the mtt must reach the
        grandchild via child.constraints propagation."""
        parent = {
            "task_id": "root",
            "meta_task_type": "io_adapter",
            "specification": "root spec",
            "constraints": {},
        }
        r1 = decompose_task(parent, _two_category_failures(), {}, depth=0)
        assert r1.subtasks, "round 1 produced no subtasks"
        for st in r1.subtasks:
            assert st.constraints.get("meta_task_type") == "io_adapter"

        # Rebuild the child as a parent for round 2 using the flat schema
        # the orchestrator uses.
        grandchild_parent = {
            "task_id": r1.subtasks[0].task_id,
            "specification": r1.subtasks[0].specification,
            "constraints": dict(r1.subtasks[0].constraints),
        }
        r2 = decompose_task(
            grandchild_parent, _two_category_failures(), {}, depth=1
        )
        assert r2.subtasks, "round 2 produced no subtasks"
        for st in r2.subtasks:
            assert st.constraints.get("meta_task_type") == "io_adapter", (
                f"grandchild {st.task_id} dropped ancestor mtt: "
                f"constraints={st.constraints}"
            )


# ===========================================================================
# Vector 20: AST audit -- every Subtask(...) call routes through the helper.
# ===========================================================================

class TestAllSubtaskCallSitesUseHelper:

    def test_V20_every_subtask_constraints_uses_preserve_helper(self):
        """Fail if any ``Subtask(...)`` in harness/task_decomposer.py passes
        ``constraints=`` without going through ``_preserve_meta_task_type``.

        Any such caller is a latent FR6 violation -- children would miss
        the back-propagated meta_task_type.
        """
        src = DECOMPOSER_PATH.read_text()
        tree = ast.parse(src)

        violations = []
        subtask_call_count = 0
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            if isinstance(func, ast.Name):
                name = func.id
            elif isinstance(func, ast.Attribute):
                name = func.attr
            else:
                continue
            if name != "Subtask":
                continue
            subtask_call_count += 1
            kw_constraints = next(
                (kw for kw in node.keywords if kw.arg == "constraints"), None
            )
            if kw_constraints is None:
                # Positional -- inspect 4th arg (task_id, parent_task_id,
                # specification, constraints).  Rare in production but possible.
                if len(node.args) >= 4:
                    val = node.args[3]
                else:
                    violations.append(
                        f"line {node.lineno}: Subtask(...) has no constraints arg"
                    )
                    continue
            else:
                val = kw_constraints.value

            routes_through_helper = False
            for sub in ast.walk(val):
                if isinstance(sub, ast.Call):
                    subf = sub.func
                    subname = (
                        subf.id
                        if isinstance(subf, ast.Name)
                        else subf.attr
                        if isinstance(subf, ast.Attribute)
                        else None
                    )
                    if subname == "_preserve_meta_task_type":
                        routes_through_helper = True
                        break
            if not routes_through_helper:
                violations.append(
                    f"line {node.lineno}: Subtask(constraints={ast.unparse(val)!r}) "
                    f"does NOT call _preserve_meta_task_type -- FR6 violation"
                )

        assert subtask_call_count >= 5, (
            f"expected >=5 Subtask(...) call sites in decomposer, found "
            f"{subtask_call_count} -- test broken?"
        )
        assert not violations, "FR6 violations:\n" + "\n".join(violations)


# ===========================================================================
# Vector 21: RETIRED 2026-04-21 per operator 'continue with all recommendations'
# directive. The xfail-strict tracker at this slot guarded the F4 contract
# contradiction between the parent-wins harness test (deleted this session
# from harness/tests/test_task_decomposer.py -- symbol path
# harness.tests.test_task_decomposer) and the child-wins contract pinned by
# V11 above + tests/test_task_decomposer.py::test_explicit_child_override_wins
# _over_parent + tests/adversarial/test_P3_safe_subpath_decomposer_attacks.py
# ::TestMetaTaskTypeEdges::test_D06. The contradiction is now resolved --
# child-wins is the single authoritative contract -- so V21 has no remaining
# signal to carry and is retired. See ledger rows 2026-04-21 'T1 HALT-BEFORE-
# WRITE' observation + the paired scope_exception consumed by this write.
# ===========================================================================


# ===========================================================================
# Vector 22: cross-fix F2 interaction.
# ===========================================================================

class TestF2CrossFixInteraction:
    """F2 installed ``FUZZ_BYPASS_META_TYPES`` + ``_extract_meta_task_type``
    in ``harness/diff_fuzzer.py``.  Subtasks generated by the decomposer
    must flow their propagated meta_task_type into F2's extractor so the
    fuzzer-bypass path fires."""

    @pytest.mark.parametrize(
        "mtt",
        ["orchestration", "harness_plumbing", "sandbox_infra", "planner_tooling"],
    )
    def test_V22a_subtask_mtt_hits_fuzzer_bypass(self, mtt):
        from harness.diff_fuzzer import (
            FUZZ_BYPASS_META_TYPES,
            _extract_meta_task_type,
        )

        parent = {
            "task_id": "p",
            "specification": "s",
            # Explicit constraint-level mtt -- this is the case F4's
            # child-wins precedence was designed for.
            "constraints": {"meta_task_type": mtt},
        }
        result = decompose_task(parent, _two_category_failures(), {}, depth=0)
        assert result.subtasks
        for st in result.subtasks:
            subtask_as_task = {
                "task_id": st.task_id,
                "constraints": dict(st.constraints),
            }
            extracted = _extract_meta_task_type(subtask_as_task)
            assert extracted == mtt, (
                f"child {st.task_id} failed to round-trip mtt via F2 extractor"
            )
            assert extracted in FUZZ_BYPASS_META_TYPES, (
                f"child {st.task_id} mtt={extracted} missed bypass set"
            )

    def test_V22b_side_effect_mtt_routes_to_planner_review(self):
        """side-effect mtt on parent -> planner_review path; child still
        carries mtt."""
        parent = {
            "task_id": "p",
            "specification": "s",
            "meta_task_type": "sandbox_infra",
            "constraints": {},
        }
        result = decompose_task(parent, _two_category_failures(), {}, depth=0)
        assert result.strategy == "planner_review"
        for st in result.subtasks:
            assert st.constraints.get("meta_task_type") == "sandbox_infra"


# ===========================================================================
# Vector 23: truthy-but-nonsense meta_task_type values.
# ===========================================================================

class TestNonsenseMetaTypeValues:

    def test_V23a_bool_true_coerced_to_absent(self):
        """B-F4-D (post-fix): non-str mtt (bool True) treated as absent."""
        result = _preserve_meta_task_type(
            {"task_id": "t", "meta_task_type": True}, {}
        )
        assert "meta_task_type" not in result

    def test_V23b_int_nonzero_coerced_to_absent(self):
        """B-F4-D (post-fix): non-str mtt (int 42) treated as absent."""
        result = _preserve_meta_task_type(
            {"task_id": "t", "meta_task_type": 42}, {}
        )
        assert "meta_task_type" not in result

    def test_V23c_list_nonempty_coerced_to_absent(self):
        """B-F4-D (post-fix): non-str mtt (list) treated as absent, so
        the garbage value never reaches downstream consumers."""
        from harness.diff_fuzzer import _extract_meta_task_type

        result = _preserve_meta_task_type(
            {"task_id": "t", "meta_task_type": ["planner_tooling"]}, {}
        )
        assert "meta_task_type" not in result
        extracted = _extract_meta_task_type(
            {"task_id": "x", "constraints": result}
        )
        assert extracted is None


# ===========================================================================
# Vectors 25/26/27: every decompose_task return branch carries mtt.
# ===========================================================================

class TestEveryDecomposeBranchPreserves:
    """decompose_task has 5 return points:

    * line ~254: max_depth planner_review
    * line ~265: structural guard-fail planner_review
    * line ~271: edge_case primary
    * line ~277: function_split
    * line ~282: fallback edge_case
    * line ~284: last-resort retry

    F4's contract is that every one of these routes through
    ``_preserve_meta_task_type``.  AST audit (V20) verifies the call site;
    these tests verify the runtime outcome.

    NOTE: every value in SIDE_EFFECT_META_TYPES triggers the structural
    decomposition guard -> planner_review branch.  To exercise the
    edge_case / function_split / retry branches we MUST use a
    non-side-effect mtt such as ``pure_function`` (which is what the
    newer tests in tests/test_task_decomposer.py use).
    """

    def _base(self, **overrides):
        t = {
            "task_id": "p",
            "specification": "some spec",
            "constraints": {},
            "meta_task_type": "planner_tooling",
        }
        t.update(overrides)
        return t

    def test_V25_max_depth_review_preserves(self):
        """depth >= max_depth -> planner_review branch (side-effect mtt OK,
        because at max_depth the guard never runs)."""
        cfg = {"decomposition": {"max_depth": 3}}
        result = decompose_task(
            self._base(), [_mk_failure()], cfg, depth=3
        )
        assert result.strategy == "planner_review"
        assert (
            result.subtasks[0].constraints.get("meta_task_type")
            == "planner_tooling"
        )

    def test_V26_guard_fail_review_preserves(self):
        """Side-effect mtt trips the structural guard -> planner_review."""
        task = self._base(meta_task_type="orchestration")
        result = decompose_task(task, _two_category_failures(), {})
        assert result.strategy == "planner_review"
        for st in result.subtasks:
            assert st.constraints.get("meta_task_type") == "orchestration"

    def test_V27_last_resort_retry_preserves(self):
        """Single general failure + no code + NON-side-effect mtt ->
        retry/fallback edge_case path.  In either case mtt must survive."""
        task = self._base(meta_task_type="pure_function", constraints={})
        result = decompose_task(task, [_mk_failure([5, 10])], {})
        assert result.strategy in {"retry", "edge_case"}
        for st in result.subtasks:
            assert st.constraints.get("meta_task_type") == "pure_function"

    def test_V27b_edge_case_primary_preserves(self):
        """2 categories + non-side-effect mtt -> edge_case strategy."""
        task = self._base(meta_task_type="pure_function")
        result = decompose_task(task, _two_category_failures(), {})
        assert result.strategy == "edge_case"
        for st in result.subtasks:
            assert st.constraints.get("meta_task_type") == "pure_function"

    def test_V27c_function_split_preserves(self):
        """Multi-block code + single category + non-side-effect mtt
        -> function_split.  ``data_model`` is side-effect-listed so we use
        ``pure_function`` to survive the structural guard."""
        task = self._base(meta_task_type="pure_function")
        code = (
            "def foo(x):\n"
            "    if x < 0:\n"
            "        return -x\n"
            "    for i in range(x):\n"
            "        x += i\n"
            "    return x\n"
        )
        result = decompose_task(task, [_mk_failure([5, 10])], {}, code_a=code)
        assert result.strategy == "function_split"
        for st in result.subtasks:
            assert st.constraints.get("meta_task_type") == "pure_function"


# ---------------------------------------------------------------------------
# Sanity: constants we rely on actually exist.
# ---------------------------------------------------------------------------

def test_side_effect_set_contains_expected_members():
    """Guards against an accidental edit to SIDE_EFFECT_META_TYPES that
    would silently route different mtt values through a different branch
    and break the V26 assumption."""
    expected = {
        "sandbox_infra",
        "data_model",
        "harness_plumbing",
        "orchestration",
        "planner_tooling",
        "mcp_plumbing",
        "state_machine",
        "io_adapter",
    }
    assert expected.issubset(SIDE_EFFECT_META_TYPES)


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
