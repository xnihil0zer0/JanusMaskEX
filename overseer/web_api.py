"""JSON handler layer for the Overseer chat panel.

``OverseerWebApi`` wraps an injected :class:`overseer.session_store.SessionStore`
and exposes the chat / mode / model endpoints used by the web UI.  Every public
method returns a plain JSON-serializable structure (``json.dumps`` succeeds) and
delegates *all* persistent state to the injected store, so re-reading through the
store always reflects any mutation made here.

No agent, driver, subprocess, model call, or network I/O happens in any path
exercised by the handlers below -- ``chat_send`` / ``chat_resend`` merely mint a
job id and record the request.  This module imports only the stdlib plus the
three sibling overseer modules.
"""
from __future__ import annotations
from typing import Any, Dict, List, Optional

class OverseerWebApi:
    """In-process JSON handler over an injected session store.

    The store is the single source of truth; no parallel in-memory conversation
    state is kept.  Identifiers are minted deterministically from a per-instance
    integer counter (no uuid/random/secrets/clock) so output is reproducible.
    """
    DEFAULT_MODE = 'observe'

    def __init__(self, session_store: Any) -> None:
        self._store = session_store
        self._seq = 0

    def chat_send(self, body: Dict[str, Any]) -> Dict[str, Any]:
            """Append a user turn, creating the conversation if needed.

            When ``body`` carries no ``conversation_id`` a fresh conversation is
            created and booted in the operator-selected ``body['mode']`` provided it
            names a self-selectable mode (a default-available Tier-R/W mode);
            otherwise -- absent / None / empty / unknown / unlock-only Tier-S -- it
            boots in ``observe`` (``DEFAULT_MODE``).  The agent backend is resolved
            from ``body['backend']`` against the allow-set ``{'claude',
            'claude-tmux'}`` (any other / absent / None value falls back to
            ``'claude'``) so the requested backend is byte-for-byte the literal
            ``turn_runner.run_chat_turn`` dispatches on.  An existing conversation
            (``conversation_id`` present) reuses the stored mode/backend and ignores
            ``body['mode']`` / ``body['backend']`` entirely (mode changes flow
            through ``mode_set``).  Returns ``{"conversation_id", "job_id"}`` with a
            non-empty ``job_id``.  No driver/agent is spawned.
            """
            def _resolve_boot_mode(requested: Any) -> str:
                # A mode is self-selectable iff it exists AND does not require an
                # unlock; unknown names raise KeyError which falls back to observe.
                if not requested:
                    return self.DEFAULT_MODE
                from overseer.modes import get_mode, requires_unlock
                try:
                    get_mode(requested)
                    if requires_unlock(requested):
                        return self.DEFAULT_MODE
                    return requested
                except KeyError:
                    return self.DEFAULT_MODE

            cid = body.get('conversation_id')
            if not cid:
                self._seq += 1
                cid = 'conv-%d' % self._seq
                boot_mode = _resolve_boot_mode(body.get('mode'))
                agent_backend = body.get('backend') if body.get('backend') in {'claude', 'claude-tmux'} else 'claude'
                self._store.create(cid, current_mode=boot_mode, model='opus', agent_backend=agent_backend)
            self._store.append_turn(cid, {'role': 'user', 'content': body['text']})
            rec = self._store.get(cid)
            job_id = 'job-%s-%d' % (cid, len(self._transcript(rec)))
            return {'conversation_id': cid, 'job_id': job_id}

    def chat_history(self, cid: str) -> Dict[str, Any]:
        """Return ``{"turns": [...]}`` for *cid* (KeyError if unknown)."""
        rec = self._store.get(cid)
        return {'turns': self._transcript(rec)}

    def chat_list(self) -> Dict[str, Any]:
        """Return ``{"conversations": [...]}`` of browsable session summaries.

        Delegates to the store's ``list_conversations`` so the web UI can browse
        past sessions; an empty store yields ``{"conversations": []}``.  Pure
        read path -- no driver/agent/subprocess.
        """
        return {'conversations': self._store.list_conversations()}

    def chat_load(self, cid: str) -> Dict[str, Any]:
        """Return the full conversation for *cid* so it can be reloaded.

        Mirrors :meth:`chat_history` in fetching ``rec = self._store.get(cid)``
        and projecting via :meth:`_transcript`; an unknown *cid* lets the store's
        ``KeyError`` propagate uncaught.
        """
        rec = self._store.get(cid)
        return {'conversation_id': cid, 'current_mode': rec['current_mode'], 'turns': self._transcript(rec)}

    def chat_resend(self, cid: str, *, rewind_to_index: Optional[int]=None) -> Dict[str, Any]:
        """Replay the transcript (``rewind_to_index is None``) or branch from a turn.

        Validates that *cid* exists, mints a fresh job id, and echoes back the
        rewind index so the caller can distinguish a whole-transcript resend
        from a branch.  No driver/agent is spawned.
        """
        self._store.get(cid)
        self._seq += 1
        return {'conversation_id': cid, 'job_id': 'job-%s-r%d' % (cid, self._seq), 'rewind_to_index': rewind_to_index}

    def mode_get(self, cid: str) -> Dict[str, Any]:
        """Return ``{"current_mode", "available_modes"}`` for *cid*.

        ``available_modes`` excludes locked Tier-S modes (those that still
        require an unlock for this session) and includes Tier-R modes.
        """
        from overseer.modes import list_available_modes
        rec = self._store.get(cid)
        unlocked = self._unlocked(rec)
        return {'current_mode': rec['current_mode'], 'available_modes': list(list_available_modes(unlocked=unlocked))}

    def mode_set(self, cid: str, mode: str) -> Dict[str, Any]:
        """Switch *cid* to *mode* when permitted.

        A Tier-R (or already-unlocked Tier-S) target persists and returns
        ``{"ok": True, "current_mode": mode}``.  A locked Tier-S target returns
        ``{"ok": False, "current_mode": <unchanged>}`` without persisting.
        """
        from overseer.modes import requires_unlock
        rec = self._store.get(cid)
        unlocked = self._unlocked(rec)
        if requires_unlock(mode) and mode not in unlocked:
            return {'ok': False, 'current_mode': rec['current_mode']}
        self._store.set_mode(cid, mode)
        return {'ok': True, 'current_mode': mode}

    def mode_unlock(self, cid: str, mode: str) -> Dict[str, Any]:
        """Record a per-session unlock for *mode* so a later ``mode_set`` works."""
        self._store.unlock_mode(cid, mode)
        rec = self._store.get(cid)
        return {'ok': True, 'unlocked_modes': list(self._unlocked(rec))}

    def model_list(self) -> Dict[str, Any]:
        """Expose the available models without selecting one."""
        from overseer.model_select import AVAILABLE_MODELS
        try:
            claude = list(AVAILABLE_MODELS['claude'])
        except (KeyError, TypeError):
            claude = ['opus', 'sonnet', 'haiku']
        try:
            agy = list(AVAILABLE_MODELS['agy'])
        except (KeyError, TypeError):
            agy = []
        return {'claude': claude, 'agy': agy}

    @staticmethod
    def _transcript(rec: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Return the list of turns recorded for a conversation record."""
        turns = rec.get('transcript')
        if turns is None:
            turns = rec.get('turns', [])
        return list(turns)

    @staticmethod
    def _unlocked(rec: Dict[str, Any]) -> 'frozenset[str]':
        """Return the per-session set of unlocked modes for a record."""
        return frozenset(rec.get('unlocked_modes', []) or [])