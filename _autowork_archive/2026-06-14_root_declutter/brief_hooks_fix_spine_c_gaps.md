---
epic: false
working_dir: "/home/xnihil0zer0/NobleGreedv2"
interfaces: "session close gate (*->done), mcp __main__ db-path resolution, submit_artifacts duplicate-rejection"
---

# Title

Fix 3 confirmed functional gaps in the NobleGreedv2 Agentic Spine session layer (Epic C gap sweep)

Three surgical, oracle-pinned fixes to already-built Epic B/C modules. The RED oracles are ALREADY
COMMITTED to NobleGreedv2 master (`fa82160`): `tests/ngv2/test_session_gate_done_wired.py`,
`tests/ngv2/test_session_mcp_main_wired.py`, `tests/ngv2/test_session_api_dup_wired.py`. Each fix
must turn its oracle GREEN while keeping the three existing C oracles
(`tests/ngv2/test_session_gate_wired.py`, `test_session_mcp_wired.py`, `test_session_api_wired.py`)
and the full 102-test `tests/ngv2` suite green. This is a single non-epic plan with EXACTLY THREE
leaf tasks — the planner emits them directly; do NOT decompose into child briefs.

# Scope

- GAP 1 `ngv2/session_gate.py`: `state_machine.ALLOWED_TRANSITIONS` permits `*->done` (every phase
  lists 'done'), but `gate_transition` has no rule for `to_phase=='done'` → returns ok=False
  ("Unknown transition") → `session_api.transition(sid,'done')` 422s and sessions can never close.
  FIX: `gate_transition` returns `GateResult(ok=True, error=None)` for ANY transition whose
  `to_phase == 'done'` (closing/aborting needs no artifact gate). The early-return MUST be the FIRST
  statement of the function body — BEFORE the existing `if not rows:` guard (the oracle asserts
  `gate_transition({}, 'detonate', 'done').ok is True`). The four existing gate rules (hunt→triage,
  triage→poc, poc→detonate, detonate→report) and the unknown-transition diagnostic for non-done
  targets are byte-for-byte unchanged.
- GAP 2 `ngv2/session_mcp.py`: the `if __name__ == '__main__':` block does `SessionApi(SessionDB())`
  but `SessionDB.__init__(db_path)` REQUIRES db_path (no default) → TypeError at launch; the stdio
  server can never start. FIX: add a NEW module-level helper `resolve_db_path(argv=None, env=None) -> str`
  and make the `__main__` block use `SessionDB(resolve_db_path())`. Pinned helper contract:
  `argv` is a sys.argv-shaped sequence (argv[0]=prog; `argv is None` → fall back to `sys.argv`);
  `env` is a mapping (`env is None` → fall back to `os.environ`); precedence `argv[1]` (when present)
  > `env['NGV2_SESSION_DB']` (when set) > the default `'ngv2_session.db'`. Import purity is
  load-bearing and MUST be preserved: no `mcp` import at module top; FastMCP + `.run()` stay ONLY
  inside `__main__`; `build_tools(api)` keeps its exact existing surface.
- GAP 3 `ngv2/session_api.py`: `_persist_artifact`'s retry loop only catches `TypeError`, so
  re-submitting an artifact whose id already exists raises an uncaught `sqlite3.IntegrityError` out
  of `submit_artifacts` — violating the "return a rejected entry, never raise" handler contract.
  FIX: in `SessionApi.submit_artifacts`, wrap the `self._persist_artifact(kind, raw, obj)` call in
  `try/except (sqlite3.IntegrityError, ValueError) as exc:` → on catch, append
  `{'index': index, 'error': str(exc) or 'persist failed'}` to `rejected`, `continue` (do NOT
  increment `accepted`), keep processing the remaining items. NOTE: `session_api.py` does NOT import
  sqlite3 at module top and a symbol patch cannot add module-level imports — put `import sqlite3` as
  a function-local statement at the top of the patched `submit_artifacts` body. Existing
  accept/reject validation behavior is unchanged.

# Non-Goals

The word integration appears here deliberately. OUT OF BOUNDS: any new module; any transport,
network, subprocess, or server-start code; any schema change to `ngv2/session_db.py`; any edit to
`ngv2/state_machine.py`, `ngv2/contracts.py`, `ngv2/phase_runner.py`; any change to the
`build_tools` surface or the four existing gate rules; any time/random/uuid usage anywhere (all
three modules are deterministic and must stay so); touching the committed oracles.

# Inputs

Already built — consume as-is: `ngv2/state_machine.py::ALLOWED_TRANSITIONS = {'hunt': ('triage',
'done'), 'triage': ('poc', 'done'), 'poc': ('detonate', 'done'), 'detonate': ('report', 'done'),
'report': ('done',), 'done': ()}`; `ngv2/session_db.py::SessionDB(db_path)` (db_path REQUIRED, no
default; `findings.id` is TEXT PRIMARY KEY — that is what fires the IntegrityError on duplicate
insert); `ngv2/contracts.py::Finding/PoC/LiveTestReport`. The committed RED oracles named above PIN
every contract — build to them exactly. Verbatim current sources of every edited surface are
embedded in `# Required plan shape` below.

# Deliverables

1. `ngv2/session_gate.py` — `gate_transition` gains the `to_phase=='done'` early-return; oracle
   `tests/ngv2/test_session_gate_done_wired.py` goes GREEN (every phase → done ok with empty rows,
   ok with `rows=={}`, ok even with artifacts that fail other gates; 4 regression checks on the
   existing gate rules stay green). meta_task_type `validation`.
2. `ngv2/session_mcp.py` — NEW `resolve_db_path(argv=None, env=None)` + `__main__` uses
   `SessionDB(resolve_db_path())`; oracle `tests/ngv2/test_session_mcp_main_wired.py` goes GREEN
   (argv[1] wins, env fallback, non-empty default, argv-beats-env, env=None reads os.environ,
   resolved path constructs a real SessionDB, source contains `SessionDB(resolve_db_path(` and no
   bare `SessionDB()`, `'mcp' not in sys.modules` after import). meta_task_type `validation`.
3. `ngv2/session_api.py` — `submit_artifacts` converts `sqlite3.IntegrityError`/`ValueError` persist
   failures into rejected entries; oracle `tests/ngv2/test_session_api_dup_wired.py` goes GREEN
   (resubmit-same-id returns rejected not raise; dup-within-batch rejected at its index; dup does
   not block a later valid item; original row survives; ValueError from the store also becomes a
   rejected entry; contract-invalid rejection regression). meta_task_type `validation`.

# Required plan shape

EXACTLY THREE leaf tasks, task_ids pinned VERBATIM, each meta_task_type `validation`, each
partial_edit touching ONE file, no new modules. Plan-shape invariants for EVERY leaf: at least two
edge_cases in its test_spec, EACH mirrored into regression_tests (the plan validator hard-drops any
leaf without this); the literal word `integration` in the leaf's non_goals; verification_command
pointing at the committed oracle under `tests/ngv2/...` (NOT `ngv2/tests/`). The plan validator
resolves files_touched against the JanusMaskJR repo root where these NGv2 paths are absent, so each
leaf reads as module-creating — that is expected (the runtime wire-up gate no-ops for external
targets). NO time/random anywhere.

- LEAF 1 task_id `cfix-gate-done` — file `ngv2/session_gate.py`.
  verification_command: `python -m pytest tests/ngv2/test_session_gate_done_wired.py -q`
  edge_cases (mirror into regression_tests): (a) `rows == {}` with to_phase='done' → ok=True (the
  done early-return precedes the `if not rows` guard); (b) artifact rows that FAIL another gate
  (duplicate finding ids, which fail triage→poc) are still ok for triage→done.
  PATCH FORMAT (MANDATORY): emit a single `__JANUSMASK_PATCHES__` with EXACTLY ONE entry, kind
  `'symbol'`, name `'gate_transition'`. In `code`, reproduce the function below BYTE-FOR-BYTE and
  add ONLY the two-line early-return as the FIRST statements of the body (before the docstring
  stays the docstring — insert the early-return immediately AFTER the docstring and BEFORE
  `if not rows:`). EXACT CURRENT SOURCE of `gate_transition` (module-level function,
  ngv2/session_gate.py):

```python
def gate_transition(rows: Dict[str, List[dict]], from_phase: str, to_phase: str) -> GateResult:
    """Validate a pipeline phase transition over a pure artifact set.

    Parameters
    ----------
    rows:
        Dict keyed by artifact type (``'findings'``, ``'pocs'``, ``'reports'``);
        each value is a list of artifact dicts.  Missing keys are treated as
        empty lists.
    from_phase, to_phase:
        The source and destination pipeline phases.

    Returns
    -------
    GateResult
        ``ok=True`` (with ``error=None``) when the transition is permitted,
        otherwise ``ok=False`` with a specific diagnostic in ``error``.
    """
    if not rows:
        return GateResult(ok=False, error='No artifacts found')
    handler = _TRANSITIONS.get((from_phase, to_phase))
    if handler is None:
        return GateResult(ok=False, error='Unknown transition: ' + str(from_phase) + ' -> ' + str(to_phase))
    return handler(rows)
```

  The ONLY change: insert after the closing docstring quotes —

```python
    if to_phase == 'done':
        return GateResult(ok=True, error=None)
```

- LEAF 2 task_id `cfix-mcp-main` — file `ngv2/session_mcp.py`.
  verification_command: `python -m pytest tests/ngv2/test_session_mcp_main_wired.py -q`
  edge_cases (mirror into regression_tests): (a) argv[1] BEATS the env var when both are supplied;
  (b) `env=None` falls back to `os.environ` (`NGV2_SESSION_DB`).
  PATCH FORMAT (MANDATORY — WHOLE-FILE): the gap lives in module-level `__main__` code, which is NOT
  a named symbol and cannot be symbol-patched, plus a NEW top-level function. Emit the COMPLETE
  replacement file for `ngv2/session_mcp.py` (whole-file emission, NOT a symbol patch): reproduce
  the module docstring, the `from __future__`/typing/SessionApi imports, and `build_tools`
  BYTE-FOR-BYTE exactly as below (the drift guard permits ≤1 changed existing symbol; verbatim
  reproduction keeps it at 0), ADD the new top-level `resolve_db_path(argv=None, env=None)` (it may
  import `os`/`sys` — add them to the module-top stdlib imports or import locally; stdlib only,
  still zero side effects, NO `mcp` at top), and change ONLY the `__main__` block so it constructs
  `SessionDB(resolve_db_path())`. The bare `SessionDB()` text must NOT appear anywhere (the oracle
  rejects it). FastMCP import + `server.run()` stay ONLY inside `__main__`. Do NOT alter the module
  docstring (the existing C2 oracle's guard check matches text inside it). NO time/random.
  Pinned helper behavior: `argv[1]` if `argv` (after the None→`sys.argv` fallback) has ≥2 elements;
  else `env['NGV2_SESSION_DB']` if set (after the None→`os.environ` fallback); else
  `'ngv2_session.db'`. EXACT CURRENT FULL SOURCE of `ngv2/session_mcp.py` (40 lines — reproduce
  every byte you are not explicitly changing):

```python
"""Thin stdio MCP transport shim for session phase control.

This module is a pure transport over :class:`ngv2.session_api.SessionApi`.
It registers exactly three tools -- ``create_session``, ``submit_artifacts``
and ``transition`` -- each delegating straight through to the matching
``SessionApi`` method and returning that method's dict result unchanged.

Import purity is load-bearing here: at module top-level we import ONLY the
standard library and ``SessionApi``. The MCP SDK (``FastMCP``) is imported
lazily inside the ``if __name__ == "__main__":`` guard, so importing this
module never pulls ``mcp`` into ``sys.modules`` and has zero side effects --
no FastMCP construction, no bound socket, no server ``.run()``.
"""
from __future__ import annotations
from typing import Callable, Dict
from ngv2.session_api import SessionApi

def build_tools(api: SessionApi) -> Dict[str, Callable]:
    """Build the session-control tool table over ``api``.

    Returns a mapping with EXACTLY the keys
    ``{'create_session', 'submit_artifacts', 'transition'}``. Each value is a
    thin closure that forwards its arguments to the matching ``SessionApi``
    method and returns that method's identical dict result -- no wrapping,
    no mutation.
    """
    return {'create_session': lambda session_id, target_spec: api.create_session(session_id, target_spec), 'submit_artifacts': lambda session_id, phase, artifacts: api.submit_artifacts(session_id, phase, artifacts), 'transition': lambda session_id, to_phase: api.transition(session_id, to_phase)}
if __name__ == '__main__':
    try:
        from mcp.server.fastmcp import FastMCP
    except ImportError:
        FastMCP = None
    if FastMCP is None:
        raise SystemExit("The 'mcp' SDK is required to run the session MCP server. Install it to launch the stdio transport.")
    from ngv2.session_db import SessionDB
    server = FastMCP('session_mcp')
    api = SessionApi(SessionDB())
    for tool_name, handler in build_tools(api).items():
        server.tool(name=tool_name)(handler)
    server.run()
```

- LEAF 3 task_id `cfix-api-dup` — file `ngv2/session_api.py`.
  verification_command: `python -m pytest tests/ngv2/test_session_api_dup_wired.py -q`
  edge_cases (mirror into regression_tests): (a) the SAME finding id duplicated WITHIN one batch →
  first accepted, second rejected at its input index, no exception; (b) a `ValueError` raised by the
  store's insert helper is also converted to a rejected entry (never raised).
  PATCH FORMAT (MANDATORY): emit a single `__JANUSMASK_PATCHES__` with EXACTLY ONE entry, kind
  `'symbol'`, name `'SessionApi.submit_artifacts'` (an INDENTED METHOD of class `SessionApi` — the
  harness dedent path handles indented-method symbol patches; reproduce the method at its original
  one-level indentation). Reproduce the method below BYTE-FOR-BYTE except: (i) add `import sqlite3`
  as the first statement after the docstring (function-local — the module top has no sqlite3 import
  and a symbol patch must not add module-level imports); (ii) wrap ONLY the
  `self._persist_artifact(kind, raw, obj)` call in the pinned try/except. Do NOT touch
  `_persist_artifact` or any other symbol. EXACT CURRENT SOURCE of `SessionApi.submit_artifacts`
  (ngv2/session_api.py):

```python
    def submit_artifacts(self, session_id: Any, phase: Any, artifacts: Any) -> Dict[str, Any]:
        """Rebuild + validate each artifact BEFORE writing.

        Invalid artifacts are never persisted; valid ones are stored through
        the real ``SessionDB`` insert helpers.  Supports partial accept and
        reports each rejection carrying its input index.
        """
        accepted = 0
        rejected: List[Dict[str, Any]] = []
        items = list(artifacts or [])
        for index, raw in enumerate(items):
            ok, error, kind, obj = self._validate_artifact(raw, phase)
            if not ok:
                rejected.append({'index': index, 'error': error})
                continue
            self._persist_artifact(kind, raw, obj)
            accepted += 1
        self._commit()
        return {'ok': True, 'accepted': accepted, 'rejected': rejected}
```

  The pinned replacement for the two persist lines inside the loop:

```python
            try:
                self._persist_artifact(kind, raw, obj)
            except (sqlite3.IntegrityError, ValueError) as exc:
                rejected.append({'index': index, 'error': str(exc) or 'persist failed'})
                continue
            accepted += 1
```

After each leaf, the committed oracle for that leaf passes AND the prior oracles
(`tests/ngv2/test_session_gate_wired.py`, `test_session_mcp_wired.py`, `test_session_api_wired.py`)
plus the full `tests/ngv2` suite (102 tests) stay green:
`python -m pytest tests/ngv2 -q`.
