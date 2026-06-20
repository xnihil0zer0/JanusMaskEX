"""RED pytest oracle for ``scripts.brief_status`` CLI rendering.

This module verifies the *observable* behaviour of
``scripts.brief_status.main()`` when it renders the rows produced by
``scripts.brief_status.classify()``.  ``classify`` is monkeypatched to return a
synthetic list of **dicts** -- the row shape the reconciled implementation is
expected to consume -- covering the four leaf states and their CLI labels:

    unplanned -> NEEDS-PLAN
    complete  -> DONE
    blocked   -> PENDING
    zombie    -> ORPHAN-PLAN

Why this oracle is RED today
----------------------------
The un-reconciled ``main()`` treats every row as a 5-tuple: it does
``len(r[0])`` to size the slug column, ``order[r[1]]`` to sort, and
``for slug, status, detail, _b, _p in ...`` to unpack.  Indexing a ``dict`` with
the integer ``0`` raises ``KeyError: 0`` (and positional unpacking would raise
``ValueError``), so ``main()`` crashes before printing anything.  These tests
therefore FAIL against the current code and only pass once ``main()`` consumes
dict rows and maps ``state`` -> label -- i.e. they go GREEN with the fix.

The tests are deliberately non-vacuous: each one drives the real ``main()`` and
asserts on its real return value and captured stdout, so a broken
implementation (or mutant) that returns non-zero, raises, or fails to render a
slug/label is detected.
"""
import sys
import pytest
import scripts.brief_status as brief_status
STATE_LABELS = {'unplanned': 'NEEDS-PLAN', 'complete': 'DONE', 'blocked': 'PENDING', 'zombie': 'ORPHAN-PLAN'}
STATE_SLUGS = {'unplanned': 'alpha-widget', 'complete': 'beta-gadget', 'blocked': 'gamma-engine', 'zombie': 'delta-sprocket'}

def _row(state):
    """Build one synthetic classify() row dict for ``state``."""
    slug = STATE_SLUGS[state]
    return {'slug': slug, 'state': state, 'brief_filename': f'{slug}.brief.md', 'plan_filename': None if state == 'unplanned' else f'{slug}.plan.md', 'remaining': 0 if state == 'complete' else 2}

def _mock_rows():
    """A full synthetic row set covering every required state."""
    return [_row(state) for state in ('unplanned', 'complete', 'blocked', 'zombie')]

def _patch(monkeypatch, rows):
    """Mock classify() -> ``rows`` and argv to the no-``--archive`` invocation.

    monkeypatch records both replacements and undoes them automatically at
    teardown, so neither the module global nor ``sys.argv`` leaks between tests.
    """
    monkeypatch.setattr(brief_status, 'classify', lambda: rows)
    monkeypatch.setattr(sys, 'argv', ['brief_status.py'])

def test_brief_status_cli_render_unplanned(monkeypatch, capsys):
    _patch(monkeypatch, _mock_rows())
    rc = brief_status.main()
    out = capsys.readouterr().out
    assert rc == 0
    assert STATE_SLUGS['unplanned'] in out
    assert 'NEEDS-PLAN' in out

def test_brief_status_cli_render_complete(monkeypatch, capsys):
    _patch(monkeypatch, _mock_rows())
    rc = brief_status.main()
    out = capsys.readouterr().out
    assert rc == 0
    assert STATE_SLUGS['complete'] in out
    assert 'DONE' in out

def test_brief_status_cli_render_blocked(monkeypatch, capsys):
    _patch(monkeypatch, _mock_rows())
    rc = brief_status.main()
    out = capsys.readouterr().out
    assert rc == 0
    assert STATE_SLUGS['blocked'] in out
    assert 'PENDING' in out

def test_brief_status_cli_render_zombie(monkeypatch, capsys):
    _patch(monkeypatch, _mock_rows())
    rc = brief_status.main()
    out = capsys.readouterr().out
    assert rc == 0
    assert STATE_SLUGS['zombie'] in out
    assert 'ORPHAN-PLAN' in out

def test_brief_status_cli_render_no_archive(monkeypatch, capsys):
    """With no ``--archive`` flag main() must take the read-only path: render,
    return 0, and never reach the archiving side-effects (git/subprocess)."""
    _patch(monkeypatch, _mock_rows())

    def _boom(*args, **kwargs):
        raise AssertionError('main() invoked subprocess without --archive; the read-only branch was not taken')
    if hasattr(brief_status, 'subprocess'):
        monkeypatch.setattr(brief_status.subprocess, 'run', _boom, raising=False)
    rc = brief_status.main()
    out = capsys.readouterr().out
    assert rc == 0
    assert out.strip(), 'main() produced no output'
    assert STATE_SLUGS['complete'] in out

def test_brief_status_cli_render_labels(monkeypatch, capsys):
    """Every state maps to its specified label and both slug + label render."""
    _patch(monkeypatch, _mock_rows())
    rc = brief_status.main()
    out = capsys.readouterr().out
    assert rc == 0
    for state, label in STATE_LABELS.items():
        assert STATE_SLUGS[state] in out, f'slug for state {state!r} not rendered'
        assert label in out, f'label {label!r} for state {state!r} not rendered'

def test_brief_status_cli_render_returns_zero(monkeypatch, capsys):
    _patch(monkeypatch, _mock_rows())
    rc = brief_status.main()
    capsys.readouterr()
    assert rc == 0

def test_brief_status_cli_render_all_slugs_present(monkeypatch, capsys):
    rows = _mock_rows()
    _patch(monkeypatch, rows)
    rc = brief_status.main()
    out = capsys.readouterr().out
    assert rc == 0
    for row in rows:
        assert row['slug'] in out, f'slug {row['slug']!r} missing from output'

def test_brief_status_cli_render_no_exception(monkeypatch, capsys):
    """main() must complete without raising any exception on dict rows."""
    _patch(monkeypatch, _mock_rows())
    try:
        rc = brief_status.main()
    except Exception as exc:
        pytest.fail(f'main() raised {type(exc).__name__}: {exc!r}')
    capsys.readouterr()
    assert rc == 0

def test_regression_keyerror_on_empty(monkeypatch, capsys):
    """Guards the ``KeyError: 0`` regression.

    The un-reconciled main() sizes its slug column with ``len(r[0])`` -- an
    integer index into each row.  On a dict (which is "empty" at the integer key
    ``0``) that raises ``KeyError: 0``.  Even a single minimal dict row whose
    optional fields are empty/zero must render without a KeyError.
    """
    rows = [{'slug': 'lonely-leaf', 'state': 'blocked', 'brief_filename': 'lonely.brief.md', 'plan_filename': 'lonely.plan.md', 'remaining': 0}]
    _patch(monkeypatch, rows)
    try:
        rc = brief_status.main()
    except KeyError as exc:
        pytest.fail(f'main() raised KeyError({exc!r}) integer-indexing a dict row; rows must be consumed by key, not position')
    out = capsys.readouterr().out
    assert rc == 0
    assert 'lonely-leaf' in out
    assert 'PENDING' in out

def test_regression_unpack_error(monkeypatch, capsys):
    """Guards the positional-unpack regression.

    The un-reconciled main() iterates with
    ``for slug, status, detail, _b, _p in sorted(rows, ...)`` and sorts via
    ``order[r[1]]`` -- both assume 5-tuples.  Dict rows must be read by key, so
    neither a ``ValueError`` (bad unpack) nor a ``KeyError`` may escape.
    """
    _patch(monkeypatch, _mock_rows())
    try:
        rc = brief_status.main()
    except (ValueError, KeyError) as exc:
        pytest.fail(f'main() raised {type(exc).__name__}({exc!r}) treating dict rows as positional tuples')
    out = capsys.readouterr().out
    assert rc == 0
    assert STATE_SLUGS['zombie'] in out
    assert 'ORPHAN-PLAN' in out