"""Contract: structured-input fuzz synthesis (ast.* nodes + pathlib.Path).

For a clean-room rebuild we possess the original, so the merged==original fuzz is
ground truth. The base strategy table only synthesized primitives/containers; an
``ast.*``/``Path``-typed param fell through to a garbage-int fallback that
FALSE-diverged a faithful body and forced an operator pin. These tests pin the
structured-input synthesis (``diff_fuzzer._ast_strategy_for`` / ``_path_strategy``
+ the sandbox JSON codec round-trip) and the matching ``harvest`` oracle-USABLE
relaxation, so the bulk of the engine's ast/Path-typed predicates rebuild blind on
the fuzz alone with NO hand-written pin.
"""
import ast

import pytest

from harness import diff_fuzzer
from harness.diff_fuzzer import _strategy_for_annotation, differential_fuzz
from harness.rebuild import harvest

pytestmark = pytest.mark.filterwarnings(
    "ignore::hypothesis.errors.NonInteractiveExampleWarning"
)


FAST_CONFIG = {
    "fuzzing": {"function_level_inputs": 40, "seed": 42, "timeout_per_input_ms": 3000},
    "sandbox": {
        "memory_limit_mb": 256,
        "cpu_time_limit_seconds": 5,
        "filesystem_root": "/tmp/janusmask_structured_fuzz_test",
    },
}


class TestAstStrategy:
    @pytest.mark.parametrize(
        "ann,node_type",
        [
            ("ast.FunctionDef", ast.FunctionDef),
            ("ast.AsyncFunctionDef", ast.AsyncFunctionDef),
            ("ast.ClassDef", ast.ClassDef),
            ("ast.Module", ast.Module),
            ("ast.Import", ast.Import),
            ("ast.ImportFrom", ast.ImportFrom),
        ],
    )
    def test_named_node_type_synthesized(self, ann, node_type):
        sample = _strategy_for_annotation(ann).example()
        assert isinstance(sample, node_type)

    def test_abstract_ast_type_yields_ast_node(self):
        # ast.AST / ast.stmt draw from a broad statement mix.
        sample = _strategy_for_annotation("ast.AST").example()
        assert isinstance(sample, ast.AST)

    def test_funcdef_corpus_is_diverse_for_non_vacuity(self):
        # A predicate fuzz must see both pure and impure bodies, else a wrong
        # impurity classifier lands silently.
        srcs = diff_fuzzer._AST_STMT_CORPUS["FunctionDef"]
        assert any(("random" in s) or ("open(" in s) or ("time" in s) for s in srcs)
        assert any(("return a + b" in s) or ("return 1" in s) for s in srcs)


class TestPathStrategy:
    def test_path_synthesized(self):
        import pathlib

        sample = diff_fuzzer._path_strategy().example()
        assert isinstance(sample, pathlib.PurePath)

    def test_path_corpus_spans_test_and_non_test_basenames(self):
        # Non-vacuity for basename predicates (e.g. _is_test_file): the corpus must
        # contain both a ``test_``-prefixed basename and a plain one.
        import pathlib

        basenames = {(pathlib.Path("/tmp/jm_fuzz") / s).name for s in diff_fuzzer._PATH_CORPUS}
        assert any(n.startswith("test_") for n in basenames)
        assert any(not n.startswith("test_") for n in basenames)


class TestSandboxRoundTrip:
    """ast / Path values must survive the JSON codec into BOTH sandbox subprocesses
    and keep the differential MEANINGFUL (equivalent when bodies agree, divergent
    when they don't)."""

    def test_ast_typed_equivalent_when_correct(self):
        code = (
            "import ast\n"
            "def has_return(node: ast.FunctionDef):\n"
            "    return any(isinstance(n, ast.Return) for n in ast.walk(node))\n"
        )
        r = differential_fuzz(code, code, "has_return", FAST_CONFIG, session_id="struct_eq")
        assert r.equivalent is True
        assert r.total_inputs > 0
        assert r.matching_inputs == r.total_inputs

    def test_ast_typed_divergent_when_wrong(self):
        good = (
            "import ast\n"
            "def has_return(node: ast.FunctionDef):\n"
            "    return any(isinstance(n, ast.Return) for n in ast.walk(node))\n"
        )
        bad = "import ast\ndef has_return(node: ast.FunctionDef):\n    return False\n"
        r = differential_fuzz(good, bad, "has_return", FAST_CONFIG, session_id="struct_div")
        assert r.equivalent is False
        assert r.failures

    def test_path_typed_equivalent_when_correct(self):
        code = (
            "import pathlib\n"
            "def is_test(p: pathlib.Path):\n"
            "    return p.name.startswith('test_')\n"
        )
        r = differential_fuzz(code, code, "is_test", FAST_CONFIG, session_id="path_eq")
        assert r.equivalent is True
        assert r.total_inputs > 0

    def test_path_typed_divergent_when_wrong(self):
        good = (
            "import pathlib\n"
            "def is_test(p: pathlib.Path):\n"
            "    return p.name.startswith('test_')\n"
        )
        bad = "import pathlib\ndef is_test(p: pathlib.Path):\n    return False\n"
        r = differential_fuzz(good, bad, "is_test", FAST_CONFIG, session_id="path_div")
        assert r.equivalent is False
        assert r.failures


class TestHarvestRelaxation:
    """The oracle-USABLE classification must stay in lock-step with the synthesizer."""

    @staticmethod
    def _ann(src):
        return ast.parse(src, mode="eval").body

    @staticmethod
    def _fn(src):
        return ast.parse(src).body[0]

    def test_ast_annotation_now_fuzzable(self):
        assert harvest._is_fuzzable_annotation(self._ann("ast.AST")) is True
        assert harvest._is_fuzzable_annotation(self._ann("ast.FunctionDef")) is True

    def test_path_annotation_now_fuzzable(self):
        assert harvest._is_fuzzable_annotation(self._ann("Path")) is True
        assert harvest._is_fuzzable_annotation(self._ann("pathlib.Path")) is True

    def test_unknown_domain_type_still_unfuzzable(self):
        assert harvest._is_fuzzable_annotation(self._ann("TargetDescriptor")) is False
        assert harvest._is_fuzzable_annotation(self._ann("os.PathLike")) is False

    def test_has_unfuzzable_params_false_for_ast_only(self):
        assert harvest._has_unfuzzable_params(self._fn("def f(n: ast.AST):\n    return 1")) is False

    def test_has_unfuzzable_params_false_for_path_only(self):
        assert harvest._has_unfuzzable_params(self._fn("def f(p: Path):\n    return 1")) is False

    def test_has_unfuzzable_params_true_for_real_domain_type(self):
        assert harvest._has_unfuzzable_params(
            self._fn("def f(d: TargetDescriptor):\n    return 1")
        ) is True
