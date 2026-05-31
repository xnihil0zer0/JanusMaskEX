"""AGY2B oracle: tighten the no-fence RAW-TEXT FALLBACK of
``harness.test_author._extract_python_block``.

RED on HEAD: the current fallback ``return text.strip() + '\n'`` returns ANY
un-fenced prose verbatim, so agy/gemini chatter (or a '# Placeholder' reply with
surrounding prose) is written to the outbox as if it were a real submission.

GREEN after the fix: when stdout has NO fenced block, the function returns a
non-empty code string ONLY if the raw text actually parses as Python
(``ast.parse`` succeeds); otherwise it returns '' so the caller
(``spawn_agent``: ``block.strip() and block.strip() != '# Placeholder'``)
treats it as "no submission".

Regression guards (must PASS on HEAD and after):
  - a proper ```python ... ``` (or bare ```) fenced block is extracted verbatim;
  - raw VALID Python with no fence is still returned non-empty (anti-overcorrection).
"""
from harness.test_author import _extract_python_block


def test_extract_python_block_no_fence_non_code_returns_empty():
    """No fence + non-code prose -> '' (no-submission). RED on HEAD."""
    prose = "Sure! Here is the code you asked for:\nLet me know if you need changes."
    out = _extract_python_block(prose)
    # The caller treats a reply as "no submission" iff
    #   block.strip() == '' or block.strip() == '# Placeholder'.
    assert out.strip() == "" or out.strip() == "# Placeholder", (
        f"non-code prose must yield no submission, got {out!r}"
    )

    placeholder = "# Placeholder\nI could not complete this; here is a stub instead."
    out2 = _extract_python_block(placeholder)
    assert out2.strip() == "" or out2.strip() == "# Placeholder", (
        f"placeholder chatter must yield no submission, got {out2!r}"
    )


def test_extract_python_block_fenced_python_still_extracted():
    """REGRESSION: a proper ```python fenced block is extracted verbatim."""
    fenced = (
        "Here is the file:\n```python\nimport pytest\n\n"
        "def test_x():\n    assert 1\n```\nDone."
    )
    out = _extract_python_block(fenced)
    assert out.startswith("import pytest"), out
    assert "```" not in out and "Done." not in out, out
    assert "def test_x" in out, out

    # Bare ``` fence also works.
    bare = "```\nx = 1\n```"
    assert _extract_python_block(bare).strip() == "x = 1"


def test_extract_python_block_no_fence_valid_python_still_returned():
    """REGRESSION / anti-overcorrection: raw valid Python with no fence is
    still returned non-empty (the AGY-FIX edge case: stdout has no markdown
    fence but IS real code)."""
    code = "def f():\n    return 1\n"
    out = _extract_python_block(code)
    assert out.strip() != "", out
    assert "def f" in out, out

    code2 = "def test_y():\n    assert 2\n"
    out2 = _extract_python_block(code2)
    assert "def test_y" in out2, out2
