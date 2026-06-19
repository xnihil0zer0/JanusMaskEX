"""RED oracle pinning harness.autowork_daemon._reset_sweep_throttle.

This test file is RED on HEAD: the helper `_reset_sweep_throttle` does not yet
exist in harness.autowork_daemon, so the module-level import below raises
ImportError and every witness errors out (collection failure). Once the helper
is implemented to best-effort unlink
``state_dir/control/autowork/sha_staleness_sweep.marker`` the oracle turns
green.

Contract pinned (per spec reset-sweep-throttle-oracle):
  - removes an existing sha_staleness_sweep.marker (present before, absent after);
  - fail-soft when the marker (or its parent dir) is absent -- must not raise;
  - the symbol is importable and callable;
  - touches ONLY sha_staleness_sweep.marker -- sibling markers are untouched.
"""
import pathlib
from harness.autowork_daemon import _reset_sweep_throttle

def _marker(state_dir) -> pathlib.Path:
    """The throttle marker path under test (mirrors the daemon's layout)."""
    return pathlib.Path(state_dir) / 'control' / 'autowork' / 'sha_staleness_sweep.marker'

def test_helper_unlinks_existing_marker(tmp_path):
    sd = tmp_path / 'state'
    m = _marker(sd)
    m.parent.mkdir(parents=True)
    m.write_text('1', encoding='utf-8')
    assert m.exists() is True
    _reset_sweep_throttle(sd)
    assert m.exists() is False

def test_helper_failsoft_when_marker_absent(tmp_path):
    sd = tmp_path / 'state'
    (sd / 'control' / 'autowork').mkdir(parents=True)
    assert _marker(sd).exists() is False
    _reset_sweep_throttle(sd)
    assert _marker(sd).exists() is False

def test_helper_failsoft_when_parent_dir_absent(tmp_path):
    sd = tmp_path / 'state'
    assert (sd / 'control' / 'autowork').exists() is False
    _reset_sweep_throttle(sd)
    assert _marker(sd).exists() is False

def test_helper_unlinks_only_sha_staleness_sweep_marker(tmp_path):
    sd = tmp_path / 'state'
    control = sd / 'control' / 'autowork'
    control.mkdir(parents=True)
    m = _marker(sd)
    m.write_text('arbitrary content unlinked regardless', encoding='utf-8')
    sibling = control / 'pause'
    sibling.write_text('keep me', encoding='utf-8')
    other = control / 'runaway_ceiling.json'
    other.write_text('{"count": 3}', encoding='utf-8')
    _reset_sweep_throttle(sd)
    assert m.exists() is False
    assert sibling.exists() is True
    assert sibling.read_text(encoding='utf-8') == 'keep me'
    assert other.exists() is True
    assert other.read_text(encoding='utf-8') == '{"count": 3}'

def test_helper_callable(tmp_path):
    assert callable(_reset_sweep_throttle)