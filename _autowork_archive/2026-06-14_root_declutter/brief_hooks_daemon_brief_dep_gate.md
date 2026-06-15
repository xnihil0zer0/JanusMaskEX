---
interfaces: "adds harness/autowork_daemon.py::_brief_dep_gate_ok(task, status_records, repo_root) -> bool (brief-level frontmatter-dependency dispatch gate, deadlock-safe, error-degrades-to-True) and applies it as a single withhold-only candidate filter in _decide immediately after collect_dispatchable_tasks — making the committed oracle tests/harness/test_brief_level_dep_gate.py GREEN"
---

# Title

harness/autowork_daemon.py — brief-level dependency gating: hold a candidate task while a sibling brief named in its owning brief's frontmatter `dependencies:` still has un-accepted, non-terminal work.

# Scope

EDIT the EXISTING module harness/autowork_daemon.py (JM self task — no working_dir). CONTRACT: a child brief may declare `dependencies: [sibling-slug]` in its markdown frontmatter — a SLUG, not an in-plan task_id, so plan normalization strips it and the task-level gate in `collect_dispatchable_tasks` never sees it. Symptom (recurring, observed during the NGv2 Phase-7 epic): a child brief importing a sibling module gets dispatched before the sibling's output lands → smoke_failed → blocked → wasted attempt. The fix holds such a candidate until every depended-on sibling brief is fully accepted. DEADLOCK-SAFE by construction: a dep slug that is absent / never-planned, or whose record is terminally blocked/zombie, and ANY error path, all fall back to DISPATCH (return True) — the queue can never wedge. No state mutation; a held task is simply re-evaluated next tick.

Exactly TWO changes, nothing else:

1. NEW top-level function `_brief_dep_gate_ok(task, status_records, repo_root)` inserted between `_auto_promote` and `_decide`.
2. ONE line added to `_decide`, immediately after the `collect_dispatchable_tasks(...)` call: `candidates = [c for c in candidates if _brief_dep_gate_ok(c, status_records, repo_root)]`. Every other line of `_decide` is byte-identical to the staged baseline. `collect_dispatchable_tasks` itself is NOT touched.

⚠️ The staged baseline of this file (working-tree content, read-only at `{WORK_DIR}/inbox/targets/harness/autowork_daemon.py`) ALREADY CONTAINS both changes, pre-validated against the committed oracle. Your job is faithful TRANSCRIPTION through the gate, not invention — reproduce the two symbols from the staged baseline EXACTLY as pinned below.

DISPATCH DIRECTIVE — PATCH FORMAT (MANDATORY — R-ANCHORED SYMBOL PATCH, NEVER WHOLE-FILE): harness/autowork_daemon.py is ~2400 lines; whole-file emission is FORBIDDEN (large whole-file emissions get paraphrased). Emit a `__JANUSMASK_PATCHES__` symbol patch targeting the 1-part qualname `_decide`, whose `code` block contains the NEW function `_brief_dep_gate_ok` FIRST (an additive extra node — extra nodes must come BEFORE the reproduced anchor def; after = silently dropped) followed by the complete reproduced `_decide`. The exact `code` block content:

    def _brief_dep_gate_ok(task: dict, status_records: list[dict], repo_root: pathlib.Path) -> bool:
        """Brief-level dependency gate (companion to the task-level gate).

        A child brief may declare ``dependencies: [sibling-slug]`` in its markdown
        frontmatter -- a SLUG, not an in-plan task_id, so it is stripped at plan
        normalization and the task-level gate in ``collect_dispatchable_tasks``
        cannot see it. This holds a candidate task until every depended-on SIBLING
        BRIEF is fully accepted, so a task that imports a sibling module is not
        dispatched (-> smoke_failed -> blocked -> wasted attempt) before the sibling
        lands.

        DEADLOCK-SAFE: the gate only HOLDS on a dep slug that EXISTS in
        ``status_records`` AND still has un-accepted, non-terminal work. A dep slug
        that is absent / never-planned, or whose record is terminally blocked, falls
        back to DISPATCH so the queue can never wedge forever. Any error degrades to
        DISPATCH (True). Returns True when the task has no resolvable owning brief or
        that brief declares no frontmatter deps (byte-identical to the prior path).
        """
        if not isinstance(task, dict):
            return True
        tid = task.get('task_id')
        if not isinstance(tid, str) or not tid:
            return True
        try:
            by_slug: dict[str, dict] = {}
            owner_slug: str | None = None
            for rec in status_records or []:
                if not isinstance(rec, dict):
                    continue
                slug = rec.get('slug')
                if not isinstance(slug, str) or not slug:
                    continue
                by_slug[slug] = rec
                if owner_slug is None and tid in (rec.get('task_ids') or []):
                    owner_slug = slug
            if owner_slug is None:
                return True
            owner = by_slug[owner_slug]
            brief_name = owner.get('brief_filename') or f'brief_hooks_{owner_slug}.md'
            brief_path = pathlib.Path(repo_root) / brief_name
            dep_slugs: list[str] = []
            try:
                from harness.planner.brief_loader import _parse_frontmatter, _coerce_optional_brief_fields
                fm, _body = _parse_frontmatter(brief_path.read_text(encoding='utf-8'))
                coerced = _coerce_optional_brief_fields(fm)
                dep_slugs = [d for d in (coerced.get('dependencies') or ()) if isinstance(d, str) and d]
            except Exception:
                return True
            for dep in dep_slugs:
                if dep == owner_slug:
                    continue
                rec = by_slug.get(dep)
                if rec is None:
                    # absent / never-planned -> no-deadlock fallback: dispatch.
                    continue
                state = rec.get('state')
                if state in ('blocked', 'zombie'):
                    # terminally / un-progressable -> no-deadlock fallback: dispatch.
                    continue
                remaining = rec.get('remaining')
                task_ids = rec.get('task_ids') or []
                # Fully accepted iff there is at least one task and none remain.
                if task_ids and not remaining:
                    continue
                # The dep brief exists and still has un-accepted, non-terminal work.
                return False
            return True
        except Exception:
            return True


    def _decide(repo_root: pathlib.Path, state_dir: pathlib.Path, running_task_ids: set[str], cap: int) -> tuple[list[dict], bool, int]:
        try:
            status_records = compute_brief_status(repo_root, state_dir)
        except Exception:
            status_records = []
        candidates = collect_dispatchable_tasks(status_records, running_task_ids, state_dir)
        candidates = [c for c in candidates if _brief_dep_gate_ok(c, status_records, repo_root)]
        ordered = prioritize(candidates)
        free = max(0, cap - len(running_task_ids))
        paused = _pause_flag_path(state_dir).exists() or _full_stop_path(state_dir).exists()
        if paused or free <= 0:
            return ([], paused, free)
        running_dicts = _load_running_task_dicts(state_dir, running_task_ids)
        all_tasks: list[dict] = list(ordered) + running_dicts
        admitted: list[dict] = []
        for cand in ordered:
            conflict_with: str | None = None
            for a in admitted:
                if not can_run_parallel(cand, a, all_tasks):
                    conflict_with = a.get('task_id', '') if isinstance(a, dict) else ''
                    break
            if conflict_with is None:
                for r in running_dicts:
                    if not can_run_parallel(cand, r, all_tasks):
                        conflict_with = r.get('task_id', '') if isinstance(r, dict) else ''
                        break
            if conflict_with is not None:
                tid = cand.get('task_id', '') if isinstance(cand, dict) else ''
                _emit_telemetry(state_dir, tid, 'skip', f'in-iteration conflict with {conflict_with}')
                continue
            admitted.append(cand)
            if len(admitted) >= free:
                break
        chosen = admitted[:free]
        return (chosen, paused, free)

POST-EMIT SELF-CHECK (mandatory): the patch anchors qualname `_decide` (1-part, top-level); the code block contains exactly TWO top-level `def`s with `_brief_dep_gate_ok` FIRST and `_decide` SECOND; `_decide` contains the exact line `candidates = [c for c in candidates if _brief_dep_gate_ok(c, status_records, repo_root)]` immediately after the `collect_dispatchable_tasks` line; no other symbol of the module is named or modified; no import statements are added at module top (`pathlib` is already imported; `_parse_frontmatter` is imported lazily inside the function body exactly as pinned).

# Required plan shape

EXACTLY ONE impl task. Use this task_id VERBATIM (the committed oracle and the operator decision file are keyed to it): `task_id`: `daemon_brief_dep_gate`. meta_task_type=`harness_self_fix` (production harness edit — bypass_fuzzer + skip_smoke_gates per META_TASK_POLICY; the operator decision file at state/control/decisions/daemon_brief_dep_gate.json authorizes the harness/** write). priority: high. dependencies: []. working_dir: ABSENT (JM self task — do NOT set it). files_touched: `["harness/autowork_daemon.py"]` ONLY. partial_edit semantics: R-ANCHORED SYMBOL PATCH per the DISPATCH DIRECTIVE — the DISPATCH DIRECTIVE — PATCH FORMAT paragraph above (including the full pinned code block) MUST be copied VERBATIM into the task's `implementation_notes` so the blind worker sees it. verification_command: `python3 -m pytest -q tests/harness/test_brief_level_dep_gate.py`. The committed RED oracle tests/harness/test_brief_level_dep_gate.py is the authoritative acceptance contract — make it GREEN (5 tests); do NOT author new tests. `test_spec.regression_tests` MUST list at least two entries that NAME existing test cases from the committed oracle (plan descriptors referencing committed tests — this does NOT authorize authoring new tests), e.g. `test_unmet_brief_dep_holds_dispatch`, `test_absent_dep_slug_does_not_deadlock`, `test_terminally_blocked_dep_does_not_deadlock`.

# Non-Goals

Do NOT touch `collect_dispatchable_tasks`, `prioritize`, `can_run_parallel`, `_auto_promote`, or any other symbol of harness/autowork_daemon.py beyond the two pinned. Do NOT touch harness/planner/brief_loader.py (its `_parse_frontmatter`/`_coerce_optional_brief_fields` are consumed as-is). Do NOT author or modify any test — the oracle is committed and authoritative. Do NOT add module-level imports, state files, telemetry events, retries, or persistence — the gate is a pure read-only filter re-evaluated each tick. Do NOT emit a whole-file replacement or a multi-file manifest. Integration/e2e testing is out of scope — verified solely by the committed unit oracle.

# Inputs

The committed authoritative oracle tests/harness/test_brief_level_dep_gate.py (currently RED on HEAD: `_brief_dep_gate_ok` does not exist → AttributeError). It pins: (i) `test_unmet_brief_dep_holds_dispatch` — owning brief declares `dependencies: [sibling]`, sibling record exists with un-accepted work ⇒ False (HOLD); (ii) `test_met_brief_dep_allows_dispatch` — sibling fully accepted (`task_ids` non-empty, `remaining` empty) ⇒ True; (iii) `test_absent_dep_slug_does_not_deadlock` — dep slug with NO record ⇒ True; (iv) `test_terminally_blocked_dep_does_not_deadlock` — dep record `state='blocked'` ⇒ True; (v) `test_no_declared_deps_is_dispatchable` — no frontmatter deps ⇒ True. `status_records` rows come from `compute_brief_status` and carry `slug`, `brief_filename`, `task_ids`, `accepted`, `remaining`, `blocked`, `state`. The owning brief is resolved by membership of the task's `task_id` in a record's `task_ids`, then its frontmatter is read from `repo_root / brief_filename` via `harness.planner.brief_loader._parse_frontmatter` + `_coerce_optional_brief_fields` (lazy import inside the function). The staged baseline already contains the full validated implementation. stdlib only.

# Deliverables

harness/autowork_daemon.py containing the new top-level `_brief_dep_gate_ok` exactly as pinned and a `_decide` that filters candidates through it immediately after `collect_dispatchable_tasks`, with every other symbol byte-identical to the staged baseline. Verified GREEN by `python3 -m pytest -q tests/harness/test_brief_level_dep_gate.py` (5 passed).
