# NobleGreedv2 — Epic #1: Substrate Beachhead (authored brief)

Status: AUTHORED, awaiting owner go-ahead (checkpoint). Targets the external repo
`/home/xnihil0zer0/NobleGreedv2` (`working_dir`). All children are deterministic,
pure, oracle-gateable Python — the regime JM's gates LOVE. The dangerous live
detonation is data-driven at NGv2 runtime later; here we build only the
deterministic ORCHESTRATION + CONTRACTS, tested with mocks.

HEAD context: NGv2 master `aac9970` (skeleton + smoke oracle), `janusmask/work`
`cccae37` (+ `ngv2/_smoke.py`). JM gap #3 fixed (`a73f294`). Gap #2 (accumulation)
fix is a prerequisite — see §C below.

---

## §A Child DAG (single level — operator owns decomposition; NO auto-recurse)

```
ngv2-artifact-contract   (L0, no deps)        -> ngv2/contracts.py
        |
        +--> ngv2-state-machine      (L1)     -> ngv2/state_machine.py   (imports contracts)
        +--> ngv2-detonation-chamber (L1)     -> ngv2/detonation.py      (imports contracts)
```

Two L1 children both depend on the L0 contract → deliberately exercises the gap #2
accumulation fix (both dependents must read `contracts.py` on the advanced base)
and the gap #3 jail-retarget fix (the synthesis agent must READ `ngv2/contracts.py`
to match real signatures). 3 children = minimal but covers every external
multi-child risk before widening in Epic #2.

Each child: NEW module → SINGLE-FILE WHOLE-FILE submission; exact target path
named; explicit `verification_command` running ONLY its own oracle in NGv2's venv;
hand-authored oracle COMMITTED to NGv2 `master` up front (external dirty-gate
requires a clean tree — untracked oracles are refused).

---

## §B Child specifications

### B1. ngv2-artifact-contract  →  `ngv2/contracts.py`  (L0, no deps)
Pure dataclasses + JSON (de)serialization + validation for the three non-patch
deliverables NGv2's runtime produces.

- `SEVERITIES = ('low','medium','high','critical')`, `VERDICTS = ('confirmed','refuted','error','inconclusive')` (module constants).
- `@dataclass Finding`: `id:str, target:str, category:str, severity:str, title:str, description:str, evidence:list[str]`.
- `@dataclass PoC`: `finding_id:str, language:str, code:str, entrypoint:str`.
- `@dataclass LiveTestReport`: `poc_finding_id:str, verdict:str, exit_code:int|None, stdout:str, stderr:str, duration_ms:int`.
- Each class: `to_dict() -> dict` and classmethod `from_dict(d) -> <cls>` that round-trip; `validate() -> None` raising `ValueError` on unknown severity/verdict or missing/empty required str fields.
- Pure: no imports beyond `dataclasses`/`typing`; no I/O, globals, randomness.

Oracle `tests/test_contracts.py` (committed): round-trip equality for each class;
`validate()` accepts good + rejects bad severity/verdict; `from_dict(to_dict(x))==x`.

### B2. ngv2-state-machine  →  `ngv2/state_machine.py`  (L1, deps: B1)
Deterministic hunt→triage→poc→detonate→report phase model + a serializable state.

- `PHASES = ('hunt','triage','poc','detonate','report','done')`.
- `ALLOWED_TRANSITIONS: dict[str, tuple[str,...]]` (linear with an allowed early `done`).
- `@dataclass HuntState`: `phase:str='hunt', findings:list[Finding]=field(default_factory=list)` — **imports `Finding` from `ngv2.contracts`** (the dependency edge).
- `class HuntStateMachine`: wraps a `HuntState`; `can_transition(to:str)->bool`; `transition(to:str)->None` (raises `ValueError` on illegal); `to_dict()/from_dict()` round-tripping the state (findings via `Finding.to_dict`).
- Pure, deterministic.

Oracle `tests/test_state_machine.py` (committed, imports `ngv2.contracts` + `ngv2.state_machine`): legal transition advances; illegal raises; `from_dict(to_dict())` round-trips including findings.

### B3. ngv2-detonation-chamber  →  `ngv2/detonation.py`  (L1, deps: B1)
Deterministic ORCHESTRATION of a PoC detonation; the exploit is DATA, the runner is
INJECTED (so it's pure + mock-testable). No real subprocess/network here.

- `class DetonationChamber`: `detonate(poc:PoC, target_spec:dict, runner) -> LiveTestReport`.
  `runner` is a callable `(poc, target_spec) -> (exit_code:int|None, stdout:str, stderr:str, duration_ms:int)`.
  Verdict rule (deterministic): runner raises → `error`; `exit_code==0` and a configurable success marker present in stdout → `confirmed`; `exit_code not in (0,None)` → `refuted`; else → `inconclusive`. Returns a fully-populated `LiveTestReport`.
- **imports `PoC, LiveTestReport` from `ngv2.contracts`** (the dependency edge).
- Pure orchestration; deterministic given a deterministic runner.

Oracle `tests/test_detonation.py` (committed, imports `ngv2.contracts` + `ngv2.detonation`): mock runners exercise each verdict branch; report fields populated; deterministic.

> pytest collects ONLY each child's own oracle file (vcmd names it explicitly), so
> committing B2/B3 oracles (which import not-yet-built `ngv2.contracts`) to master
> up front does not break B1's run — uncollected files aren't imported.

---

## §C Gap #2 fix (accumulation) — PREREQUISITE, deny-listed, via pipeline

PROBLEM: accepted external output lands on `janusmask/work`, but the staging
worktree detaches from the static checked-out `master`, which JM never advances —
so B2/B3 (built after B1) would NOT see `ngv2/contracts.py`.

REFINED FIX (simpler than the two-part option discussed; recommend): in
`git_integration.merge_staging_to_parent`, on the EXTERNAL branch, AFTER the
`janusmask/work` ref-update, ALSO advance the checked-out branch via
`git -C parent_root merge --ff-only <staging_sha>` — GATED on a valid JM ownership
marker (`target_bootstrap._read_valid_marker(parent_root)`), so a foreign repo's
branch is never touched. Staging already bases on `master` HEAD, and `staging_sha`
is a descendant of it, so the ff-only is clean (the EXTERNAL_DIRTY_GATE guarantees
a clean tree). Net effect: `master` accumulates, I commit oracles to `master`, the
next child's staging sees prior output. `janusmask/work` is kept as the audit
branch. Single self-contained edit to the external branch of `merge_staging_to_parent`
+ hand-authored RED oracle (temp git repo + marker: assert master advances to the
pushed SHA on an external merge, and does NOT advance without a marker).

## §D Gap #4 (vcmd normalize self-rooting) — execution-mechanics decision

The planner's `normalize_plan` globs `Path(cwd).glob('tests/**/test_<leaf>.py')` at
JM's cwd, so the daemon's epic-planning path would MANGLE each external child's
`verification_command` into a self-import smoke (never running NGv2's oracle).
TWO ways to run the epic hands-off:
  (a) HAND-AUTHOR the 3-task child plan (deps + working_dir + explicit vcmds) and
      have the daemon stage it dep-gated — bypasses normalize entirely (what the
      smoke + gap#3 did). Lowest-risk; recommended for Epic #1.
  (b) Pipeline-fix `normalize_plan` to skip/retarget for external `working_dir`,
      then use the full epic-brief machinery. More general but another deny-listed
      change; defer to when epics get large.

RECOMMEND (a) for Epic #1.

---

## §E Execution plan (after go-ahead)
1. Land gap #2 fix via pipeline (harness_self_fix + decision + RED oracle); JM sweep green.
2. Hand-author `ngv2/contracts.py`-etc child plan (3 tasks, deps, working_dir).
3. Hand-author + COMMIT the 3 oracles to NGv2 master.
4. Stage the L0 child; add to allowlist / set gate run; start daemon by PID.
   Daemon: bootstrap (idempotent) → stage L0 → build → accept → master advances
   (gap #2) → dep-gate releases L1 ×2 → build (agents read contracts via gap #3) →
   accept. Monitor `impl_progress.jsonl`, NGv2 git, and TOKEN/WALL spend.
5. Fix-brief any failing child before continuing. Kill daemon by explicit PID.
6. Close out: JM sweep green, gate paused, push JM changes w/ owner sign-off; NGv2
   commits live in NGv2's own git.
