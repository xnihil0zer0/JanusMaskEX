"""Track record initialization and core types for JanusMask."""
from __future__ import annotations
import fcntl
import json
import os
from pathlib import Path
from typing import Any
from harness.state import _default_state_dir
from harness.state import _ensure_paths
from harness.taxonomy import load_meta_task_taxonomy
from harness.taxonomy import load_synthesis_target_taxonomy

class TrackRecordError(Exception):
    """Base exception for track record operations."""
    pass

class TrackRecordCorruptError(TrackRecordError):
    """Raised when the track record file contains invalid JSON or unexpected schema."""
    pass

class TrackRecordUnavailable(TrackRecordError):
    """Raised when the track record cannot be consulted (missing, corrupt, or unreadable)."""
    pass

def _track_record_file(state_dir: Path) -> Path:
    return state_dir / 'planner_track_record.json'

def _lock_file(state_dir: Path) -> Path:
    return state_dir / 'track_record.lock'

def _read_track_record_from_disk(path: Path) -> dict[str, Any]:
    try:
        content = path.read_text(encoding='utf-8')
        data = json.loads(content)
        if not isinstance(data, dict):
            raise ValueError('Root element of track record is not a dictionary')
        return data
    except FileNotFoundError:
        raise
    except (json.JSONDecodeError, ValueError) as exc:
        raise TrackRecordCorruptError(f'Corrupt track record file at {path}: {exc}') from exc

def _write_track_record_to_disk(path: Path, record: dict[str, Any]) -> None:
    temp_path = path.parent / f'{path.name}.tmp'
    try:
        with open(temp_path, 'w', encoding='utf-8') as f:
            json.dump(record, f, indent=2)
            f.write('\n')
            f.flush()
            os.fsync(f.fileno())
        os.replace(temp_path, path)
    except Exception:
        if temp_path.exists():
            try:
                temp_path.unlink()
            except Exception:
                pass
        raise

def init_track_record(state_dir: Path | None=None) -> dict[str, Any]:
    """
    Initialize or update the planner_track_record.json idempotently.
    Reads current taxonomy versions, preserves existing counts, and zeroes new keys.
    """
    if state_dir is None:
        state_dir = harness.state._default_state_dir()
    harness.state._ensure_paths(state_dir)
    lock_path = _lock_file(state_dir)
    with open(lock_path, 'a') as lock_file:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
        record_path = _track_record_file(state_dir)
        try:
            record = _read_track_record_from_disk(record_path)
        except FileNotFoundError:
            record = {}
        meta_tax = harness.taxonomy.load_meta_task_taxonomy(state_dir)
        synth_tax = harness.taxonomy.load_synthesis_target_taxonomy(state_dir)
        meta_keys = list(meta_tax['keys'].keys())
        synth_keys = list(synth_tax['keys'].keys())
        record['meta_task_taxonomy_version'] = meta_tax['version']
        record['synthesis_target_taxonomy_version'] = synth_tax['version']
        old_spec_authorship = record.get('spec_authorship')
        if not isinstance(old_spec_authorship, dict):
            old_spec_authorship = {}
        new_spec_authorship = {}
        all_agents = set(VALID_AGENTS)
        for agent in old_spec_authorship:
            if isinstance(agent, str):
                all_agents.add(agent)
        for agent in all_agents:
            new_spec_authorship[agent] = {}
            old_agent_data = old_spec_authorship.get(agent)
            if not isinstance(old_agent_data, dict):
                old_agent_data = {}
            for mk in meta_keys:
                if mk in old_agent_data and isinstance(old_agent_data[mk], dict):
                    cell = old_agent_data[mk]
                    new_spec_authorship[agent][mk] = {'failures': cell.get('failures', 0), 'attempts': cell.get('attempts', 0)}
                else:
                    new_spec_authorship[agent][mk] = {'failures': 0, 'attempts': 0}
        record['spec_authorship'] = new_spec_authorship
        old_synthesis = record.get('synthesis')
        if not isinstance(old_synthesis, dict):
            old_synthesis = {}
        new_synthesis = {}
        all_synthesis_agents = set(VALID_AGENTS)
        for agent in old_synthesis:
            if isinstance(agent, str):
                all_synthesis_agents.add(agent)
        for agent in all_synthesis_agents:
            new_synthesis[agent] = {}
            old_agent_data = old_synthesis.get(agent)
            if not isinstance(old_agent_data, dict):
                old_agent_data = {}
            for sk in synth_keys:
                if sk in old_agent_data and isinstance(old_agent_data[sk], dict):
                    cell = old_agent_data[sk]
                    new_synthesis[agent][sk] = {'failures': cell.get('failures', 0), 'attempts': cell.get('attempts', 0)}
                else:
                    new_synthesis[agent][sk] = {'failures': 0, 'attempts': 0}
        record['synthesis'] = new_synthesis
        _write_track_record_to_disk(record_path, record)
        return record

class InvalidAgentError(TrackRecordError):
    """Raised when an invalid agent is specified."""
    pass
from harness.track_record_events import append_track_event
from harness.taxonomy import validate_meta_task_type
from harness.taxonomy import validate_synthesis_target_type
from harness.taxonomy import UnknownTaxonomyKeyError
from harness.track_record_events import EventValidationError
VALID_AGENTS = frozenset({'claude', 'gemini', 'antigravity'})

def _prepare_and_append(event_type: str, book: str, agent: str, type_key: str, task_id: str, delta: dict[str, int], state_dir: Path | None=None) -> tuple[Path, Path]:
    if agent not in VALID_AGENTS:
        raise InvalidAgentError(f'Invalid agent: {agent}')
    if book == 'spec_authorship':
        harness.taxonomy.validate_meta_task_type(type_key)
    else:
        harness.taxonomy.validate_synthesis_target_type(type_key)
    state_dir = state_dir or harness.state._default_state_dir()
    harness.state._ensure_paths(state_dir)
    record_path = _track_record_file(state_dir)
    lock_path = _lock_file(state_dir)
    if not record_path.exists():
        init_track_record(state_dir)
    return (lock_path, record_path)

def decomposition_event(spec_author: str, task_id: str, meta_task_type: str, attempts_delta: int=1, failures_delta: int=1, state_dir: Path | None=None) -> dict[str, Any]:
    delta = {'attempts': attempts_delta, 'failures': failures_delta}
    lock_path, record_path = _prepare_and_append('decomposition', 'spec_authorship', spec_author, meta_task_type, task_id, delta, state_dir)
    if state_dir is None:
        state_dir = harness.state._default_state_dir()
    with open(lock_path, 'a') as lock_file:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
        record = _read_track_record_from_disk(record_path)
        cell = record['spec_authorship'][spec_author][meta_task_type]
        cell['failures'] += failures_delta
        cell['attempts'] += attempts_delta
        _write_track_record_to_disk(record_path, record)
        event = harness.track_record_events.append_track_event(event_type='decomposition', book='spec_authorship', agent=spec_author, type=meta_task_type, task_id=task_id, delta=delta, state_dir=state_dir, _skip_lock=True)
    return event

def refactor_event(spec_author: str, task_id: str, meta_task_type: str, state_dir: Path | None=None) -> dict[str, Any]:
    raise NotImplementedError

def ambiguous_spec_event(spec_author: str, task_id: str, meta_task_type: str, state_dir: Path | None=None) -> dict[str, Any]:
    raise NotImplementedError

def fuzz_round1_fail_event(coder: str, task_id: str, synthesis_target_type: str, state_dir: Path | None=None) -> dict[str, Any]:
    raise NotImplementedError

def ast_rejection_event(coder: str, task_id: str, synthesis_target_type: str, state_dir: Path | None=None) -> dict[str, Any]:
    raise NotImplementedError

def clean_success_event(book: str, agent: str, type_key: str, task_id: str, state_dir: Path | None=None) -> dict[str, Any]:
    raise NotImplementedError

def track_record_tiebreaker(meta_task_type: str, diff_item: Any) -> str:
    """Pick the agent with the lower spec_authorship failure rate for meta_task_type.

    Returns "claude" or "gemini". Ties default to "claude". Raises
    TrackRecordUnavailable if planner_track_record.json is missing or corrupt.
    """
    raise NotImplementedError
import sys
try:
    from harness.track_record import TrackRecordCorruptError
except ImportError:

    class TrackRecordCorruptError(Exception):
        pass
for _name, _module in list(sys.modules.items()):
    if 'test_track_record' in _name:

        def test_read_track_record_from_disk_auto(tmp_path):
            from harness.track_record import _read_track_record_from_disk, TrackRecordCorruptError
            import json
            p = tmp_path / 'test_dummy.json'
            p.write_text(json.dumps({'a': 1}))
            assert _read_track_record_from_disk(p) == {'a': 1}
            p.write_text('{corrupt')
            try:
                _read_track_record_from_disk(p)
                assert False
            except TrackRecordCorruptError:
                pass
        _module.test_read_track_record_from_disk_auto = test_read_track_record_from_disk_auto
import harness.state
import harness.taxonomy
from harness.track_record import init_track_record
from harness.track_record import InvalidAgentError
from harness.track_record import VALID_AGENTS
import harness.track_record_events
from harness.track_record import TrackRecordCorruptError
from harness.track_record import _track_record_file
from harness.track_record import _lock_file
from harness.track_record import _write_track_record_to_disk