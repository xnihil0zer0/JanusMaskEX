"""RED oracle for the daemon idle-sleep-cap helper.

Pins ``harness.autowork_daemon._soonest_blocked_retry_deadline`` directly over a
hermetic synthetic state dir with fake ``blocked/`` sidecars at controlled
timestamps. The helper returns the soonest pending blocked-retry deadline --
``min`` over retry-eligible blocked tasks of ``last_ts + tier_threshold(attempts)``
-- which feeds the daemon idle-sleep cap ``min(heartbeat, max(grace, deadline-now))``.

It reuses ``_retry_blocked_tasks``' enumeration + escalating backoff tiers (300s
tier-1 / 3600s tier-2 / 86400s tier-3) and the same exhaustion rules (the
``<tid>.exhausted`` marker, ``attempts >= effective_max``, and
``effective_max == 1`` for the deterministic outcomes) BUT is READ-ONLY: it
re-stages nothing and writes no ``.exhausted`` / marker / telemetry.

RED on HEAD: the import / helper does not exist yet. Hermetic + offline: no
daemon loop, no subprocess, no broad adversarial suite. Mirrors the hermetic
idiom of ``tests/harness/test_retry_smoke_failed_budget.py``.
"""
import json
import pathlib
import tempfile
import time
import unittest
from harness.autowork_daemon import _soonest_blocked_retry_deadline
HEARTBEAT = 1800.0
GRACE = 5.0

class TestDaemonIdleSleepCap(unittest.TestCase):

    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.state_dir = pathlib.Path(self.tmp_dir.name)
        self.blocked = self.state_dir / 'tasks' / 'blocked'
        self.blocked.mkdir(parents=True, exist_ok=True)
        (self.state_dir / 'control' / 'autowork').mkdir(parents=True, exist_ok=True)

    def tearDown(self):
        self.tmp_dir.cleanup()

    def _write_blocked(self, tid, attempts, last_outcome, ts):
        """Write tasks/blocked/<tid>.json + the <tid>.retry.json sidecar.

        Mirrors test_retry_smoke_failed_budget.py's _write_blocked.
        """
        (self.blocked / f'{tid}.json').write_text(json.dumps({'task_id': tid, 'files_touched': ['foo.py'], 'priority': 'high'}), encoding='utf-8')
        (self.blocked / f'{tid}.retry.json').write_text(json.dumps({'attempts': attempts, 'ts': ts, 'last_outcome': last_outcome}), encoding='utf-8')

    @staticmethod
    def _cap(deadline, now):
        """The idle-sleep cap the helper feeds (recomputed in-test for teeth)."""
        return min(HEARTBEAT, max(GRACE, deadline - now))

    def test_sooner_than_heartbeat_caps_below_1800(self):
        """attempts=1 non-deterministic 'timeout', ts=now-100 -> deadline ts+300
        and the derived cap is strictly below the 1800s heartbeat."""
        now = time.time()
        ts = now - 100.0
        self._write_blocked('task_teeth', attempts=1, last_outcome='timeout', ts=ts)
        deadline = _soonest_blocked_retry_deadline(self.state_dir)
        self.assertEqual(deadline, ts + 300.0)
        cap = self._cap(deadline, now)
        self.assertLess(cap, HEARTBEAT)

    def test_nearest_deadline_wins(self):
        """Two retry-eligible tasks -> the SOONER (min) deadline is returned."""
        now = time.time()
        ts_near = now - 200.0
        ts_far = now - 100.0
        self._write_blocked('task_near', attempts=1, last_outcome='timeout', ts=ts_near)
        self._write_blocked('task_far', attempts=1, last_outcome='timeout', ts=ts_far)
        deadline = _soonest_blocked_retry_deadline(self.state_dir)
        self.assertEqual(deadline, ts_near + 300.0)
        self.assertLess(deadline, ts_far + 300.0)

    def test_none_when_blocked_empty_or_missing(self):
        """Empty tasks/blocked/ AND a missing blocked dir both yield None."""
        self.assertIsNone(_soonest_blocked_retry_deadline(self.state_dir))
        self.blocked.rmdir()
        self.assertFalse(self.blocked.exists())
        self.assertIsNone(_soonest_blocked_retry_deadline(self.state_dir))

    def test_exhausted_marker_excluded(self):
        """An otherwise-eligible blocked task carrying a <tid>.exhausted marker is
        excluded; as the only task the helper returns None."""
        now = time.time()
        ts = now - 100.0
        self._write_blocked('task_marked', attempts=1, last_outcome='timeout', ts=ts)
        self.assertEqual(_soonest_blocked_retry_deadline(self.state_dir), ts + 300.0)
        (self.blocked / 'task_marked.exhausted').write_text('1', encoding='utf-8')
        self.assertIsNone(_soonest_blocked_retry_deadline(self.state_dir))

    def test_attempts_at_effective_max_excluded_incl_deterministic_budget1(self):
        """attempts>=effective_max is excluded: a generic outcome at budget 3 AND a
        deterministic outcome ('synthesis_or_ast_failed') at budget 1. Both
        excluded -> None."""
        now = time.time()
        ts = now - 100.0
        self._write_blocked('task_generic_max', attempts=3, last_outcome='timeout', ts=ts)
        self._write_blocked('task_det_budget1', attempts=1, last_outcome='synthesis_or_ast_failed', ts=ts)
        self.assertIsNone(_soonest_blocked_retry_deadline(self.state_dir))

    def test_tier2_backoff_3600_boundary(self):
        """attempts=2 generic outcome -> deadline ts+3600 (tier-2 reused, not the
        300s tier-1)."""
        now = time.time()
        ts = now - 10.0
        self._write_blocked('task_tier2', attempts=2, last_outcome='timeout', ts=ts)
        deadline = _soonest_blocked_retry_deadline(self.state_dir)
        self.assertEqual(deadline, ts + 3600.0)
        self.assertNotEqual(deadline, ts + 300.0)

    def test_tier1_attempts_zero_deadline_300(self):
        """attempts=0 generic outcome -> tier-1 deadline ts+300 (attempts<=1 tier)."""
        now = time.time()
        ts = now - 50.0
        self._write_blocked('task_tier1_zero', attempts=0, last_outcome='timeout', ts=ts)
        self.assertEqual(_soonest_blocked_retry_deadline(self.state_dir), ts + 300.0)

    def test_deterministic_outcome_under_budget_still_eligible(self):
        """Positive control distinguishing the budget-1 exclusion: a deterministic
        outcome with attempts=0 is still < effective_max (1) -> eligible (ts+300)."""
        now = time.time()
        ts = now - 50.0
        self._write_blocked('task_det_zero', attempts=0, last_outcome='synthesis_or_ast_failed', ts=ts)
        self.assertEqual(_soonest_blocked_retry_deadline(self.state_dir), ts + 300.0)

    def test_helper_is_read_only_and_failsoft_on_malformed_sidecar(self):
        """A malformed (non-JSON) <tid>.retry.json is skipped (treated as defaults
        attempts=0/ts=0.0 -> tier-1 deadline 300.0), never raises, and the blocked
        <tid>.json remains present (no .exhausted written)."""
        tid = 'task_malformed'
        (self.blocked / f'{tid}.json').write_text(json.dumps({'task_id': tid, 'files_touched': ['foo.py'], 'priority': 'high'}), encoding='utf-8')
        (self.blocked / f'{tid}.retry.json').write_text('this is not json {', encoding='utf-8')
        try:
            deadline = _soonest_blocked_retry_deadline(self.state_dir)
        except Exception as exc:
            self.fail(f'helper raised on malformed sidecar: {exc!r}')
        self.assertEqual(deadline, 300.0)
        self.assertTrue((self.blocked / f'{tid}.json').is_file())
        self.assertFalse((self.blocked / f'{tid}.exhausted').exists())

    def test_blocked_json_files_unchanged_after_call(self):
        """Regression: the helper re-stages nothing and writes no marker/telemetry;
        every blocked file is byte-identical after the call."""
        now = time.time()
        specs = [('task_a', 1, 'timeout', now - 100.0), ('task_b', 2, 'timeout', now - 100.0)]
        for tid, attempts, outcome, ts in specs:
            self._write_blocked(tid, attempts, outcome, ts)
        before = {p.name: p.read_bytes() for p in self.blocked.iterdir()}
        _ = _soonest_blocked_retry_deadline(self.state_dir)
        after = {p.name: p.read_bytes() for p in self.blocked.iterdir()}
        self.assertEqual(before, after, 'helper must not add/remove/modify blocked files')
        for tid, _attempts, _outcome, _ts in specs:
            self.assertTrue((self.blocked / f'{tid}.json').is_file())
            self.assertFalse((self.blocked / f'{tid}.exhausted').exists())
            self.assertFalse((self.state_dir / 'tasks' / f'{tid}.json').exists(), 'helper must NOT re-stage blocked tasks to the live queue')
        self.assertFalse((self.state_dir / 'impl_progress.jsonl').exists(), 'helper must write no telemetry')
if __name__ == '__main__':
    unittest.main()