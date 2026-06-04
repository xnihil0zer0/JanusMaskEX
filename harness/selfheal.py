"""Self-heal closed-loop primitives (leaf module).

This module owns the small set of helpers used by the self-heal closed
loop so that the large ``harness.autowork_daemon`` only needs a single
re-export import line.

It is intentionally a *leaf* module: it depends on the standard library
plus ``harness.paths.agent_workroot`` and MUST NOT import
``harness.autowork_daemon`` (that would create an import cycle).

Exports
-------
- ``_selfheal_auto_promote_enabled(config) -> bool``
- ``_harvest_selfheal_briefs(state_dir, repo_root, config) -> int``
- ``_is_selfheal_brief(slug) -> bool``
"""
from __future__ import annotations
import re
import shutil
from pathlib import Path
from typing import Any
_AGENTS = ('claude', 'gemini', 'antigravity')
_FIX_BRIEF_RE = re.compile('^brief_hooks_(.+)_fix\\.md$')

def _selfheal_auto_promote_enabled(config: Any) -> bool:
    """Return whether the self-heal auto-promote flag is enabled.

    Reads ``config['autowork']['selfheal_auto_promote']`` with a
    default-deny policy: any missing key/section, a non-mapping config,
    or a non-mapping ``autowork`` section yields ``False``.
    """
    try:
        autowork = config.get('autowork', {})
    except AttributeError:
        return False
    try:
        return bool(autowork.get('selfheal_auto_promote', False))
    except AttributeError:
        return False

def _is_selfheal_brief(slug: Any) -> bool:
    """Return ``True`` iff ``slug`` is a self-heal-originated brief slug.

    Self-heal harvests use the deterministic ``selfheal_`` prefix, so the
    eligibility branch in the daemon can recognise them without consulting
    the operator allowlist.
    """
    return isinstance(slug, str) and slug.startswith('selfheal_')

def _synthesize_selfheal_plan(repo_root: Any, state_dir: Any, task_id: str, brief_path: Path) -> None:
    """Synthesize a corrective plan file from a harvested diagnosis brief.

    Writes ``<repo_root>/plan_hooks_selfheal_<task_id>.json`` containing a
    JanusMask-shaped ``tasks`` list with exactly one task whose
    ``task_id`` is the original inner id. The synthesized task copies
    ``meta_task_type`` and ``dependencies`` out of the blocked sidecar
    ``state/tasks/blocked/<task_id>.json`` (read here, BEFORE any caller
    evicts it) and derives ``files_touched``/``objective``/corrective
    constraint from the markdown diagnosis brief, falling back to the
    blocked sidecar and then to reasonable defaults.

    Idempotency note: the original ``plan_hooks_<slug>.json`` may also
    target the same ``task_id``. ``stage_task`` is idempotent on identical
    content and refuses only already-accepted tasks, so re-targeting the
    same id from this synthesized plan does not cause a double-stage.
    """
    import json
    tid = task_id
    repo_root_path = Path(repo_root)
    state_dir_path = Path(state_dir)
    blocked_path = state_dir_path / 'tasks' / 'blocked' / f'{tid}.json'
    try:
        blocked = json.loads(blocked_path.read_text()) if blocked_path.exists() else {}
    except Exception:
        blocked = {}
    if not isinstance(blocked, dict):
        blocked = {}
    meta_task_type = blocked.get('meta_task_type', 'refactor')
    dependencies = blocked.get('dependencies', [])
    brief_text = ''
    try:
        brief_text = Path(brief_path).read_text()
    except Exception:
        brief_text = ''

    def _heading_section(text: str, *names: str) -> str:
        for nm in names:
            pat = '(?ims)^[ \\t]*#{1,6}[ \\t]*' + re.escape(nm) + '[ \\t]*:?[ \\t]*$(.*?)(?=^[ \\t]*#{1,6}[ \\t]|\\Z)'
            m = re.search(pat, text)
            if m and m.group(1).strip():
                return m.group(1).strip()
            inline = re.search('(?im)^[ \\t]*' + re.escape(nm) + '[ \\t]*[:=][ \\t]*(.+)$', text)
            if inline and inline.group(1).strip():
                return inline.group(1).strip()
        return ''
    files_touched = []
    list_match = re.search('(?is)files[_ \\t-]*touched[ \\t]*[:=][ \\t]*(\\[[^\\]]*\\])', brief_text)
    if list_match:
        try:
            parsed = json.loads(list_match.group(1))
            if isinstance(parsed, list):
                files_touched = [str(p).strip() for p in parsed if str(p).strip()]
        except Exception:
            files_touched = []
    if not files_touched:
        section = _heading_section(brief_text, 'files_touched', 'files touched', 'files')
        if section:
            for line in section.splitlines():
                bullet = re.match('[ \\t]*[-*+][ \\t]+`?([^`\\n]+?)`?[ \\t]*$', line)
                if bullet:
                    files_touched.append(bullet.group(1).strip())
                elif line.strip() and (not line.lstrip().startswith('#')):
                    files_touched.append(line.strip().strip('`'))
    if not files_touched:
        fallback_ft = blocked.get('files_touched', [])
        if isinstance(fallback_ft, list):
            files_touched = [str(p) for p in fallback_ft]
    objective = _heading_section(brief_text, 'objective', 'goal')
    if not objective:
        objective = blocked.get('objective') or f'Self-heal corrective task for {tid}'
    constraint = _heading_section(brief_text, 'corrective constraint', 'corrective constraints', 'constraint', 'constraints', 'corrective action', 'diagnosis')
    if not constraint:
        constraint = objective
    implementation_notes = constraint + '\n\nNote: stage_task is idempotent on identical content; if the original ' + f'plan also targets {tid} this synthesized plan will not double-target.'
    task = {'task_id': tid, 'title': f'Self-heal corrective task for {tid}', 'meta_task_type': meta_task_type, 'priority': blocked.get('priority', 5), 'dependencies': dependencies, 'files_touched': files_touched, 'objective': objective, 'spec': {'objective': objective, 'implementation_notes': implementation_notes}}
    plan = {'tasks': [task]}
    out_path = repo_root_path / f'plan_hooks_selfheal_{tid}.json'
    try:
        out_path.write_text(json.dumps(plan, indent=2))
    except Exception:
        pass
def _selfheal_secret() -> bytes:
    """Return the operator/daemon HMAC secret bytes, minting on first use.

    The secret path comes from the ``JANUSMASK_SELFHEAL_SECRET_PATH``
    environment override or defaults to
    ``~/.config/janusmask/selfheal_hmac_secret`` -- deliberately outside
    every jail bind (never under ``state/`` or ``repo_root``). When the
    file is absent it is minted from ``os.urandom(32)``, written with
    ``0o600`` permissions (parent directories created), and returned.
    """
    import os
    path_str = os.environ.get('JANUSMASK_SELFHEAL_SECRET_PATH')
    if path_str:
        secret_path = Path(path_str)
    else:
        secret_path = Path(os.path.expanduser('~/.config/janusmask/selfheal_hmac_secret'))
    if secret_path.exists():
        return secret_path.read_bytes()
    secret_path.parent.mkdir(parents=True, exist_ok=True)
    secret = os.urandom(32)
    fd = os.open(str(secret_path), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 384)
    try:
        os.write(fd, secret)
    finally:
        os.close(fd)
    try:
        os.chmod(str(secret_path), 384)
    except OSError:
        pass
    return secret

def _selfheal_provenance_valid(slug: str, brief_path: Any, state_dir: Any) -> bool:
    """Return ``True`` iff the provenance marker for ``slug`` is authentic.

    Reads ``state/control/autowork/selfheal_provenance/<slug>.json``,
    recomputes ``HMAC_SHA256(secret, slug + ':' + sha256_hex(brief bytes))``
    over the bytes read from ``brief_path``, and compares it with the
    stored marker using :func:`hmac.compare_digest`. Fails closed,
    returning ``False`` on any exception, a missing secret/marker, or a
    mismatch.
    """
    try:
        import hashlib
        import hmac
        import json
        state_dir_path = Path(state_dir)
        prov_path = state_dir_path / 'control' / 'autowork' / 'selfheal_provenance' / f'{slug}.json'
        if not prov_path.exists():
            return False
        marker_data = json.loads(prov_path.read_text())
        if not isinstance(marker_data, dict):
            return False
        stored = marker_data.get('marker')
        if not isinstance(stored, str):
            return False
        secret = _selfheal_secret()
        brief_bytes = Path(brief_path).read_bytes()
        digest = hashlib.sha256(brief_bytes).hexdigest()
        expected = hmac.new(secret, (slug + ':' + digest).encode(), hashlib.sha256).hexdigest()
        return hmac.compare_digest(stored, expected)
    except Exception:
        return False
def _harvest_selfheal_briefs(state_dir: Any, repo_root: Any, config: Any) -> int:
    """Harvest self-heal "fix" briefs from agent outboxes into ``repo_root``.

    Scans ``agent_workroot()/<agent>/<session>/outbox`` for files named
    ``brief_hooks_<task_id>_fix.md`` and, *only* when
    :func:`_selfheal_auto_promote_enabled` is true, copies each into
    ``<repo_root>/brief_hooks_selfheal_<task_id>.md`` (deterministic slug
    ``selfheal_<task_id>``).

    For every brief newly delivered it also synthesizes the corrective
    plan via :func:`_synthesize_selfheal_plan` (writing
    ``plan_hooks_selfheal_<task_id>.json`` next to the brief) and then
    evicts the three blocked-task sidecars under
    ``state/tasks/blocked/<task_id>.*`` so that ``compute_brief_status``
    no longer excludes the task from promotion. The synthesis is invoked
    BEFORE the eviction so the blocked sidecar is still readable when its
    ``meta_task_type``/``dependencies``/``files_touched`` are copied.

    The operation is content-aware idempotent: an existing destination
    whose bytes match the source (by sha256) is skipped, but a
    destination that *differs* from the source brief is atomically
    refreshed -- the source is copied over it, the corrective plan is
    re-synthesized, any stale ``selfheal_<task_id>.json`` plan-attempts
    markers are cleared, and the blocked sidecars are re-evicted, exactly
    as on initial delivery. Returns the number of briefs newly delivered.
    When the flag is false it is a pure no-op returning ``0`` without
    touching ``repo_root``.

    On both initial delivery and content-aware refresh it also mints an
    HMAC-SHA256 provenance marker at
    ``state/control/autowork/selfheal_provenance/selfheal_<task_id>.json``
    so jailed processes cannot forge self-heal briefs: the marker binds
    the slug to the brief bytes via the operator-only secret. Minting is
    best-effort and never raises.

    It never raises: per-file errors (including the refresh path, which
    is fail-closed and best-effort) are swallowed and scanning continues.
    """
    if not _selfheal_auto_promote_enabled(config):
        return 0
    delivered = 0
    try:
        import harness.paths as _paths
        workroot = Path(_paths.agent_workroot())
        repo_root_path = Path(repo_root)
    except Exception:
        return delivered
    state_dir_path = Path(state_dir)

    def _mint_provenance(slug: str, tid: str, brief_bytes: bytes) -> None:
        # Mint an HMAC-SHA256 provenance marker binding the slug to the
        # brief bytes. Best-effort and fail-closed: any error is swallowed
        # so the harvest loop never raises. The marker (HMAC output) is
        # safe to live under state/; the secret never is.
        try:
            import hashlib
            import hmac
            import json
            import time
            secret = _selfheal_secret()
            digest = hashlib.sha256(brief_bytes).hexdigest()
            marker = hmac.new(secret, (slug + ':' + digest).encode(), hashlib.sha256).hexdigest()
            prov_dir = state_dir_path / 'control' / 'autowork' / 'selfheal_provenance'
            prov_dir.mkdir(parents=True, exist_ok=True)
            prov_path = prov_dir / f'{slug}.json'
            prov_path.write_text(json.dumps({
                'slug': slug,
                'origin_task_id': tid,
                'marker': marker,
                'ts': int(time.time()),
                'version': 1,
            }))
        except Exception:
            pass

    for agent in _AGENTS:
        try:
            agent_dir = workroot / agent
            if not agent_dir.is_dir():
                continue
            session_dirs = sorted((p for p in agent_dir.iterdir() if p.is_dir()))
        except Exception:
            continue
        for session_dir in session_dirs:
            try:
                outbox = session_dir / 'outbox'
                if not outbox.is_dir():
                    continue
                brief_files = sorted(outbox.iterdir())
            except Exception:
                continue
            for brief in brief_files:
                try:
                    match = _FIX_BRIEF_RE.match(brief.name)
                    if not match:
                        continue
                    if not brief.is_file():
                        continue
                    task_id = match.group(1)
                    dest = repo_root_path / f'brief_hooks_selfheal_{task_id}.md'
                    if dest.exists():
                        # Content-aware refresh: only re-deliver when the
                        # destination brief differs from the source. This whole
                        # block is fail-closed -- any error (hashlib/os/IO) is
                        # swallowed so the harvest loop never raises.
                        try:
                            import hashlib
                            import os
                            src_bytes = brief.read_bytes()
                            dest_bytes = dest.read_bytes()
                            if hashlib.sha256(src_bytes).hexdigest() == hashlib.sha256(dest_bytes).hexdigest():
                                # Identical content -> idempotent skip.
                                continue
                            # Different content -> atomically replace dest with
                            # the source brief (temp write + os.replace).
                            tmp_dest = dest.with_name(dest.name + '.selfheal.tmp')
                            try:
                                tmp_dest.write_bytes(src_bytes)
                                os.replace(str(tmp_dest), str(dest))
                            except Exception:
                                try:
                                    shutil.copyfile(str(brief), str(dest))
                                finally:
                                    try:
                                        tmp_dest.unlink()
                                    except OSError:
                                        pass
                            # Re-run plan synthesis BEFORE evicting the blocked
                            # sidecar so it is still readable for synthesis.
                            try:
                                _synthesize_selfheal_plan(repo_root_path, state_dir_path, task_id, dest)
                            except Exception:
                                pass
                            # Mint a fresh provenance marker bound to the
                            # refreshed brief bytes.
                            _mint_provenance(f'selfheal_{task_id}', task_id, src_bytes)
                            # Clear any stale plan-attempts markers so the
                            # refreshed brief is re-planned from scratch.
                            for _marker in (
                                state_dir_path / 'plan_attempts' / f'selfheal_{task_id}.json',
                                state_dir_path / 'control' / 'autowork' / 'plan_attempts' / f'selfheal_{task_id}.json',
                            ):
                                try:
                                    _marker.unlink()
                                except OSError:
                                    pass
                            # Re-evict the blocked sidecars, identical to the
                            # initial-delivery eviction below.
                            blocked_dir = state_dir_path / 'tasks' / 'blocked'
                            for _sidecar in (f'{task_id}.json', f'{task_id}.retry.json', f'{task_id}.exhausted'):
                                try:
                                    (blocked_dir / _sidecar).unlink()
                                except OSError:
                                    pass
                        except Exception:
                            pass
                        continue
                    shutil.copyfile(str(brief), str(dest))
                    delivered += 1
                    # Synthesize the corrective plan FIRST -- this reads the
                    # blocked sidecar (meta_task_type/dependencies/files_touched)
                    # which must still exist at this point.
                    try:
                        _synthesize_selfheal_plan(repo_root_path, state_dir_path, task_id, dest)
                    except Exception:
                        pass
                    # Mint a provenance marker bound to the delivered brief
                    # bytes so the brief cannot be forged by jailed processes.
                    try:
                        _delivered_bytes = dest.read_bytes()
                    except Exception:
                        _delivered_bytes = b''
                    _mint_provenance(f'selfheal_{task_id}', task_id, _delivered_bytes)
                    # ONLY AFTER synthesis returns do we evict the blocked
                    # sidecars (best-effort, swallowing OSError) so the read
                    # of blocked/<tid>.json is never preceded by its unlink.
                    blocked_dir = state_dir_path / 'tasks' / 'blocked'
                    for _sidecar in (f'{task_id}.json', f'{task_id}.retry.json', f'{task_id}.exhausted'):
                        try:
                            (blocked_dir / _sidecar).unlink()
                        except OSError:
                            pass
                except Exception:
                    continue
    return delivered
