#!/usr/bin/env python3
"""Reconcile repo-root briefs/plans against GROUND TRUTH (oracle + git).

Unlike ``cleanup_stale_artifacts.py`` (a hand-maintained KEEP/DELETE list that
goes stale the instant a new brief is authored or built), this tool derives
each brief's status DYNAMICALLY, so it is correct by construction:

  - epic frontmatter ``epic: true``     -> EPIC      (decomposed via children;
                                                       never auto-archived)
  - has plan, oracle GREEN at HEAD       -> DONE      (archivable)
  - has plan, oracle RED / errors        -> PENDING   (real work, or in-flight)
  - no plan, not an epic                 -> NEEDS-PLAN (genuinely un-planned leaf)
  - plan with no brief                   -> ORPHAN-PLAN

"DONE" means: the verification_command(s) named in the plan pass against the
CURRENT tree. That is the same contract the gate uses, so a green leaf is, by
definition, already integrated -- its brief/plan are spent paperwork.

Read-only by default. ``--archive STAMP`` git-mv's DONE leaves + ORPHAN-PLANs
into _autowork_archive/<STAMP>/reconciled/ (epics are never touched). STAMP is
passed in explicitly (e.g. 2026-06-08) so the tool stays deterministic.
"""
import argparse
import json
import pathlib
import re
import shutil
import subprocess
import sys

REPO = pathlib.Path(__file__).resolve().parent.parent

FM_RE = re.compile(r'^---\s*\n(.*?)\n---\s*\n', re.DOTALL)


def brief_is_epic(path: pathlib.Path) -> bool:
    """True if the brief's YAML frontmatter declares ``epic: true``."""
    m = FM_RE.match(path.read_text(encoding='utf-8', errors='replace'))
    if not m:
        return False
    return bool(re.search(r'^\s*epic\s*:\s*true\s*$', m.group(1), re.MULTILINE))


def brief_command(path: pathlib.Path):
    """Best-effort verification_command from a brief body (when no plan exists).

    Looks for an explicit ``verification_command: "..."`` first, then falls back
    to the first ``python -m pytest ...`` line in the brief (its Deliverables /
    Required-plan-shape sections). Returns None if neither is present.
    """
    text = path.read_text(encoding='utf-8', errors='replace')
    m = re.search(r'verification_command["\s:]+["\']([^"\']+)["\']', text)
    if m:
        return m.group(1).strip()
    m = re.search(r'^\s*(python -m pytest .+?)\s*$', text, re.MULTILINE)
    return m.group(1).strip() if m else None


def plan_commands(plan_path: pathlib.Path):
    """Distinct verification_command strings across a plan's tasks."""
    try:
        data = json.loads(plan_path.read_text(encoding='utf-8'))
    except (OSError, json.JSONDecodeError):
        return []
    seen, out = set(), []
    for task in data.get('tasks', []):
        cmd = (task.get('verification_command') or '').strip()
        if cmd and cmd not in seen:
            seen.add(cmd)
            out.append(cmd)
    return out


def run_green(cmd: str) -> bool:
    """Run a verification_command from the repo root; True iff exit 0."""
    try:
        rc = subprocess.run(cmd, shell=True, cwd=REPO, timeout=600,
                            stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL).returncode
    except subprocess.SubprocessError:
        return False
    return rc == 0


def classify():
    briefs = {p.name[len('brief_hooks_'):-len('.md')]: p
              for p in REPO.glob('brief_hooks_*.md')}
    plans = {p.name[len('plan_hooks_'):-len('.json')]: p
             for p in REPO.glob('plan_hooks_*.json')}

    rows = []  # (slug, status, detail, path, plan_path|None)
    for slug, bpath in sorted(briefs.items()):
        ppath = plans.get(slug)
        if brief_is_epic(bpath):
            rows.append((slug, 'EPIC', 'decomposed via children', bpath, None))
            continue
        if ppath is None:
            # No persisted plan -- but the leaf may already be built (its plan
            # was never kept at root). Probe the brief's own oracle before
            # calling it un-planned work.
            cmd = brief_command(bpath)
            if cmd and run_green(cmd):
                rows.append((slug, 'DONE', 'built; oracle green @HEAD (no plan kept)',
                             bpath, None))
            else:
                rows.append((slug, 'NEEDS-PLAN', 'leaf with no plan', bpath, None))
            continue
        cmds = plan_commands(ppath)
        if not cmds:
            rows.append((slug, 'PENDING', 'plan has no verification_command',
                         bpath, ppath))
            continue
        green = all(run_green(c) for c in cmds)
        if green:
            rows.append((slug, 'DONE', f'{len(cmds)} oracle(s) green @HEAD',
                         bpath, ppath))
        else:
            rows.append((slug, 'PENDING', 'oracle RED/errors', bpath, ppath))

    for slug, ppath in sorted(plans.items()):
        if slug not in briefs:
            rows.append((slug, 'ORPHAN-PLAN', 'plan with no brief', None, ppath))
    return rows


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--archive', metavar='STAMP',
                    help='git-mv DONE leaves + ORPHAN-PLANs into '
                         '_autowork_archive/<STAMP>/reconciled/ (epics untouched)')
    args = ap.parse_args()

    rows = classify()
    width = max((len(r[0]) for r in rows), default=10)
    order = {'NEEDS-PLAN': 0, 'PENDING': 1, 'EPIC': 2, 'DONE': 3, 'ORPHAN-PLAN': 4}
    for slug, status, detail, _b, _p in sorted(rows, key=lambda r: (order[r[1]], r[0])):
        print(f'  {status:<12} {slug:<{width}}  {detail}')

    counts = {}
    for _s, status, *_ in rows:
        counts[status] = counts.get(status, 0) + 1
    print('\n  ' + '  '.join(f'{k}={v}' for k, v in sorted(counts.items())))

    if not args.archive:
        return 0

    dest = REPO / '_autowork_archive' / args.archive / 'reconciled'
    dest.mkdir(parents=True, exist_ok=True)
    moved = 0
    for slug, status, _d, bpath, ppath in rows:
        if status not in ('DONE', 'ORPHAN-PLAN'):
            continue
        for f in (bpath, ppath):
            if not (f and f.exists()):
                continue
            target = dest / f.name
            # Prefer ``git mv`` so tracked files keep rename history; fall back
            # to a plain move for untracked files (git mv rejects those).
            subprocess.run(['git', 'mv', str(f), str(target)],
                           cwd=REPO, check=False,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            if f.exists():
                shutil.move(str(f), str(target))
            moved += 1
    print(f'\n  archived {moved} spent artifact(s) -> {dest.relative_to(REPO)}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
