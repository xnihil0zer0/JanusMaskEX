"""W112 adversarial — _persist_fuzz_results atomic write.

Pre-fix (orchestrator.py:734-742): naive
    with open(path, 'w') as f:
        json.dump(summary, f, indent=2)
        f.write('\n')
A mid-write crash (SIGKILL, OOM, disk-full) left a truncated JSON file
that downstream auditing tools (and any future durability check) would
fail on.

Post-fix: tmp + flush + fsync + replace pattern mirroring
``_save_final_output`` (W106 G3-3) and ``harness/state.py:88-95``.

Static-source pin matches the W106 G3-3 test shape so future refactors
that drop the atomic guarantee fail loudly.
"""
from __future__ import annotations

import inspect
import json
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO_ROOT))

from harness import orchestrator  # noqa: E402
from harness.diff_fuzzer import FuzzResult  # noqa: E402


def _stage_state(tmp_path: Path) -> Path:
    state_dir = tmp_path / 'state'
    state_dir.mkdir()
    return state_dir


def _empty_result() -> FuzzResult:
    return FuzzResult(
        equivalent=True,
        total_inputs=10,
        matching_inputs=10,
        failures=[],
        error=None,
        skipped_reason=None,
    )


# ---------------------------------------------------------------------------
# Static-source pin
# ---------------------------------------------------------------------------


def test_w112_persist_fuzz_results_uses_atomic_pattern():
    """Source must include tmp_path = with_suffix('.json.tmp') + flush +
    fsync + replace pattern (mirror of harness/state.py:88-95)."""
    src = inspect.getsource(orchestrator._persist_fuzz_results)
    assert ".with_suffix('.json.tmp')" in src
    assert 'f.flush()' in src
    assert 'os.fsync(f.fileno())' in src
    assert 'tmp_path.replace(path)' in src


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


def test_w112_writes_file_with_summary_and_no_tmp_residue(tmp_path):
    state_dir = _stage_state(tmp_path)
    task_id = 'T-w112-happy'
    round_label = 'round1'

    orchestrator._persist_fuzz_results(state_dir, task_id, round_label, _empty_result())

    fuzz_dir = state_dir.parent / 'logs' / 'fuzz_results'
    out_path = fuzz_dir / f'{task_id}_{round_label}.json'
    tmp_path_glob = list(fuzz_dir.glob('*.tmp'))

    assert out_path.exists()
    assert tmp_path_glob == [], f"unexpected tmp residue: {tmp_path_glob}"

    summary = json.loads(out_path.read_text())
    assert summary['task_id'] == task_id
    assert summary['round'] == round_label
    assert summary['equivalent'] is True
    assert summary['total_inputs'] == 10
    assert summary['matching_inputs'] == 10
    assert summary['failure_count'] == 0


def test_w112_overwrite_atomic_replaces_prior_file(tmp_path):
    state_dir = _stage_state(tmp_path)
    task_id = 'T-w112-overwrite'
    round_label = 'round2'
    fuzz_dir = state_dir.parent / 'logs' / 'fuzz_results'
    fuzz_dir.mkdir(parents=True)
    prior = fuzz_dir / f'{task_id}_{round_label}.json'
    prior.write_text('OLD')

    orchestrator._persist_fuzz_results(state_dir, task_id, round_label, _empty_result())

    summary = json.loads(prior.read_text())
    assert summary['equivalent'] is True
    assert not (fuzz_dir / f'{task_id}_{round_label}.json.tmp').exists()


# ---------------------------------------------------------------------------
# Crash simulation: fsync raises mid-write
# ---------------------------------------------------------------------------


def test_w112_fsync_failure_does_not_corrupt_prior_file(tmp_path, monkeypatch):
    """If fsync raises, replace() is not called; the prior file (if any)
    remains intact and the partial tmp file is left for diagnostic
    inspection (operator can rm it manually)."""
    state_dir = _stage_state(tmp_path)
    task_id = 'T-w112-fsync-fail'
    round_label = 'round1'
    fuzz_dir = state_dir.parent / 'logs' / 'fuzz_results'
    fuzz_dir.mkdir(parents=True)
    prior_path = fuzz_dir / f'{task_id}_{round_label}.json'
    prior_path.write_text('{"task_id":"PRIOR_VALID"}')

    real_fsync = orchestrator.os.fsync

    def fail_fsync(fd):
        raise OSError('simulated fsync failure')

    monkeypatch.setattr(orchestrator.os, 'fsync', fail_fsync)

    with pytest.raises(OSError, match='simulated fsync failure'):
        orchestrator._persist_fuzz_results(
            state_dir, task_id, round_label, _empty_result()
        )

    # Prior file untouched — replace() never ran.
    assert prior_path.read_text() == '{"task_id":"PRIOR_VALID"}'
    monkeypatch.setattr(orchestrator.os, 'fsync', real_fsync)


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
