"""Hermetic oracle for ``harness.symbol_ledger``.

Pins the public contract of the new ``harness/symbol_ledger.py`` module:

* the exact public signatures of ``resolve_interfaces`` and ``record_symbols``,
* the *lazy* (read-at-call-time) derivation of committed top-level symbols from
  ``state/impl_progress.jsonl`` accepted ``auto_commit`` rows + their committed
  ``.py`` files, recomputed on every call (no persisted ledger required), and
* the unchanged-input-on-miss behaviour of ``resolve_interfaces``.

Every input is built from local fixture files under a temporary ``state_dir``.
The oracle never globs the planner test tree and never touches network or pip.
"""

import inspect
import json
import socket
from pathlib import Path

import pytest

import harness.symbol_ledger as symbol_ledger


# --------------------------------------------------------------------------- #
# Fixture source materials (built in-test, no committed fixture files).
# --------------------------------------------------------------------------- #
COMMITTED_SRC = (
    "WIDGET_DEFAULT = 7\n"
    "\n"
    "def make_widget(count: int, label: str = \"x\") -> dict:\n"
    "    \"\"\"Build a widget mapping.\"\"\"\n"
    "    return {\"count\": count, \"label\": label}\n"
    "\n"
    "async def fetch_widget(widget_id: str) -> bytes:\n"
    "    return b\"\"\n"
    "\n"
    "class _Internal:\n"
    "    pass\n"
)

SECOND_SRC = (
    "def second_sym(value: float) -> float:\n"
    "    return value * 2.0\n"
)


def _make_committed(dirpath: Path, name: str, src: str) -> str:
    """Write a committed sample module and return its ABSOLUTE path string.

    Absolute paths resolve identically regardless of whatever base the module
    joins them against, keeping the oracle robust to path-resolution choices.
    """
    dirpath.mkdir(parents=True, exist_ok=True)
    target = dirpath / name
    target.write_text(src, encoding="utf-8")
    return str(target)


def _write_jsonl(state_dir: Path, rows: list) -> None:
    """Write ``impl_progress.jsonl`` under ``state_dir``.

    The text is mirrored into a nested ``state/`` subdir as cheap insurance
    against either ``state_dir/impl_progress.jsonl`` or
    ``state_dir/state/impl_progress.jsonl`` being the canonical location.
    """
    text = "".join(json.dumps(r) + "\n" for r in rows)
    state_dir.mkdir(parents=True, exist_ok=True)
    (state_dir / "impl_progress.jsonl").write_text(text, encoding="utf-8")
    nested = state_dir / "state"
    nested.mkdir(parents=True, exist_ok=True)
    (nested / "impl_progress.jsonl").write_text(text, encoding="utf-8")


def _build_fixture(tmp_path: Path) -> Path:
    """Return a populated ``state_dir`` exposing the ``make_widget`` symbol."""
    state_dir = tmp_path / "state"
    committed = _make_committed(tmp_path / "repo", "widgets.py", COMMITTED_SRC)
    row = {
        "phase": "accepted",
        "event": "auto_commit",
        "task_id": "t1",
        "files": [committed],
    }
    _write_jsonl(state_dir, [row])
    return state_dir


# --------------------------------------------------------------------------- #
# Annotation normalisation helpers (tolerate string vs real-type annotations).
# --------------------------------------------------------------------------- #
def _ann_repr(annotation) -> str:
    if annotation is inspect.Parameter.empty:
        return ""
    if isinstance(annotation, str):
        return annotation.replace(" ", "")
    rendered = str(annotation)
    name = getattr(annotation, "__name__", None)
    if name is not None and "[" not in rendered:
        return name
    return rendered.replace(" ", "")


# --------------------------------------------------------------------------- #
# Signature pinning.
# --------------------------------------------------------------------------- #
def test_resolve_interfaces_signature_pinned():
    sig = inspect.signature(symbol_ledger.resolve_interfaces)
    params = list(sig.parameters.values())
    assert [p.name for p in params] == ["interfaces_spec", "state_dir"]
    assert _ann_repr(params[0].annotation) == "str"
    assert _ann_repr(params[1].annotation).endswith("Path")
    assert _ann_repr(sig.return_annotation) == "str"


def test_record_symbols_signature_pinned():
    sig = inspect.signature(symbol_ledger.record_symbols)
    params = list(sig.parameters.values())
    assert [p.name for p in params] == ["state_dir"]
    assert _ann_repr(params[0].annotation).endswith("Path")
    ret = _ann_repr(sig.return_annotation).lower().replace("typing.", "")
    assert ret == "dict[str,str]"


# --------------------------------------------------------------------------- #
# Lazy derivation contract.
# --------------------------------------------------------------------------- #
def test_record_symbols_lazy_derives_from_accepted_auto_commit_rows(tmp_path):
    state_dir = _build_fixture(tmp_path)
    mapping = symbol_ledger.record_symbols(state_dir)
    assert isinstance(mapping, dict)
    assert "make_widget" in mapping
    signature = mapping["make_widget"]
    assert isinstance(signature, str)
    # The value is a committed *signature*, not a bare name.
    assert "make_widget" in signature
    assert "(" in signature


def test_record_symbols_recomputed_at_call_time(tmp_path):
    state_dir = tmp_path / "state"
    first_file = _make_committed(tmp_path / "repo", "widgets.py", COMMITTED_SRC)
    rows = [{"phase": "accepted", "event": "auto_commit", "files": [first_file]}]
    _write_jsonl(state_dir, rows)

    first = symbol_ledger.record_symbols(state_dir)
    assert "make_widget" in first
    assert "second_sym" not in first

    # Mutate the ledger on disk AFTER the first call: a cached result would miss it.
    second_file = _make_committed(tmp_path / "repo", "more.py", SECOND_SRC)
    rows.append({"phase": "accepted", "event": "auto_commit", "files": [second_file]})
    _write_jsonl(state_dir, rows)

    second = symbol_ledger.record_symbols(state_dir)
    assert "second_sym" in second
    assert "make_widget" in second


def test_record_symbols_ignores_non_accepted_rows(tmp_path):
    state_dir = tmp_path / "state"
    committed = _make_committed(tmp_path / "repo", "widgets.py", COMMITTED_SRC)
    rows = [
        {"phase": "proposed", "event": "auto_commit", "files": [committed]},
        {"phase": "accepted", "event": "review", "files": [committed]},
        {"phase": "rejected", "event": "auto_commit", "files": [committed]},
    ]
    _write_jsonl(state_dir, rows)
    mapping = symbol_ledger.record_symbols(state_dir)
    assert mapping == {}


def test_record_symbols_skips_missing_committed_file(tmp_path):
    state_dir = tmp_path / "state"
    good = _make_committed(tmp_path / "repo", "widgets.py", COMMITTED_SRC)
    ghost = str(tmp_path / "repo" / "ghost_does_not_exist.py")
    rows = [
        {"phase": "accepted", "event": "auto_commit", "files": [ghost]},
        {"phase": "accepted", "event": "auto_commit", "files": [good]},
    ]
    _write_jsonl(state_dir, rows)
    # The missing-file row must be skipped without raising.
    mapping = symbol_ledger.record_symbols(state_dir)
    assert "make_widget" in mapping
    assert "ghost_does_not_exist" not in mapping


# --------------------------------------------------------------------------- #
# resolve_interfaces hit / miss contract.
# --------------------------------------------------------------------------- #
def test_resolve_interfaces_hit_returns_committed_signature(tmp_path):
    state_dir = _build_fixture(tmp_path)
    mapping = symbol_ledger.record_symbols(state_dir)
    spec = "Provide the implementation for make_widget exactly as specified."
    resolved = symbol_ledger.resolve_interfaces(spec, state_dir)
    assert resolved != spec
    assert mapping["make_widget"] in resolved


def test_resolve_interfaces_miss_returns_input_unchanged(tmp_path):
    state_dir = _build_fixture(tmp_path)
    spec = "Implement totally_unknown_symbol that does nothing in particular."
    resolved = symbol_ledger.resolve_interfaces(spec, state_dir)
    assert resolved == spec


# --------------------------------------------------------------------------- #
# Integration: jsonl + committed file -> resolved signature.
# --------------------------------------------------------------------------- #
def test_fixture_jsonl_plus_committed_file_to_resolved_signature(tmp_path):
    state_dir = _build_fixture(tmp_path)
    mapping = symbol_ledger.record_symbols(state_dir)
    committed_signature = mapping["make_widget"]

    spec = "Spec naming make_widget for resolution."
    resolved = symbol_ledger.resolve_interfaces(spec, state_dir)
    assert committed_signature in resolved
    assert resolved != spec


# --------------------------------------------------------------------------- #
# Property: prose naming no derivable symbol is returned byte-for-byte.
# --------------------------------------------------------------------------- #
def test_unknown_symbol_prose_always_returned_verbatim(tmp_path):
    state_dir = _build_fixture(tmp_path)  # populated ledger, still must miss
    samples = [
        "Implement zzz_absent_thing returning None.",
        "No derivable symbols are mentioned at all here.",
        "",
        "Multi\nline\nprose with foo_bar_absent tokens.",
        "punctuation ?!#@ and numbers 1234567890",
    ]
    for prose in samples:
        assert symbol_ledger.resolve_interfaces(prose, state_dir) == prose


# --------------------------------------------------------------------------- #
# Regression: missing jsonl + hermeticity.
# --------------------------------------------------------------------------- #
def test_missing_impl_progress_jsonl_returns_empty_and_unchanged(tmp_path):
    state_dir = tmp_path / "state"
    state_dir.mkdir(parents=True, exist_ok=True)  # exists, but no jsonl inside
    assert symbol_ledger.record_symbols(state_dir) == {}
    spec = "Implement make_widget even though no ledger exists."
    assert symbol_ledger.resolve_interfaces(spec, state_dir) == spec


def test_oracle_is_hermetic_no_network(tmp_path, monkeypatch):
    # Real calls must succeed with all network access forbidden.
    def _forbidden(*_args, **_kwargs):
        raise RuntimeError("network access attempted by symbol_ledger")

    monkeypatch.setattr(socket, "socket", _forbidden)
    monkeypatch.setattr(socket, "create_connection", _forbidden, raising=False)

    state_dir = _build_fixture(tmp_path)
    mapping = symbol_ledger.record_symbols(state_dir)
    assert "make_widget" in mapping
    resolved = symbol_ledger.resolve_interfaces("Resolve make_widget now.", state_dir)
    assert mapping["make_widget"] in resolved
