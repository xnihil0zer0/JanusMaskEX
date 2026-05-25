"""JOB: daemon-drivable rebuild-job lifecycle (create / status / resume).

A rebuild JOB is the unit the autowork daemon's rebuild-watcher supervises. It
bundles a discovered ``TargetDescriptor``, an initialized output repo (skeleton
+ git + out-of-repo stash), per-unit task specs queued in the output repo, a
companion brief, and an allowlist opt-in -- all persisted under
``state/control/rebuild/jobs/<slug>.json`` so a resumable ``harness.rebuild.loop``
run can be launched, interrupted, and continued to completion hands-off.

Model A (see brief): the WebUI "Begin" button calls ``create_job`` (set-up only);
the daemon then launches ``build_loop_command(job)`` as a supervised subprocess.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

from harness.rebuild import discover as _discover
from harness.rebuild import harvest as _harvest
from harness.rebuild import loop as _loop
from harness.rebuild import task as _task
from harness.rebuild import venv as _venv
from harness.rebuild.target import TargetDescriptor

PARENT_ROOT = Path(__file__).resolve().parents[2]


def job_slug(name: str) -> str:
    """Stable allowlist/brief slug for a rebuild of project ``name``."""
    return f'rebuild_{name}'


def _jobs_dir(state_dir: Path) -> Path:
    return Path(state_dir) / 'control' / 'rebuild' / 'jobs'


def _allowlist_path(state_dir: Path) -> Path:
    return Path(state_dir) / 'control' / 'autowork' / 'auto_promote.allowlist'


def add_to_allowlist(state_dir: Path, slug: str) -> None:
    """Append ``slug`` to the autowork allowlist (idempotent). The Begin opt-in."""
    path = _allowlist_path(state_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    existing = path.read_text(encoding='utf-8') if path.exists() else ''
    present = {
        ln.strip() for ln in existing.splitlines() if ln.strip() and not ln.strip().startswith('#')
    }
    if slug in present:
        return
    sep = '' if existing.endswith('\n') or not existing else '\n'
    with path.open('a', encoding='utf-8') as f:
        f.write(f'{sep}{slug}\n')


def _descriptor_loop_json(descriptor: TargetDescriptor) -> dict:
    return {
        'name': descriptor.name,
        'source_root': str(descriptor.source_root),
        'modules': list(descriptor.modules),
        'test_files': list(descriptor.test_files),
        'seed_files': list(descriptor.seed_files),
        'full_test_command': descriptor.full_test_command,
        'unit_test_selector': descriptor.unit_test_selector,
        'dependencies': list(descriptor.dependencies),
        'requirements_files': list(descriptor.requirements_files),
    }


def _descriptor_from_job(job: dict) -> TargetDescriptor:
    d = job['descriptor']
    return TargetDescriptor(
        name=d['name'],
        source_root=Path(d['source_root']),
        modules=d['modules'],
        test_files=d['test_files'],
        output_dir=Path(job['output_dir']),
        stash_dir=Path(job['stash_dir']),
        seed_files=d.get('seed_files', []),
        full_test_command=d.get('full_test_command', 'python -m pytest -q'),
        unit_test_selector=d.get('unit_test_selector', ''),
        dependencies=d.get('dependencies', []),
        requirements_files=d.get('requirements_files', []),
    )


def _all_unit_qualnames(descriptor: TargetDescriptor) -> list[str]:
    out: list[str] = []
    for mod in descriptor.modules:
        src = (descriptor.source_root / mod).read_text(encoding='utf-8')
        out.extend(u.qualname for u in _harvest.harvest_module(mod, src, include_methods=True))
    return out


def _write_unit_tasks(descriptor: TargetDescriptor, stash_map: dict) -> int:
    """Pre-queue per-unit task specs in the OUTPUT repo (loop regenerates at run)."""
    tasks_dir = descriptor.output_dir / 'state' / 'tasks'
    tasks_dir.mkdir(parents=True, exist_ok=True)
    unit_test_text = '\n\n'.join(
        (descriptor.source_root / rel).read_text(encoding='utf-8')
        for rel in descriptor.test_files
        if (descriptor.source_root / rel).exists()
    )
    ext_modules = _loop._dep_import_names(descriptor.dependencies)
    count = 0
    for mod in descriptor.modules:
        src = (descriptor.source_root / mod).read_text(encoding='utf-8')
        units = _harvest.harvest_module(mod, src, external_modules=ext_modules)
        by_name = {u.name: u for u in units}
        for unit in units:
            sib = [by_name[c].signature for c in sorted(unit.calls) if c in by_name]
            spec = _task.build_unit_task(
                descriptor=descriptor,
                unit=unit,
                module_rel=mod,
                oracle_original_path=stash_map.get(mod, ''),
                sibling_signatures=sib,
                unit_test_text=unit_test_text,
                parent_root=str(PARENT_ROOT),
            )
            (tasks_dir / f'{spec["task_id"]}.json').write_text(
                json.dumps(spec, indent=2), encoding='utf-8'
            )
            count += 1
    return count


_BRIEF_TEMPLATE = """# REBUILD JOB (generated, audit-only): {name}

This file is auto-generated by ``harness.rebuild.job`` when a clean-room rebuild
job is created. It uses CUSTOM headings on purpose so the Path-B planner's
``brief_loader`` REJECTS it (it is NOT a dispatchable brief) -- the autowork
daemon's rebuild-WATCHER drives this job from
``state/control/rebuild/jobs/{slug}.json``, not from this brief.

## job
- slug: {slug}
- input (source, read-only oracle): {source_root}
- output (replicant, generated): {output_dir}
- modules: {modules}
- units: {n_units}

## how
The daemon supervises ``harness.rebuild.loop --resume`` until every unit's body
is reconstructed blind by the dual agents (Claude == Gemini ^ merged == original
^ scoped tests), each accepted body committed into the output repo's own git.
"""


def _write_companion_brief(descriptor: TargetDescriptor, slug: str, repo_root: Path, n_units: int) -> Path:
    path = Path(repo_root) / f'brief_hooks_{slug}.md'
    path.write_text(
        _BRIEF_TEMPLATE.format(
            name=descriptor.name,
            slug=slug,
            source_root=descriptor.source_root,
            output_dir=descriptor.output_dir,
            modules=', '.join(descriptor.modules),
            n_units=n_units,
        ),
        encoding='utf-8',
    )
    return path


def create_job(
    *,
    input_dir: Path,
    output_dir: Path,
    state_dir: Path,
    name: str | None = None,
    stash_dir: Path | None = None,
    modules: list[str] | None = None,
    test_files: list[str] | None = None,
    seed_files: list[str] | None = None,
    dependencies: list[str] | None = None,
    requirements_files: list[str] | None = None,
    repo_root: Path | None = None,
    write_brief: bool = True,
    unit_byte_budget: int | None = None,
) -> dict:
    """Set up a rebuild job: descriptor + skeleton + tasks + brief + allowlist.

    Returns the persisted job dict. Does NOT run the reconstruction (the daemon
    does, via ``build_loop_command``). ``output_dir`` MUST differ from
    ``input_dir`` (the source stays a read-only oracle).
    """
    input_dir = Path(input_dir).resolve()
    output_dir = Path(output_dir).resolve()
    if output_dir == input_dir:
        raise ValueError('output_dir must differ from input_dir (source is read-only)')
    repo_root = Path(repo_root) if repo_root is not None else PARENT_ROOT
    name = name or input_dir.name
    if stash_dir is None:
        # Default the stash ADJACENT to (but outside) the output repo so the
        # replicant never carries the answer key. Derived from output_dir, NOT
        # Path.home(), to keep harness/ clone-portable (no $HOME coupling --
        # tests/adversarial/test_replication_clean_room_static.py).
        stash_dir = output_dir.parent / f'.{output_dir.name}_rebuild_stash'
    stash_dir = Path(stash_dir).resolve()

    descriptor = _discover.build_descriptor(
        input_dir,
        output_dir=output_dir,
        stash_dir=stash_dir,
        name=name,
        modules=modules,
        test_files=test_files,
        seed_files=seed_files,
        # Forward an explicit dep list so a SLICE rebuild (e.g. a stdlib-only
        # module of a dep-bearing repo) can pass ``dependencies=[]`` to skip a
        # spurious .venv provision from the repo's own requirements (R2/#42).
        dependencies=dependencies,
        requirements_files=requirements_files,
    )
    info = _loop.init_output_repo(descriptor)
    n_tasks = _write_unit_tasks(descriptor, info['stash'])
    units = _all_unit_qualnames(descriptor)
    slug = job_slug(descriptor.name)

    jobs_dir = _jobs_dir(state_dir)
    jobs_dir.mkdir(parents=True, exist_ok=True)
    descriptor_path = jobs_dir / f'{slug}.descriptor.json'
    descriptor_path.write_text(json.dumps(_descriptor_loop_json(descriptor), indent=2), encoding='utf-8')

    brief_path = None
    if write_brief:
        brief_path = str(_write_companion_brief(descriptor, slug, repo_root, len(units)))

    job = {
        'job_id': slug,
        'name': descriptor.name,
        'status': 'pending',
        'input_dir': str(input_dir),
        'output_dir': str(output_dir),
        'stash_dir': str(stash_dir),
        'descriptor': _descriptor_loop_json(descriptor),
        'descriptor_path': str(descriptor_path),
        'brief_path': brief_path,
        'units': units,
        'n_units': len(units),
        'n_tasks': n_tasks,
        'attempts': 0,
        'unit_byte_budget': unit_byte_budget,
        'created_ts': time.time(),
        'updated_ts': time.time(),
    }
    (jobs_dir / f'{slug}.json').write_text(json.dumps(job, indent=2), encoding='utf-8')
    add_to_allowlist(state_dir, slug)
    return job


def load_job(state_dir: Path, job_id: str) -> dict | None:
    path = _jobs_dir(state_dir) / f'{job_id}.json'
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except (OSError, json.JSONDecodeError):
        return None


def list_jobs(state_dir: Path) -> list[dict]:
    jobs_dir = _jobs_dir(state_dir)
    if not jobs_dir.exists():
        return []
    out: list[dict] = []
    for p in sorted(jobs_dir.glob('*.json')):
        if p.name.endswith('.descriptor.json'):
            continue
        try:
            out.append(json.loads(p.read_text(encoding='utf-8')))
        except (OSError, json.JSONDecodeError):
            continue
    return out


def _head_sha(output_dir: Path) -> str | None:
    res = _loop._git(['rev-parse', 'HEAD'], Path(output_dir), check=False)
    return res.stdout.strip() if res.returncode == 0 else None


def job_status(state_dir: Path, job_id: str, *, persist: bool=True) -> dict:
    """Recompute a job's progress from the output repo's real bodies.

    When ``persist`` is True (default) the recomputed status is written back to
    the job file. Read-only callers (status queries, monitors, the daemon's
    completion check) MUST pass ``persist=False`` (B3, session #37): a status
    read that flips persisted ``status`` to 'complete' would suppress the
    daemon's one-shot ``rebuild_complete`` telemetry (its guard keys off the
    persisted status), hanging a ledger-grep monitor. The complete-transition
    and that telemetry are owned solely by ``autowork_daemon._watch_rebuild_jobs``.
    """
    job = load_job(state_dir, job_id)
    if job is None:
        return {'job_id': job_id, 'status': 'unknown', 'error': 'not_found'}
    descriptor = _descriptor_from_job(job)
    remaining = _loop._remaining_stubs(descriptor)
    all_units = job.get('units') or _all_unit_qualnames(descriptor)
    done = [u for u in all_units if u not in remaining]
    complete = not remaining
    status = 'complete' if complete else job.get('status', 'pending')
    job['status'] = status
    job['updated_ts'] = time.time()
    if persist:
        (_jobs_dir(state_dir) / f'{job_id}.json').write_text(json.dumps(job, indent=2), encoding='utf-8')
    out_dir = Path(job['output_dir'])
    return {
        'job_id': job_id,
        'name': job.get('name'),
        'status': status,
        'output_dir': job.get('output_dir'),
        'done': done,
        'remaining': remaining,
        'current': remaining[0] if remaining else None,
        'total': len(all_units),
        'complete': complete,
        'head_sha': _head_sha(out_dir),
        'dependencies': list(descriptor.dependencies),
        'venv_ready': _venv.venv_ready(out_dir),
    }


def build_loop_command(job: dict) -> list[str]:
    """Argv to drive ``job`` to completion via a resumable loop subprocess.

    The loop runs IN THE PARENT JanusMask (it needs ``import harness`` and is the
    process that, per-unit, spawns the output-repo worker by file path). So it is
    launched ``-m harness.rebuild.loop`` with cwd = the parent root (NOT by file
    path -- ``loop.py`` has no sys.path bootstrap; the file-path/retarget law
    applies to the orchestrator_worker the loop itself spawns into the output
    repo, see harness/rebuild/loop.build_worker_invocation). ``--resume`` so a
    re-launch continues rather than re-strips; ``--source-root`` pins the
    read-only original.
    """
    cmd = [
        sys.executable,
        '-m',
        'harness.rebuild.loop',
        '--target',
        job['descriptor_path'],
        '--output',
        job['output_dir'],
        '--stash',
        job['stash_dir'],
        '--source-root',
        job['descriptor']['source_root'],
        '--resume',
    ]
    budget = job.get('unit_byte_budget')
    if budget:
        cmd += ['--unit-byte-budget', str(int(budget))]
    return cmd


def parent_root() -> str:
    """Absolute path of the parent JanusMask root (cwd for the loop subprocess)."""
    return str(PARENT_ROOT)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description='Rebuild job lifecycle.')
    sub = p.add_subparsers(dest='cmd', required=True)
    c = sub.add_parser('create')
    c.add_argument('--input', required=True)
    c.add_argument('--output', required=True)
    c.add_argument('--state-dir', required=True)
    c.add_argument('--name', default=None)
    c.add_argument('--stash', default=None)
    s = sub.add_parser('status')
    s.add_argument('--state-dir', required=True)
    s.add_argument('--job-id', required=True)
    ls = sub.add_parser('list')
    ls.add_argument('--state-dir', required=True)
    args = p.parse_args(argv)

    if args.cmd == 'create':
        job = create_job(
            input_dir=Path(args.input),
            output_dir=Path(args.output),
            state_dir=Path(args.state_dir),
            name=args.name,
            stash_dir=Path(args.stash) if args.stash else None,
        )
        sys.stdout.write(json.dumps(job, indent=2) + '\n')
        return 0
    if args.cmd == 'status':
        sys.stdout.write(json.dumps(job_status(Path(args.state_dir), args.job_id, persist=False), indent=2) + '\n')
        return 0
    if args.cmd == 'list':
        sys.stdout.write(json.dumps(list_jobs(Path(args.state_dir)), indent=2) + '\n')
        return 0
    return 1


if __name__ == '__main__':
    sys.exit(main())
