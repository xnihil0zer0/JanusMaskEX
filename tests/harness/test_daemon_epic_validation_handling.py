"""RED oracle: harness.autowork_daemon._auto_promote validation-rejected branch.

This is a test_authoring verification oracle (NOT an implementation). It drives
the REAL ``harness.autowork_daemon._auto_promote`` over a fully hermetic tmp
``repo_root`` / ``state_dir`` (``state_dir = repo_root/'state'``) and pins the
DESIRED post-fix behaviour for a planner result that REJECTS a brief on
validation (rc=1, no plan persisted):

  * a DISTINCT ``planner_validation_rejected`` telemetry event (NOT the generic
    ``planner_hallucination_discarded`` row HEAD emits today), and
  * deterministic plan-attempt parking (marker ``deterministic`` True so the
    slug stays parked within the long backoff window).

RED on HEAD is correct and expected: today the rc=1 / no-plan path falls through
to the unconditional ``plan_dict`` read + ``_check_hallucination`` and emits
``planner_hallucination_discarded`` / ``empty_plan``; the deterministic token set
also lacks ``missing_required_child`` (and the simulated tail deliberately avoids
HEAD's space-spelled tokens). Assertions (a)/(b) therefore fail until the paired
impl lands -- that RED is the point of this oracle.

verification_command: python -m pytest tests/harness/test_daemon_epic_validation_handling.py -q
"""
import json
import os
import pathlib
import time
import pytest
import harness.autowork_daemon as autowork_daemon
SIM_WALL = 30.0
MIN_WALL = 5.0

def _build_b6_stderr_tail(child='child_payments'):
    """Synthesise a realistic B6-ordered planner stderr tail.

    Several preceding per-child violation reprs (``code=missing_required_field``,
    ``code=epic_coverage_gap``) followed by a FINAL line carrying the meaningful
    ``code=missing_required_child child=...`` repr -- sized so that repr lands
    well within the trailing 512 bytes.

    NB: deliberately avoids HEAD's deterministic tokens
    ('planvalidationerror', 'missing required field' with a SPACE,
    'validation failed') so HEAD does NOT mark the park deterministic -- that
    keeps assertions (b) genuinely RED on HEAD.
    """
    preceding = []
    for i in range(6):
        preceding.append('Violation(code=missing_required_field child=child_%d field=acceptance_criteria)' % i)
        preceding.append('Violation(code=epic_coverage_gap child=child_%d)' % i)
    final = 'Violation(code=missing_required_child child=%s parent=epic_root detail=required child brief absent)' % child
    return '\n'.join(preceding + [final]) + '\n'

def _make_config():
    return {'autowork': {'planner_min_wall_sec': MIN_WALL}}

def _setup_repo(tmp_path, slug, brief_age_sec=3600.0):
    """Build a hermetic repo_root/state_dir with a discoverable, eligible brief."""
    repo_root = tmp_path / 'repo'
    state_dir = repo_root / 'state'
    (state_dir / 'control' / 'autowork').mkdir(parents=True, exist_ok=True)
    allowlist = state_dir / 'control' / 'autowork' / 'auto_promote.allowlist'
    allowlist.write_text(slug + '\n', encoding='utf-8')
    brief = repo_root / ('brief_hooks_%s.md' % slug)
    brief.write_text('# brief for %s\n\nPlan this epic into child briefs.\n' % slug, encoding='utf-8')
    past = time.time() - brief_age_sec
    os.utime(brief, (past, past))
    return (repo_root, state_dir, brief)

def _install_fake_planner(monkeypatch, stderr_tail):
    """Monkeypatch the seam BY ATTRIBUTE NAME; write NO output plan, rc=1."""
    calls = []

    def fake(brief_path, output_plan, state_dir, timeout_sec=300.0):
        calls.append({'brief_path': pathlib.Path(brief_path), 'output_plan': pathlib.Path(output_plan), 'state_dir': pathlib.Path(state_dir), 'timeout_sec': timeout_sec})
        return (1, SIM_WALL, stderr_tail)
    monkeypatch.setattr(autowork_daemon, '_run_planner_subprocess', fake)
    return calls

def _read_rows(state_dir):
    ledger = pathlib.Path(state_dir) / 'impl_progress.jsonl'
    rows = []
    if ledger.exists():
        for line in ledger.read_text(encoding='utf-8').splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except (ValueError, json.JSONDecodeError):
                continue
            if isinstance(obj, dict):
                rows.append(obj)
    return rows

def _rows_for_event_slug(rows, event, slug):
    out = []
    for r in rows:
        if r.get('event') != event:
            continue
        detail = r.get('detail') or ''
        if slug in detail or r.get('task_id') == slug:
            out.append(r)
    return out

def _snapshot_dir(p):
    p = pathlib.Path(p)
    if not p.exists():
        return None
    out = {}
    for f in sorted(p.rglob('*')):
        try:
            out[str(f)] = f.stat().st_mtime if f.is_file() else None
        except OSError:
            out[str(f)] = None
    return out

def _run_case(tmp_path, monkeypatch, slug):
    stderr_tail = _build_b6_stderr_tail()
    repo_root, state_dir, brief = _setup_repo(tmp_path, slug)
    calls = _install_fake_planner(monkeypatch, stderr_tail)
    summary = autowork_daemon._auto_promote(repo_root, state_dir, config=_make_config())
    return {'repo_root': repo_root, 'state_dir': state_dir, 'brief': brief, 'slug': slug, 'stderr_tail': stderr_tail, 'calls': calls, 'summary': summary, 'rows': _read_rows(state_dir)}

def test_validation_rejected_emits_distinct_event_not_hallucination(tmp_path, monkeypatch):
    slug = 'epicvalrej_a'
    res = _run_case(tmp_path, monkeypatch, slug)
    assert len(res['calls']) == 1
    rejected = _rows_for_event_slug(res['rows'], 'planner_validation_rejected', slug)
    assert rejected, 'expected a planner_validation_rejected row for slug %r; events=%r' % (slug, [(r.get('event'), r.get('detail')) for r in res['rows']])

def test_no_planner_hallucination_discarded_row_for_slug(tmp_path, monkeypatch):
    slug = 'epicvalrej_b'
    res = _run_case(tmp_path, monkeypatch, slug)
    hallu = _rows_for_event_slug(res['rows'], 'planner_hallucination_discarded', slug)
    assert hallu == [], 'a validation rejection must NOT be reported as a hallucination; got %r' % hallu
    rejected = _rows_for_event_slug(res['rows'], 'planner_validation_rejected', slug)
    assert rejected, 'the distinct planner_validation_rejected row must be present'

def test_validation_rejected_is_the_only_discard_event_for_slug(tmp_path, monkeypatch):
    slug = 'epicvalrej_i'
    res = _run_case(tmp_path, monkeypatch, slug)
    discard_events = {r.get('event') for r in res['rows'] if (slug in (r.get('detail') or '') or r.get('task_id') == slug) and r.get('event') in ('planner_validation_rejected', 'planner_hallucination_discarded')}
    assert discard_events == {'planner_validation_rejected'}, 'only the validation-rejected discard event may fire for the slug; got %r' % discard_events

def test_plan_attempt_marker_written_deterministic_true(tmp_path, monkeypatch):
    slug = 'epicvalrej_c'
    res = _run_case(tmp_path, monkeypatch, slug)
    marker = autowork_daemon._plan_attempt_marker_path(res['state_dir'], slug)
    assert marker.exists(), 'plan-attempt marker must be written'
    data = json.loads(marker.read_text(encoding='utf-8'))
    assert isinstance(data, dict)
    assert data.get('deterministic') is True, 'a validation rejection is a DETERMINISTIC failure; marker=%r' % data

def test_recently_failed_to_plan_parks_slug_within_backoff_window(tmp_path, monkeypatch):
    slug = 'epicvalrej_d'
    res = _run_case(tmp_path, monkeypatch, slug)
    marker = autowork_daemon._plan_attempt_marker_path(res['state_dir'], slug)
    assert marker.exists()
    data = json.loads(marker.read_text(encoding='utf-8'))
    assert res['brief'].stat().st_mtime <= float(data['last_ts']), 'brief mtime must be <= marker last_ts so _recently_failed_to_plan keeps the park'
    assert autowork_daemon._recently_failed_to_plan(res['state_dir'], slug) is True, 'a deterministic validation rejection must park the slug within the backoff window'

def test_plan_attempt_marker_under_expected_control_path(tmp_path, monkeypatch):
    slug = 'epicvalrej_h'
    res = _run_case(tmp_path, monkeypatch, slug)
    expected = res['state_dir'] / 'control' / 'autowork' / 'plan_attempts' / (slug + '.json')
    assert expected.exists(), 'marker must live under state/control/autowork/plan_attempts/'
    assert autowork_daemon._plan_attempt_marker_path(res['state_dir'], slug) == expected

def test_plan_attempt_marker_records_positive_attempt_count(tmp_path, monkeypatch):
    slug = 'epicvalrej_j'
    res = _run_case(tmp_path, monkeypatch, slug)
    marker = autowork_daemon._plan_attempt_marker_path(res['state_dir'], slug)
    data = json.loads(marker.read_text(encoding='utf-8'))
    assert isinstance(data, dict)
    attempts = data.get('attempts')
    assert isinstance(attempts, int) and (not isinstance(attempts, bool))
    assert attempts >= 1
    assert isinstance(data.get('last_ts'), (int, float)) and (not isinstance(data.get('last_ts'), bool))

def test_missing_required_child_token_lands_in_trailing_512_bytes(tmp_path, monkeypatch):
    slug = 'epicvalrej_e'
    res = _run_case(tmp_path, monkeypatch, slug)
    tail = res['stderr_tail']
    assert 'missing_required_child' in tail[-512:], 'the meaningful B6 repr must remain inside the captured trailing 512 bytes'
    assert 'missing_required_field' in tail
    assert 'epic_coverage_gap' in tail
    assert 'missing_required_child' in tail.rstrip('\n').splitlines()[-1]

def test_hermetic_tmp_repo_never_touches_live_state(tmp_path, monkeypatch):
    live_state = pathlib.Path('state')
    before = _snapshot_dir(live_state)
    slug = 'epicvalrej_f'
    res = _run_case(tmp_path, monkeypatch, slug)
    after = _snapshot_dir(live_state)
    assert before == after, 'the live repo state/ must not be read or written'
    assert str(res['state_dir']).startswith(str(tmp_path))
    marker = autowork_daemon._plan_attempt_marker_path(res['state_dir'], slug)
    assert str(marker).startswith(str(tmp_path))
    assert (res['state_dir'] / 'impl_progress.jsonl').exists()
    assert isinstance(res['summary'], dict)

def test_no_output_plan_written_by_fake_planner_subprocess(tmp_path, monkeypatch):
    slug = 'epicvalrej_g'
    res = _run_case(tmp_path, monkeypatch, slug)
    output_plan = res['repo_root'] / ('plan_hooks_%s.json' % slug)
    assert not output_plan.exists(), 'the fake planner must write NO output plan'
    assert len(res['calls']) == 1
    assert res['calls'][0]['output_plan'].name == 'plan_hooks_%s.json' % slug