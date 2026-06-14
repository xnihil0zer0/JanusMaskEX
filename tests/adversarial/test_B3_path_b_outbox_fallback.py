"""Adversarial tests for harness.orchestrator._path_b_outbox_fallback.

Context
-------
B3 #12 / F3 workaround.  When claude-code's `-p` PostToolUse hook drops and
fails to promote `outbox/submission.py` to
`state/sessions/<name>_submission.json`, `_path_b_outbox_fallback` fills the
gap.  It AST-validates the outbox content and atomically writes the canonical
JSON shape `{"code": <src>, "task_id": <tid>}` via tmp+rename.

These tests are hermetic: `tmp_path` for all filesystem state, `monkeypatch`
for injected errors, no subprocess spawns, no network.

Filed under tests/adversarial/ per META allow-list.  No production edits.

Vector coverage (25 vectors from the brief):
 1  happy path                              -> test_v01_happy_path
 2  missing outbox file                     -> test_v02_missing_outbox_file
 3  outbox path doesnt exist at all         -> test_v03_outbox_dir_missing
 4  empty file (0 bytes)                    -> test_v04_empty_file
 5  whitespace-only file                    -> test_v05_whitespace_only_*
 6  syntactically invalid python            -> test_v06_syntax_error_*
 7  SyntaxWarning (valid, only a warning)   -> test_v07_syntax_warning_accepted
 8  only-comments file                      -> test_v08_only_comments_accepted
 9  shebang + valid code                    -> test_v09_shebang_plus_code
10  from __future__ import ...              -> test_v10_future_import
11  non-utf8 bytes                          -> test_v11_non_utf8_bytes (xfail)
12  permission-denied read                  -> test_v12_permission_denied_read
13  permission-denied write on mkdir        -> test_v13_mkdir_permission_denied_still_returns_content
14  concurrent canonical sub_path           -> test_v14_preexisting_sub_path_overwritten
15  large content (1MB+)                    -> test_v15_large_content
16  work_dir doesnt exist                   -> test_v16_work_dir_missing
17  outbox is a directory, not a file       -> test_v17_outbox_is_directory
18  symlink pointing outside work_dir       -> test_v18_symlink_outside_work_dir
19  sub_path parent already exists          -> test_v19_sub_path_parent_exists
20  stale tmp file from prior crash         -> test_v20_stale_tmp_overwritten
21  task_id = ''                            -> test_v21_empty_task_id
22  task_id with special chars              -> test_v22_special_chars_task_id
23  unicode content round-trip              -> test_v23_unicode_content_round_trip
24  idempotency                             -> test_v24_idempotent
25  return value invariant                  -> test_v25_return_value_is_exact_content
"""

from __future__ import annotations

import ast
import json
import os
import stat
import sys
from pathlib import Path

import pytest

# tests/adversarial/ lives two levels under project root
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from harness import orchestrator  # noqa: E402
from harness.orchestrator import _path_b_outbox_fallback  # noqa: E402


# ---------------------------------------------------------------------------
# Shared fixture: plant `outbox/submission.py` with arbitrary bytes/text and
# hand back (work_dir, sub_path, task_id).  Leaves the fallback uncalled so
# each vector can exercise its own pre-conditions.
# ---------------------------------------------------------------------------


@pytest.fixture
def outbox_env(tmp_path):
    """Return a helper that lays down `tmp_path/work/outbox/submission.py`.

    Usage::

        work_dir, sub_path, task_id = outbox_env("print(1)")

    Accepts ``content`` as ``str`` (written via ``write_text``) or ``bytes``
    (written via ``write_bytes``).  Pass ``content=None`` to skip creation
    entirely (simulates missing outbox).
    """

    def _build(content="print(1)", *, task_id="T1", skip_create=False,
               outbox_name="submission.py"):
        work_dir = tmp_path / "work"
        outbox_dir = work_dir / "outbox"
        outbox_dir.mkdir(parents=True, exist_ok=True)
        outbox_path = outbox_dir / outbox_name
        if not skip_create:
            if isinstance(content, bytes):
                outbox_path.write_bytes(content)
            else:
                outbox_path.write_text(content)
        sub_path = tmp_path / "state" / "sessions" / "sess_submission.json"
        return work_dir, sub_path, task_id

    return _build


# ---------------------------------------------------------------------------
# 1. happy path
# ---------------------------------------------------------------------------

def test_v01_happy_path(outbox_env):
    src = "def f(x):\n    return x + 1\n"
    work_dir, sub_path, tid = outbox_env(src, task_id="TASK-42")

    result = _path_b_outbox_fallback(work_dir, sub_path, tid)

    assert result == src
    assert sub_path.is_file()
    payload = json.loads(sub_path.read_text())
    assert payload == {"code": src, "task_id": "TASK-42"}
    # tmp sibling should not linger
    tmp_sibling = sub_path.with_suffix(sub_path.suffix + ".tmp")
    assert not tmp_sibling.exists()


# ---------------------------------------------------------------------------
# 1b. str work_dir (PTY backend) -- _ExitedProc._work_dir is a str, so
#     poll_for_submission passes a str here; the fallback must coerce to Path
#     instead of raising TypeError on ``str / 'outbox'`` (the live agy-fallback bug).
# ---------------------------------------------------------------------------

def test_v01b_str_work_dir_from_pty_backend(outbox_env):
    src = "def f(x):\n    return x + 1\n"
    work_dir, sub_path, tid = outbox_env(src, task_id="PTY-1")

    # the PTY worker's _ExitedProc stamps _work_dir as a plain string
    result = _path_b_outbox_fallback(str(work_dir), sub_path, tid)

    assert result == src
    assert sub_path.is_file()
    assert json.loads(sub_path.read_text()) == {"code": src, "task_id": "PTY-1"}


# ---------------------------------------------------------------------------
# 2. missing outbox file (outbox dir exists, submission.py does not)
# ---------------------------------------------------------------------------

def test_v02_missing_outbox_file(outbox_env):
    work_dir, sub_path, tid = outbox_env(skip_create=True)
    # outbox dir exists, but submission.py does not
    assert (work_dir / "outbox").is_dir()
    assert not (work_dir / "outbox" / "submission.py").exists()

    result = _path_b_outbox_fallback(work_dir, sub_path, tid)

    assert result is None
    assert not sub_path.exists()


# ---------------------------------------------------------------------------
# 3. outbox directory itself doesn't exist
# ---------------------------------------------------------------------------

def test_v03_outbox_dir_missing(tmp_path):
    work_dir = tmp_path / "work_no_outbox"
    work_dir.mkdir()
    sub_path = tmp_path / "state" / "sessions" / "x.json"

    result = _path_b_outbox_fallback(work_dir, sub_path, "T")

    assert result is None
    assert not sub_path.exists()


# ---------------------------------------------------------------------------
# 4. empty file (0 bytes): .strip() guard returns None
# ---------------------------------------------------------------------------

def test_v04_empty_file(outbox_env):
    work_dir, sub_path, tid = outbox_env("")

    result = _path_b_outbox_fallback(work_dir, sub_path, tid)

    assert result is None
    assert not sub_path.exists()


# ---------------------------------------------------------------------------
# 5. whitespace-only file (spaces/tabs/newlines): .strip() guard trips BEFORE
#    ast.parse runs (ast.parse("") would succeed with an empty Module, so the
#    strip-guard is what actually rejects this case).
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("ws", ["   ", "\t\t\t", "\n\n\n", "  \t\n  \t\n"])
def test_v05_whitespace_only_rejected(outbox_env, ws):
    work_dir, sub_path, tid = outbox_env(ws)

    result = _path_b_outbox_fallback(work_dir, sub_path, tid)

    assert result is None
    assert not sub_path.exists()


# ---------------------------------------------------------------------------
# 6. syntactically invalid python
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "bad_src",
    [
        "def f(:\n    pass\n",           # unclosed paren
        "def f():\nreturn 1\n",          # bad indent
        "@@@@\n",                        # stray chars
        "def f(:\n",                     # truncated
        "class C:\n  def m(self\n",      # missing paren/body
    ],
)
def test_v06_syntax_error_rejected(outbox_env, bad_src):
    work_dir, sub_path, tid = outbox_env(bad_src)

    result = _path_b_outbox_fallback(work_dir, sub_path, tid)

    assert result is None
    assert not sub_path.exists()


# ---------------------------------------------------------------------------
# 7. valid python that would only trigger a SyntaxWarning (e.g. `is` with a
#    literal).  ast.parse must NOT raise on these, so the helper must return
#    the content unchanged.
# ---------------------------------------------------------------------------

def test_v07_syntax_warning_accepted(outbox_env):
    # `"foo" is "bar"` triggers SyntaxWarning at compile time but parses fine.
    src = 'def f():\n    return "foo" is "bar"\n'
    # sanity: ast.parse does not raise
    ast.parse(src)

    work_dir, sub_path, tid = outbox_env(src)
    result = _path_b_outbox_fallback(work_dir, sub_path, tid)

    assert result == src
    assert json.loads(sub_path.read_text()) == {"code": src, "task_id": tid}


# ---------------------------------------------------------------------------
# 8. only-comments file: ast.parse returns an empty Module.  The helper only
#    validates parseability, not semantics, so this is accepted.  Documented
#    as a design choice below.
# ---------------------------------------------------------------------------

def test_v08_only_comments_accepted(outbox_env):
    """Design choice: helper validates *parseability*, not semantics.

    A pure-comments file parses to an empty Module, which is valid Python.
    Downstream AST-gates (persist-time, fuzz-time) handle definition presence.
    """
    src = "# just a comment\n# and another\n"
    work_dir, sub_path, tid = outbox_env(src)

    result = _path_b_outbox_fallback(work_dir, sub_path, tid)

    assert result == src
    assert sub_path.is_file()
    assert json.loads(sub_path.read_text())["code"] == src


# ---------------------------------------------------------------------------
# 9. shebang + valid code
# ---------------------------------------------------------------------------

def test_v09_shebang_plus_code(outbox_env):
    src = "#!/usr/bin/env python3\ndef f(x):\n    return x\n"
    work_dir, sub_path, tid = outbox_env(src)

    result = _path_b_outbox_fallback(work_dir, sub_path, tid)

    assert result == src
    assert json.loads(sub_path.read_text()) == {"code": src, "task_id": tid}


# ---------------------------------------------------------------------------
# 10. `from __future__ import ...`
# ---------------------------------------------------------------------------

def test_v10_future_import(outbox_env):
    src = "from __future__ import annotations\n\ndef f(x: int) -> int:\n    return x\n"
    work_dir, sub_path, tid = outbox_env(src)

    result = _path_b_outbox_fallback(work_dir, sub_path, tid)

    assert result == src
    assert json.loads(sub_path.read_text())["code"] == src


# ---------------------------------------------------------------------------
# 11. non-UTF8 bytes: read_text() raises UnicodeDecodeError, which is NOT
#     caught.  This is a latent defect.  Marked xfail(strict=True) so the
#     moment the production fix widens the except clause the xfail flips and
#     we get a notification.
# ---------------------------------------------------------------------------

def test_v11_non_utf8_bytes(outbox_env):
    # 0xff is not valid UTF-8 — helper catches UnicodeDecodeError, fails closed.
    bad = b"\xff\xfe\xfd\xfc def f(): pass\n"
    work_dir, sub_path, tid = outbox_env(bad)

    result = _path_b_outbox_fallback(work_dir, sub_path, tid)

    assert result is None
    assert not sub_path.exists()


# ---------------------------------------------------------------------------
# 12. permission-denied read (PermissionError <: OSError -> caught -> None)
# ---------------------------------------------------------------------------

def test_v12_permission_denied_read(outbox_env, monkeypatch):
    src = "def f():\n    return 1\n"
    work_dir, sub_path, tid = outbox_env(src)
    outbox_path = work_dir / "outbox" / "submission.py"

    real_read_text = Path.read_text

    def fake_read_text(self, *a, **kw):
        if self == outbox_path:
            raise PermissionError(13, "denied", str(self))
        return real_read_text(self, *a, **kw)

    monkeypatch.setattr(Path, "read_text", fake_read_text)

    result = _path_b_outbox_fallback(work_dir, sub_path, tid)

    assert result is None
    assert not sub_path.exists()


# ---------------------------------------------------------------------------
# 13. permission-denied write on sub_path.parent.mkdir: helper logs a warning
#     but still returns the content (write is best-effort; caller can proceed
#     with the in-memory recovered code).
# ---------------------------------------------------------------------------

def test_v13_mkdir_permission_denied_still_returns_content(
    outbox_env, monkeypatch, caplog
):
    src = "def f():\n    return 1\n"
    work_dir, sub_path, tid = outbox_env(src)

    real_mkdir = Path.mkdir

    def fake_mkdir(self, *a, **kw):
        if self == sub_path.parent:
            raise PermissionError(13, "denied", str(self))
        return real_mkdir(self, *a, **kw)

    monkeypatch.setattr(Path, "mkdir", fake_mkdir)

    with caplog.at_level("WARNING", logger="janusmask.orchestrator"):
        result = _path_b_outbox_fallback(work_dir, sub_path, tid)

    # best-effort: content is still recovered
    assert result == src
    # canonical was not written
    assert not sub_path.exists()
    # warning logged
    assert any("Path-B fallback" in rec.message for rec in caplog.records)


# ---------------------------------------------------------------------------
# 14. pre-existing canonical sub_path: helper overwrites (tmp+rename is
#     atomic, last-writer-wins).  Documented as intentional: the fallback
#     path is only taken when poll_for_submission didn't see the canonical
#     shape, so overwriting a stale/partial file is safe.
# ---------------------------------------------------------------------------

def test_v14_preexisting_sub_path_overwritten(outbox_env):
    src = "def new(): return 'new'\n"
    work_dir, sub_path, tid = outbox_env(src, task_id="NEW")
    sub_path.parent.mkdir(parents=True, exist_ok=True)
    sub_path.write_text(json.dumps({"code": "def old(): return 'old'\n",
                                    "task_id": "OLD"}))

    result = _path_b_outbox_fallback(work_dir, sub_path, tid)

    assert result == src
    payload = json.loads(sub_path.read_text())
    assert payload == {"code": src, "task_id": "NEW"}


# ---------------------------------------------------------------------------
# 15. large content (1MB+)
# ---------------------------------------------------------------------------

def test_v15_large_content(outbox_env):
    # Build ~1.2MB of valid python: a function with a large docstring.
    body = "a" * (1_200_000)
    src = f'def f():\n    """{body}"""\n    return 1\n'
    assert len(src) > 1_000_000

    work_dir, sub_path, tid = outbox_env(src)
    result = _path_b_outbox_fallback(work_dir, sub_path, tid)

    assert result == src
    assert sub_path.is_file()
    payload = json.loads(sub_path.read_text())
    assert payload["code"] == src
    assert payload["task_id"] == tid


# ---------------------------------------------------------------------------
# 16. work_dir doesn't exist at all -> is_file() False -> None (no crash)
# ---------------------------------------------------------------------------

def test_v16_work_dir_missing(tmp_path):
    work_dir = tmp_path / "does_not_exist"  # never created
    sub_path = tmp_path / "state" / "sessions" / "x.json"

    result = _path_b_outbox_fallback(work_dir, sub_path, "T")

    assert result is None
    assert not sub_path.exists()


# ---------------------------------------------------------------------------
# 17. outbox/submission.py is a directory, not a file
# ---------------------------------------------------------------------------

def test_v17_outbox_is_directory(tmp_path):
    work_dir = tmp_path / "work"
    (work_dir / "outbox" / "submission.py").mkdir(parents=True)
    sub_path = tmp_path / "state" / "sessions" / "x.json"

    result = _path_b_outbox_fallback(work_dir, sub_path, "T")

    assert result is None
    assert not sub_path.exists()


# ---------------------------------------------------------------------------
# 18. symlink at outbox/submission.py pointing outside work_dir.  is_file()
#     follows symlinks, so if the target is readable + parseable the helper
#     will promote it.  Documented as a lower-severity followup: work_dir is
#     UUID-namespaced so only the agent can plant symlinks, and we'd be
#     promoting the linked content either way.
# ---------------------------------------------------------------------------

def test_v18_symlink_outside_work_dir(tmp_path):
    # external target outside work_dir
    external = tmp_path / "external_src.py"
    external_src = "def external():\n    return 99\n"
    external.write_text(external_src)

    work_dir = tmp_path / "work"
    outbox_dir = work_dir / "outbox"
    outbox_dir.mkdir(parents=True)
    link = outbox_dir / "submission.py"
    try:
        link.symlink_to(external)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks not supported on this platform")

    sub_path = tmp_path / "state" / "sessions" / "x.json"
    result = _path_b_outbox_fallback(work_dir, sub_path, "T")

    # FOLLOWUP: symlink is followed. Documented as lower-severity because
    # work_dir is UUID-namespaced per-agent.  This test pins the current
    # behaviour so an intentional tightening would surface as a test change.
    assert result == external_src
    assert json.loads(sub_path.read_text())["code"] == external_src


# ---------------------------------------------------------------------------
# 19. sub_path parent already exists (common happy-path): mkdir(exist_ok=True)
#     must not raise.
# ---------------------------------------------------------------------------

def test_v19_sub_path_parent_exists(outbox_env):
    work_dir, sub_path, tid = outbox_env("def g(): return 0\n")
    sub_path.parent.mkdir(parents=True, exist_ok=True)  # pre-create
    # pre-exists: no error on call
    result = _path_b_outbox_fallback(work_dir, sub_path, tid)
    assert result == "def g(): return 0\n"
    assert sub_path.is_file()


# ---------------------------------------------------------------------------
# 20. stale tmp file from a prior crashed run: tmp.write_text overwrites ->
#     safe atomic replace.
# ---------------------------------------------------------------------------

def test_v20_stale_tmp_overwritten(outbox_env):
    src = "def ok(): return 1\n"
    work_dir, sub_path, tid = outbox_env(src)
    sub_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_sibling = sub_path.with_suffix(sub_path.suffix + ".tmp")
    tmp_sibling.write_text("STALE GARBAGE FROM PRIOR CRASH")

    result = _path_b_outbox_fallback(work_dir, sub_path, tid)

    assert result == src
    assert sub_path.is_file()
    # tmp was renamed over sub_path; no stale sibling remaining
    assert not tmp_sibling.exists()
    payload = json.loads(sub_path.read_text())
    assert payload == {"code": src, "task_id": tid}


# ---------------------------------------------------------------------------
# 21. task_id = ''
# ---------------------------------------------------------------------------

def test_v21_empty_task_id(outbox_env):
    src = "def f(): return 1\n"
    work_dir, sub_path, tid = outbox_env(src, task_id="")

    result = _path_b_outbox_fallback(work_dir, sub_path, "")

    assert result == src
    payload = json.loads(sub_path.read_text())
    assert payload == {"code": src, "task_id": ""}


# ---------------------------------------------------------------------------
# 22. task_id with special characters (newline, quote, backslash, unicode)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "tid",
    [
        "line1\nline2",
        'quote"inside',
        "back\\slash",
        "tab\there",
        "unicode-\u2603-snowman",
        "\x00null\x00",
    ],
)
def test_v22_special_chars_task_id(outbox_env, tid):
    src = "def f(): return 1\n"
    work_dir, sub_path, _ = outbox_env(src)

    result = _path_b_outbox_fallback(work_dir, sub_path, tid)

    assert result == src
    payload = json.loads(sub_path.read_text())
    assert payload["code"] == src
    assert payload["task_id"] == tid


# ---------------------------------------------------------------------------
# 23. unicode content round-trip
# ---------------------------------------------------------------------------

def test_v23_unicode_content_round_trip(outbox_env):
    # Use BMP + a valid supplementary-plane codepoint (\U...) rather than
    # a surrogate pair, which Python 3 refuses to encode in source.
    src = (
        "# \u2603 snowman\n"
        "def greet():\n"
        "    return '\u4f60\u597d, world \U0001f44b'\n"
    )
    ast.parse(src)  # sanity
    work_dir, sub_path, tid = outbox_env(src)

    result = _path_b_outbox_fallback(work_dir, sub_path, tid)

    assert result == src
    payload = json.loads(sub_path.read_text())
    assert payload["code"] == src
    assert payload["task_id"] == tid


# ---------------------------------------------------------------------------
# 24. idempotency: calling twice returns the same content; canonical file
#     byte-identical after both invocations.
# ---------------------------------------------------------------------------

def test_v24_idempotent(outbox_env):
    src = "def h(x): return x * 2\n"
    work_dir, sub_path, tid = outbox_env(src, task_id="IDEMP")

    r1 = _path_b_outbox_fallback(work_dir, sub_path, tid)
    bytes1 = sub_path.read_bytes()
    r2 = _path_b_outbox_fallback(work_dir, sub_path, tid)
    bytes2 = sub_path.read_bytes()

    assert r1 == r2 == src
    assert bytes1 == bytes2


# ---------------------------------------------------------------------------
# 25. return value invariant: when the helper returns non-None, the return
#     value equals *exactly* what was in the outbox (no mangling).
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "src",
    [
        "def f(): return 1\n",
        "def f():\n    return 1\n",   # no trailing newline at end? keep trailing
        "def f():\n\treturn 1\n",     # tab indent
        "def f():\n    pass\n",       # pass
        "def f():\n    return 1",     # no trailing newline
        "\n\ndef f(): return 1\n\n",  # leading/trailing blank lines
    ],
)
def test_v25_return_value_is_exact_content(outbox_env, src):
    work_dir, sub_path, tid = outbox_env(src, task_id="EXACT")

    result = _path_b_outbox_fallback(work_dir, sub_path, tid)

    assert result is not None
    assert result == src
    payload = json.loads(sub_path.read_text())
    assert payload["code"] == src
    assert payload["task_id"] == "EXACT"


# ---------------------------------------------------------------------------
# Sanity: helper lives in orchestrator module and retains the signature the
# test suite pins against.  Catches accidental rename/refactor.
# ---------------------------------------------------------------------------

def test_helper_signature_pinned():
    import inspect
    sig = inspect.signature(orchestrator._path_b_outbox_fallback)
    params = list(sig.parameters.keys())
    assert params == ["work_dir", "sub_path", "task_id"]
