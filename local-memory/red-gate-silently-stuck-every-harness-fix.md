---
name: red-gate-silently-stuck-every-harness-fix
description: CORRECTED 2026-06-16 — the harness_self_fix gate is the brief's LITERAL vcmd (honored verbatim) run in the bwrap --unshare-net jail + a 2-test RO-gate; it is NOT an automatic full tests/adversarial/ suite. The full suite only runs if the vcmd IS broad (forbidden). Keep each vcmd narrow AND hermetic.
metadata: 
  node_type: memory
  type: project
  originSessionId: ae16acba-9ad9-45c6-989f-a8c880d79cef
---

⚠️ ROOT CAUSE of the recurring "you said it's running but it's stuck" pattern
(owner named it 2026-06-15, multiple sessions).

🔧 MECHANISM CORRECTED 2026-06-16 (direct code read, ae16acba round-5): the gate is
NOT an automatic full-suite run. `_resolve_verification_command`
(`orchestrator.py:1952`) returns the task's OWN `verification_command` VERBATIM
(or from the parent chain) — nothing force-expands it to `tests/adversarial/`. The
only suite-style gate is `_verify_from_ro_parent` (`git_integration.py:1608`) run
with `_RO_GATE_TESTS` = exactly 2 hermetic tests (`test_sec_inv2_trustroot.py`,
`test_p10b_denylist_widen.py`) at auto-approve commit time when
`autowork.auto_approve_ro_gate:true`. So the harness gate = (the brief's LITERAL
vcmd, run in the `bwrap --unshare-net` jail) + (the 2-test RO-gate). The WHOLE
`tests/adversarial/` suite only runs when a brief's *vcmd* IS the broad suite —
which [[broad-adversarial-suite-vcmd-is-flaky-gate]] forbids. The episodes below
were real (the suite WAS genuinely red), but they bit because those briefs' vcmds
ran broad / PASS5 repointed a vacuous import-smoke vcmd onto a then-red committed
test — not because of an unconditional full-suite gate. **Takeaway: keep every
harness vcmd NARROW and HERMETIC (no net/abspath/subprocess so it passes inside
`--unshare-net`); you DON'T need to green the whole suite to land a scoped fix.**

(Historical, for the broad-vcmd case:) when a vcmd does run the suite in a fresh
worktree and even ONE test is red, the gate fails, the task routes to `blocked/`
and loops to retry-exhaustion — failure reason non-obvious: `worker_exit.stderr_tail`
clobbered by `git worktree remove ... exit 128` noise, and the real
`verification_failed` row uses an ISO-string `ts` (not float) so naive log parsers
skip it.

2026-06-15: the suite had 15 deterministic fresh-worktree failures from
repo-completeness drift, blocking ALL harness fixes. Fixed in `402f5c4`:
- `state/` is gitignored → a fresh clone had no `state/*.json`, so taxonomy (×6)
  and P1 track-record (×2) tests failed. `git add -f state/meta_task_taxonomy.json
  state/synthesis_target_taxonomy.json`.
- declutter `d7bbf36` archived REPL-10 smoke fixtures → restore
  `brief_hooks_smoke.md` + `plan_hooks_smoke.json` to repo root from
  `_autowork_archive/2026-06-14_root_declutter/`.
- `harness/smoke_target.py` stub had drifted to define `__version__` (a prior
  smoke dispatch got committed) → remove it (docstring says stub must omit it).
Then home-free markers landed via pipeline `d7f582c` (first trust-core
orchestrator.py edit to land that day — it WORKED once the gate was green).

2026-06-15 (SECOND instance, same class): even AFTER the worktree was complete,
2 tests still failed IN THE JAIL because they `pip install` real distributions
over the network (`provision_venv` → inflection; `post_rebuild_start` → hypothesis)
and the gate jail is `bwrap --unshare-net` (no off-host network). Fixed `ba505dd`:
both tests now skip/tolerate when PyPI is unreachable (re-raise/assert when it IS,
so real bugs aren't masked). Full suite then GREEN in the real jail: 4467 passed.
The 2 offenders: `test_init_output_repo_writes_requirements_and_gitignores_venv`
(test_rebuild_envfaithful.py), `test_post_rebuild_start_module_slice`
(test_rebuild_webui.py).

⚠️ PROBE FAITHFULLY: the real jail is `bwrap --die-with-parent --unshare-net
--unshare-ipc --bind / / --proc /proc --tmpfs /tmp --dev-bind /dev /dev` (mount
order matters: `--bind / /` BEFORE `--dev-bind /dev /dev` or /dev/null → EACCES at
dill import). bwrap `--unshare-net` brings LOOPBACK UP (127.0.0.1 works; external
blocked) — so webui localhost-server tests PASS in it. Do NOT probe with
`unshare -n -r`: it leaves `lo` DOWN and maps you to root → 41 FALSE failures (all
the webui 127.0.0.1 tests + a P5 readonly-as-root artifact). The authoritative
signal is the real factory `verification_failed` telemetry ("2 failed: …").
Also: a backgrounded `--die-with-parent` bwrap dies when the launching subshell
exits (0-byte output) — run it as a foreground tracked task, not `nohup … &`.

**RULE going forward (corrected):** the brief's `verification_command` IS honored
verbatim (`_resolve_verification_command`), so the right move is to SCOPE the vcmd
narrowly to the changed symbols and make those tests hermetic — you do NOT have to
green the whole suite. PASS5 `_sanitize_impl_verification_commands` may repoint a
*vacuous* import-smoke vcmd onto a committed test, so give a real scoped vcmd up
front (don't ship a bare `python -c "import X"`). If you DO need to run a broad set,
probe it in a REAL `bwrap --unshare-net` jail (argv above), NOT `unshare -n -r`
(41 false fails), and make network-dependent tests skip when the index is
unreachable. Report only VERIFIED landings (SHA + green re-run), never "monitor
watching / should land".
See [[fixes-are-permanent-and-reusable]], [[dont-conflate-built-with-works]].
