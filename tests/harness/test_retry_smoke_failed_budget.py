"""RED oracle for gap#1 — smoke_failed retry budget.

`harness.autowork_daemon._retry_blocked_tasks` historically treated
``smoke_failed`` as a *deterministic* outcome with an effective retry budget of
1 (``_DETERMINISTIC_OUTCOMES``). But the daemon RE-SYNTHESIZES a brand-new
candidate on each retry, so ``smoke_failed`` is non-deterministic at the draft
level: a flaky first draft fails the smoke gate, and a plain re-dispatch (no spec
change) passes. Budget-1 dead-ends such drafts into self-heal instead of giving
them the normal escalating-backoff retries.

Fix: ``smoke_failed`` must get the full ``max_attempts`` (3) budget like any
other re-synthesis flake, while the budget stays *bounded* (it must still
permanently park a task once the budget is genuinely exhausted).
"""
import json
import pathlib
import tempfile
import time
import unittest
from unittest.mock import patch

from harness.autowork_daemon import _retry_blocked_tasks


class TestSmokeFailedRetryBudget(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.state_dir = pathlib.Path(self.tmp_dir.name)
        (self.state_dir / 'tasks' / 'blocked').mkdir(parents=True, exist_ok=True)
        (self.state_dir / 'control' / 'autowork').mkdir(parents=True, exist_ok=True)

    def tearDown(self):
        self.tmp_dir.cleanup()

    def _write_blocked(self, tid, attempts, last_outcome, ts):
        blocked = self.state_dir / 'tasks' / 'blocked'
        (blocked / f'{tid}.json').write_text(
            json.dumps({'task_id': tid, 'files_touched': ['foo.py'], 'priority': 'high'}),
            encoding='utf-8',
        )
        (blocked / f'{tid}.retry.json').write_text(
            json.dumps({'attempts': attempts, 'ts': ts, 'last_outcome': last_outcome}),
            encoding='utf-8',
        )

    @patch('harness.autowork_daemon._escalate_to_autobrief')
    def test_smoke_failed_restages_under_budget(self, _mock_escalate):
        """attempts=1 smoke_failed (with an elapsed backoff window) must RE-STAGE,
        not be parked at budget 1."""
        tid = 'task_smoke_flake'
        # ts well in the past so the 300s tier-1 backoff window has elapsed.
        self._write_blocked(tid, attempts=1, last_outcome='smoke_failed', ts=0.0)

        summary = {}
        restaged = _retry_blocked_tasks(self.state_dir, summary, max_attempts=3)

        dest = self.state_dir / 'tasks' / f'{tid}.json'
        exhausted = self.state_dir / 'tasks' / 'blocked' / f'{tid}.exhausted'
        self.assertTrue(dest.is_file(), 'smoke_failed task should be re-staged to the live queue')
        self.assertFalse(exhausted.exists(), 'smoke_failed must NOT be parked at budget 1')
        self.assertEqual(restaged, 1)

    @patch('harness.autowork_daemon._escalate_to_autobrief')
    def test_smoke_failed_budget_stays_bounded(self, _mock_escalate):
        """Budget is raised, not removed: attempts>=max_attempts still exhausts."""
        tid = 'task_smoke_dead'
        self._write_blocked(tid, attempts=3, last_outcome='smoke_failed', ts=time.time())

        summary = {}
        _retry_blocked_tasks(self.state_dir, summary, max_attempts=3)

        exhausted = self.state_dir / 'tasks' / 'blocked' / f'{tid}.exhausted'
        dest = self.state_dir / 'tasks' / f'{tid}.json'
        self.assertTrue(exhausted.is_file(), 'a genuinely-exhausted smoke_failed task must be parked')
        self.assertFalse(dest.exists(), 'exhausted task must not be re-staged')


if __name__ == '__main__':
    unittest.main()
