"""Regression-lock the P0/C9.14 REBUILD-SCOPED restricted str fuzz alphabet (W1).

A pure str transform whose behaviour on pathological astral/exotic unicode is
under-determined (inflection.titleize/pluralize case-folding) makes the two blind
agent drafts -- and the merged==original oracle -- false-diverge, blocking the
rebuild. The fix restricts the str fuzz alphabet to ASCII-printable, but ONLY on
the rebuild path: opt-in via config['rebuild']['fuzz_str_ascii'] (threaded through
the per-unit task to the Claude==Gemini gate, and via oracle.py --str-ascii to the
merged==original gate). The MAIN differential pipeline keeps the full unicode
alphabet and must be byte-for-byte unaffected.
"""

from __future__ import annotations

from pathlib import Path

import harness.diff_fuzzer as df
import harness.rebuild.task as task
from harness.rebuild.harvest import harvest_module
from harness.rebuild.target import TargetDescriptor


def _sample(strategy, n=400):
    return [strategy.example() for _ in range(n)]


def test_str_ascii_strategy_only_emits_ascii_printable():
    import ast
    node = ast.parse("str", mode="eval").body
    s_ascii = df._ast_node_to_strategy(node, str_ascii=True)
    for val in _sample(s_ascii):
        assert isinstance(val, str)
        assert all(32 <= ord(c) <= 126 for c in val), repr(val)


def test_default_strategy_can_emit_non_ascii():
    import ast
    node = ast.parse("str", mode="eval").body
    s_default = df._ast_node_to_strategy(node)
    # The default (full-unicode L/N/P/Z) alphabet must NOT be ASCII-restricted; over
    # a healthy sample at least one non-ASCII codepoint should appear.
    saw_non_ascii = any(
        any(ord(c) > 126 for c in val) for val in _sample(s_default, n=600)
    )
    assert saw_non_ascii, "default str strategy unexpectedly produced only ASCII"


def test_nested_container_str_threads_ascii():
    import ast
    node = ast.parse("list[str]", mode="eval").body
    s = df._ast_node_to_strategy(node, str_ascii=True)
    for lst in _sample(s, n=200):
        for val in lst:
            assert all(32 <= ord(c) <= 126 for c in val), repr(val)


def test_build_input_strategy_threads_str_ascii():
    code = "def f(s: str) -> str:\n    return s\n"
    strat = df.build_input_strategy(code, "f", str_ascii=True)
    for args, _kwargs in _sample(strat, n=200):
        assert all(32 <= ord(c) <= 126 for c in args[0]), repr(args[0])


def test_fuzz_from_task_injects_rebuild_flag(monkeypatch):
    captured = {}

    def fake_diff(code_a, code_b, func_name, config, session_id="default"):
        captured["config"] = config

        class _R:
            error = None
            equivalent = True
        return _R()

    monkeypatch.setattr(df, "differential_fuzz", fake_diff)
    code = "def f(s: str) -> str:\n    return s\n"
    task_spec = {"constraints": {"function_signature": "def f(s: str) -> str:"},
                 "fuzz_str_ascii": True}
    df.fuzz_from_task(code, code, task_spec, {"fuzzing": {}}, session_id="t")
    assert captured["config"].get("rebuild", {}).get("fuzz_str_ascii") is True


def test_fuzz_from_task_main_pipeline_unaffected(monkeypatch):
    captured = {}

    def fake_diff(code_a, code_b, func_name, config, session_id="default"):
        captured["config"] = config

        class _R:
            error = None
            equivalent = True
        return _R()

    monkeypatch.setattr(df, "differential_fuzz", fake_diff)
    code = "def f(s: str) -> str:\n    return s\n"
    # a normal (non-rebuild) task has no fuzz_str_ascii flag -> no rebuild key added.
    df.fuzz_from_task(code, code, {"constraints": {"function_signature": "def f(s: str) -> str:"}},
                      {"fuzzing": {}}, session_id="t")
    assert "rebuild" not in captured["config"]


def _descriptor(tmp_path):
    return TargetDescriptor(
        name="infl", source_root=tmp_path / "src", modules=["infl.py"],
        test_files=["test_infl.py"], output_dir=tmp_path / "out",
        stash_dir=tmp_path / "stash", unit_test_selector="test_infl.py -k {unit}",
    )


def _titleize_unit():
    src = 'def titleize(word: str) -> str:\n    """T."""\n    return word.title()\n'
    return [u for u in harvest_module("infl.py", src, include_methods=True)
            if u.name == "titleize"][0]


def test_build_unit_task_sets_flag_and_oracle_arg(tmp_path):
    d = _descriptor(tmp_path)
    spec = task.build_unit_task(
        descriptor=d, unit=_titleize_unit(), module_rel="infl.py",
        oracle_original_path="/abs/stash/infl.py.orig",
        sibling_signatures=[], unit_test_text="def test_infl_titleize_x(): pass",
        parent_root="/parent", fuzz_str_ascii=True,
    )
    assert spec["fuzz_str_ascii"] is True
    assert "--str-ascii" in spec["verification_command"]


def test_build_unit_task_default_no_str_ascii(tmp_path):
    d = _descriptor(tmp_path)
    spec = task.build_unit_task(
        descriptor=d, unit=_titleize_unit(), module_rel="infl.py",
        oracle_original_path="/abs/stash/infl.py.orig",
        sibling_signatures=[], unit_test_text="def test_infl_titleize_x(): pass",
        parent_root="/parent",
    )
    assert "fuzz_str_ascii" not in spec
    assert "--str-ascii" not in spec["verification_command"]
