"""Adversarial sub-agent A2 vectors against F2 (harness/diff_fuzzer.py bypass path).

These tests complement tests/adversarial/test_B3_diff_fuzzer_meta_bypass.py
(A1 / base F2 coverage) by probing edge cases the base suite does NOT hit:

- AST discovery ambiguities (class methods, decorators, async, nested-in-if,
  nested-in-function, unicode/non-ASCII identifiers, keyword collisions)
- Non-string / malformed code inputs (empty, bytes-as-str-ish, giant input)
- Malformed `task` payload shapes for `_extract_meta_task_type`
- Case-sensitivity / whitespace / None handling of meta_task_type values
- Multi-module source, module-level state immutability, concurrency
- Serialisation of `FuzzResult.skipped_reason` via orchestrator persistence
- Round-trip regression for a permissive meta_type with fully-defined target

Filed under tests/adversarial/ per META allow-list.  No production writes.
Each test is hermetic and budgets <5s wall time.
"""

from __future__ import annotations

import ast
import importlib
import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

# tests/adversarial/ is two levels under project root
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from harness.diff_fuzzer import (  # noqa: E402
    FUZZ_BYPASS_META_TYPES,
    FuzzResult,
    _code_defines_function,
    _extract_meta_task_type,
    fuzz_from_task,
)


# ---------------------------------------------------------------------------
# Shared fast fuzz config.  Different filesystem_root from the sibling suite
# so parallel test runs never collide on /tmp.
# ---------------------------------------------------------------------------


@pytest.fixture
def fast_config(tmp_path):
    return {
        "fuzzing": {
            "function_level_inputs": 4,
            "float_tolerance": 1e-9,
            "seed": 17,
            "timeout_per_input_ms": 1000,
        },
        "sandbox": {
            "memory_limit_mb": 256,
            "cpu_time_limit_seconds": 5,
            "filesystem_root": str(tmp_path / "sb_f2_adv"),
        },
        "batch_execution": {"enabled": False},
    }


# ---------------------------------------------------------------------------
# Vector 1: class-method shadowing module-level function
# ---------------------------------------------------------------------------


class TestFunctionVsClassMethod:
    """code_a: target is a class METHOD; code_b: target is module-level.

    ast.walk visits every descendant FunctionDef, so the method WILL be
    counted by `_code_defines_function`.  That is current documented
    behaviour — assert it precisely so a future stricter implementation
    is forced to update this test.
    """

    def test_class_method_currently_counts_as_defined(self):
        code = (
            "class Foo:\n"
            "    def should_bypass_fuzzer(self, task):\n"
            "        return True\n"
        )
        # ast.walk() recurses through the class body, so method matches.
        assert _code_defines_function(code, "should_bypass_fuzzer") is True

    def test_module_level_only_also_detected(self):
        code = "def should_bypass_fuzzer(task):\n    return True\n"
        assert _code_defines_function(code, "should_bypass_fuzzer") is True

    def test_class_only_a_module_only_b_fuzz_from_task_no_error(self, fast_config):
        """Both "have" the name, so fuzz_from_task will attempt normal fuzz.
        The differential_fuzz path may fail building inputs against a method
        that requires a bound ``self`` — we only assert it does NOT raise at
        the top level and does NOT surface a "not found" error.
        """
        code_a = (
            "class Foo:\n"
            "    def should_bypass_fuzzer(self, task: int) -> int:\n"
            "        return task\n"
        )
        code_b = "def should_bypass_fuzzer(task: int) -> int:\n    return task\n"
        task = {
            "task_id": "VEC-1",
            "meta_task_type": "planner_tooling",
            "constraints": {"function_signature": "def should_bypass_fuzzer(task: int) -> int"},
        }
        result = fuzz_from_task(code_a, code_b, task, fast_config, session_id="vec1")
        # Because both sides "have" the name per AST walk, we do NOT enter
        # the bypass/skip branch; the real fuzzer runs.  The assertion is
        # that we didn't crash with "Function not found in code".
        assert isinstance(result, FuzzResult)
        if result.error is not None:
            assert "not found" not in result.error.lower()


# ---------------------------------------------------------------------------
# Vector 2: decorator-wrapped target
# ---------------------------------------------------------------------------


class TestDecoratorWrappedTarget:
    def test_lru_cache_decorated_function_detected(self):
        code = (
            "import functools\n"
            "@functools.lru_cache(maxsize=None)\n"
            "def should_bypass_fuzzer(task):\n"
            "    return True\n"
        )
        # Decorators do not change the FunctionDef node identity; should match.
        assert _code_defines_function(code, "should_bypass_fuzzer") is True

    def test_multiple_stacked_decorators_detected(self):
        code = (
            "def deco1(fn): return fn\n"
            "def deco2(fn): return fn\n"
            "@deco1\n@deco2\n"
            "def target(x): return x\n"
        )
        assert _code_defines_function(code, "target") is True


# ---------------------------------------------------------------------------
# Vector 3: async variants
# ---------------------------------------------------------------------------


class TestAsyncTarget:
    def test_async_def_detected(self):
        assert _code_defines_function("async def target(x): return x\n", "target") is True

    def test_async_with_decorator_detected(self):
        code = (
            "import functools\n"
            "def noop(fn): return fn\n"
            "@noop\n"
            "async def target(x):\n    return x\n"
        )
        assert _code_defines_function(code, "target") is True

    def test_async_one_sided_planner_tooling_skips(self, fast_config):
        code_a = "async def should_bypass_fuzzer(task): return True\n"
        code_b = "def unrelated(): pass\n"
        task = {
            "task_id": "VEC-3-ASYNC",
            "meta_task_type": "planner_tooling",
            "constraints": {"function_signature": "def should_bypass_fuzzer(task) -> bool"},
        }
        result = fuzz_from_task(code_a, code_b, task, fast_config, session_id="vec3_async")
        assert result.error is None
        assert result.equivalent is True
        assert result.skipped_reason is not None
        assert "one side only" in result.skipped_reason


# ---------------------------------------------------------------------------
# Vector 4: nested-function scoping
# ---------------------------------------------------------------------------


class TestNestedDefinitions:
    def test_function_nested_inside_if_counts(self):
        """Top-level conditional def — ast.walk visits it.  Document current
        behaviour.  If this becomes undesirable, the helper needs stricter
        top-level filtering; this test will then fail and signal that pivot.
        """
        code = (
            "import sys\n"
            "if sys.version_info >= (3, 8):\n"
            "    def target():\n        return 1\n"
        )
        assert _code_defines_function(code, "target") is True

    def test_function_nested_inside_function_counts(self):
        """Inner-only definition: ast.walk still finds it.  Current
        behaviour; asserted so a switch to top-level-only discovery is
        forced to update this test.
        """
        code = (
            "def outer():\n"
            "    def target():\n"
            "        return 1\n"
            "    return target\n"
        )
        assert _code_defines_function(code, "target") is True

    def test_function_nested_inside_try_counts(self):
        code = (
            "try:\n"
            "    def target():\n        return 1\n"
            "except Exception:\n"
            "    pass\n"
        )
        assert _code_defines_function(code, "target") is True


# ---------------------------------------------------------------------------
# Vector 5 & 6: malformed / degenerate code inputs
# ---------------------------------------------------------------------------


class TestDegenerateCodeInputs:
    def test_string_only_code_module_is_miss(self):
        assert _code_defines_function('"""just a docstring"""\n', "anything") is False

    def test_syntactically_invalid_code_returns_false_not_raises(self):
        # Base suite covers `def foo(: pass`; here we pick a different
        # broken construct (unterminated string) to triangulate.
        assert _code_defines_function('def target(: "unterminated\n', "target") is False

    def test_tab_indent_error_returns_false(self):
        # Mixed tabs/spaces in 3.13+ raises TabError (SyntaxError subclass).
        code = "def outer():\n\tif True:\n        def target():\n            pass\n"
        # We don't care about the True/False value here so long as no
        # uncaught exception escapes.
        result = _code_defines_function(code, "target")
        assert result in (True, False)

    def test_null_byte_in_code_returns_false(self):
        # Python's compile() rejects source containing null bytes.
        assert _code_defines_function("def target():\x00 pass\n", "target") is False

    def test_extremely_short_code(self):
        assert _code_defines_function("x", "target") is False
        assert _code_defines_function("\n", "target") is False

    def test_not_a_string_is_graceful(self):
        """Non-string input: ast.parse raises TypeError, not SyntaxError.

        F2's helper only catches SyntaxError.  We document current
        behaviour via xfail so a hardening pass (catch Exception /
        TypeError) picks it up.
        """
        try:
            result = _code_defines_function(None, "target")  # type: ignore[arg-type]
        except Exception as exc:
            pytest.xfail(
                f"_code_defines_function(None, ...) raised {type(exc).__name__}; "
                "hardening: catch broader Exception or coerce to str. "
                "BLOCKER-F2-A2-01 (severity: low, defensive-programming)."
            )
        else:
            assert result is False


# ---------------------------------------------------------------------------
# Vector 7: unicode / non-ASCII identifiers
# ---------------------------------------------------------------------------


class TestUnicodeTargets:
    def test_non_ascii_target_detected(self):
        code = "def éclair(x):\n    return x\n"
        assert _code_defines_function(code, "éclair") is True

    def test_eszett_target_detected(self):
        code = "def should_bypass_fuzzer_ß(x):\n    return x\n"
        assert _code_defines_function(code, "should_bypass_fuzzer_ß") is True

    def test_non_ascii_target_missing_returns_false(self):
        code = "def plain_name():\n    pass\n"
        assert _code_defines_function(code, "éclair") is False


# ---------------------------------------------------------------------------
# Vector 8: case-sensitivity of target lookup
# ---------------------------------------------------------------------------


class TestCaseSensitivity:
    def test_uppercase_target_does_not_match_lowercase_def(self):
        code = "def should_bypass_fuzzer(task):\n    return True\n"
        assert _code_defines_function(code, "Should_Bypass_Fuzzer") is False
        assert _code_defines_function(code, "SHOULD_BYPASS_FUZZER") is False

    def test_camelcase_mismatch(self):
        code = "def should_bypass_fuzzer(task):\n    return True\n"
        assert _code_defines_function(code, "shouldBypassFuzzer") is False


# ---------------------------------------------------------------------------
# Vector 9: Python keyword collisions in target-name slot
# ---------------------------------------------------------------------------


class TestKeywordCollision:
    def test_keyword_target_name_never_matches_anything(self):
        """`in`, `class`, `def` can never be function names in valid Python,
        so _code_defines_function should always return False and must not
        be tricked into treating them specially.
        """
        code = "def legit():\n    return 1\n"
        for kw in ("in", "class", "def", "return", "if", "for"):
            assert _code_defines_function(code, kw) is False, f"keyword {kw!r} leaked"


# ---------------------------------------------------------------------------
# Vector 10 & 11: malformed meta_task_type values
# ---------------------------------------------------------------------------


class TestExtractMetaTaskTypeMalformed:
    def test_list_meta_task_type_treated_as_absent(self):
        assert _extract_meta_task_type({"meta_task_type": ["planner_tooling"]}) is None

    def test_dict_meta_task_type_treated_as_absent(self):
        assert _extract_meta_task_type({"meta_task_type": {"kind": "planner_tooling"}}) is None

    def test_int_meta_task_type_treated_as_absent(self):
        assert _extract_meta_task_type({"meta_task_type": 42}) is None

    def test_bool_meta_task_type_treated_as_absent(self):
        # bool is a subclass of int; the helper rejects non-str.
        assert _extract_meta_task_type({"meta_task_type": True}) is None

    def test_bytes_meta_task_type_treated_as_absent(self):
        assert _extract_meta_task_type({"meta_task_type": b"planner_tooling"}) is None

    def test_uppercase_value_not_leniently_bypassed(self, fast_config):
        """FUZZ_BYPASS_META_TYPES entries are lower-case; comparison is
        exact.  'PLANNER_TOOLING' (upper) must NOT bypass, even though the
        semantic intent is identical.  Documents the exact-match contract.
        """
        code_a = "def helper_a(): pass\n"
        code_b = "def helper_b(): pass\n"
        task = {
            "task_id": "VEC-11",
            "meta_task_type": "PLANNER_TOOLING",
            "constraints": {
                "function_signature": "def should_bypass_fuzzer(task) -> bool"
            },
        }
        result = fuzz_from_task(code_a, code_b, task, fast_config, session_id="vec11")
        assert result.equivalent is False
        assert result.error is not None
        assert result.skipped_reason is None

    def test_whitespace_padded_value_not_bypassed(self, fast_config):
        """' planner_tooling ' (padded with whitespace) must not bypass —
        contract is exact-match after minimal coercion.  Documents the
        current behaviour: a whitespace typo breaks the bypass.
        """
        code_a = "def helper_a(): pass\n"
        code_b = "def helper_b(): pass\n"
        task = {
            "task_id": "VEC-11-WS",
            "meta_task_type": " planner_tooling ",
            "constraints": {
                "function_signature": "def should_bypass_fuzzer(task) -> bool"
            },
        }
        result = fuzz_from_task(code_a, code_b, task, fast_config, session_id="vec11ws")
        assert result.equivalent is False
        assert result.error is not None


class TestExtractMetaTaskTypeNesting:
    def test_dual_level_task_wins_even_if_constraints_better(self):
        """If both levels are set but only task-level is non-bypass, bypass
        should NOT trigger — task-level wins.
        """
        task = {
            "meta_task_type": "content_fix",  # NOT in bypass set
            "constraints": {"meta_task_type": "planner_tooling"},
        }
        assert _extract_meta_task_type(task) == "content_fix"

    def test_empty_string_task_level_falls_back_to_constraints(self):
        """`"" or None` at task-level should defer to constraints."""
        task = {
            "meta_task_type": "",
            "constraints": {"meta_task_type": "sandbox_infra"},
        }
        assert _extract_meta_task_type(task) == "sandbox_infra"

    def test_constraints_none_and_task_none_returns_none(self):
        assert _extract_meta_task_type({"meta_task_type": None, "constraints": None}) is None


# ---------------------------------------------------------------------------
# Vector 14: multi-module / concatenated source
# ---------------------------------------------------------------------------


class TestMultipleModulesJoined:
    def test_two_modules_concatenated_both_discoverable(self):
        code = (
            "# module A\n"
            "def first(x):\n    return x\n"
            "\n"
            "# module B\n"
            "def second(y):\n    return y\n"
        )
        assert _code_defines_function(code, "first") is True
        assert _code_defines_function(code, "second") is True


# ---------------------------------------------------------------------------
# Vector 15: explicit non-permissive still raises / errors
# ---------------------------------------------------------------------------


class TestNonPermissiveStillErrors:
    def test_explicit_content_fix_meta_type_both_missing_errors(self, fast_config):
        """`meta_task_type="content_fix"` + target absent both sides:
        fuzz_from_task must propagate an error, NOT skip.
        """
        code_a = "def helper_a(): pass\n"
        code_b = "def helper_b(): pass\n"
        task = {
            "task_id": "CONTENT-FIX-001",
            "meta_task_type": "content_fix",
            "constraints": {
                "function_signature": "def compute_answer(x: int) -> int"
            },
        }
        result = fuzz_from_task(code_a, code_b, task, fast_config, session_id="content_fix_miss")
        assert result.equivalent is False
        assert result.error is not None
        assert "compute_answer" in result.error
        assert result.skipped_reason is None


# ---------------------------------------------------------------------------
# Vector 16 & 17: skipped_reason property
# ---------------------------------------------------------------------------


class TestSkippedReasonInvariant:
    @pytest.mark.parametrize(
        "meta_type,code_a,code_b,expect_skip",
        [
            ("planner_tooling", "def a(): pass\n", "def b(): pass\n", True),
            ("orchestration", "def a(): pass\n", "def b(): pass\n", True),
            ("harness_plumbing", "def a(): pass\n", "def b(): pass\n", True),
            ("sandbox_infra", "def a(): pass\n", "def b(): pass\n", True),
            # Non-bypass meta_type → error path, skipped_reason MUST be None
            ("content_fix", "def a(): pass\n", "def b(): pass\n", False),
            (None, "def a(): pass\n", "def b(): pass\n", False),
        ],
    )
    def test_skipped_reason_exclusive_to_skip_paths(
        self, fast_config, meta_type, code_a, code_b, expect_skip
    ):
        task = {
            "task_id": f"INV-{meta_type}",
            "constraints": {
                "function_signature": "def missing_target(x: int) -> int"
            },
        }
        if meta_type is not None:
            task["meta_task_type"] = meta_type
        result = fuzz_from_task(code_a, code_b, task, fast_config, session_id=f"inv_{meta_type}")
        if expect_skip:
            assert result.equivalent is True
            assert result.error is None
            assert result.skipped_reason is not None
        else:
            assert result.equivalent is False
            assert result.error is not None
            assert result.skipped_reason is None


# ---------------------------------------------------------------------------
# Vector 18: `_persist_fuzz_results` does NOT serialize skipped_reason
# ---------------------------------------------------------------------------


class TestSkippedReasonSerialization:
    def test_persist_fuzz_results_omits_skipped_reason_xfail(self, tmp_path):
        """F2-agent followup (c): `_persist_fuzz_results` in harness/orchestrator.py
        does not include skipped_reason in the JSON summary, so downstream
        log/audit consumers cannot distinguish a real pass from a policy skip
        without re-reading the FuzzResult object.  Track as BLOCKER-F2-A2-02
        (severity: low / cosmetic).  Xfail until fixed.
        """
        from harness.orchestrator import _persist_fuzz_results

        state_dir = tmp_path / "state"
        state_dir.mkdir()
        (state_dir.parent / "logs").mkdir(exist_ok=True)

        result = FuzzResult(
            equivalent=True,
            skipped_reason="synthetic reason for assertion",
        )
        _persist_fuzz_results(state_dir, "T-SKIP", "round1", result)

        out_path = state_dir.parent / "logs" / "fuzz_results" / "T-SKIP_round1.json"
        assert out_path.exists()
        summary = json.loads(out_path.read_text())
        if "skipped_reason" not in summary:
            pytest.xfail(
                "_persist_fuzz_results does not serialize skipped_reason. "
                "BLOCKER-F2-A2-02 (severity: low, cosmetic). "
                "Fix: add 'skipped_reason': result.skipped_reason to the "
                "summary dict at harness/orchestrator.py L649."
            )
        assert summary["skipped_reason"] == "synthetic reason for assertion"


# ---------------------------------------------------------------------------
# Vector 19: FUZZ_BYPASS_META_TYPES module-level state immutability
# ---------------------------------------------------------------------------


class TestBypassSetImmutability:
    def test_bypass_set_is_frozenset(self):
        """Module-level constant must be immutable — otherwise concurrent
        `fuzz_from_task` calls with different meta_types could race a
        mutation (.add()/.remove()) on each other's ground truth.
        """
        assert isinstance(FUZZ_BYPASS_META_TYPES, frozenset)

    def test_bypass_set_rejects_mutation(self):
        """Sanity: frozenset has no `.add`."""
        assert not hasattr(FUZZ_BYPASS_META_TYPES, "add")
        assert not hasattr(FUZZ_BYPASS_META_TYPES, "remove")

    def test_concurrent_fuzz_from_task_stable_state(self, fast_config):
        """Race 16 fuzz_from_task invocations with mixed meta_types from a
        thread pool.  FUZZ_BYPASS_META_TYPES content must match exactly
        before and after (no mutation, no new entries, no drops).
        """
        snapshot = frozenset(FUZZ_BYPASS_META_TYPES)

        def worker(mtype: str):
            task = {
                "task_id": f"RACE-{mtype}",
                "meta_task_type": mtype,
                "constraints": {
                    "function_signature": "def absent_target(x: int) -> int"
                },
            }
            code_a = "def helper_a(): pass\n"
            code_b = "def helper_b(): pass\n"
            return fuzz_from_task(code_a, code_b, task, fast_config, session_id=f"race_{mtype}")

        types = list(FUZZ_BYPASS_META_TYPES) * 4 + ["content_fix"] * 4  # 20 calls
        with ThreadPoolExecutor(max_workers=8) as pool:
            list(pool.map(worker, types))

        assert frozenset(FUZZ_BYPASS_META_TYPES) == snapshot


# ---------------------------------------------------------------------------
# Vector 20: performance guard — huge function count + missing target
# ---------------------------------------------------------------------------


class TestPerformanceBound:
    def test_thousands_of_unrelated_defs_fast_miss(self):
        """10k unrelated defs, target absent.  Must return in well under 1s.

        Bound is intentionally loose (500ms) to tolerate CI jitter.  A
        regression to O(n^2) or to string-scanning would blow past it.
        """
        code = "\n".join(f"def helper_{i}(x): return x" for i in range(10_000)) + "\n"
        start = time.perf_counter()
        found = _code_defines_function(code, "missing_target")
        elapsed = time.perf_counter() - start
        assert found is False
        assert elapsed < 0.5, f"_code_defines_function too slow ({elapsed:.3f}s)"


# ---------------------------------------------------------------------------
# Vector 22: dynamically-declared target (exec) — NOT discoverable
# ---------------------------------------------------------------------------


class TestDynamicTargetUndiscoverable:
    def test_exec_defined_function_not_seen_by_ast(self):
        code = 'exec("def target(x): return x")\n'
        # ast.walk never executes the exec() call; target never appears
        # as a FunctionDef node in this module's AST.
        assert _code_defines_function(code, "target") is False

    def test_type_dynamic_class_method_not_seen(self):
        code = 'T = type("T", (), {"target": lambda self: None})\n'
        # Lambdas are not FunctionDef nodes; the assignment's RHS is a Call.
        assert _code_defines_function(code, "target") is False

    def test_lambda_assigned_not_seen_as_functiondef(self):
        code = "target = lambda x: x\n"
        # Module-level `target = lambda ...` is an Assign with a Lambda node,
        # NOT a FunctionDef.  Must return False.
        assert _code_defines_function(code, "target") is False


# ---------------------------------------------------------------------------
# Vector 23: decorated class + method on second class — cross-check
# ---------------------------------------------------------------------------


class TestDecoratedClassMethodCrossCheck:
    def test_dataclass_plus_second_class_method(self):
        code = (
            "from dataclasses import dataclass\n"
            "@dataclass\n"
            "class Foo:\n    pass\n"
            "class Bar:\n"
            "    def target(self, x):\n"
            "        return x\n"
        )
        assert _code_defines_function(code, "target") is True
        # Foo has no `target` method of its own — but ast.walk doesn't
        # scope by class, so matching is still True.  Document behaviour:
        assert _code_defines_function(code, "Foo") is False  # class name, not a def


# ---------------------------------------------------------------------------
# Vector 24: round-trip — permissive meta_type, target fully defined both
# sides.  Must go through the REAL fuzzer, NOT the bypass branch.
# ---------------------------------------------------------------------------


class TestRoundTripPermissiveBothDefined:
    def test_planner_tooling_both_defined_runs_real_fuzzer(self, fast_config):
        code = (
            "def should_bypass_fuzzer(x: int) -> int:\n    return x + 1\n"
        )
        task = {
            "task_id": "ROUND-TRIP-1",
            "meta_task_type": "planner_tooling",
            "constraints": {
                "function_signature": "def should_bypass_fuzzer(x: int) -> int"
            },
        }
        result = fuzz_from_task(code, code, task, fast_config, session_id="rt_both_defined")
        # Real fuzz happened: skipped_reason must be None.
        assert result.skipped_reason is None
        # Equivalent (same code both sides).
        assert result.equivalent is True
        # Evidence of real fuzzing:
        assert result.total_inputs > 0


# ---------------------------------------------------------------------------
# Vector 25: meta_task_type only at top-level, constraints is a LIST
# ---------------------------------------------------------------------------


class TestTaskShapeResilience:
    def test_top_level_meta_type_wins_even_when_constraints_is_list(self, fast_config):
        code_a = "def helper_a(): pass\n"
        code_b = "def helper_b(): pass\n"
        task = {
            "task_id": "SHAPE-1",
            "meta_task_type": "planner_tooling",
            "constraints": ["this", "is", "a", "list"],  # malformed
        }
        # fuzz_from_task treats non-dict constraints as {}, which gives it
        # no function_signature → uses _get_primary_function fallback →
        # helper_a/helper_b available → renames, fuzzes normally.
        # We assert no crash + no "not found" error.
        result = fuzz_from_task(code_a, code_b, task, fast_config, session_id="shape_list")
        assert isinstance(result, FuzzResult)
        if result.error is not None:
            assert "not found" not in result.error.lower()

    def test_empty_task_is_not_bypassed(self, fast_config):
        """An empty task dict: no meta_task_type, no constraints, no sig.
        Both sides have no primary function → original "Could not determine"
        error path fires (skipped_reason None, error set).
        """
        code_a = "x = 1\n"
        code_b = "y = 2\n"
        result = fuzz_from_task(code_a, code_b, {}, fast_config, session_id="shape_empty")
        assert result.equivalent is False
        assert result.error is not None
        assert "target function name" in result.error.lower()
        assert result.skipped_reason is None


# ---------------------------------------------------------------------------
# Sentinel: FuzzResult default invariants
# ---------------------------------------------------------------------------


class TestFuzzResultDefaults:
    def test_default_skipped_reason_is_none(self):
        r = FuzzResult(equivalent=True)
        assert r.skipped_reason is None

    def test_skipped_reason_explicit_kwarg(self):
        r = FuzzResult(equivalent=True, skipped_reason="hi")
        assert r.skipped_reason == "hi"

    def test_skipped_reason_is_str_or_none(self):
        # dataclass does NOT enforce type at runtime, but the annotation
        # declares `str | None`.  We assert the class's __annotations__
        # reflect that contract for downstream tooling.
        ann = FuzzResult.__annotations__.get("skipped_reason", "")
        # Must mention str and None / Optional
        assert "str" in ann
        assert "None" in ann or "Optional" in ann
