"""Oracle: config COMMENTS are not module registrations (wire_up scanning).

Root cause under test (found 2026-06-10): ``discover_live_roots`` and
``_grep_config`` scan RAW config text under ``config/**`` for module
references (``*.py`` tokens, ``-m`` targets, dotted paths). A YAML/TOML
``#`` comment that merely *mentions* a module path — e.g. the doc comment
``# harness/wire_up.py::_grep_config — "dynamic wiring"`` in
``config/autocompiler.yaml`` — is treated as a real registration:

  * ``discover_live_roots`` promoted the internal module
    ``harness/wire_up.py`` to a LIVE ROOT (broke
    ``test_live_root_reconciliation.py::test_internal_modules_are_not_promoted_to_roots``);
  * ``_grep_config`` would equally launder a genuine orphan as
    CONFIG_WIRED if a config comment name-dropped it.

CONTRACT: ``#`` comments (full-line, or trailing when preceded by
whitespace — the YAML/TOML comment forms) must be stripped from config
text BEFORE module-reference scanning, in BOTH ``discover_live_roots``
and ``_grep_config``. Real (non-comment) registrations keep working.

Hermetic: each test builds its own temp repo_root; no dependence on the
live repo's config tree.
"""
from __future__ import annotations

from pathlib import Path

from harness.wire_up import discover_live_roots, _grep_config


def _mk_repo(tmp_path: Path, config_text: str, config_name: str = "app.yaml") -> Path:
    """A minimal repo: one internal module (no __main__ guard) + one config file."""
    root = tmp_path / "repo"
    (root / "harness").mkdir(parents=True)
    (root / "harness" / "internal_mod.py").write_text(
        "def helper():\n    return 1\n", encoding="utf-8"
    )
    (root / "config").mkdir()
    (root / "config" / config_name).write_text(config_text, encoding="utf-8")
    return root


# ---------------------------------------------------------------------------
# discover_live_roots: comments must not mint roots
# ---------------------------------------------------------------------------

def test_full_line_comment_py_reference_not_promoted_to_root(tmp_path):
    root = _mk_repo(
        tmp_path,
        '# wired-ness is classified by harness/internal_mod.py::helper — "dynamic wiring"\n'
        "enabled: false\n",
    )
    roots = set(discover_live_roots(root))
    assert "harness/internal_mod.py" not in roots, (
        "a full-line YAML comment mentioning a .py path must not promote it to a live root"
    )


def test_trailing_comment_py_reference_not_promoted_to_root(tmp_path):
    root = _mk_repo(
        tmp_path,
        "enabled: false  # mirrors harness/internal_mod.py\n",
    )
    roots = set(discover_live_roots(root))
    assert "harness/internal_mod.py" not in roots, (
        "a trailing YAML comment mentioning a .py path must not promote it to a live root"
    )


def test_comment_dash_m_reference_not_promoted_to_root(tmp_path):
    root = _mk_repo(
        tmp_path,
        "# run by hand: python -m harness.internal_mod\nenabled: false\n",
    )
    roots = set(discover_live_roots(root))
    assert "harness/internal_mod.py" not in roots, (
        "a commented-out `-m` invocation must not promote its target to a live root"
    )


def test_real_py_path_registration_still_promoted(tmp_path):
    root = _mk_repo(tmp_path, "entry_module: harness/internal_mod.py\n")
    roots = set(discover_live_roots(root))
    assert "harness/internal_mod.py" in roots, (
        "a genuine (non-comment) .py path registration must still be promoted"
    )


def test_real_dash_m_registration_still_promoted(tmp_path):
    root = _mk_repo(tmp_path, "command: python -m harness.internal_mod\n")
    roots = set(discover_live_roots(root))
    assert "harness/internal_mod.py" in roots, (
        "a genuine (non-comment) -m registration must still be promoted"
    )


# ---------------------------------------------------------------------------
# _grep_config: comments must not launder CONFIG_WIRED
# ---------------------------------------------------------------------------

def test_grep_config_ignores_comment_only_mention(tmp_path):
    root = _mk_repo(
        tmp_path,
        '# see harness/internal_mod.py for the classifier\nenabled: false\n',
    )
    assert _grep_config(root, "internal_mod") == "", (
        "a module mentioned only in a config comment must not be CONFIG_WIRED"
    )


def test_grep_config_ignores_trailing_comment_mention(tmp_path):
    root = _mk_repo(
        tmp_path,
        "enabled: false  # validated against internal_mod.py\n",
    )
    assert _grep_config(root, "internal_mod") == "", (
        "a module mentioned only in a trailing config comment must not be CONFIG_WIRED"
    )


def test_grep_config_real_reference_still_counts(tmp_path):
    root = _mk_repo(tmp_path, "module: harness/internal_mod.py\n")
    assert _grep_config(root, "internal_mod") == "config/app.yaml", (
        "a genuine config registration must still classify as CONFIG_WIRED"
    )
