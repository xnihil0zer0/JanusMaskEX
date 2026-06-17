import argparse
import importlib.util
import json
import logging
import shutil
import sys
from pathlib import Path
import yaml
PIPELINE_STAGES = ['load_brief', 'blind_drafts', 'diff', 'reconciliation', 'attribution_stamp', 'adversarial_review', 'auto_amend_gate', 'persist_plan']

class PlanPipelineError(Exception):
    pass

class _PipelineTracker:

    def __init__(self):
        self.call_order = []

    def record(self, stage: str):
        self.call_order.append(stage)

    def verify(self, expected_stages: list[str]):
        if self.call_order != expected_stages:
            raise PlanPipelineError(f'Pipeline executed out of order: {self.call_order} != {expected_stages}')
_tracker = _PipelineTracker()

def _emit_planner_lifecycle(stage: str, state_dir: Path | None=None) -> None:
    """Append a planner lifecycle row to state/planning/planner_progress.jsonl.

    META-D2b: closes Agent-3 blind spots P1/P3/P5/P8 by tagging every
    _tracker.record(stage) boundary with a structured JSONL emit. Best-effort
    write (swallows OSError per W113). state_dir is optional because some
    callers (load_brief/diff/attribution_stamp/persist_plan) don't receive
    it; falls back to Path('state') matching cli.main hardcode.
    """
    try:
        import time as _time
        from harness._journal import write_jsonl_row
        target = (state_dir or Path('state')) / 'planning' / 'planner_progress.jsonl'
        write_jsonl_row(target, {'ts': _time.time(), 'stage': stage, 'kind': 'tracker_record'})
    except OSError:
        pass

def load_brief(brief_path: Path):
    _tracker.record('load_brief')
    _emit_planner_lifecycle('load_brief')
    from harness.planner.brief_loader import load_brief as _load
    return _load(brief_path)

def blind_drafts(brief, config, state_dir):
    _tracker.record('blind_drafts')
    _emit_planner_lifecycle('blind_drafts', state_dir)
    from harness.planner.blind_draft import run_blind_drafts as _run
    return _run(brief, config, state_dir)

def diff(c_draft, g_draft):
    _tracker.record('diff')
    _emit_planner_lifecycle('diff')
    from harness.planner.diff_extractor import extract_diff as _extract
    return _extract(c_draft, g_draft)

def reconciliation(diff_obj, c_draft, g_draft, config, state_dir):
    _tracker.record('reconciliation')
    _emit_planner_lifecycle('reconciliation', state_dir)
    from harness.planner.reconciliation import run_reconciliation as _run
    return _run(diff_obj, c_draft, g_draft, config, state_dir)

def attribution_stamp(merged_tasks, plan_diff, recon_result, bootstrap):
    _tracker.record('attribution_stamp')
    _emit_planner_lifecycle('attribution_stamp')
    from harness.planner.attribution import stamp_attribution as _stamp
    return _stamp(merged_tasks, plan_diff, recon_result, bootstrap)

def adversarial_review(merged_plan, config, state_dir):
    _tracker.record('adversarial_review')
    _emit_planner_lifecycle('adversarial_review', state_dir)
    from harness.planner.adversarial_review import run_adversarial_review as _run
    return _run(merged_plan, config, state_dir)

def auto_amend_gate(merged_plan, critique_path, config, state_dir):
    _tracker.record('auto_amend_gate')
    _emit_planner_lifecycle('auto_amend_gate', state_dir)
    from harness.planner.auto_amend import auto_amend as _run
    return _run(merged_plan, critique_path, config, state_dir)

def persist_plan(plan, out_path, brief_obj=None):
    """Persist merged plan JSON. If brief_obj is supplied and the plan lacks wrapper
    fields, inject source_brief_path + source_brief_sha256 for schema v2.1 traceability.
    Injection is skipped when brief_obj attrs are not plain strings (defensive against
    mock objects in tests).
    """
    _tracker.record('persist_plan')
    _emit_planner_lifecycle('persist_plan')
    out_path.parent.mkdir(parents=True, exist_ok=True)
    if brief_obj is not None and isinstance(plan, dict):
        sp = getattr(brief_obj, 'source_path', None)
        sh = getattr(brief_obj, 'sha256', None)
        if isinstance(sp, str) and 'source_brief_path' not in plan:
            plan['source_brief_path'] = sp
        if isinstance(sh, str) and 'source_brief_sha256' not in plan:
            plan['source_brief_sha256'] = sh
        wd = getattr(brief_obj, 'working_dir', None)
        if isinstance(wd, str) and wd and ('working_dir' not in plan):
            plan['working_dir'] = wd
        rti = getattr(brief_obj, 'required_task_ids', ()) or ()
        if isinstance(rti, (list, tuple)) and rti and ('required_task_ids' not in plan):
            plan['required_task_ids'] = list(rti)
        pe = getattr(brief_obj, 'parent_epic_slug', None)
        if isinstance(pe, str) and pe and ('parent_epic_slug' not in plan):
            plan['parent_epic_slug'] = pe
        if plan.get('plan_kind') == 'epic' and 'epic_slug' not in plan:
            sp2 = getattr(brief_obj, 'source_path', None)
            if isinstance(sp2, str):
                stem = Path(sp2).stem
                slug = stem[len('brief_hooks_'):] if stem.startswith('brief_hooks_') else stem
                plan['epic_slug'] = slug
    with open(out_path, 'w', encoding='utf-8') as f:
        json.dump(plan, f, indent=2)

def _should_run_epic(brief_obj, config) -> bool:
    """Return True only for an epic brief when hierarchical planning is enabled.

    Both conditions must hold: the brief carries a truthy ``epic`` attribute and
    ``config['hierarchical_planning']['enabled']`` is truthy. Missing keys/attrs
    default to falsy, so anything underspecified falls through to the leaf pipeline.
    """
    return bool(getattr(brief_obj, 'epic', False)) and bool(config.get('hierarchical_planning', {}).get('enabled', False))

def _finalize_epic_children(merged, epic_wd, child_epics, *, state_dir=None):
    """Canonicalize, dedupe and (optionally) epic-mark reconciled child briefs.

    Pure helper: returns a NEW list of NEW child dicts and never mutates the
    input list or its dicts. For each child in ``merged`` carrying a truthy
    ``slug``, the slug is canonicalized (``strip()`` then ``_`` -> ``-``);
    children whose canonical slug was already seen are dropped (first wins).

    On top of that exact-canonical pass, a near-synonym (subset-token) dedup is
    applied: each kept child's significant-token set is ``frozenset(canonical
    .split('-')) - _STOPWORDS``. A child whose NON-EMPTY token set is a subset
    of, equal to, or a superset of any already-kept child's token set is a
    near-synonym twin and is dropped (first-seen of the group wins). A child
    with an EMPTY token set (e.g. an all-stopword slug) falls back to
    canonical-only dedup and is never subset-matched.

    A kept child lacking a truthy ``working_dir`` is stamped with ``epic_wd``
    when that is a non-empty str, and ``epic`` is set True when ``child_epics``
    is truthy.

    When ``state_dir`` is truthy, each drop appends one JSON row
    ``{"event": "epic_child_dropped", "dropped_slug": ..., "reason": ...,
    "kept_slug": ...}`` to the state_dir-relative journal
    ``Path(state_dir)/'epic_dedup'/'dropped_children.jsonl'``. Journaling is
    best-effort (failures are swallowed) and never alters the returned list.
    """
    import json
    from pathlib import Path

    def _journal_drop(dropped_slug, reason, kept_slug):
        if not state_dir:
            return
        try:
            p = Path(state_dir) / 'epic_dedup' / 'dropped_children.jsonl'
            p.parent.mkdir(parents=True, exist_ok=True)
            row = {'event': 'epic_child_dropped', 'dropped_slug': dropped_slug, 'reason': reason, 'kept_slug': kept_slug}
            with open(p, 'a', encoding='utf-8') as f:
                f.write(json.dumps(row) + chr(10))
        except OSError:
            pass

    _STOPWORDS = frozenset({'and', 'of', 'the', 'for', 'to', 'a', 'an'})
    finalized = []
    seen = set()
    kept_token_sets = []
    kept_owner = []
    for child in merged:
        slug = child.get('slug')
        if not slug:
            continue
        canonical = str(slug).strip().replace('_', '-')
        import os
        import re
        canonical = os.path.basename(canonical)
        canonical = re.sub('[^A-Za-z0-9_-]', '', canonical).strip('.')
        if not canonical:
            continue
        if canonical in seen:
            _journal_drop(canonical, 'canonical_duplicate', canonical)
            continue
        child_tokens = frozenset(canonical.split('-')) - _STOPWORDS
        if child_tokens:
            survivor = None
            for ts, owner in zip(kept_token_sets, kept_owner):
                if child_tokens <= ts or ts <= child_tokens:
                    survivor = owner
                    break
            if survivor is not None:
                _journal_drop(canonical, 'near_synonym', survivor)
                continue
        seen.add(canonical)
        kept_token_sets.append(child_tokens)
        kept_owner.append(canonical)
        new_child = dict(child)
        new_child['slug'] = canonical
        if isinstance(epic_wd, str) and epic_wd and (not new_child.get('working_dir')):
            new_child['working_dir'] = epic_wd
        if child_epics:
            new_child['epic'] = True
        finalized.append(new_child)
    return finalized

def _run_epic_pipeline(brief_obj, config, state_dir, output_plan) -> int:
    """Decompose an epic brief into re-plannable child briefs plus an epic record.

    Drafts the epic with both agents, diffs and reconciles in ``mode='epic'``,
    writes a ``brief_hooks_<slug>.md`` for each merged child that carries a slug,
    and persists an epic plan record to ``output_plan``. Returns 0 on success,
    2 when both agents fail, 1 when reconciliation yields no children.
    """
    from harness.planner.blind_draft import run_blind_drafts
    from harness.planner.diff_extractor import extract_diff
    from harness.planner.reconciliation import run_reconciliation
    from harness.planner.brief_generator import serialize_child_brief_to_markdown
    drafts = run_blind_drafts(brief_obj, config, state_dir)
    if not drafts.claude_draft and (not drafts.gemini_draft):
        print('Both agents failed to produce a valid epic draft.', file=sys.stderr)
        return 2
    c = drafts.claude_draft or {'plan_kind': 'epic', 'child_briefs': []}
    g = drafts.gemini_draft or {'plan_kind': 'epic', 'child_briefs': []}
    diff_obj = extract_diff(c, g)
    recon = run_reconciliation(diff_obj, c, g, config, state_dir, mode='epic')
    merged = list(recon.merged_tasks)
    if not merged:
        print('Epic reconciliation produced no child briefs.', file=sys.stderr)
        return 1
    from harness.planner.brief_loader import _parse_frontmatter
    fm, _ = _parse_frontmatter(getattr(brief_obj, 'raw_text', '') or '')
    _ce = fm.get('child_epics') if isinstance(fm, dict) else None
    if _ce is True:
        child_epics = True
    elif isinstance(_ce, str):
        child_epics = _ce.strip().lower() in {'true', '1', 'yes', 'on'}
    else:
        child_epics = bool(_ce)
    repo_root = state_dir.parent
    epic_wd = getattr(brief_obj, 'working_dir', None)
    merged = _finalize_epic_children(merged, epic_wd, child_epics)
    child_slugs = []
    for child in merged:
        (repo_root / ('brief_hooks_' + child['slug'] + '.md')).write_text(serialize_child_brief_to_markdown(child), encoding='utf-8')
        child_slugs.append(child['slug'])
    epic_record = {'plan_kind': 'epic', 'epic': True, 'child_briefs': merged, 'child_slugs': child_slugs}
    persist_plan(epic_record, output_plan, brief_obj=brief_obj)
    return 0

def _resolve_max_planner_depth(config) -> int:
    """Resolve the planner depth budget from config defensively.

    Reads ``config['hierarchical_planning']['max_planner_depth']`` without
    introducing a new flag. When the key is absent/unparseable (or hierarchical
    planning is disabled and the key is simply missing), returns ``sys.maxsize``
    so the depth gate is a no-op and existing leaf planning is never broken.
    """
    try:
        hp = config.get('hierarchical_planning', {}) or {}
        val = hp.get('max_planner_depth', None)
    except AttributeError:
        return sys.maxsize
    if val is None:
        return sys.maxsize
    try:
        return int(val)
    except (TypeError, ValueError):
        return sys.maxsize

def _brief_slug(brief_obj) -> str:
    """Derive the brief slug used for epic-lineage lookups.

    Prefers an explicit ``slug`` attribute; otherwise falls back to the
    ``source_path`` stem, stripping the conventional ``brief_hooks_`` prefix so
    child briefs written by _run_epic_pipeline resolve to their epic slug.
    """
    slug = getattr(brief_obj, 'slug', None)
    if isinstance(slug, str) and slug:
        return slug
    sp = getattr(brief_obj, 'source_path', None)
    if isinstance(sp, str) and sp:
        stem = Path(sp).stem
        return stem[len('brief_hooks_'):] if stem.startswith('brief_hooks_') else stem
    return ''

def main(args=None):
    parser = argparse.ArgumentParser(description='Planning CLI driver')
    parser.add_argument('brief', type=Path, help='Path to the planning brief')
    parser.add_argument('--output-plan', type=Path, default=Path('state/planning/merged_plan.json'))
    parser.add_argument('--output-critique', type=Path, default=Path('state/planning/critique.json'))
    parser.add_argument('--bootstrap', action='store_true', default=True, help='Run in bootstrap mode (default)')
    parser.add_argument('--non-bootstrap', action='store_false', dest='bootstrap', help='Run in non-bootstrap mode')
    parser.add_argument('--config', type=Path, default=Path('harness/config.yaml'))
    parser.add_argument('--dry-run', action='store_true', help='Validate imports and brief, then exit')
    parsed = parser.parse_args(args)
    if parsed.dry_run:
        try:
            load_brief(parsed.brief)
        except Exception as e:
            print(f'Brief invalid: {e}', file=sys.stderr)
            sys.exit(3)
        from harness.planner.diff_extractor import extract_diff
        from harness.planner.reconciliation import run_reconciliation
        from harness.planner.attribution import stamp_attribution
        from harness.planner.adversarial_review import run_adversarial_review
        from harness.planner.auto_amend import auto_amend
        sys.exit(0)
    if parsed.bootstrap:
        if importlib.util.find_spec('harness.track_record') is None:
            import types
            dummy = types.ModuleType('harness.track_record')

            def dummy_tiebreaker(*args, **kwargs):
                from harness.planner.reconciliation import TrackRecordUnavailable
                raise TrackRecordUnavailable('bootstrap mode: track_record not available')
            dummy.track_record_tiebreaker = dummy_tiebreaker
            sys.modules['harness.track_record'] = dummy
    elif importlib.util.find_spec('harness.track_record') is None:
        print('Track record unavailable', file=sys.stderr)
        sys.exit(2)
    try:
        from harness.orchestrator import load_config
        config = load_config(parsed.config)
    except Exception as e:
        print(f'Config load failed: {e}', file=sys.stderr)
        sys.exit(2)
    state_dir = Path('state')
    try:
        brief_obj = load_brief(parsed.brief)
    except Exception as e:
        print(f'Brief load failed: {e}', file=sys.stderr)
        sys.exit(3)
    from harness.depth_validator import check_brief_depth
    repo_root = state_dir.parent
    slug = _brief_slug(brief_obj)
    max_depth = _resolve_max_planner_depth(config)
    if slug and (not check_brief_depth(slug, repo_root, max_depth)):
        print(f'Epic depth budget exceeded for brief {slug!r}; refusing to plan.', file=sys.stderr)
        sys.exit(2)
    if _should_run_epic(brief_obj, config):
        sys.exit(_run_epic_pipeline(brief_obj, config, state_dir, parsed.output_plan))
    try:
        drafts = blind_drafts(brief_obj, config, state_dir)
    except Exception as e:
        print(f'Orchestration failure: {e}', file=sys.stderr)
        sys.exit(2)
    if not drafts.claude_draft and (not drafts.gemini_draft):
        print('Both agents failed to produce a valid draft.', file=sys.stderr)
        sys.exit(2)
    if not parsed.bootstrap:
        if not drafts.claude_draft:
            print('Empty draft from claude agent (PLANNER_LOUD_FAIL_EMPTY_DRAFT)', file=sys.stderr)
            sys.exit(2)
        if not drafts.gemini_draft:
            print('Empty draft from gemini agent (PLANNER_LOUD_FAIL_EMPTY_DRAFT)', file=sys.stderr)
            sys.exit(2)
    c_safe = drafts.claude_draft or {'tasks': []}
    g_safe = drafts.gemini_draft or {'tasks': []}
    diff_obj = diff(c_safe, g_safe)
    try:
        from harness.planner.reconciliation import TrackRecordUnavailable
        recon_result = reconciliation(diff_obj, c_safe, g_safe, config, state_dir)
    except TrackRecordUnavailable:
        if not parsed.bootstrap:
            print('Track record unavailable', file=sys.stderr)
            sys.exit(2)
        raise
    except Exception as e:
        print(f'Reconciliation failure: {e}', file=sys.stderr)
        sys.exit(2)
    stamped_tasks = attribution_stamp(recon_result.merged_tasks, diff_obj, recon_result, parsed.bootstrap)
    merged_plan = {'tasks': stamped_tasks}
    gen_critique_path = adversarial_review(merged_plan, config, state_dir)
    if gen_critique_path != parsed.output_critique:
        parsed.output_critique.parent.mkdir(parents=True, exist_ok=True)
        if gen_critique_path.exists():
            shutil.copy2(gen_critique_path, parsed.output_critique)
    amend_result = auto_amend_gate(merged_plan, parsed.output_critique, config, state_dir)
    final_plan = amend_result.amended_plan
    from harness.planner.plan_normalizer import normalize_plan
    final_plan = normalize_plan(final_plan, repo_root=_effective_repo_root(brief_obj))
    _stamp_brief_metadata(final_plan, brief_obj)
    from harness.planner.plan_validator import validate_plan
    violations = validate_plan(final_plan)
    if violations:
        print(f'Merged plan failed validation: {violations}', file=sys.stderr)
        sys.exit(1)
    persist_plan(final_plan, parsed.output_plan, brief_obj=brief_obj)
    sys.exit(0)

def _effective_repo_root(brief_obj):
    from harness.paths import _target_is_self
    wd = getattr(brief_obj, 'working_dir', None)
    if isinstance(wd, str) and wd and (not _target_is_self(wd)):
        return Path(wd)
    return Path.cwd()

def _stamp_brief_metadata(plan, brief_obj):
    """Idempotently stamp brief-derived metadata onto ``plan`` BEFORE validation.

    Mirrors the stamping block inside ``persist_plan`` so the plan validator
    sees ``working_dir`` and ``required_task_ids`` (and the v2.1 traceability
    fields) at ``validate_plan`` time rather than only after persistence. Each
    write is guarded by ``'<key>' not in plan`` so an existing key is never
    overwritten, which makes the helper idempotent (a second call -- or the
    later ``persist_plan`` stamping -- is a no-op for these keys).

    Returns ``plan`` unchanged when ``brief_obj`` is None or ``plan`` is not a
    dict. Brief attributes are read defensively via ``getattr`` and only
    present, correctly-typed values are stamped; ``required_task_ids`` is
    coerced via ``list(rti)`` only when it is a non-empty list/tuple.
    """
    if brief_obj is None or not isinstance(plan, dict):
        return plan
    sp = getattr(brief_obj, 'source_path', None)
    if isinstance(sp, str) and 'source_brief_path' not in plan:
        plan['source_brief_path'] = sp
    sh = getattr(brief_obj, 'sha256', None)
    if isinstance(sh, str) and 'source_brief_sha256' not in plan:
        plan['source_brief_sha256'] = sh
    wd = getattr(brief_obj, 'working_dir', None)
    if isinstance(wd, str) and wd and ('working_dir' not in plan):
        plan['working_dir'] = wd
    rti = getattr(brief_obj, 'required_task_ids', ()) or ()
    if isinstance(rti, (list, tuple)) and rti and ('required_task_ids' not in plan):
        plan['required_task_ids'] = list(rti)
    pe = getattr(brief_obj, 'parent_epic_slug', None)
    if isinstance(pe, str) and pe and ('parent_epic_slug' not in plan):
        plan['parent_epic_slug'] = pe
    return plan
if __name__ == '__main__':
    main()