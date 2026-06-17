#!/usr/bin/env python3
"""Filter stale brief/plan/task artifacts out of the JanusMaskJR repo root.

Three buckets:
  KEEP    -- active overseer-chat build + code-referenced fixtures (stay in root)
  ARCHIVE -- reusable but inactive (NGv2 parked work, overseer reference briefs,
             external/open fix-plans) -> moved to _autowork_archive/<STAMP>/
  DELETE  -- confirmed-superseded JM-internal fix-plans whose fix already landed
             on master (worthless clutter, irreversible removal)

Dry-run by default; pass --execute to act. Re-runnable / idempotent.
Stamp is passed in (the runtime forbids Date.now-style calls in some contexts);
default mirrors the handoff date.
"""
import argparse
import json
import pathlib
import shutil
import sys

REPO = pathlib.Path(__file__).resolve().parent.parent

# --- active overseer-chat build: these stay in root -------------------------
OV_LEAVES = ['modes', 'mode-gate', 'mode-prompts', 'transcript', 'session-store', 'model-select']
BUILT_OV = ['model-select', 'session-store']  # already built+committed -> plans are spent

KEEP_BRIEFS = {'brief_hooks_overseer_chat.md', 'brief_hooks_smoke.md'} | {
    f'brief_hooks_ov-{l}.md' for l in OV_LEAVES}
KEEP_PLANS = {'plan_hooks_overseer_chat.json', 'plan_hooks_smoke.json',
              'plan_hooks_symbol_ledger_module.json'} | {
    f'plan_hooks_ov-{l}.json' for l in OV_LEAVES if l not in BUILT_OV}

# --- confirmed-landed JM-internal fix-plans (safe to delete) ----------------
DELETE_PLANS = {
    'plan_fix_capture_gate_errors.json',      # landed: gate-failure capture (Epic-4 T1)
    'plan_fix_epic_hallucination_guard.json', # landed: 689e493 epic-kickoff halluc guard
    'plan_fix_inject_oracle_sources.json',    # landed: e399c33 oracle-injection
}

# --- stale staged tasks to archive (re-stageable from kept briefs/plans) -----
STALE_TASK_SUBSTR = ['ngv2', 'T1_rlcf', 'T1_workers', 'MFF-', 'impl_js_poc',
                     'hunting-roi', 'rl-debate', 'recon-detectors', 'submission']
# pre-staged overseer impl tasks from this session's churn (re-stage from plans)
STALE_OV_TASKS = ['ov-mode-prompts-impl', 'ov-transcript-impl', 'ov-modes-impl',
                  'ov-mode-gate-impl']


def categorize_root():
    rows = []
    for p in sorted(REPO.glob('brief_hooks_*.md')) + sorted(REPO.glob('plan_*.json')):
        name = p.name
        if name in KEEP_BRIEFS or name in KEEP_PLANS:
            rows.append((name, 'KEEP', 'active overseer / code-referenced'))
        elif name in DELETE_PLANS:
            rows.append((name, 'DELETE', 'JM-internal fix already landed on master'))
        elif name.startswith('plan_hooks_ov-') or name.startswith('brief_hooks_ov-'):
            rows.append((name, 'ARCHIVE', 'spent plan for an already-built overseer leaf'))
        elif any(k in name for k in ['export', 'ngv2', 'analytics', 'rlcf', 'workers',
                                     'portfolio', 'progress', 'findings', 'huntr', 'poc',
                                     'taint', 'submission']):
            rows.append((name, 'ARCHIVE', 'NGv2 parked work (resumable per NGv2 handoff)'))
        elif any(k in name for k in ['external', 'sandbox_child', 'master_advance',
                                     'jail_project', 'smoke_import', 'working_dir',
                                     'spawn_worker', 'effective_repo', 'brief_gen']):
            rows.append((name, 'ARCHIVE', 'NGv2 external-build fix (open / NGv2-resume)'))
        elif any(k in name for k in ['interactive-driver', 'mode-and-session',
                                     'webui-backend', 'webui-control', 'webui-server',
                                     'web-api', 'config-block', 'overseer-']):
            rows.append((name, 'ARCHIVE', 'overseer epic/leaf reference brief (superseded by ov- pins)'))
        elif any(k in name for k in ['plan_fix_', 'plan_inject_', 'plan_epic_']):
            rows.append((name, 'ARCHIVE', 'stale one-off fix-plan (uncertain landed; keep reusable)'))
        else:
            rows.append((name, 'ARCHIVE', 'unclassified stale artifact (archived to be safe)'))
    return rows


def categorize_tasks():
    rows = []
    tasks_dir = REPO / 'state' / 'tasks'
    for sub in ['', 'blocked']:
        d = tasks_dir / sub if sub else tasks_dir
        if not d.is_dir():
            continue
        for p in sorted(d.glob('*.json')):
            n = p.name
            if any(s in n for s in STALE_TASK_SUBSTR):
                rows.append((str(p.relative_to(REPO)), 'ARCHIVE', 'stale NGv2/parked task (auto-dispatch landmine)'))
            elif any(n.startswith(t) for t in STALE_OV_TASKS):
                rows.append((str(p.relative_to(REPO)), 'ARCHIVE', 'stale pre-staged overseer task (re-stage from plan)'))
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--execute', action='store_true', help='perform moves/deletes (default: dry-run)')
    ap.add_argument('--stamp', default='2026-06-08', help='archive subdir stamp')
    args = ap.parse_args()

    arch = REPO / '_autowork_archive' / f'stale_briefs_{args.stamp}'
    root_rows = categorize_root()
    task_rows = categorize_tasks()
    allrows = root_rows + task_rows

    counts = {'KEEP': 0, 'ARCHIVE': 0, 'DELETE': 0}
    for _, b, _ in allrows:
        counts[b] += 1
    print(f"{'ACTION':8} {'FILE':52} REASON")
    print('-' * 110)
    for name, bucket, reason in allrows:
        if bucket == 'KEEP':
            continue  # don't spam the kept set
        print(f"{bucket:8} {name:52} {reason}")
    print('-' * 110)
    print(f"KEEP={counts['KEEP']}  ARCHIVE={counts['ARCHIVE']}  DELETE={counts['DELETE']}  (mode={'EXECUTE' if args.execute else 'DRY-RUN'})")

    if not args.execute:
        print("\n(dry-run; re-run with --execute to act)")
        return

    arch.mkdir(parents=True, exist_ok=True)
    (arch / 'TASKS').mkdir(exist_ok=True)
    manifest = []
    for name, bucket, reason in allrows:
        src = REPO / name
        if not src.exists():
            continue
        if bucket == 'ARCHIVE':
            dest = (arch / 'TASKS' / src.name) if 'state/tasks' in name else (arch / src.name)
            shutil.move(str(src), str(dest))
            manifest.append(f'ARCHIVE\t{name}\t{reason}')
        elif bucket == 'DELETE':
            src.unlink()
            manifest.append(f'DELETE\t{name}\t{reason}')
    (arch / 'MANIFEST.tsv').write_text('\n'.join(manifest) + '\n')
    print(f"\nexecuted. manifest: {arch / 'MANIFEST.tsv'}  ({len(manifest)} files acted on)")


if __name__ == '__main__':
    main()
