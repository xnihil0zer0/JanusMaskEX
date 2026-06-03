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

def _harvest_selfheal_briefs(state_dir: Any, repo_root: Any, config: Any) -> int:
    """Harvest self-heal "fix" briefs from agent outboxes into ``repo_root``.

    Scans ``agent_workroot()/<agent>/<session>/outbox`` for files named
    ``brief_hooks_<task_id>_fix.md`` and, *only* when
    :func:`_selfheal_auto_promote_enabled` is true, copies each into
    ``<repo_root>/brief_hooks_selfheal_<task_id>.md`` (deterministic slug
    ``selfheal_<task_id>``).

    The operation is idempotent (an existing destination is skipped) and
    returns the number of briefs newly delivered. When the flag is false
    it is a pure no-op returning ``0`` without touching ``repo_root``.

    It never raises: per-file errors are swallowed and scanning continues.
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
                        continue
                    shutil.copyfile(str(brief), str(dest))
                    delivered += 1
                except Exception:
                    continue
    return delivered