"""Oracle for the symbol-patch indented-method fix.

RED on HEAD: the partial-edit pipeline cannot edit an in-place Python class
method because agents emit the symbol ``code`` WITH its class-level indentation
(e.g. ``    def m(self): ...``). ``git_integration._apply_symbol_patch`` and the
``orchestrator._validate_submission`` patch-validation loop both ``ast.parse``
that block as standalone source, which raises ``unexpected indent``.

GREEN after fix: both sites ``textwrap.dedent`` the symbol ``code`` before
parsing (apply re-indents to the located node's ``col_offset``), so an indented
method body round-trips. Already-column-0 top-level symbols are unaffected
(dedent is a no-op), which the regression cases below pin.
"""
import ast
import textwrap

from harness import git_integration
from harness import orchestrator


_CLASS_SRC = textwrap.dedent(
    '''\
    class Foo:
        def bar(self, x):
            return x + 1

        def baz(self):
            return 2
    '''
)


def test_apply_symbol_patch_accepts_indented_method_block():
    # The agent-natural form: the method copied verbatim from the file, i.e.
    # indented 4 spaces under the class. This must round-trip.
    indented = "    def bar(self, x):\n        return x + 99\n"
    out = git_integration._apply_symbol_patch(_CLASS_SRC, "Foo.bar", indented)
    ast.parse(out)  # result is valid Python (no double-indent)
    assert "return x + 99" in out
    assert "    def bar(self, x):" in out          # method at one 4-space level
    assert "        return x + 99" in out          # body at 8 (not 12) spaces
    assert "    def baz(self):" in out             # sibling method preserved


def test_validate_submission_accepts_indented_symbol_patch():
    patch_code = "    def post_planner_kickoff(self, body):\n        return (200, {})\n"
    code = (
        "__JANUSMASK_PATCHES__ = [{'file': 'tools/webui_control.py', "
        "'kind': 'symbol', 'name': 'ControlHandlers.post_planner_kickoff', "
        "'code': %r}]\n" % patch_code
    )
    task = {
        "partial_edit": True,
        "task_id": "oracle_indent",
        "files_touched": ["tools/webui_control.py"],
        "meta_task_type": "refactor",
    }
    ok, violations = orchestrator._validate_submission(code, "claude", task)
    assert ok, [(v.rule, v.message) for v in violations]


def test_apply_symbol_patch_top_level_def_unchanged_regression():
    # Already column-0 top-level symbol: dedent is a no-op; existing behavior
    # must be byte-for-byte intact.
    src = "def a():\n    return 1\n\n\ndef b():\n    return 2\n"
    out = git_integration._apply_symbol_patch(src, "a", "def a():\n    return 100\n")
    ast.parse(out)
    assert "return 100" in out
    assert "def b():" in out


def test_validate_submission_top_level_symbol_patch_regression():
    # Column-0 top-level def patch (the case that already works) must keep working.
    code = (
        "__JANUSMASK_PATCHES__ = [{'file': 'pkg/mod.py', 'kind': 'symbol', "
        "'name': 'helper', 'code': %r}]\n" % "def helper(x):\n    return x\n"
    )
    task = {
        "partial_edit": True,
        "task_id": "oracle_toplevel",
        "files_touched": ["pkg/mod.py"],
        "meta_task_type": "refactor",
    }
    ok, violations = orchestrator._validate_submission(code, "claude", task)
    assert ok, [(v.rule, v.message) for v in violations]
