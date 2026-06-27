__JANUSMASK_PATCHES__ = [
    {'file': 'harness/planner/cli.py', 'kind': 'symbol', 'name': '_run_epic_pipeline', 'code': r'''def _run_epic_pipeline(brief_obj, config, state_dir, output_plan) -> int:
    """Decompose an epic brief into re-plannable child briefs plus an epic record.

    Drafts the epic with both agents, diffs and reconciles in ``mode='epic'``,
    and then runs the six ordered B6 steps before any child file is written:

      1. Log reconciliation drops: for every ``recon.unresolved_items`` entry
         append a state_dir-relative ``epic_child_unresolved`` advisory row
         carrying the ``diff_item_id`` and resolution ``policy``.
      2. Inherit ``required_task_ids`` from the parent brief onto each merged
         child via ``setdefault`` (before any child file is written).
      3. Build the epic record, stamping ``required_child_slugs`` from the brief
         when declared and ``epic_slug`` from the brief source stem.
      4. Compute ``coverage_check`` via ``compute_epic_coverage``.
      5. Validate the record BEFORE writing anything; partition violations by
         ``.path`` -- a ``plan``/``plan.*`` path (or ``missing_required_child``
         code) hard-fails (exit 1, no child files, no plan), while a
         ``child_briefs[...]`` path is advisory-only.
      6. On clean validation write each ``brief_hooks_<slug>.md`` child, emit an
         ``epic_coverage_gap`` row when coverage advisories exist, persist the
         plan, and return 0.

    Returns 0 on success, 2 when both agents fail, 1 when reconciliation yields
    no children or a structural (plan-path) validation hard-fail occurs. Every
    ledger/journal write is state_dir-relative and wrapped in try/except OSError.
    """
    from harness.planner.blind_draft import run_blind_drafts
    from harness.planner.diff_extractor import extract_diff
    from harness.planner.reconciliation import run_reconciliation
    from harness.planner.brief_generator import serialize_child_brief_to_markdown
    from harness.planner.plan_validator import validate_plan, compute_epic_coverage

    def _journal_row(row):
        try:
            jp = Path(state_dir) / 'planning' / 'planner_progress.jsonl'
            jp.parent.mkdir(parents=True, exist_ok=True)
            with jp.open('a', encoding='utf-8') as f:
                f.write(json.dumps(row) + '\n')
        except OSError:
            pass

    drafts = run_blind_drafts(brief_obj, config, state_dir)
    if not drafts.claude_draft and (not drafts.gemini_draft):
        print('Both agents failed to produce a valid epic draft.', file=sys.stderr)
        return 2
    c = drafts.claude_draft or {'plan_kind': 'epic', 'child_briefs': []}
    g = drafts.gemini_draft or {'plan_kind': 'epic', 'child_briefs': []}
    diff_obj = extract_diff(c, g)
    recon = run_reconciliation(diff_obj, c, g, config, state_dir, mode='epic')

    # Step 1: journal reconciliation drops (unresolved items) -- advisory only.
    policy = getattr(recon, 'resolution_policy', None)
    for item in getattr(recon, 'unresolved_items', None) or []:
        _journal_row({
            'phase': 'planning',
            'event': 'epic_child_unresolved',
            'diff_item_id': getattr(item, 'diff_item_id', None),
            'policy': policy,
        })

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
    merged = _finalize_epic_children(merged, epic_wd, child_epics, state_dir=state_dir)

    # Step 2: inherit parent required_task_ids onto each merged child BEFORE any
    # child file is written.
    for child in merged:
        child.setdefault('required_task_ids', list(getattr(brief_obj, 'required_task_ids', ()) or []))

    child_slugs = [child['slug'] for child in merged]

    # Step 3: build + stamp the epic record.
    epic_record = {'plan_kind': 'epic', 'epic': True, 'child_briefs': merged, 'child_slugs': child_slugs}
    rcs = getattr(brief_obj, 'required_child_slugs', ()) or ()
    if isinstance(rcs, (list, tuple)) and rcs:
        epic_record['required_child_slugs'] = list(rcs)
    source = getattr(brief_obj, 'source_path', None)
    if isinstance(source, str) and source:
        stem = Path(source).stem
        epic_record['epic_slug'] = stem[len('brief_hooks_'):] if stem.startswith('brief_hooks_') else stem

    # Step 4: coverage check.
    epic_record['coverage_check'] = compute_epic_coverage(getattr(brief_obj, 'deliverables', ''), merged)

    # Step 5: validate BEFORE writing children; partition strictly by .path.
    violations = validate_plan(epic_record)
    hard_violations = []
    child_advisories = []
    for v in violations:
        vpath = getattr(v, 'path', '') or ''
        vcode = getattr(v, 'code', '') or ''
        vsev = getattr(v, 'severity', 'error') or 'error'
        if vsev != 'advisory' and (vpath == 'plan' or vpath.startswith('plan.') or vcode == 'missing_required_child'):
            hard_violations.append(v)
        else:
            # advisory-severity violations (e.g. B5 coverage_gap_warning at
            # plan.coverage_warnings) and child_briefs[...] paths are advisory, never hard-fail.
            child_advisories.append(v)

    for v in child_advisories:
        _journal_row({
            'phase': 'planning',
            'event': 'epic_child_advisory',
            'path': getattr(v, 'path', ''),
            'code': getattr(v, 'code', ''),
            'message': getattr(v, 'message', ''),
            'violation': repr(v),
        })

    if hard_violations:
        # Print hard-fail violation reprs to stderr LAST so the code= substring
        # lands in the daemon's trailing stderr_tail; write NO child files / plan.
        for v in hard_violations:
            print(repr(v), file=sys.stderr)
        return 1

    # Step 6: clean validation -- write children, journal coverage gaps, persist.
    for child in merged:
        (repo_root / ('brief_hooks_' + child['slug'] + '.md')).write_text(serialize_child_brief_to_markdown(child), encoding='utf-8')

    coverage_check = epic_record.get('coverage_check')
    uncovered = coverage_check.get('uncovered', []) if isinstance(coverage_check, dict) else []
    if uncovered:
        _journal_row({'phase': 'planning', 'event': 'epic_coverage_gap', 'uncovered': list(uncovered)})

    persist_plan(epic_record, output_plan, brief_obj=brief_obj)
    return 0
'''},
]
