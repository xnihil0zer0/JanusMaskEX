"""Wire-up-sweep remediation (#3): `_grep_config` must match module references,
not arbitrary config keys.

The Wave-2 audit (WIRE_UP_HANDOFF.md §5/§7) found `_grep_config` whole-word-matched
a module's stem in ANY `config/**` file, so a stem that merely appears as an
unrelated JSON key (e.g. the `"actions"` object key in
`config/gemini_settings.json`) produced a bogus CONFIG_WIRED that MASKED a real
orphan (`overseer/actions.py`). This oracle pins the tightened contract:
`_grep_config` counts a reference ONLY when the stem looks like a module path /
`-m` target -- a `stem.py` file path or a dotted-path segment (`pkg.stem` /
`stem.sub`) -- and NEVER when it is a bare identifier / JSON key.

These tests are deletion-safe: they exercise `_grep_config` over synthetic config
trees plus the stable "actions"-key fact in the real config, NOT the existence of
`overseer/actions.py` (which is independently a retire candidate).
"""
from __future__ import annotations

import json
from pathlib import Path

from harness.wire_up import _grep_config

REPO_ROOT = Path(__file__).resolve().parents[2]


def _write_config(tmp_path: Path, name: str, text: str) -> Path:
    cfg = tmp_path / "config"
    cfg.mkdir(exist_ok=True)
    (cfg / name).write_text(text, encoding="utf-8")
    return tmp_path


def test_bare_json_key_is_not_a_module_reference(tmp_path):
    """A stem appearing only as a JSON object key must NOT count as wiring."""
    root = _write_config(
        tmp_path,
        "settings.json",
        json.dumps({"hooks": {"actions": {"foo": 1}, "actions_list": []}}, indent=2),
    )
    assert _grep_config(root, "actions") == ""


def test_py_path_reference_matches(tmp_path):
    """A `stem.py` path reference is genuine module wiring -> match."""
    root = _write_config(
        tmp_path,
        "run.json",
        json.dumps({"command": ["python", "overseer/actions.py"]}),
    )
    assert _grep_config(root, "actions").endswith("run.json")


def test_dotted_tail_reference_matches(tmp_path):
    """A dotted module path with the stem as the tail segment -> match."""
    root = _write_config(
        tmp_path,
        "entry.yaml",
        "entrypoint: -m overseer.actions\n",
    )
    assert _grep_config(root, "actions").endswith("entry.yaml")


def test_dotted_head_reference_matches(tmp_path):
    """A dotted module path with the stem as a leading segment -> match."""
    root = _write_config(
        tmp_path,
        "entry.txt",
        "module = actions.handlers\n",
    )
    assert _grep_config(root, "actions").endswith("entry.txt")


def test_bare_dash_m_target_matches(tmp_path):
    """A bare `-m <module>` target is genuine wiring -> match (this is the form
    tests/harness/test_sweep_classifier.py relies on; must stay supported)."""
    root = _write_config(
        tmp_path,
        "hooks.json",
        json.dumps({"command": "python3 -m config_only"}),
    )
    assert _grep_config(root, "config_only").endswith("hooks.json")


def test_substring_inside_longer_identifier_does_not_match(tmp_path):
    """`actions` inside `transactions.py` must not be a match (word boundary)."""
    root = _write_config(
        tmp_path,
        "other.json",
        json.dumps({"script": "harness/transactions.py"}),
    )
    assert _grep_config(root, "actions") == ""


def test_no_config_dir_returns_empty(tmp_path):
    """No config/ dir -> empty string, never raises."""
    assert _grep_config(tmp_path, "actions") == ""


def test_live_actions_key_is_not_counted():
    """Regression on the REAL tree: the `"actions"` JSON key in
    config/gemini_settings.json is NOT a module reference, so `_grep_config`
    must return '' for stem 'actions'. (Stable regardless of whether
    overseer/actions.py exists.)"""
    assert _grep_config(REPO_ROOT, "actions") == ""
