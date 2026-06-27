#!/usr/bin/env python3
"""Analytic cross-check of the differential-fuzz coverage meter.

Method A  = the meter's own discriminator: accepted task ids (a phase_transition
            row with phase/to == 'accepted') whose phase SET across the ledger
            contains the phase 'fuzzing'.
Method B  = INDEPENDENT discriminator: an accepted task was FUZZED iff an
            on-disk fuzz-result artifact  logs/fuzz_results/<task_id>_<round>.json
            exists (written by orchestrator._persist_fuzz_results on a SEPARATE
            disk-write path, not via the set_phase/_emit_lifecycle ledger calls).

We compute accepted/fuzzed/bypassed by both, confirm Method A reproduces the
emitted 214/17/197 row, and compare the two methods per-task.
"""
import json
import os
import pathlib

REPO = pathlib.Path(__file__).resolve().parents[1]
LEDGER = REPO / 'state' / 'impl_progress.jsonl'
FUZZ_DIR = REPO / 'logs' / 'fuzz_results'

# ---------------------------------------------------------------------------
# Parse the ledger ONCE: phase sets per task + accepted-task order (first-seen).
# This mirrors compute_fuzz_coverage's traversal exactly.
# ---------------------------------------------------------------------------
task_phases: dict[str, set[str]] = {}
accepted_tasks: list[str] = []
with open(LEDGER, encoding='utf-8', errors='ignore') as f:
    for line in f:
        line = line.strip()
        if not line:
            continue
        try:
            d = json.loads(line)
        except Exception:
            continue
        if not isinstance(d, dict):
            continue
        tid = d.get('task_id')
        if not tid or not isinstance(tid, str):
            continue
        if d.get('event') == 'phase_transition':
            phase = d.get('phase')
            if not phase:
                pt = d.get('phase_transition')
                if isinstance(pt, dict):
                    phase = pt.get('to')
            if phase and isinstance(phase, str):
                task_phases.setdefault(tid, set()).add(phase)
                if phase == 'accepted' and tid not in accepted_tasks:
                    accepted_tasks.append(tid)

accepted_total = len(accepted_tasks)

# ---------------------------------------------------------------------------
# METHOD A: fuzzed iff 'fuzzing' in the task's phase set.
# ---------------------------------------------------------------------------
A_fuzzed = {t for t in accepted_tasks if 'fuzzing' in task_phases.get(t, set())}
A_bypassed = {t for t in accepted_tasks if t not in A_fuzzed}

print('=' * 70)
print('METHOD A (meter discriminator: "fuzzing" phase present)')
print('=' * 70)
print(f'  accepted_total = {accepted_total}')
print(f'  fuzzed         = {len(A_fuzzed)}')
print(f'  bypassed       = {len(A_bypassed)}')
print(f'  fuzzed_fraction= {len(A_fuzzed)/accepted_total if accepted_total else 0:.16f}')
reproduces = (accepted_total == 214 and len(A_fuzzed) == 17 and len(A_bypassed) == 197)
print(f'  REPRODUCES emitted 214/17/197 ? -> {reproduces}')

# ---------------------------------------------------------------------------
# METHOD B: independent — accepted task fuzzed iff a fuzz_results artifact
# exists for it. Map artifact -> task_id by stripping the _<round>.json suffix.
# A task may have multiple rounds; collapse to the base task id.
# ---------------------------------------------------------------------------
ROUND_SUFFIXES = ('_round1', '_round2', '_round3', '_round4', '_stateful')
fuzzed_artifact_tasks: set[str] = set()
artifact_files = sorted(os.listdir(FUZZ_DIR)) if FUZZ_DIR.is_dir() else []
for name in artifact_files:
    if not name.endswith('.json'):
        continue
    stem = name[:-len('.json')]
    base = stem
    for suf in ROUND_SUFFIXES:
        if stem.endswith(suf):
            base = stem[:-len(suf)]
            break
    fuzzed_artifact_tasks.add(base)

# Restrict to ACCEPTED tasks for the comparison (the meter only counts accepts).
B_fuzzed = {t for t in accepted_tasks if t in fuzzed_artifact_tasks}
B_bypassed = {t for t in accepted_tasks if t not in B_fuzzed}

print()
print('=' * 70)
print('METHOD B (INDEPENDENT: logs/fuzz_results/<task>_<round>.json exists)')
print('=' * 70)
print(f'  total fuzz_results artifacts on disk = {len(artifact_files)}')
print(f'  distinct base task ids w/ artifact   = {len(fuzzed_artifact_tasks)}')
print(f'  ...of which are ACCEPTED tasks        = {len(B_fuzzed)}')
print(f'  B fuzzed (accepted)  = {len(B_fuzzed)}')
print(f'  B bypassed (accepted)= {len(B_bypassed)}')

# ---------------------------------------------------------------------------
# PER-TASK AGREEMENT
# ---------------------------------------------------------------------------
agree = 0
disagree_A_not_B = []  # Method A says fuzzed, Method B says no artifact
disagree_B_not_A = []  # Method B has artifact, Method A says bypassed
for t in accepted_tasks:
    a = t in A_fuzzed
    b = t in B_fuzzed
    if a == b:
        agree += 1
    elif a and not b:
        disagree_A_not_B.append(t)
    else:
        disagree_B_not_A.append(t)

print()
print('=' * 70)
print('PER-TASK AGREEMENT (over all 214 accepted tasks)')
print('=' * 70)
print(f'  identical classification: {agree}/{accepted_total}')
print(f'  A=fuzzed but NO artifact (B=bypassed): {len(disagree_A_not_B)}')
for t in disagree_A_not_B:
    print(f'      - {t}   phases={sorted(task_phases.get(t, set()))}')
print(f'  B=artifact but A=bypassed (no fuzzing phase): {len(disagree_B_not_A)}')
for t in disagree_B_not_A:
    print(f'      - {t}   phases={sorted(task_phases.get(t, set()))}')

# Artifacts whose base task is NOT in the accepted set (rejected-after-fuzz etc.)
non_accepted_artifacts = sorted(fuzzed_artifact_tasks - set(accepted_tasks))
print()
print(f'  fuzz artifacts whose base task is NOT in accepted set: {len(non_accepted_artifacts)}')
for t in non_accepted_artifacts[:40]:
    ph = sorted(task_phases.get(t, set())) if t in task_phases else 'NO-LEDGER-ROWS'
    print(f'      - {t}   phases={ph}')

# ---------------------------------------------------------------------------
# SECONDARY METRICS reproduction (capture_rate / fp_rate) exactly as the meter.
# meta_task_type is checked for presence in the ledger.
# ---------------------------------------------------------------------------
mtt_present = 0
with open(LEDGER, encoding='utf-8', errors='ignore') as f:
    for line in f:
        line = line.strip()
        if not line:
            continue
        try:
            d = json.loads(line)
        except Exception:
            continue
        if isinstance(d, dict) and d.get('meta_task_type'):
            mtt_present += 1

# Reproduce capture_rate / fp_rate with the meter's logic
BYPASS = {'harness_plumbing', 'orchestration', 'test_e2e', 'hooks_integration',
          'planner_tooling', 'test_unit', 'config_schema', 'epic_planning',
          'docs_writing', 'validation', 'sandbox_infra', 'test_integration',
          'harness_self_fix', 'test_acceptance', 'mcp_plumbing', 'mcp_server_change'}
# task_types is empty because meta_task_type never appears in ledger rows.
task_types: dict[str, str] = {}
fuzzable = 0
fuzzed_fuzzable = 0
fuzzed_with_xexam = 0
fuzzed_cnt = 0
for t in accepted_tasks:
    ph = task_phases.get(t, set())
    isf = 'fuzzing' in ph
    if isf:
        fuzzed_cnt += 1
        if 'cross_examination' in ph:
            fuzzed_with_xexam += 1
    mtt = task_types.get(t)
    is_fuzzable = mtt is None or mtt not in BYPASS
    if is_fuzzable:
        fuzzable += 1
        if isf:
            fuzzed_fuzzable += 1
capture = fuzzed_fuzzable / fuzzable if fuzzable else 0.0
fp = fuzzed_with_xexam / fuzzed_cnt if fuzzed_cnt else 0.0

print()
print('=' * 70)
print('SECONDARY METRICS (reproduced with meter logic)')
print('=' * 70)
print(f'  rows carrying meta_task_type in ledger = {mtt_present}  '
      f'(=> task_types dict is {"EMPTY" if mtt_present == 0 else "populated"})')
print(f'  fuzzable_accepted_count               = {fuzzable}  (== accepted_total? {fuzzable == accepted_total})')
print(f'  capture_rate = {capture:.16f}')
print(f'  fuzzed_fraction = {len(A_fuzzed)/accepted_total:.16f}')
print(f'  capture_rate == fuzzed_fraction ? -> {abs(capture - len(A_fuzzed)/accepted_total) < 1e-15}')
print(f'  fuzzed_accepted_with_cross_examination = {fuzzed_with_xexam}')
print(f'  fuzzed_accepted_count                  = {fuzzed_cnt}')
print(f'  fp_rate = {fp:.16f}   (== {fuzzed_with_xexam}/{fuzzed_cnt})')
