"""Composition root for the overseer chat panel.

``OverseerService`` is the single entry point the WebUI control handlers call. It
wires together the persistent :class:`overseer.session_store.SessionStore`, the
record-only :class:`overseer.web_api.OverseerWebApi`, and the live
``overseer.turn_runner`` bridge, gates every mutation on the default-OFF
``overseer.enabled`` config flag, and adapts the ``body``-shaped requests the
handlers pass into the typed calls the web API/runner expect.

Every method returns an ``(http_status, json_dict)`` tuple. The agent is only
ever spawned (via the turn runner) on the chat-send / resend paths AND only when
``overseer.enabled`` is true.

Stdlib + sibling overseer modules + the harness config loader.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Dict, Optional, Tuple

from overseer.session_store import SessionStore
from overseer.web_api import OverseerWebApi
from overseer import turn_runner

JsonResult = Tuple[int, Dict[str, Any]]


def _load_config() -> Dict[str, Any]:
    from harness.orchestrator import load_config
    return load_config()


class OverseerService:
    """Stateful-per-request facade over the overseer chat subsystem."""

    def __init__(self, state_dir: Any, config: Optional[Dict[str, Any]] = None,
                 *, run_turn_fn: Optional[Callable[..., Dict[str, Any]]] = None) -> None:
        self.state_dir = Path(state_dir)
        self.repo_root = self.state_dir.parent
        self.logs_dir = self.repo_root / 'logs'
        self.config = config if config is not None else _load_config()
        ov = (self.config or {}).get('overseer') or {}
        self.enabled = bool(ov.get('enabled', False))
        store_rel = ov.get('store_path') or 'state/overseer/sessions.json'
        self.store_path = (self.repo_root / store_rel).resolve()
        self._store = SessionStore(self.store_path)
        self._api = OverseerWebApi(self._store)
        self._run_turn_fn = run_turn_fn or turn_runner.run_chat_turn

    # -- gating -----------------------------------------------------------
    def _disabled(self) -> JsonResult:
        return (403, {'error': 'overseer disabled',
                      'detail': 'set overseer.enabled: true in harness/config.yaml and restart the server'})

    # -- chat -------------------------------------------------------------
    def chat_send(self, body: Dict[str, Any]) -> JsonResult:
        """Record the user turn, then RUN the assistant turn and persist it."""
        if not self.enabled:
            return self._disabled()
        text = (body or {}).get('text')
        if not text or not str(text).strip():
            return (400, {'error': 'empty message', 'detail': 'body.text is required'})
        recorded = self._api.chat_send(body)          # appends user turn, mints ids
        cid = recorded['conversation_id']
        result = self._run_turn_fn(
            self._store, cid, str(text), config=self.config,
            repo_root=self.repo_root, state_dir=self.state_dir, logs_dir=self.logs_dir,
        )
        status = 200 if result.get('ok', True) else 502
        return (status, {**recorded, **result})

    def chat_resend(self, body: Dict[str, Any]) -> JsonResult:
        """Re-run the last user turn, optionally forking at ``rewind_to_index``."""
        if not self.enabled:
            return self._disabled()
        cid = (body or {}).get('conversation_id')
        if not cid:
            return (400, {'error': 'missing conversation_id'})
        try:
            rec = self._store.get(cid)
        except KeyError:
            return (404, {'error': 'unknown conversation', 'conversation_id': cid})
        rewind = (body or {}).get('rewind_to_index')
        meta = self._api.chat_resend(cid, rewind_to_index=rewind)   # validate + mint job id
        last_user = next((t.get('content', '') for t in reversed(rec.get('transcript') or [])
                          if t.get('role') == 'user'), None)
        if not last_user:
            return (200, {**meta, 'ok': True, 'text': '', 'detail': 'nothing to resend'})
        result = self._run_turn_fn(
            self._store, cid, str(last_user), config=self.config,
            repo_root=self.repo_root, state_dir=self.state_dir, logs_dir=self.logs_dir,
            rewind_to_index=rewind,
        )
        status = 200 if result.get('ok', True) else 502
        return (status, {**meta, **result})

    # -- mode -------------------------------------------------------------
    def mode_set(self, body: Dict[str, Any]) -> JsonResult:
        """Switch the conversation mode (Tier-S targets need a prior unlock)."""
        if not self.enabled:
            return self._disabled()
        cid = (body or {}).get('conversation_id')
        mode = (body or {}).get('mode')
        if not cid or not mode:
            return (400, {'error': 'conversation_id and mode are required'})
        try:
            result = self._api.mode_set(cid, mode)
        except KeyError:
            return (404, {'error': 'unknown conversation', 'conversation_id': cid})
        status = 200 if result.get('ok') else 409
        return (status, result)
