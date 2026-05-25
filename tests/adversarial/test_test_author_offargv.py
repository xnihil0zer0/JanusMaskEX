"""Regression-lock P3/C9.14d: the live test-author passes its prompt OFF-ARGV.

_default_gen_fn embeds the module SOURCE in the prompt (B7 source-aware author).
Passing that prompt as a ``claude -p <prompt>`` argv element makes a source
>~120KB exceed Linux MAX_ARG_STRLEN (128KB) -> OSError [Errno 7] Argument list too
long, which blocked gen_testless on large test-less modules. The fix passes the
prompt via STDIN (subprocess.run(..., input=prompt)); this test locks that
contract so a refactor can't silently regress to a positional arg.
"""

from __future__ import annotations

import harness.test_author as ta


class _FakeProc:
    returncode = 0
    stdout = "```python\nimport pytest\n\n\ndef test_x():\n    assert True\n```"
    stderr = ""


def test_default_gen_fn_passes_prompt_off_argv(tmp_path, monkeypatch):
    recorded = {}

    def fake_run(cmd, *, input=None, **kw):
        recorded["cmd"] = cmd
        recorded["input"] = input
        return _FakeProc()

    monkeypatch.setattr(ta.subprocess, "run", fake_run)

    big = "X" * 200_000  # well past the 128KB argv ceiling
    test_code, vcmd = ta._default_gen_fn(big, session_dir=tmp_path, attempt=0)

    # the giant prompt must NOT ride in argv ...
    assert all(len(a) < 1000 for a in recorded["cmd"]), "prompt leaked into argv"
    assert big not in recorded["cmd"]
    # ... it must be passed via stdin ...
    assert recorded["input"] is not None and big in recorded["input"]
    # ... and -p is still present (print/stdin mode).
    assert "-p" in recorded["cmd"]
    # return shape preserved: (test_code, verification_command)
    assert "def test_x" in test_code
    assert vcmd == "python -m pytest -q"
