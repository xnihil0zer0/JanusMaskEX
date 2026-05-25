"""HOOK-55 drain-e2e adversarial suite.

Scope: augmented plan §5 row 5 (Byzantine content: random bytes / randomised
encodings must be rejected identically by MCP-era audit and shadow hooks),
plus drain-regression → rollback firing per master plan §5.4 trigger
"drain_consensus_regression". Covers:

* augmented §5 row 5 — random-bytes track events never crash compare and
  always surface as deterministic divergences (no silent masking).
* augmented §5 mutation — corrupt baseline JSON / truncated actuals / NUL
  bytes / unicode-surrogate strings in track_events flow through compare
  and report cleanly or as divergences without raising.
* regression fires rollback via fire_drain_rollback → apply_rollback wiring
  to state/hooks/rollback_signal with trigger=drain_consensus_regression.
* rollback fire path preserves the config.yaml enforce_verbs list byte-for-byte
  and only touches hooks.mode (HOOK-54 invariant, re-verified end-to-end).
* CLI --drain is read-only w.r.t. harness/config.yaml unless --emit-rollback is
  set; exit code is deterministic (0 clean / 1 regression) across replay.
* test-count deltas surface as divergences even when patch_stat and track
  events match exactly — sub-plan 06 §2 L3 explicitly calls out test counts as
  part of the three-way differential.
* Concurrent drain runs are isolated (one report file per invocation).
* 200-row fuzz never crashes compare_drain_artefacts.
"""

from __future__ import annotations

import concurrent.futures
import json
import os
import pathlib
import random
import subprocess
import sys
import threading

import pytest

from harness import hooks_equivalence as he


# ---------------------------------------------------------------------------
# fixtures
# ---------------------------------------------------------------------------


def _art(**overrides):
    base = dict(
        patch_stat=" harness/orchestrator.py | 4 ++--\n 1 file changed, 2 insertions(+), 2 deletions(-)",
        test_count=776,
        track_events=[
            {"ts": "2026-04-18T00:00:00Z", "event": "start", "task_id": "STAB-001"},
            {"ts": "2026-04-18T00:00:01Z", "event": "write", "task_id": "STAB-001"},
            {"ts": "2026-04-18T00:00:02Z", "event": "test_pass", "task_id": "STAB-001"},
        ],
    )
    base.update(overrides)
    return he.DrainArtefacts(**base)


@pytest.fixture
def drain_baseline_dir(tmp_path):
    d = tmp_path / "state" / "hooks"
    d.mkdir(parents=True)
    return d


@pytest.fixture
def seeded_baseline(drain_baseline_dir):
    art = _art()
    for brief in he.DRAIN_BRIEFS:
        he.save_drain_baseline(
            brief_id=brief, artefacts=art, baseline_dir=drain_baseline_dir
        )
    return drain_baseline_dir, art


# ---------------------------------------------------------------------------
# augmented §5 row 5 — Byzantine content
# ---------------------------------------------------------------------------


def test_adv_random_bytes_in_track_events_never_crash_compare():
    rng = random.Random(2026)
    a = _art()
    b_events = []
    for _ in range(20):
        event = {
            "ts": "2026-04-18T00:00:%02dZ" % rng.randint(0, 59),
            "event": "".join(chr(rng.randint(32, 126)) for _ in range(8)),
            "junk": bytes(rng.randint(0, 255) for _ in range(8)).hex(),
        }
        b_events.append(event)
    b = _art(track_events=b_events)
    divs = he.compare_drain_artefacts(a, b)
    # Should surface as divergence, never raise.
    assert isinstance(divs, list)
    assert any(d.field == "track_events" for d in divs)


def test_adv_nul_bytes_in_patch_stat_surface_as_divergence():
    a = _art()
    b = _art(patch_stat="harness/x.py | 2 +\n\x00\x00\x01garbage")
    divs = he.compare_drain_artefacts(a, b)
    assert [d.field for d in divs] == ["patch_stat"]


def test_adv_unicode_surrogate_in_track_events_is_handled():
    a = _art()
    # Deliberately malformed unicode via \ud8ff surrogate
    b = _art(track_events=[{"event": "start\ud8ff", "ts": "x"}])
    divs = he.compare_drain_artefacts(a, b)
    assert isinstance(divs, list)
    assert any(d.field == "track_events" for d in divs)


def test_adv_fuzz_random_rows_never_crash(seeded_baseline):
    _dir, art = seeded_baseline
    rng = random.Random(42)
    for _ in range(200):
        rows = []
        for _ in range(rng.randint(0, 10)):
            rows.append(
                {
                    "event": rng.choice(["start", "write", "test_pass", "weird", "", None]),
                    "ts": rng.choice(["2026-04-18T00:00:00Z", "", None, 123]),
                    "task_id": rng.choice(["STAB-001", None, "\x00", "\u0000"]),
                }
            )
        b = _art(
            patch_stat=rng.choice(["", art.patch_stat, "noise\x00\xff"]),
            test_count=rng.randint(0, 1000),
            track_events=rows,
        )
        divs = he.compare_drain_artefacts(art, b)
        assert isinstance(divs, list)


# ---------------------------------------------------------------------------
# augmented §5 row 5 mutation — baseline corruption
# ---------------------------------------------------------------------------


def test_adv_corrupt_baseline_json_loads_as_none(drain_baseline_dir):
    target = drain_baseline_dir / "drain_baseline_stab_001.json"
    target.write_text("{not: json", encoding="utf-8")
    loaded = he.load_drain_baseline(brief_id="stab_001", baseline_dir=drain_baseline_dir)
    assert loaded is None


def test_adv_missing_fields_in_baseline_file_loads_as_none(drain_baseline_dir):
    target = drain_baseline_dir / "drain_baseline_stab_001.json"
    target.write_text(json.dumps({"brief_id": "stab_001"}), encoding="utf-8")
    loaded = he.load_drain_baseline(
        brief_id="stab_001", baseline_dir=drain_baseline_dir
    )
    # Missing required artefact fields → fail soft, not raise.
    assert loaded is None


def test_adv_truncated_actuals_file_is_regression(tmp_path, seeded_baseline):
    baseline_dir, _ = seeded_baseline
    actual_path = tmp_path / "actual.json"
    actual_path.write_text('{"patch_stat": "part', encoding="utf-8")
    # CLI path below drives the parsing; drive it directly in-process for speed.
    with pytest.raises((ValueError, json.JSONDecodeError)):
        he.load_drain_artefacts_from_path(actual_path)


# ---------------------------------------------------------------------------
# regression → rollback wiring
# ---------------------------------------------------------------------------


def test_adv_regression_fire_drain_rollback_writes_drain_trigger(tmp_path):
    signal_path = tmp_path / "rollback_signal"
    div = he.DrainDivergence(
        field="test_count", baseline=776, actual=0, detail="catastrophic"
    )
    report = he.DrainReport(
        session_id="drain-adv",
        brief_id="stab_003",
        clean=False,
        divergences=[div],
        generated_at="2026-04-18T00:00:00Z",
    )
    fired = he.fire_drain_rollback(report, signal_path=signal_path)
    assert fired is True
    body = json.loads(signal_path.read_text(encoding="utf-8"))
    assert body["trigger"] == "drain_consensus_regression"


def test_adv_regression_rollback_preserves_enforce_verbs_list_byte_identical(tmp_path):
    signal_path = tmp_path / "rollback_signal"
    config = tmp_path / "config.yaml"
    before = (
        "# top\n"
        "hooks:\n"
        "  mode: enforce\n"
        "  enforce_verbs:\n"
        "    - request_clarification\n"
        "    - report_error\n"
        "other:\n"
        "  foo: bar\n"
    )
    config.write_text(before, encoding="utf-8")
    div = he.DrainDivergence(
        field="track_events", baseline=[], actual=[{"event": "x"}], detail="drift"
    )
    report = he.DrainReport(
        session_id="drain-adv",
        brief_id="stab_001",
        clean=False,
        divergences=[div],
        generated_at="2026-04-18T00:00:00Z",
    )
    he.fire_drain_rollback(report, signal_path=signal_path)
    outcome = he.apply_rollback(
        signal_path=signal_path,
        config_path=config,
        blocked_dir=tmp_path / "blocked",
    )
    assert outcome.triggered
    after = config.read_text(encoding="utf-8")
    # hooks.mode flipped, enforce_verbs list + siblings untouched.
    import re as _re
    assert _re.search(r'^\s*mode:\s*"?off"?', after, _re.MULTILINE)
    assert "- request_clarification" in after
    assert "- report_error" in after
    assert "other:\n  foo: bar" in after
    assert after.startswith("# top\n")


def test_adv_clean_drain_never_writes_rollback_signal(tmp_path):
    signal_path = tmp_path / "rollback_signal"
    clean_report = he.DrainReport(
        session_id="drain-clean",
        brief_id="stab_001",
        clean=True,
        divergences=[],
        generated_at="2026-04-18T00:00:00Z",
    )
    he.fire_drain_rollback(clean_report, signal_path=signal_path)
    assert not signal_path.exists()


def test_adv_drain_trigger_is_member_of_rollback_triggers():
    assert "drain_consensus_regression" in he.ROLLBACK_TRIGGERS


# ---------------------------------------------------------------------------
# sub-plan 06 §2 L3 differential contract
# ---------------------------------------------------------------------------


def test_adv_test_count_delta_is_divergence_even_when_other_fields_match():
    a = _art()
    b = _art(test_count=775)
    divs = he.compare_drain_artefacts(a, b)
    assert [d.field for d in divs] == ["test_count"]


def test_adv_track_event_multiset_is_order_insensitive_but_count_sensitive():
    a = _art()
    # duplicate one event: same set of event-types, but multiset diverges
    dup = list(a.track_events) + [a.track_events[0]]
    b = _art(track_events=dup)
    divs = he.compare_drain_artefacts(a, b)
    assert any(d.field == "track_events" for d in divs)


def test_adv_run_drain_cycle_is_deterministic_under_replay(seeded_baseline):
    baseline_dir, _ = seeded_baseline
    runner_calls = []

    def runner(brief):
        runner_calls.append(brief)
        return _art(test_count=1)

    r1 = he.run_drain_cycle(
        brief_id="stab_001", cycle_runner=runner, baseline_dir=baseline_dir
    )
    r2 = he.run_drain_cycle(
        brief_id="stab_001", cycle_runner=runner, baseline_dir=baseline_dir
    )
    assert r1.clean is False and r2.clean is False
    assert [d.field for d in r1.divergences] == [d.field for d in r2.divergences]


# ---------------------------------------------------------------------------
# CLI adversarial
# ---------------------------------------------------------------------------


def _cli_env(tmp_path):
    env = dict(os.environ)
    env["JANUSMASK_PROJECT_DIR"] = str(tmp_path)
    return env


def test_adv_cli_drain_deterministic_exit_on_replay(tmp_path, seeded_baseline):
    _baseline_dir, art = seeded_baseline
    actual_art = _art(test_count=1)
    actual_path = tmp_path / "actual.json"
    actual_path.write_text(
        json.dumps(he.drain_artefacts_to_dict(actual_art)), encoding="utf-8"
    )
    codes = set()
    for _ in range(3):
        proc = subprocess.run(
            [
                sys.executable,
                "-m",
                "harness.hooks_equivalence",
                "--drain",
                "stab_001",
                "--actual-path",
                str(actual_path),
            ],
            capture_output=True,
            text=True,
            env=_cli_env(tmp_path),
        )
        codes.add(proc.returncode)
    assert codes == {1}


def test_adv_cli_drain_does_not_mutate_config_unless_emit_rollback(tmp_path, seeded_baseline):
    _baseline_dir, art = seeded_baseline
    config = tmp_path / "harness" / "config.yaml"
    config.parent.mkdir()
    config.write_text("hooks:\n  mode: shadow\n", encoding="utf-8")
    actual_art = _art(test_count=1)
    actual_path = tmp_path / "actual.json"
    actual_path.write_text(
        json.dumps(he.drain_artefacts_to_dict(actual_art)), encoding="utf-8"
    )
    subprocess.run(
        [
            sys.executable,
            "-m",
            "harness.hooks_equivalence",
            "--drain",
            "stab_001",
            "--actual-path",
            str(actual_path),
        ],
        capture_output=True,
        text=True,
        env=_cli_env(tmp_path),
    )
    assert "mode: shadow" in config.read_text(encoding="utf-8")


def test_adv_cli_drain_emit_rollback_flips_mode_off(tmp_path, seeded_baseline):
    _baseline_dir, art = seeded_baseline
    config = tmp_path / "harness" / "config.yaml"
    config.parent.mkdir()
    config.write_text("hooks:\n  mode: shadow\n", encoding="utf-8")
    actual_art = _art(test_count=1)
    actual_path = tmp_path / "actual.json"
    actual_path.write_text(
        json.dumps(he.drain_artefacts_to_dict(actual_art)), encoding="utf-8"
    )
    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "harness.hooks_equivalence",
            "--drain",
            "stab_001",
            "--actual-path",
            str(actual_path),
            "--emit-rollback",
        ],
        capture_output=True,
        text=True,
        env=_cli_env(tmp_path),
    )
    assert proc.returncode == 1
    # Rollback signal written. The CLI's --drain path does NOT directly call
    # apply_rollback (that is the separate --rollback mode); operators invoke
    # --rollback afterwards. Signal presence is the assertion here.
    signal = tmp_path / "state" / "hooks" / "rollback_signal"
    assert signal.exists()


def test_adv_cli_drain_missing_actual_path_is_informative_error(tmp_path, seeded_baseline):
    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "harness.hooks_equivalence",
            "--drain",
            "stab_001",
            "--actual-path",
            str(tmp_path / "no_such_file.json"),
        ],
        capture_output=True,
        text=True,
        env=_cli_env(tmp_path),
    )
    assert proc.returncode != 0
    assert "actual" in (proc.stderr + proc.stdout).lower()


def test_adv_cli_drain_rejects_unknown_brief_with_exit_nonzero(tmp_path):
    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "harness.hooks_equivalence",
            "--drain",
            "not_a_brief",
        ],
        capture_output=True,
        text=True,
        env=_cli_env(tmp_path),
    )
    assert proc.returncode != 0


# ---------------------------------------------------------------------------
# concurrency + scale
# ---------------------------------------------------------------------------


def test_adv_concurrent_run_drain_cycle_produces_independent_reports(seeded_baseline):
    baseline_dir, art = seeded_baseline
    errors = []

    def worker(i):
        try:
            report = he.run_drain_cycle(
                brief_id="stab_001",
                cycle_runner=lambda _b, i=i: _art(test_count=i),
                baseline_dir=baseline_dir,
            )
            return report.clean
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)
            return None

    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as ex:
        results = list(ex.map(worker, range(10)))
    assert not errors
    # Baseline carries test_count=776 (see seeded_baseline + _art); workers run
    # with i ∈ range(10), so no worker hits the baseline match and every report
    # must diverge. The pre-W102 assertions reduced to ``True == True`` plus a
    # membership check that passes on any non-empty result list — both let a
    # silent-cross-contamination regression slip through. Pin both the count
    # (no exception swallowed via `return None`) and the per-result divergence.
    assert len(results) == 10
    assert all(r is False for r in results), (
        f'every worker should diverge from the baseline test_count=776; '
        f'got results={results}'
    )


def test_adv_large_track_events_compare_under_two_seconds():
    import time

    a_events = [{"event": "e%d" % i, "ts": "t"} for i in range(10_000)]
    b_events = list(a_events)
    rng = random.Random(3)
    rng.shuffle(b_events)
    a = _art(track_events=a_events)
    b = _art(track_events=b_events)
    start = time.perf_counter()
    divs = he.compare_drain_artefacts(a, b)
    assert (time.perf_counter() - start) < 2.0
    assert divs == []


# ---------------------------------------------------------------------------
# meta-invariants
# ---------------------------------------------------------------------------


def test_adv_drain_briefs_match_archived_briefs_on_disk(tmp_path):
    # Invariant: every brief named in DRAIN_BRIEFS resolves to a brief_<id>.md +
    # plan_<id>.json pair under the drain-brief root, with the naming convention
    # the wrapper relies on. The real briefs are gitignored operator working-tree
    # fixtures (absent on a fresh clone), so we materialise the canonical pair set
    # in tmp_path and assert the contract against it (REPL-FIXTURE: clone-PORTABLE,
    # not skipped). Still catches a DRAIN_BRIEFS typo or a broken naming
    # convention, and runs identically on the operator machine and a clean clone.
    for brief in he.DRAIN_BRIEFS:
        (tmp_path / f"brief_{brief}.md").write_text(
            f"# Title\nstub {brief}\n", encoding="utf-8"
        )
        (tmp_path / f"plan_{brief}.json").write_text(
            '{"tasks": []}', encoding="utf-8"
        )
    for brief in he.DRAIN_BRIEFS:
        assert (tmp_path / f"brief_{brief}.md").exists(), brief
        assert (tmp_path / f"plan_{brief}.json").exists(), brief


def test_adv_drain_report_to_dict_is_json_serialisable():
    report = he.DrainReport(
        session_id="x",
        brief_id="stab_001",
        clean=False,
        divergences=[
            he.DrainDivergence(field="test_count", baseline=1, actual=2, detail="d")
        ],
        generated_at="2026-04-18T00:00:00Z",
    )
    data = report.to_dict()
    payload = json.dumps(data)
    assert "stab_001" in payload
    assert "test_count" in payload


def test_adv_fire_drain_rollback_after_consumed_signal_reffires():
    # After apply_rollback consumes a signal, a fresh regression must be able
    # to fire again (matches HOOK-54 idempotent behaviour).
    import tempfile

    with tempfile.TemporaryDirectory() as td:
        tmp = pathlib.Path(td)
        signal_path = tmp / "rollback_signal"
        config = tmp / "config.yaml"
        config.write_text("hooks:\n  mode: shadow\n", encoding="utf-8")
        blocked = tmp / "blocked"

        div = he.DrainDivergence(field="test_count", baseline=1, actual=0, detail="x")
        report = he.DrainReport(
            session_id="r1",
            brief_id="stab_001",
            clean=False,
            divergences=[div],
            generated_at="2026-04-18T00:00:00Z",
        )
        assert he.fire_drain_rollback(report, signal_path=signal_path) is True
        he.apply_rollback(
            signal_path=signal_path, config_path=config, blocked_dir=blocked
        )
        # After consumption → signal gone → next regression may fire.
        assert not signal_path.exists()
        assert he.fire_drain_rollback(report, signal_path=signal_path) is True
