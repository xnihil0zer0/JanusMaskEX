"""ngv2/poc_runner_live.py -- the QUARANTINED live detonation runner.

OWNER-HAND-AUTHORED, irreducible-tier infrastructure. This module is deliberately
NOT pipeline-built and NOT fuzz-verifiable: it performs real ``fork``/``execve`` of
an attacker-controlled PoC inside a bubblewrap jail with the network namespace
unshared. The JanusMaskJR differential fuzzer cannot validate non-deterministic,
side-effecting execution, and its verification sandbox blocks the very syscalls a
detonation needs -- which is exactly why everything *around* this seam
(:class:`ngv2.detonation.DetonationChamber` and :func:`ngv2.detonation.semantic_verdict`)
is pure and oracle-verified, while this single injected callable is hand-authored and
reviewed.

It implements the canonical runner contract consumed by ``DetonationChamber.detonate``::

    runner(poc, target_spec) -> (exit_code, stdout, stderr, duration_ms)

and additionally exposes :func:`detonate_live`, which returns the ``fs_snapshot_diff``
that :func:`ngv2.detonation.semantic_verdict` consumes (the richer Semantic-Oracle gate)
alongside the 4-tuple fields.

Containment (the load-bearing controls, mirrored from JanusMaskJR's
``harness/agent_jail.py::build_jail_argv`` execute path, ``bind_credentials=False``):
  * ``--unshare-net``/``--unshare-ipc``/``--unshare-pid`` -- no off-host exfil, no
    shared IPC, no host process visibility;
  * the TARGET repo is bind-mounted **read-only** (``--ro-bind``) -- the PoC cannot
    tamper with the code under audit;
  * the only writable surface is a per-detonation ``--tmpfs`` workspace -- the PoC's
    filesystem effects are observable there and nowhere else;
  * ``--die-with-parent`` + a hard wall-clock timeout bound the blast in time.

The Semantic Oracle is a cleanroom filesystem snapshot/diff (the
``audit_mvp`` strace/FS-snapshot reference is not vendored here): the writable
workspace is hashed before and after detonation and the structured diff is what
``semantic_verdict`` matches ``expected_fs_signature`` against.

NOTE: this module is impure by design (subprocess, clock, tmpfs). Do NOT import it
from the stdlib-only ``ngv2`` core paths; it is injected at runtime only.
"""
from __future__ import annotations
import hashlib
import os
import shutil
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Callable
from typing import Iterable
from typing import Mapping
from typing import Optional
from typing import Sequence
from typing import Tuple
from ngv2.contracts import PoC
__all__ = ('LiveRunnerError', 'bwrap_available', 'build_detonation_jail_argv', 'snapshot_tree', 'diff_snapshots', 'make_live_runner', 'detonate_live', 'run_jailed_poc_with_loopback')
_SYSTEM_RO: Tuple[str, ...] = ('/usr', '/bin', '/sbin', '/lib', '/lib32', '/lib64', '/etc', '/opt')
DEFAULT_TIMEOUT_S: float = 30.0
TIMEOUT_EXIT_CODE: int = 124
DEFAULT_SUCCESS_MARKER: str = 'VULNERABLE'
_LANG_EXT: Mapping[str, str] = {'python': 'py', 'py': 'py', 'python3': 'py', 'bash': 'sh', 'sh': 'sh', 'shell': 'sh', 'node': 'js', 'javascript': 'js', 'js': 'js'}
_LANG_INTERP: Mapping[str, Tuple[str, ...]] = {'py': ('python3',), 'sh': ('bash',), 'js': ('node',)}

class LiveRunnerError(RuntimeError):
    """Raised when the live jail cannot be constructed (fail-closed)."""

def bwrap_available() -> bool:
    """True iff ``bwrap`` is on PATH (required; fail-closed otherwise)."""
    return shutil.which('bwrap') is not None

def build_detonation_jail_argv(cmd: Sequence[str], *, repo_root: Optional[str | Path], work_dir: str | Path, extra_ro: Iterable[str | Path]=(), shared_loopback_netns: bool=False) -> list[str]:
    """Wrap ``cmd`` in a minimal, maximally-isolated detonation ``bwrap`` argv.

    The target ``repo_root`` (if given) is bind-mounted READ-ONLY; ``work_dir`` is
    the sole writable surface (the caller hands in a tmpfs-backed scratch dir, also
    re-exposed inside the jail as a ``--tmpfs`` so writes never escape). The network,
    IPC and PID namespaces are unshared. Raises :class:`LiveRunnerError` if ``bwrap``
    is unavailable -- never silently runs un-jailed.

    **Network isolation knob (``shared_loopback_netns``).** Both modes give the PoC a
    FRESH, fully-isolated network namespace with ONLY ``lo`` (no ``eth*``, no route
    off-host -- outbound stays blocked either way). The difference is *who* owns the
    netns and whether ``CAP_NET_ADMIN`` is retained inside it:

      * ``False`` (default, legacy path): ``--unshare-net`` -- a fresh netns the PoC
        cannot reconfigure. Used for callback-free CWEs (RCE / path-trav / code-inj).
      * ``True`` (P1.3 leaf-2 shared-loopback path): the jail itself OWNS a fresh
        user+network namespace and retains ``CAP_NET_ADMIN`` *within that userns only*
        (``--unshare-user --uid 0 --gid 0 --cap-add CAP_NET_ADMIN --unshare-net
        --unshare-ipc --unshare-pid``) so the FIRST process of the jail -- the
        :mod:`ngv2._loopback_netns` bootstrap -- can bring ``lo`` UP and bind the
        loopback listener *inside* this same netns, which the jailed PoC then reaches
        over one shared loopback stack. We let ``bwrap`` own the userns (rather than
        creating it ourselves before exec) for RELIABILITY/simplicity -- bwrap does the
        ``setgroups``-deny + ``uid_map``/``gid_map`` dance correctly and atomically; it
        is NOT because nested userns creation would fail here (single-mapping ``uid_map``
        writes succeed from this host's init userns). The private PID namespace
        (``--unshare-pid``) is RETAINED for host-process isolation: it works inside the
        bwrap-owned userns and keeps the PoC from seeing/signalling host processes,
        while ``lo``-up and the listener bind are independent of it (no functional cost).
        This is the ONLY net-policy change; it adds NO new bind mount and does NOT widen
        the host's privileges (the cap is scoped to the jail's own userns/netns and
        confers no authority over host network resources). Outbound is STILL blocked
        (only ``lo``; no ``eth*``/route). Taken only when a loopback listener is in play
        (SSRF / CWE-918); never silently for the callback-free path.
    """
    bwrap = shutil.which('bwrap')
    if bwrap is None:
        raise LiveRunnerError("bubblewrap ('bwrap') is not on PATH; refusing to detonate a PoC without a jail (fail-closed).")
    work_dir = str(Path(work_dir).resolve())
    if shared_loopback_netns:
        # The jail OWNS a fresh user+net namespace; CAP_NET_ADMIN is scoped to THAT
        # userns only (lets the in-jail bootstrap bring `lo` up). Still only `lo`, so
        # outbound stays blocked. `--unshare-pid` IS retained on this path: a private
        # pid namespace works fine here (bwrap creates it inside its own userns; this
        # is NOT prevented on this host) and is load-bearing for host-process
        # isolation -- without it the jailed PoC would run in the HOST init pid-ns,
        # seeing ~hundreds of host processes (info disclosure) and able to signal its
        # own listener (self-DoS). Bringing `lo` up and binding the listener are
        # independent of the pid namespace, so retaining it has zero functional cost.
        # The PoC also remains a child subprocess (no parent-memory access).
        net_flags: list[str] = ['--unshare-user', '--uid', '0', '--gid', '0', '--cap-add', 'CAP_NET_ADMIN', '--unshare-net', '--unshare-ipc', '--unshare-pid']
    else:
        net_flags = ['--unshare-net', '--unshare-ipc', '--unshare-pid']
    argv: list[str] = [bwrap, '--die-with-parent', *net_flags, '--new-session', '--proc', '/proc', '--dev', '/dev', '--tmpfs', '/tmp']
    for d in _SYSTEM_RO:
        if os.path.exists(d):
            argv += ['--ro-bind', d, d]
    if repo_root is not None:
        rr = str(Path(repo_root).resolve())
        if os.path.exists(rr):
            argv += ['--ro-bind', rr, rr]
    for d in extra_ro:
        d = str(d)
        if d and os.path.exists(d):
            argv += ['--ro-bind', d, d]
    argv += ['--bind', work_dir, work_dir]
    argv += ['--chdir', work_dir]
    argv += ['--']
    argv += list(cmd)
    return argv

def snapshot_tree(root: str | Path) -> dict[str, str]:
    """Return a deterministic ``{relpath: sha256}`` map of every file under ``root``.

    Directories are recorded as ``relpath + '/'`` -> ``''`` so empty-dir creation is
    visible. Symlinks are recorded by their target string (not followed). The walk is
    sorted for reproducibility.
    """
    root = Path(root)
    out: dict[str, str] = {}
    if not root.exists():
        return out
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames.sort()
        rel_dir = os.path.relpath(dirpath, root)
        if rel_dir != '.':
            out[rel_dir.replace(os.sep, '/') + '/'] = ''
        for name in sorted(filenames):
            full = Path(dirpath) / name
            rel = os.path.relpath(full, root).replace(os.sep, '/')
            try:
                if full.is_symlink():
                    out[rel] = 'symlink:' + os.readlink(full)
                    continue
                h = hashlib.sha256()
                with open(full, 'rb') as fh:
                    for chunk in iter(lambda: fh.read(65536), b''):
                        h.update(chunk)
                out[rel] = 'sha256:' + h.hexdigest()
            except OSError as exc:
                out[rel] = 'ERR:' + type(exc).__name__
    return out

def diff_snapshots(before: Mapping[str, str], after: Mapping[str, str]) -> str:
    """Render a deterministic textual diff of two :func:`snapshot_tree` maps.

    Lines are ``A <path>``/``D <path>``/``M <path>`` (added/deleted/modified),
    sorted by path. An empty string means the writable surface was untouched. This
    is the ``fs_snapshot_diff`` that :func:`ngv2.detonation.semantic_verdict` scans
    for an ``expected_fs_signature``.
    """
    lines: list[str] = []
    for path in sorted(set(before) | set(after)):
        b = before.get(path)
        a = after.get(path)
        if b is None and a is not None:
            lines.append(f'A {path}')
        elif b is not None and a is None:
            lines.append(f'D {path}')
        elif b != a:
            lines.append(f'M {path}')
    return '\n'.join(lines)

def _resolve_target_spec(target_spec: object) -> dict:
    """Coerce ``target_spec`` (dict, mapping, or attr-bag) to a plain dict.

    Recognized keys: ``repo_root`` (ro-bind target), ``extra_ro`` (iterable of
    ro-bind paths), ``timeout_s`` (wall-clock bound), ``cmd`` (explicit entrypoint
    argv; overrides language inference), ``env`` (extra child env). Unknown shapes
    yield ``{}`` (a jail with no target ro-bind, scratch-only).
    """
    if isinstance(target_spec, Mapping):
        return dict(target_spec)
    spec: dict = {}
    for key in ('repo_root', 'extra_ro', 'timeout_s', 'cmd', 'env'):
        if hasattr(target_spec, key):
            spec[key] = getattr(target_spec, key)
    return spec

def _poc_filename(poc: PoC) -> str:
    ext = _LANG_EXT.get((poc.language or '').lower().strip(), 'txt')
    return f'poc.{ext}'

def _entry_cmd(poc: PoC, poc_path: str, python_bin: Optional[str]=None) -> list[str]:
    """Build the in-jail command that runs the PoC.

    Precedence: an explicit ``poc.entrypoint`` that names an interpreter+args is
    honored verbatim (split on whitespace, with ``{poc}`` substituted); otherwise the
    interpreter is inferred from the language and the written PoC file is the argv[1].
    A ``python_bin`` override (from ``target_spec``) supplies the interpreter for
    python PoCs -- targets needing a specific runtime (e.g. 3.11+ for ``tomllib``)
    pass their own interpreter path here.
    """
    ext = _LANG_EXT.get((poc.language or '').lower().strip(), 'txt')
    interp = _LANG_INTERP.get(ext, ('python3',))
    if python_bin and ext == 'py':
        interp = (python_bin,)
    entry = (poc.entrypoint or '').strip()
    if entry and entry not in {poc_path, os.path.basename(poc_path)}:
        parts = entry.split()
        return [p.replace('{poc}', poc_path) for p in parts]
    return [*interp, poc_path]

def detonate_live(poc: PoC, target_spec: object=None, *, timeout_s: Optional[float]=None, success_marker: str=DEFAULT_SUCCESS_MARKER, expected_fs_signature: Optional[str]=None, pip_installer: Optional[Callable[[str, str], bool]]=None, jail_runner: Optional[Callable[..., dict]]=None, loopback: bool=False) -> dict:
    """Detonate ``poc`` for real in a bwrap jail and return the full result.

    Returns a dict with the 4 runner fields plus ``fs_snapshot_diff`` and (when an
    ``expected_fs_signature`` is supplied) the :func:`ngv2.detonation.semantic_verdict`
    it implies::

        {exit_code, stdout, stderr, duration_ms, fs_snapshot_diff, verdict?}

    On a wall-clock timeout, ``exit_code`` is :data:`TIMEOUT_EXIT_CODE` and partial
    output is preserved. Never raises for PoC-side failures; only a jail-construction
    failure (no bwrap) raises :class:`LiveRunnerError`.

    **Missing-dep install fallback.** When the first run FAILS (non-zero exit, not
    confirmed) with a ``ModuleNotFoundError`` for a genuine third-party dep of the
    cloned target (a name that is NOT one of the target's own top-level packages),
    the missing dep is ``pip install``-ed HOST-SIDE (network available, outside the
    jail) into a ``_jmdeps`` dir, which is then bound READ-ONLY into a fresh jail and
    prepended to ``PYTHONPATH`` for a re-run. This lets a REAL sink fire when it was
    only masked by an uninstalled transitive import; it never changes the verdict
    gate, so it cannot manufacture a false positive. Bounded to
    :data:`MAX_DEP_INSTALL_ROUNDS` rounds; pip failure degrades to the original
    failure. The before/after fs snapshots are taken around the FINAL run and exclude
    ``_jmdeps`` so installed deps never appear in the diff.

    ``pip_installer(name, target_dir) -> bool`` and
    ``jail_runner(cmd, *, repo_root, work_dir, extra_ro, child_env, timeout_s) -> dict``
    are injectable seams (defaulting to the real host-pip / subprocess-in-bwrap
    paths) so the install/rerun loop is unit-testable without real network or jail.
    """
    _injected_jail_runner = jail_runner
    if jail_runner is None and (not loopback):
        jail_runner = _default_jail_runner
    spec = _resolve_target_spec(target_spec)
    repo_root = spec.get('repo_root')
    extra_ro = list(spec.get('extra_ro') or ())
    python_bin = spec.get('python_bin')
    if pip_installer is None:
        _jail_py = python_bin or '/usr/bin/python3'
        pip_installer = lambda _name, _target_dir: _default_pip_installer(_name, _target_dir, _jail_py)
    if timeout_s is None:
        timeout_s = float(spec.get('timeout_s', DEFAULT_TIMEOUT_S))
    path_entries = ['/usr/bin', '/bin', '/usr/local/bin']
    if python_bin:
        pb = Path(python_bin).resolve()
        bin_dir = str(pb.parent)
        prefix = str(pb.parent.parent)
        if os.path.isdir(prefix):
            extra_ro.append(prefix)
        path_entries.insert(0, bin_dir)
    child_env = {'PATH': ':'.join(path_entries), 'HOME': '/tmp', 'LANG': 'C.UTF-8', 'PYTHONDONTWRITEBYTECODE': '1'}
    if isinstance(spec.get('env'), Mapping):
        child_env.update({str(k): str(v) for k, v in spec['env'].items()})
    work_dir = tempfile.mkdtemp(prefix='ngv2-detonate-')
    deps_dir = os.path.join(work_dir, JMDEPS_DIRNAME)
    os.makedirs(deps_dir, exist_ok=True)
    target_top = _target_top_packages(repo_root, ())
    try:
        poc_name = _poc_filename(poc)
        poc_path = os.path.join(work_dir, poc_name)
        with open(poc_path, 'w', encoding='utf-8') as fh:
            fh.write(poc.code or '')
        cmd = spec.get('cmd') or _entry_cmd(poc, poc_path, python_bin=python_bin)
        loopback_hits: list = []
        active_jail_runner = jail_runner
        if loopback and _injected_jail_runner is None:
            # Shared-loopback-netns path: the listener lives INSIDE the jail's netns.
            # Bind the leaf-2 runner with this run's poc_path / fs_signature so it can
            # rewrite the `<<PORT>>` placeholder to the bound port and record callbacks.
            _lb_sig = expected_fs_signature or ''

            def active_jail_runner(_cmd, *, repo_root, work_dir, extra_ro, child_env, timeout_s):
                return run_jailed_poc_with_loopback(_cmd, repo_root=repo_root, work_dir=work_dir, extra_ro=extra_ro, child_env=child_env, timeout_s=timeout_s, fs_signature=_lb_sig, callback_env_keys=('NGV2_SSRF_CALLBACK',), poc_path=poc_path)
        elif loopback and _injected_jail_runner is not None:
            active_jail_runner = _injected_jail_runner

        def _snapshot_excluding_deps(root: str) -> dict:
            snap = snapshot_tree(root)
            prefix = JMDEPS_DIRNAME + '/'
            # Exclude the _jmdeps install dir AND the leaf-2 loopback config artifact so
            # neither pollutes the FS-snapshot oracle (they are infra, not PoC effects).
            return {k: v for k, v in snap.items() if k != prefix and (not k.startswith(prefix)) and (k != LOOPBACK_CFG_FILENAME)}

        def _run_once(env: Mapping[str, str], extra: Sequence[str]) -> dict:
            before = _snapshot_excluding_deps(work_dir)
            start = time.monotonic()
            run = active_jail_runner(cmd, repo_root=repo_root, work_dir=work_dir, extra_ro=list(extra), child_env=env, timeout_s=timeout_s)
            duration_ms = int(round((time.monotonic() - start) * 1000))
            after = _snapshot_excluding_deps(work_dir)
            fs_snapshot_diff = diff_snapshots(before, after)
            hits = run.get('hits')
            if hits:
                loopback_hits[:] = list(hits)
            return {'exit_code': run.get('exit_code'), 'stdout': run.get('stdout') or '', 'stderr': run.get('stderr') or '', 'duration_ms': duration_ms, 'fs_snapshot_diff': fs_snapshot_diff, 'timed_out': bool(run.get('timed_out'))}
        result = _run_once(child_env, extra_ro)
        installed: set = set()
        deps_extra_ro = list(extra_ro)
        deps_env = dict(child_env)
        for _round in range(MAX_DEP_INSTALL_ROUNDS):
            if result.get('exit_code') == 0 or result.get('timed_out'):
                break
            missing = [m for m in _missing_modules_from_stderr(result.get('stderr') or '') if m not in target_top and m not in installed]
            if not missing:
                break
            any_installed = False
            for name in missing:
                installed.add(name)
                try:
                    ok = pip_installer(name, deps_dir)
                except Exception:
                    ok = False
                if ok:
                    any_installed = True
            if not any_installed:
                break
            if deps_dir not in deps_extra_ro:
                deps_extra_ro.append(deps_dir)
            prior_pp = deps_env.get('PYTHONPATH', '')
            deps_env['PYTHONPATH'] = deps_dir + (os.pathsep + prior_pp if prior_pp else '')
            result = _run_once(deps_env, deps_extra_ro)
        if loopback:
            result['loopback_hits'] = list(loopback_hits)
        if expected_fs_signature is not None:
            from ngv2.detonation import semantic_verdict
            result['verdict'] = semantic_verdict(result['exit_code'], result['stdout'], result['stderr'], result['fs_snapshot_diff'], success_marker=success_marker, expected_fs_signature=expected_fs_signature)
        return result
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)

def make_live_runner(*, repo_root: Optional[str | Path]=None, timeout_s: float=DEFAULT_TIMEOUT_S, extra_ro: Iterable[str | Path]=()) -> Callable[[PoC, object], Tuple[Optional[int], str, str, int]]:
    """Return a runner closure matching the ``DetonationChamber`` injected seam.

    The returned ``runner(poc, target_spec)`` detonates the PoC in a fresh jail and
    yields ``(exit_code, stdout, stderr, duration_ms)`` -- the exact 4-tuple
    ``DetonationChamber.detonate`` maps onto a :class:`ngv2.contracts.LiveTestReport`.
    Defaults (``repo_root``/``timeout_s``/``extra_ro``) are overridable per call via
    keys on ``target_spec``.
    """
    base_extra = tuple(extra_ro)

    def runner(poc: PoC, target_spec: object) -> Tuple[Optional[int], str, str, int]:
        spec = _resolve_target_spec(target_spec)
        if 'repo_root' not in spec and repo_root is not None:
            spec['repo_root'] = repo_root
        merged_extra = (*base_extra, *(spec.get('extra_ro') or ()))
        if merged_extra:
            spec['extra_ro'] = merged_extra
        spec.setdefault('timeout_s', timeout_s)
        res = detonate_live(poc, spec)
        return (res['exit_code'], res['stdout'], res['stderr'], res['duration_ms'])
    return runner
import re
import sys
from typing import List
JMDEPS_DIRNAME: str = '_jmdeps'
MAX_DEP_INSTALL_ROUNDS: int = 3
PIP_INSTALL_TIMEOUT_S: float = 180.0
_MISSING_MODULE_RE = re.compile('ModuleNotFoundError: No module named [\'\\"]([^\'\\"]+)[\'\\"]')

def _missing_modules_from_stderr(stderr: str) -> List[str]:
    """Top-level names of every ``ModuleNotFoundError: No module named 'X'`` in
    ``stderr`` (deduped, order-preserving). ``X.y.z`` is reduced to ``X`` because
    ``pip install`` operates on the distribution's top-level import package; the
    install round only needs the importable top name to satisfy the import.
    """
    seen: dict[str, None] = {}
    for match in _MISSING_MODULE_RE.finditer(stderr or ''):
        top = match.group(1).split('.')[0].strip()
        if top:
            seen.setdefault(top, None)
    return list(seen)

def _target_top_packages(repo_root: Optional[str | Path], cmd: Sequence[str]) -> frozenset:
    """Top-level package names that belong to the TARGET itself (never auto-installed).

    A ``ModuleNotFoundError`` for the target's own package means the PoC's
    ``sys.path`` / grounding is wrong, NOT a missing third-party dep -- installing
    a same-named PyPI package would be both wrong and a false-positive risk, so
    such names are excluded from the install fallback. The target's top packages
    are the top-level entries (dirs with ``__init__.py`` or bare ``.py`` modules)
    under ``repo_root``.
    """
    names: set = set()
    if repo_root is None:
        return frozenset()
    root = Path(repo_root)
    try:
        if not root.is_dir():
            return frozenset()
        for child in root.iterdir():
            try:
                if child.is_dir() and (child / '__init__.py').exists():
                    names.add(child.name)
                elif child.is_file() and child.suffix == '.py':
                    names.add(child.stem)
            except OSError:
                continue
    except OSError:
        return frozenset()
    return frozenset(names)

def _default_pip_installer(name: str, target_dir: str, python_bin: str='/usr/bin/python3') -> bool:
    """Host-side ``pip install --target`` of a single dep, run with the JAIL's
    interpreter so the installed (possibly compiled) ABI matches the interpreter
    that will detonate the PoC. Network available (runs OUTSIDE the bwrap jail).
    Returns True iff pip exits 0; fail-soft (any infra error -> False, never raises).
    """
    interp = python_bin or '/usr/bin/python3'
    try:
        proc = subprocess.run([interp, '-m', 'pip', 'install', '--target', target_dir, '--no-input', '--disable-pip-version-check', name], capture_output=True, text=True, timeout=PIP_INSTALL_TIMEOUT_S)
        return proc.returncode == 0
    except Exception:
        return False

def _default_jail_runner(cmd: Sequence[str], *, repo_root: Optional[str | Path], work_dir: str, extra_ro: Sequence[str], child_env: Mapping[str, str], timeout_s: float) -> dict:
    """Build a fresh detonation jail and run ``cmd`` once; return the run fields.

    Returns ``{exit_code, stdout, stderr, timed_out}``. Raises
    :class:`LiveRunnerError` only when the jail cannot be built (fail-closed); all
    PoC-side failures are reported through the returned fields, never raised.
    """
    argv = build_detonation_jail_argv(cmd, repo_root=repo_root, work_dir=work_dir, extra_ro=extra_ro)
    try:
        proc = subprocess.run(argv, cwd=work_dir, env=dict(child_env), capture_output=True, text=True, timeout=timeout_s)
        return {'exit_code': proc.returncode, 'stdout': proc.stdout or '', 'stderr': proc.stderr or '', 'timed_out': False}
    except subprocess.TimeoutExpired as exc:
        out = exc.stdout.decode('utf-8', 'replace') if isinstance(exc.stdout, bytes) else exc.stdout or ''
        err = exc.stderr.decode('utf-8', 'replace') if isinstance(exc.stderr, bytes) else exc.stderr or ''
        return {'exit_code': TIMEOUT_EXIT_CODE, 'stdout': out, 'stderr': err, 'timed_out': True}

_LOOPBACK_BOOTSTRAP_MODULE: str = 'ngv2._loopback_netns'
LOOPBACK_CFG_FILENAME: str = '_loopback_cfg.json'

def _ngv2_pkg_root() -> str:
    """Filesystem dir that must be on ``PYTHONPATH`` to ``import ngv2`` (this pkg's
    PARENT dir). Read-only-bound into the jail so the in-jail bootstrap can import
    :mod:`ngv2._loopback_netns` + :mod:`ngv2.loopback_listener` (both stdlib-only)."""
    return str(Path(__file__).resolve().parent.parent)

def run_jailed_poc_with_loopback(cmd: Sequence[str], *, repo_root: Optional[str | Path], work_dir: str, extra_ro: Sequence[str], child_env: Mapping[str, str], timeout_s: float, fs_signature: str='', callback_env_keys: Sequence[str]=('NGV2_SSRF_CALLBACK',), poc_path: Optional[str]=None) -> dict:
    """Detonate ``cmd`` in a jail that SHARES one isolated loopback netns with the
    ``LoopbackListener`` -- the P1.3 leaf-2 SSRF/loopback path.

    Drop-in compatible with :func:`_default_jail_runner` (returns
    ``{exit_code, stdout, stderr, timed_out}``) and ADDITIONALLY returns ``hits``: the
    request paths the in-netns listener recorded. The jail OWNS a fresh user+net
    namespace (``--unshare-user ... --cap-add CAP_NET_ADMIN --unshare-net
    --unshare-ipc --unshare-pid`` -- the private pid-ns is retained for host-process
    isolation); its first
    process is the :mod:`ngv2._loopback_netns` bootstrap, which brings ``lo`` up, binds
    the listener inside the netns, rewrites the PoC's ``<<PORT>>`` placeholder to the
    bound port, and runs the PoC as a child in the SAME netns. The callback then
    reaches the listener over a shared loopback while outbound stays blocked.

    **Fail-closed:** the bootstrap MUST emit a single
    ``__NGV2_LOOPBACK_RESULT__ <json>`` line. If it does not (namespace/listener setup
    failed) and the run did not time out, this raises :class:`LiveRunnerError` -- it
    NEVER degrades to a host-netns / outbound-open path.
    """
    work_dir = str(Path(work_dir).resolve())
    pkg_root = _ngv2_pkg_root()
    # Bootstrap import path: ngv2 pkg root, read-only-bound. Separate from the PoC's
    # own child_env (the bootstrap sets the PoC's env from the config, unchanged).
    boot_extra_ro = list(extra_ro)
    if pkg_root not in boot_extra_ro and os.path.isdir(pkg_root):
        boot_extra_ro.append(pkg_root)
    cfg = {'cmd': list(cmd), 'work_dir': work_dir, 'child_env': {str(k): str(v) for k, v in dict(child_env).items()}, 'timeout_s': float(timeout_s), 'listener_port': 0, 'fs_signature': str(fs_signature or ''), 'callback_env_keys': list(callback_env_keys or ()), 'poc_path': poc_path}
    cfg_path = os.path.join(work_dir, LOOPBACK_CFG_FILENAME)
    import json as _json
    with open(cfg_path, 'w', encoding='utf-8') as fh:
        fh.write(_json.dumps(cfg))
    boot_cmd = ['python3', '-m', _LOOPBACK_BOOTSTRAP_MODULE, cfg_path]
    argv = build_detonation_jail_argv(boot_cmd, repo_root=repo_root, work_dir=work_dir, extra_ro=boot_extra_ro, shared_loopback_netns=True)
    boot_env = {'PATH': child_env.get('PATH', '/usr/bin:/bin:/usr/local/bin'), 'HOME': '/tmp', 'LANG': 'C.UTF-8', 'PYTHONDONTWRITEBYTECODE': '1', 'PYTHONPATH': pkg_root}
    try:
        proc = subprocess.run(argv, cwd=work_dir, env=boot_env, capture_output=True, text=True, timeout=timeout_s + 5.0)
        stdout = proc.stdout or ''
        stderr = proc.stderr or ''
    except subprocess.TimeoutExpired as exc:
        out = exc.stdout.decode('utf-8', 'replace') if isinstance(exc.stdout, bytes) else exc.stdout or ''
        err = exc.stderr.decode('utf-8', 'replace') if isinstance(exc.stderr, bytes) else exc.stderr or ''
        return {'exit_code': TIMEOUT_EXIT_CODE, 'stdout': out, 'stderr': err, 'timed_out': True, 'hits': []}
    payload = _parse_loopback_result(stdout)
    if payload is None:
        # No result sentinel and no timeout => the in-jail setup failed (lo down,
        # listener unbound, namespace refused). FAIL CLOSED: never fall back to a
        # host-netns / outbound-open run.
        raise LiveRunnerError('shared-loopback-netns detonation produced no result sentinel ' f'(jail/listener setup failed; refusing to degrade to host-netns). bootstrap stderr: {stderr[-500:]!r}')
    return {'exit_code': payload.get('exit_code'), 'stdout': payload.get('stdout') or '', 'stderr': payload.get('stderr') or '', 'timed_out': bool(payload.get('timed_out')), 'hits': list(payload.get('hits') or [])}

def _parse_loopback_result(stdout: str) -> Optional[dict]:
    """Extract the ``__NGV2_LOOPBACK_RESULT__ <json>`` payload from bootstrap stdout.

    Returns the parsed dict, or ``None`` if the sentinel is absent/malformed (which
    the caller treats as a fail-closed condition).
    """
    import json as _json
    from ngv2._loopback_netns import RESULT_SENTINEL
    marker = RESULT_SENTINEL + ' '
    for line in (stdout or '').splitlines():
        if line.startswith(marker):
            try:
                return _json.loads(line[len(marker):])
            except Exception:
                return None
    return None