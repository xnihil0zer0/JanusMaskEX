"""GATE-B gating integration test (REV29 Step 4).

Deterministic, hermetic, end-to-end self-heal CONVERGENCE regression test.

This is a GREEN gating regression test (NOT a RED oracle): on current HEAD the
self-heal loop is closed (REV29 Step 0 clobber-guard + §2c provenance mint), so
this test must PASS. It pins the full convergence chain:

  1. An ORIGINAL allowlisted plan (slug ``orig``) has a ``harness_self_fix``
     task ``<tid>`` and a dependent task ``<dep_tid>`` that depends on it.
  2. ``<tid>`` has reached the genuinely-exhausted post-escalation blocked
     state (blocked.json + retry.json{attempts=1,deterministic-outcome} +
     .exhausted marker), and the diagnosing agent has dropped a
     ``brief_hooks_<tid>_fix.md`` in its outbox -- exactly what the daemon
     produces after a deterministic AST/validation failure (agent B returning
     ``eval(...)``). We seed that end-state directly so there is ZERO model
     variance, no real worker subprocess, no network, and no sleeps.
  3. TICK 1 -- one ``_auto_promote`` pass drives the closure entirely
     in-process:
       * ``_retry_blocked_tasks`` short-circuits on the ``.exhausted`` marker
         (does NOT re-stage), so the blocked sidecar survives for harvest.
       * ``_harvest_selfheal_briefs`` harvests the fix brief, synthesizes
         ``plan_hooks_selfheal_<tid>.json`` keyed on the ORIGINAL ``<tid>``,
         mints the §2c HMAC provenance marker, and evicts the three blocked
         sidecars.
       * The REV29 Step 0 clobber-guard skips staging ``<tid>`` from the
         ORIGINAL plan (because ``plan_hooks_selfheal_<tid>.json`` now exists),
         so the self-heal-corrected task is the one that gets staged.
       * The dependent ``<dep_tid>`` is NOT staged yet (its dependency is not
         accepted).
  4. We then simulate the corrected task RUNNING -- the only way that does not
     introduce model variance: move it into ``tasks/processed/`` (a successful
     worker drop) but WITHOUT an acceptance ledger row yet (the "processed but
     not-yet-accepted" / zombie window). Running a real worker is exactly the
     non-deterministic, model-driven step GATE-B forbids exercising.
  5. TICK 2 (pre-acceptance) -- a second ``_auto_promote`` pass must NOT stage
     the dependent ``<dep_tid>``: the STAGING_DEP_GATE sees its dependency
     ``<tid>`` processed-but-unaccepted and gates it.
  6. We write the ``accepted``/``auto_commit`` ledger row that acceptance would
     have produced for ``<tid>``.
  7. TICK 3 -- a third ``_auto_promote`` pass observes ``<tid>`` accepted, so
     the STAGING_DEP_GATE is satisfied and the dependent ``<dep_tid>`` is
     finally staged: the dependency edge is UNBLOCKED. Loop converged.

Owner flags stay DEFAULT-OFF: ``enable_single_agent_promotion`` and
``auto_approve_sensitive_harness`` are never touched, and the test does not
depend on auto-approve. ``selfheal_auto_promote`` is supplied ONLY as a local
``config`` dict argument to ``_auto_promote`` (the documented gating mechanism
the harvest consults -- see tests/adversarial/test_selfheal_*; it is NOT a
mutation of any global config / load_config default). Operator approval, where
needed, is expressed as ``state/control/decisions/<id>.json`` in the test's OWN
tmp state dir.

Hermetic: ``JANUSMASK_SELFHEAL_SECRET_PATH`` is redirected to a tmp file so the
host ``~/.config/janusmask/selfheal_hmac_secret`` is never read or written, and
all repo/state I/O is confined to ``tmp_path``.
"""
from __future__ import annotations

import json
import os
import pathlib
import time

import harness.paths as _paths
from harness import autowork_daemon as d


def _patch_workroot(monkeypatch, workroot: pathlib.Path) -> None:
    """Redirect the agent workroot used by the self-heal harvest to tmp."""
    monkeypatch.setattr(_paths, "agent_workroot", lambda: workroot)
    if hasattr(d, "agent_workroot"):
        monkeypatch.setattr(d, "agent_workroot", lambda: workroot)


def _seed_fix_brief(workroot: pathlib.Path, agent: str, task_id: str) -> None:
    """Drop the diagnosing-agent fix brief in an outbox, as the daemon would."""
    sess = workroot / agent / f"{agent}-r1-{task_id}-cafef00d" / "outbox"
    sess.mkdir(parents=True)
    (sess / f"brief_hooks_{task_id}_fix.md").write_text(
        "# Title\n"
        "Corrected spec: edit the target directly; do NOT use eval/exec/decorators.\n"
        "# Objective\nCORRECTED\n",
        encoding="utf-8",
    )


def _accepted_task_ids(state_dir: pathlib.Path) -> set[str]:
    """Task ids with an accepted/auto_commit row in the ledger."""
    ledger = state_dir / "impl_progress.jsonl"
    out: set[str] = set()
    if not ledger.exists():
        return out
    for line in ledger.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if (
            isinstance(row, dict)
            and row.get("phase") == "accepted"
            and row.get("event") == "auto_commit"
        ):
            tid = row.get("task_id")
            if isinstance(tid, str) and tid:
                out.add(tid)
    return out


def test_gateb_selfheal_convergence(tmp_path, monkeypatch) -> None:
    # ---- 1. Hermetic directory layout (everything under tmp_path) ----------
    workroot = tmp_path / "agentwork"
    workroot.mkdir()
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    state_dir = tmp_path / "state"
    (state_dir / "tasks").mkdir(parents=True)
    (state_dir / "tasks" / "processed").mkdir(parents=True)
    (state_dir / "tasks" / "blocked").mkdir(parents=True)
    (state_dir / "control" / "autowork").mkdir(parents=True)
    (state_dir / "control" / "decisions").mkdir(parents=True)

    # ---- 2. Hermetic self-heal HMAC secret (never touch host ~/.config) ----
    monkeypatch.setenv(
        "JANUSMASK_SELFHEAL_SECRET_PATH", str(tmp_path / "selfheal_hmac_secret")
    )

    # ---- 3. Redirect agent workroot to tmp ---------------------------------
    _patch_workroot(monkeypatch, workroot)

    # ---- 4. Local config: ONLY selfheal_auto_promote, default-off flags off.
    # This is a local arg to _auto_promote (the documented harvest gate), NOT a
    # global/config.yaml mutation. enable_single_agent_promotion and
    # auto_approve_sensitive_harness are intentionally absent (i.e. off).
    config = {"autowork": {"selfheal_auto_promote": True}}

    tid = "gate_b_task"
    dep_tid = "gate_b_dependent_task"
    orig_slug = "orig"

    # ---- 5. Operator approvals in the test's OWN tmp state dir --------------
    # (Expressed the approved way; we do NOT flip any auto-approve flag.)
    for _t in (tid, dep_tid):
        (state_dir / "control" / "decisions" / f"{_t}.json").write_text(
            json.dumps({"decision": "approve"}), encoding="utf-8"
        )

    # ---- 6. Seed the ORIGINAL allowlisted plan + brief ---------------------
    (repo_root / f"brief_hooks_{orig_slug}.md").write_text(
        "# Original Brief\n", encoding="utf-8"
    )
    orig_plan = {
        "slug": orig_slug,
        "brief": f"brief_hooks_{orig_slug}.md",
        "tasks": [
            {
                "task_id": tid,
                "meta_task_type": "harness_self_fix",
                "dependencies": [],
                "files_touched": ["harness/selfheal.py"],
                "objective": "ORIGINAL",
            },
            {
                "task_id": dep_tid,
                "meta_task_type": "refactor",
                "dependencies": [tid],
                "files_touched": ["foo.py"],
                "objective": "Dependent task",
            },
        ],
    }
    orig_plan_path = repo_root / f"plan_hooks_{orig_slug}.json"
    orig_plan_path.write_text(json.dumps(orig_plan, indent=2), encoding="utf-8")

    allowlist_path = state_dir / "control" / "autowork" / "auto_promote.allowlist"
    allowlist_path.write_text(f"{orig_slug}\n", encoding="utf-8")

    # ---- 7. Seed the genuinely-exhausted post-escalation blocked state ------
    # This is the deterministic end-state after agent B returned eval(...) and
    # exhausted the retry budget: blocked.json + retry.json (attempts=1 with a
    # deterministic outcome -> effective_max=1) + .exhausted marker.
    blocked_path = state_dir / "tasks" / "blocked" / f"{tid}.json"
    blocked_path.write_text(
        json.dumps(
            {
                "task_id": tid,
                "meta_task_type": "harness_self_fix",
                "dependencies": [],
                "files_touched": ["harness/selfheal.py"],
                "objective": "CORRECTED",
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    retry_path = state_dir / "tasks" / "blocked" / f"{tid}.retry.json"
    retry_path.write_text(
        json.dumps(
            {"attempts": 1, "last_outcome": "synthesis_or_ast_failed", "ts": time.time()}
        ),
        encoding="utf-8",
    )
    exhausted_path = state_dir / "tasks" / "blocked" / f"{tid}.exhausted"
    exhausted_path.write_text("1", encoding="utf-8")

    # The diagnosing agent's fix brief sits in the outbox.
    _seed_fix_brief(workroot, "claude", tid)

    # Ensure the original brief sorts as the OLDER record (so the clobber-guard
    # is genuinely exercised against an established original plan).
    past = time.time() - 3600
    os.utime(repo_root / f"brief_hooks_{orig_slug}.md", (past, past))
    os.utime(orig_plan_path, (past, past))

    # ======================= TICK 1: harvest -> synth -> stage corrected =====
    d._auto_promote(repo_root, state_dir, config)

    # (a) Corrective plan synthesized, keyed on the ORIGINAL tid.
    selfheal_plan_path = repo_root / f"plan_hooks_selfheal_{tid}.json"
    assert selfheal_plan_path.exists(), "self-heal corrective plan must be synthesized"
    selfheal_plan = json.loads(selfheal_plan_path.read_text(encoding="utf-8"))
    assert len(selfheal_plan.get("tasks", [])) == 1
    assert selfheal_plan["tasks"][0]["task_id"] == tid, "plan must be keyed on ORIGINAL tid"

    # (b) §2c provenance marker minted (hermetic secret) for the selfheal slug.
    prov_path = (
        state_dir / "control" / "autowork" / "selfheal_provenance" / f"selfheal_{tid}.json"
    )
    assert prov_path.exists(), "self-heal provenance marker must be minted"

    # (c) All three blocked sidecars evicted by harvest.
    assert not blocked_path.exists(), "blocked sidecar must be evicted"
    assert not retry_path.exists(), "retry sidecar must be evicted"
    assert not exhausted_path.exists(), "exhausted sidecar must be evicted"

    # (d) The CORRECTED task is staged; the clobber-guard kept the ORIGINAL
    #     plan from re-clobbering it (objective stays CORRECTED, not ORIGINAL).
    staged_path = state_dir / "tasks" / f"{tid}.json"
    assert staged_path.exists(), "self-heal-corrected task must be staged"
    staged = json.loads(staged_path.read_text(encoding="utf-8"))
    assert staged.get("objective") == "CORRECTED", (
        f"clobber detected: expected CORRECTED objective, got {staged.get('objective')!r}"
    )

    assert tid not in _accepted_task_ids(state_dir)

    # ======================= simulate the corrected task RUNNING ============
    # A successful worker run on the corrected task moves it into processed/.
    # We model exactly that drop (running a real worker is the model-variant
    # step GATE-B forbids). Until an acceptance row exists, <tid> is a
    # processed-but-unaccepted dependency -> the STAGING_DEP_GATE must gate the
    # dependent. We also clear the dependent's prematurely-queued copy so the
    # gate is tested on a fresh re-stage attempt.
    dep_staged_path = state_dir / "tasks" / f"{dep_tid}.json"
    if dep_staged_path.exists():
        dep_staged_path.unlink()
    staged_path.rename(state_dir / "tasks" / "processed" / f"{tid}.json")

    # ======================= TICK 2: dependent still GATED ==================
    d._auto_promote(repo_root, state_dir, config)
    assert not dep_staged_path.exists(), (
        "dependent must stay gated while its dependency is processed-unaccepted"
    )

    # ======================= record deterministic acceptance ================
    from harness._journal import write_jsonl_row

    write_jsonl_row(
        state_dir / "impl_progress.jsonl",
        {
            "ts": time.time(),
            "phase": "accepted",
            "task_id": tid,
            "event": "auto_commit",
            "commit_sha": "deadbeef",
            "files": ["harness/selfheal.py"],
            "exit": 0,
        },
    )
    assert tid in _accepted_task_ids(state_dir), "acceptance row must be recorded"

    # ======================= TICK 3: dependent UNBLOCKED ====================
    d._auto_promote(repo_root, state_dir, config)
    assert dep_staged_path.exists(), (
        "dependent must be staged once its dependency is accepted (loop converged)"
    )
    dep_staged = json.loads(dep_staged_path.read_text(encoding="utf-8"))
    assert dep_staged.get("task_id") == dep_tid
