---
working_dir: "/home/xnihil0zer0/AI-Data/JanusMaskEX"
required_task_ids:
  - agy-communicate-bounded-capture-oracle
  - agy-communicate-bounded-capture-impl
interfaces: "harness/orchestrator.py::spawn_agent"
---

# Title

agy_communicate_bounded_capture — bound the agy/codex `spawn_agent` stdout capture
so a slow/unproductive agy agent cannot monopolize the FULL synthesis budget (1800s),
AND so an agent that has EXITED but whose stdout pipe is still held open by a grandchild
returns promptly instead of waiting the full timeout.

# Scope

In `harness/orchestrator.py`, `spawn_agent(agent, prompt, config, round_number=1)`
(def at line 369) has an `_is_agy` branch (lines ~438-481), taken whenever the agent's
configured command basename is `agy` or `codex`. In the live factory that covers the
`gemini`, `claude_fallback`, `antigravity` and `codex` agents — ALL map to the `agy`
binary in `harness/config.yaml` — so this branch fires on EVERY planner blind-draft and
reconciliation spawn (not a rare path). The relevant lines:

```
proc = subprocess.Popen(agy_cmd, stdin=PIPE, stdout=PIPE, stderr=PIPE, text=True,
                        env=env, start_new_session=True, cwd=...)          # ~line 449
proc._work_dir = Path(env['JANUSMASK_WORK_DIR'])                           # ~line 450
_timeout = config.get('synthesis', {}).get('timeout_seconds', 1200)        # ~line 451
try:
    out, _err = proc.communicate(input=stdin_prompt, timeout=_timeout)     # ~line 453  <-- the cap
except subprocess.TimeoutExpired:
    ... os.killpg(...); proc.kill(); proc.wait(timeout=5); return proc      # ~line 454-467
block = _extract_python_block(out)                                         # ~line 468
... write outbox/submission.py ...                                         # ~line 469-477
return proc                                                                # ~line 478
finally:
    if _dbus_stack is not None: _dbus_stack.close()                        # ~line 479-481
```

`_timeout` here resolves to `synthesis.timeout_seconds` = **1800** in prod
(`harness/config.yaml:138`; the planner stages also inject 1800 because no
`planning_timeout_seconds` is configured). The literal `1200` default at line ~451 is
shadowed. So EVERY agy planner spawn is given a blind 1800-second `communicate()` budget
with NO no-progress / liveness bound.

OBSERVED FAILURE (evidence-verified): planning the 29KB brief
`brief_hooks_p11_build_evidence_perphase.md` produced
`planner_validation_rejected ... wall=1625.2 reason=rc=2`. Hard evidence on what
actually happened:
- The daemon emits `wall=...` + `reason=rc=2` at `harness/autowork_daemon.py:1857` ONLY
  for `rc not in (0, 124)` — i.e. the planner subprocess RAN TO COMPLETION and exited
  rc=2; it was NOT killed by the daemon's plan_timeout (which is rc=124, a different
  branch at line ~1821). So the 1625s is the planner's own runtime, dominated by a
  blocking agy spawn.
- `wall=1625.2 < _timeout=1800` ⇒ the agy `proc.communicate(timeout=1800)` RETURNED ON
  ITS OWN (the pipe reached EOF at ~1625s) — it did NOT raise `TimeoutExpired`. The agy
  process genuinely ran ~1625 seconds and then exited; it was not a zombie whose pipe was
  stuck open past exit.
- The agy agent ran that long and produced an EMPTY/invalid draft (the per-spawn outbox
  dirs `…_agentwork/{gemini,claude_fallback}/…-r1-notask-*/outbox/` for the failing spawns
  are empty — no `submission.py`, no `plan_draft.json` — while OTHER spawns of the SAME
  prompt in the SAME run drafted fine). The agent death is TRANSIENT (a slow/idle agy run),
  not a deterministic prompt/auth/size error: 29KB ≈ 7.3K tokens is trivial; the real
  `claude` CLI and other agy spawns drafted this identical brief.

ROOT CAUSE (the lever this brief fixes): the `_is_agy` capture has NO bound shorter than
the full synthesis budget, so a single slow/unproductive agy agent monopolizes up to
1800s of planner wall before the planner can fail and move on. This brief adds a
CONFIGURABLE, shorter agy-capture cap so a slow agy planner spawn is bounded to a sane
value (e.g. 300s) instead of 1800s, and the planner fails fast / falls back to the
productive agent in seconds-to-minutes instead of ~1625s.

SECOND, LATENT HAZARD (closed by the same patch, proven by repro): if an agy/codex agent
EXITS but a grandchild it forked inside the bwrap jail (e.g. an `xdg-dbus-proxy` it
spawns) inherits and keeps the stdout PIPE write-end open, then `proc.communicate()`
would block the FULL `_timeout` because the pipe never reaches EOF — even though
`proc.poll()` already returned a non-None exit code. This is a DISTINCT failure mode from
the observed hang (the observed run's communicate DID return at 1625 < 1800, so this did
NOT fire that time), but it is a real latent wedge. PROVEN ANALYTICALLY in the standalone
repro `_autowork_scratch/pipe_eof_leak_repro.py`: a child that prints one stdout line,
forks a detached grandchild inheriting fd 1, then exits immediately, makes
`proc.communicate(timeout=T)` block ~T (8.01s for T=8); the proposed poll-for-exit +
bounded-drain + killpg-the-group returns in ~0.5-1.0s AND captures the same bytes (15x+).

THE FIX (both levers, in the same ~5-line region, lines ~451-467 only): (1) read a
CONFIGURABLE agy-capture timeout that defaults to a value well below the synthesis budget
(closes the monopolization), and (2) capture stdout/stderr via reader threads + wait for
the AGENT PROCESS to exit, then drain with a SHORT bounded grace and `os.killpg` the
agent's process group to force EOF / reap any lingering grandchild (closes the latent
pipe-EOF wedge AND fast-fails when the agent has exited). The existing
`TimeoutExpired -> killpg -> kill -> wait(5) -> return proc` semantics, the captured
`out`/`_err` strings, the downstream `_extract_python_block(out)` +
`outbox/submission.py` write, the `finally: _dbus_stack.close()`, and the `return proc`
shape are ALL preserved byte-for-byte.

The fix edits ONLY `harness/orchestrator.py`, ONLY inside the `_is_agy` branch of
`spawn_agent`. `harness/orchestrator.py` is in `_NEVER_AUTO_APPROVE`, so the impl commit
needs a pre-staged operator decision file (see Implementation notes).

# Non-Goals

- This is NOT an integration of any new IPC, isolation, dbus, or scheduler mechanism, and
  NOT a rework of `harness/dbus_proxy.py`, the planner stages, or the agy outbox-collection
  path. The word `integration` is explicitly out of scope.
- Do NOT attempt to FIX the transient agy emptiness/flakiness itself (retry-on-empty-draft,
  agy prompt changes, the `submission.py` vs `plan_draft.json` collector mismatch). Those
  are separate, orthogonal concerns explicitly OUT of scope here. This brief ONLY bounds the
  capture so a slow/empty agy spawn fails FAST instead of after ~1625s.
- Do NOT kill a STILL-RUNNING agy process before its (new, configurable) cap elapses — the
  cap is a hard upper bound, exactly like the existing `_timeout`; the fast path fires only
  when the process has ALREADY EXITED (`proc.poll() is not None`). Do not add a
  no-output-progress heuristic that could SIGKILL a legitimately-working agent mid-draft.
- Do NOT change the `synthesis.timeout_seconds` config key, the synthesis worker budget, or
  the non-agy spawn path (the real `claude` agent at line ~482: `Popen(...)` +
  `start_stream_threads` + outbox `poll_for_submission`) — that path never calls
  `communicate()` and is unaffected.
- Do NOT change the `outbox/submission.py` extraction/write, the `_no_write_tail` suffix,
  the `-p` strip, the `proc._work_dir` stamp, the `finally: _dbus_stack.close()`, or the
  public signature / return type of `spawn_agent` (still returns the `Popen`).
- Do NOT add a new module-level import. Any `threading` needed must be a LAZY import inside
  the `_is_agy` branch.

# Inputs

READ before authoring/implementing:

- `harness/orchestrator.py` lines 369-492 — the whole `spawn_agent`. The `_is_agy` branch
  is ~438-481; the blocking capture is ~453; the `except subprocess.TimeoutExpired:`
  handler is ~454-467; the post-success `_extract_python_block(out)` + outbox write is
  ~468-477; the `finally` closing `_dbus_stack` is ~479-481. `os`, `signal`, `subprocess`,
  `time` are already module-top imports; `threading`/`select` are NOT (use a lazy import).
- `harness/test_author.py:150` — `_extract_python_block(text: str) -> str`. It consumes the
  captured stdout `out`, which is a `str` (Popen is `text=True`). The fix MUST keep `out` a
  decoded `str` so this call is unchanged.
- `harness/config.yaml:127-139` — `synthesis.timeout_seconds: 1800` (the prod value the
  current capture reads), `verification_timeout_seconds: 1200`. There is NO
  agy/planning-specific shorter cap today. The new configurable key the fix reads (see
  notes) must DEFAULT (when absent — as it is today) to a value well below 1800 so the
  behavior change is automatic without a config edit, AND must still be overridable.
- `harness/autowork_daemon.py:1820-1863` — proves `wall=1625.2 reason=rc=2` is the
  `rc not in (0,124)` branch (planner exited rc=2 on its own), NOT the plan_timeout (rc=124)
  branch. Confirms the agy `communicate()` returned naturally at 1625 < 1800.
- `harness/dbus_proxy.py:49-114` — `proxied_session_bus()` spawns `xdg-dbus-proxy` via a
  bare `subprocess.Popen(argv)` from inside the PLANNER (no stdout kwarg → inherits the
  planner's fd1, `close_fds=True` → inherits no pipes) and is entered at orchestrator.py:420
  — BEFORE the agent's stdout PIPE is created at :449. So that sibling proxy can NOT hold
  the agent's stdout pipe; the only pipe-holder in the latent case is a grandchild forked
  INSIDE the bwrap'd agent (reaped by killing the agent's process group).
- `tests/adversarial/test_agy2a_timeout_reap.py` — the EXISTING behavioral oracle for the
  `_is_agy` timeout branch. It injects a `FakePopen` via
  `monkeypatch.setattr(orch.subprocess, "Popen", MockPopen)`, monkeypatches
  `orch.os.getpgid`/`orch.os.killpg`, stubs `orch.start_stream_threads`, and uses
  `config = {"state_dir": ..., "agents": {"gemini": {"command": "agy", "args": ["-p","--sandbox"]}}}`.
  Use THIS exact deterministic fixture pattern for the new oracle (no real subprocess). This
  file MUST stay green after the fix (regression lock).
- `_autowork_scratch/pipe_eof_leak_repro.py` — the standalone analytic repro for the latent
  pipe-EOF case. Read it for the exact reader-thread / poll-for-exit / bounded-drain /
  killpg mechanics; do NOT ship it.

# Deliverables

1. `tests/adversarial/test_agy_communicate_bounded_capture.py` — the RED-first behavioral
   oracle (Task 1).
2. A `harness/orchestrator.py` patch (Task 2, `__JANUSMASK_PATCHES__`, ONE `kind:symbol`
   patch for `spawn_agent`) implementing both levers in the `_is_agy` capture region.

# Required plan shape

Emit EXACTLY TWO tasks (pin BOTH via `required_task_ids`:
`agy-communicate-bounded-capture-oracle`, `agy-communicate-bounded-capture-impl`) in
dependency order — oracle FIRST, impl DEPENDS ON it. PRIORITY on BOTH tasks MUST be
canonical lowercase `critical` (NEVER P0/P1/ints/Capitalized).

**TASK 1 — oracle (RED first)**
- `task_id` EXACTLY `agy-communicate-bounded-capture-oracle`.
- `priority: critical`
- `dependencies: []`
- `meta_task_type: test_authoring`
- `mutation_target: harness.orchestrator` (REQUIRED — BARE DOTTED MODULE, no slashes, no
  `.py`; maps to `harness/orchestrator.py`, which EXISTS — satisfies the fix-forward
  red-pair predicate in `harness/redpair_acceptance.py::is_fix_forward_redpair`).
- `spec_author: null`
- `files_touched: ["tests/adversarial/test_agy_communicate_bounded_capture.py"]`
- Submit the test source DIRECTLY as ordinary Python (NO `__JANUSMASK_PATCHES__` /
  `__JANUSMASK_MANIFEST__` marker).
- `verification_command: python -m pytest tests/adversarial/test_agy_communicate_bounded_capture.py tests/adversarial/test_agy2a_timeout_reap.py -q`
  (emit EXACTLY — it CONTAINS the new oracle path, required by the red-pair predicate and by
  `plan_normalizer._drop_redundant_precommitted_oracles`, AND runs the AGY2A regression lock).
- The oracle MUST drive the REAL `harness.orchestrator.spawn_agent(...)` (NOT a mock of it),
  reusing the `test_agy2a_timeout_reap.py` injection pattern (FakePopen via
  `monkeypatch.setattr(orch.subprocess, "Popen", ...)`, `orch.os.getpgid`/`orch.os.killpg`
  monkeypatched, `orch.start_stream_threads` stubbed, agy `command: "agy"` config), and MUST
  assert (RED today, GREEN after):

  - CAP (bounded, configurable): set `config["synthesis"]["timeout_seconds"] = 1800` AND set
    the NEW agy-capture-cap config key (see impl notes) to a SMALL sentinel (e.g. 7). Inject
    a `FakePopen` whose capture would otherwise consume the full 1800s. Assert the cap the
    fix actually applies to its agent-wait/communicate is the SMALL sentinel (7), NOT 1800 —
    e.g. record the `timeout=` the fix passes to the FakePopen's `wait`/`communicate`, or
    assert via a recorded flag, and assert it equals the sentinel. RED on HEAD: today the
    capture is bounded only by `synthesis.timeout_seconds` (1800). GREeN after: the capture
    is bounded by the new (smaller) configurable cap. Also assert the cap FALLS BACK to a
    sane default well below 1800 when the new key is ABSENT (default-on behavior).

  - FAST-FAIL-ON-EXIT (latent pipe-EOF): inject a `FakePopen` modelling "agent EXITED but
    stdout pipe still held": `poll()` returns 0 (non-None) immediately, and the blocking
    capture (`communicate(timeout=full)`) MODELS the held pipe by NOT returning at the full
    timeout. Wrap the `spawn_agent` call in a `time.monotonic()` measurement and assert it
    returns in well under the cap (e.g. `< 2s`) — i.e. the fix detected `poll() is not None`
    and drained with a short grace rather than waiting the cap. Make this deterministic and
    FAST (no real multi-second sleeps): model the held pipe so the fix's poll/drain path is
    exercised structurally (record whether the fix entered a full-timeout blocking wait, and
    assert it did NOT). RED on HEAD (blocks the cap), GREEN after (returns on exit-detect).

  - OUTPUT-PRESERVED (non-vacuity, MANDATORY): the injected exited `FakePopen` exposes real
    captured stdout containing a fenced ```python block (e.g. `"```python\\nx = 1\\n```"`).
    Assert that after `spawn_agent` returns, the fix STILL extracted that block and wrote it
    to `<work_dir>/outbox/submission.py` (read the file back; assert it contains `x = 1`).
    Proves the bounded/fast path does NOT drop the agent's output — a fix that returns fast
    but loses the captured block MUST FAIL here.

  - GROUP-REAP (lingering grandchild reaped): assert that on the exit-with-still-open-pipe
    path the fix calls `os.killpg(os.getpgid(proc.pid), signal.SIGKILL)` to force EOF / reap
    the lingerer (capture via monkeypatched `orch.os.killpg`/`orch.os.getpgid`, exactly as
    `test_agy2a_timeout_reap.py` does). Proves the grandchild is reaped, not leaked.

  - REGRESSION (legacy timeout path unchanged): include a case (or rely on the bundled
    `test_agy2a_timeout_reap.py` in the vcmd) where the agent process NEVER exits — model a
    `FakePopen.poll()` that always returns `None` and a capture that hits the cap — and
    assert the EXISTING behavior still fires: `os.killpg(...)` + `proc.kill()` +
    `proc.wait(timeout=5)` all called, and `spawn_agent` returns the proc.

  - DETERMINISTIC + FAST: NO real multi-second waits, NO real subprocess. Match
    `test_agy2a_timeout_reap.py`'s style; instrument the FakePopen with recorded flags so
    assertions are structural where possible.

**TASK 2 — implementation**
- `task_id` EXACTLY `agy-communicate-bounded-capture-impl`.
- `priority: critical`
- `dependencies: ["agy-communicate-bounded-capture-oracle"]` (REQUIRED — makes TASK 2 the
  discoverable red-pair sibling via the oracle's reverse-dependency edge).
- `meta_task_type: harness_self_fix` (gates on the REAL bwrap adversarial jail).
- OMIT `mutation_target` entirely. `spec_author: null`.
- `files_touched: ["harness/orchestrator.py"]` (MUST equal the oracle's `mutation_target`
  file — required by the red-pair predicate).
- `non_goals` MUST contain the literal word `integration`.
- `regression_tests` (>= 2): `tests/adversarial/test_agy2a_timeout_reap.py` (legacy timeout
  path) and `tests/adversarial/test_agy_communicate_bounded_capture.py` (the new oracle).
  MAY add `tests/test_orchestrator.py`.
- `verification_command: python -m pytest tests/adversarial/test_agy_communicate_bounded_capture.py tests/adversarial/test_agy2a_timeout_reap.py -q`
  (emit EXACTLY — same string as the oracle; it CONTAINS the oracle test path, required so
  `plan_normalizer._drop_redundant_precommitted_oracles` does NOT drop the oracle and the
  red-pair predicate's `vc` check passes).
- Emit `__JANUSMASK_PATCHES__` (NOT a manifest), exactly ONE `kind:symbol` patch with
  `name: 'spawn_agent'` targeting `harness/orchestrator.py`. The patch rewrites ONLY the
  `_is_agy` capture region (lines ~451-467); everything else in the function is byte-identical.

Both vcmds run with NO `cd` prefix and select real tests. Do NOT use a broad
`pytest tests/adversarial/ -q` vcmd (non-hermetic, flaky-blocks).

REDPAIR RATIONALE (`harness/redpair_acceptance.py::is_fix_forward_redpair`): the oracle is
`test_authoring` (cond 1), `mutation_target: harness.orchestrator` maps to the on-disk
`harness/orchestrator.py` (conds 2+3), non-empty `files_touched` (cond 4). The impl is
discoverable because it DEPENDS ON the oracle, is NOT `test_authoring`, its `files_touched`
includes `harness/orchestrator.py`, AND its vcmd CONTAINS the oracle's test path (cond 5).
All five hold, so the RED oracle lands without needing exit 0 pre-impl.

# Implementation notes / hazards

- THE FIX (inside the `_is_agy` branch of `spawn_agent`, replacing lines ~451-467 only).
  Keep `_timeout = config.get('synthesis', {}).get('timeout_seconds', 1200)` as the OUTER
  hard ceiling, then introduce a SECOND, configurable, smaller agy-capture cap and a
  poll-for-exit + bounded-drain capture:
    1. Read a configurable cap, defaulting WELL below 1800 so the behavior change is
       automatic with no config edit, e.g.:
       `_agy_cap = config.get('synthesis', {}).get('agy_capture_timeout_seconds', 300)`
       then `_cap = min(_timeout, _agy_cap)`. (`_cap` is the effective wait budget; choose
       300 as the default — generous for a real agy draft, ~6x faster fail than 1800.)
    2. LAZY `import threading` inside the branch (no new module-level import).
    3. Start two daemon reader threads calling `proc.stdout.read()` / `proc.stderr.read()`
       into captured buffers (each returns the full decoded `str` at EOF — preserves
       `text=True`, so `out` stays a `str` for `_extract_python_block`). Capture each
       thread's result into a small list (e.g. `out_box = []`, `err_box = []`).
    4. Write `stdin_prompt` to `proc.stdin` and close it (wrap in
       `try/except (BrokenPipeError, OSError): pass`).
    5. `try: proc.wait(timeout=_cap)` — wait for the AGENT PROCESS to exit within the
       (smaller) cap. On `subprocess.TimeoutExpired` (agent itself never exited within the
       cap) → run the EXISTING handler VERBATIM:
       `os.killpg(os.getpgid(proc.pid), signal.SIGKILL)` (suppress
       `(ProcessLookupError, PermissionError, OSError)`), `proc.kill()` (same suppression),
       `proc.wait(timeout=5)` (suppress `(subprocess.TimeoutExpired, ProcessLookupError,
       PermissionError, OSError)`), then `return proc`. This preserves exactly what AGY2A
       asserts — only the budget that triggers it shrank from 1800 to `_cap`.
    6. The agent PROCESS has now exited. `join` both reader threads with a SHORT bounded
       grace (a small constant, e.g. `_GRACE = 5.0`, NOT `_cap`). If a reader is still alive
       after the grace, a grandchild holds the pipe: `os.killpg(os.getpgid(proc.pid),
       signal.SIGKILL)` (same exception suppression) to force EOF and reap the lingerer, then
       `join` the readers again with a short timeout (e.g. 2s). This converts a stuck-pipe
       wedge into ~grace seconds.
    7. `out = out_box[0] if out_box else ''` (decoded `str`); `_err` similarly. Then fall
       through to the UNCHANGED `_extract_python_block(out)` + `outbox/submission.py` write +
       `return proc`.
  - The `finally: if _dbus_stack is not None: _dbus_stack.close()` (lines ~479-481) stays
    EXACTLY as-is and still runs.
  - WHY reader threads (not `select`/raw-fd `os.read`): `proc.stdout` is a `text=True`
    `TextIOWrapper`; `proc.stdout.read()` returns the full DECODED `str` and stops at EOF, so
    `out` keeps the SAME type/contents `communicate()` would have produced. Raw
    `os.read(fileno)` returns BYTES (verified) and would need manual decode — avoid it.
  - The killpg-on-grace-expiry reaps the lingering grandchild because the agent was spawned
    `start_new_session=True` (line ~449) → it leads its own process group → killing
    `os.getpgid(proc.pid)` kills the agent AND every grandchild it forked (closing the
    inherited stdout write-end → readers hit EOF).
  - The cap (`_cap = min(_timeout, agy_capture_timeout_seconds)`) is the lever that fixes the
    OBSERVED 1625s hang; the poll-for-exit + grace-drain is the lever that fixes the LATENT
    pipe-EOF wedge. Both live in the same ~5-line region.
- SYMBOL PATCH SHAPE: ONE `kind:symbol` patch, `name: 'spawn_agent'`, for
  `harness/orchestrator.py`. `spawn_agent` is an EXISTING top-level symbol → a bare
  `kind:symbol` patch applies cleanly (no R-ANCHOR needed). Emit the FULL replacement body of
  `spawn_agent` with ONLY the `_is_agy` capture region changed; keep every other line
  byte-identical (the non-agy path, the tmux delegation, the jail wrapping, the dbus stack,
  the `_no_write_tail`, the `-p` strip, the `proc._work_dir` stamp, the `finally`).
- NESTED-QUOTE HAZARD: emit `"""` (triple double-quote) for any docstring inside the patched
  function, NEVER `'''`. `spawn_agent`'s existing docstring uses `"""`; keep it.
- NO new module-level import — `threading` is imported LAZILY inside the `_is_agy` branch.
  `os`, `signal`, `subprocess`, `time` are already module-top imports; reuse them.
- DECISION FILE (BARRIER): `harness/orchestrator.py` is in `_NEVER_AUTO_APPROVE`, so the impl
  commit (`agy-communicate-bounded-capture-impl`) needs a pre-staged operator approval at
  `state/control/decisions/agy-communicate-bounded-capture-impl.json` before the worker can
  auto-commit. The oracle task (`agy-communicate-bounded-capture-oracle`) only writes a test
  file under `tests/` and does NOT need a decision. (The operator stages the decision
  out-of-band; this brief does not author it.)
- DAEMON RESTART: this edits `harness/orchestrator.py`. The daemon caches its own code at
  startup and self-reloads on idle source change; planner/worker subprocesses pick up the new
  `orchestrator.py` fresh per spawn. The NEW default cap (300s) takes effect with no config
  edit. Treat as a barrier — do not land another orchestrator spawn-path edit concurrently.
- RESIDUAL CAVEAT (state honestly in the report): this fix bounds the agy capture so a
  slow/unproductive agy planner spawn fails FAST (≤ ~300s default, vs ~1625s) and the latent
  pipe-EOF wedge can no longer block the full budget. It does NOT make the specific 29KB brief
  PLANNABLE on its own: the underlying agy emptiness is TRANSIENT (other spawns of the same
  prompt drafted fine), and there is a SEPARATE architectural mismatch (the agy branch writes
  `outbox/submission.py` while the planner collectors read `plan_draft.json`/`reconciliation.json`)
  that is OUT OF SCOPE here. After this lands, a slow/empty agy spawn surfaces its failure in
  seconds-to-minutes instead of ~1625s, un-wedging the planner so the productive agent's draft
  (or a prompt re-dispatch) can proceed.
