#!/usr/bin/env python3
"""
Lane 3 — Documented-intervention forensics for the JanusMask factory.

Walks the documented-intervention artifacts (archives, scratch, handoffs,
decision files) and classifies each by:
  * BLOCKER CLASS  — the recurring root cause that FORCED a manual/supervisor
                     intervention (the thing the owner wants automated away)
  * INTERVENTION TYPE — what the supervisor actually did about it

Emits JSON frequency tables to stdout and to
scripts/intervention_analysis/lane3_counts.json.

Counts are derived from the ARTIFACTS (file contents), not from memory.
Pure stdlib; run with:  python3 scripts/intervention_analysis/lane3_archive_forensics.py
"""
from __future__ import annotations
import json
import os
import re
import sys
from collections import Counter, defaultdict

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))

# ---------------------------------------------------------------------------
# Artifact corpus (all paths relative to repo root)
# ---------------------------------------------------------------------------
SCAN_DIRS = [
    "_autowork_archive",
    "_autowork_scratch",
    "adversarial_review_2026-06-08",
    "adversarial_test_plans",
    "_phase_prep",
    "_phase4_rebrief",
    "_c3_pending",
    "held_briefs_selfheal_build",
    "_ngv2_staged_oracles",
]
# Root narrative docs (handoffs were declutter-archived, but also catch any at root)
ROOT_DOC_GLOBS = ("HANDOFF_", "EPIC_", "PROVENANCE_REVIEW_", "SESSION_", "WIRE_UP", "NGV2_", "OVERSEER_")

TEXT_EXT = {".md", ".txt", ".log", ".rst"}

# ---------------------------------------------------------------------------
# BLOCKER CLASS signatures — regex (case-insensitive) -> canonical class name.
# A document/decision is credited to a blocker class if ANY of its patterns hit.
# Each artifact may be credited to multiple blocker classes (a session can hit
# several), which is the honest representation of a multi-blocker session.
# ---------------------------------------------------------------------------
BLOCKER_SIGNATURES = {
    "planner_stray_mutation_target": [
        r"stray\s+mutation_target", r"mutation_target=module\.function",
        r"mutation\s+gate\s+maps\s+to\s+bogus", r"strip_stray_mutation_targets",
        r"mutation[_\s]gate.*bogus",
    ],
    "blind_worker_clobber": [
        r"clobber", r"blind\s+worker\s+stub", r"stubbed\s+run_stage",
        r"anti-?clobber", r"clobber-?bomb", r"clobber-?guard",
    ],
    "vcmd_vacuous_import_bomb": [
        r"vacuous[- ]?import", r"vacuous\s+vcmd", r'python\s+-c\s+["\']import',
        r"import-?smoke", r"weak\s+(?:import-?smoke|vcmd|verification)",
        r"importable\s+module\s+ACCEPT", r"vcmd[- ]?sanitize",
    ],
    "dep_gate_leak_or_wedge": [
        r"dep-?gate\s+leak", r"dep-?gate\s+wedge", r"dep[- ]gate",
        r"premature\s+release", r"dependency\s+gate", r"brief.?dep.*deadlock",
        r"strip_unresolvable_depend", r"unresolvable\s+dep",
    ],
    "stale_sidecar_precedence": [
        r"stale\s+sidecar", r"\.patches\.json", r"\.files\.json",
        r"sidecar\s+preceden", r"purge_stale_sidecars", r"retry-?poison",
        r"stale\s+state/output",
    ],
    "planner_ignores_verification_command": [
        r"planner\s+ignores?\s+(?:the\s+)?(?:brief\s+)?verification_command",
        r"honors?[- _]verification[- _]command", r"verification_command.*manual\s+drive",
        r"planner.*verification[- _]command", r"ignores?\s+brief\s+verification",
    ],
    "decompose_false_block": [
        r"decompose\s+false-?block", r"false-?block(?:ed)?\s+on\s+complex",
        r"DECOMPOSE.*block", r"decompose.*prune", r"phantom[- ]count",
    ],
    "nonpy_multifile_apply_routing": [
        r"non-?python", r"non-?\.py", r"multi-?file\s+(?:apply|manifest|bundle|edit)",
        r"verbatim\s+manifest", r"manifest\s+(?:routing|dispatch)",
        r"_requires_verbatim_manifest", r"nonpy[- ]manifest",
    ],
    "implementation_not_wired_orphan": [
        r"orphan(?:ed)?\s+module", r"orphan_unwired", r"IMPLEMENTATION\s*≠\s*WIRED",
        r"not[- ]wired", r"wire[- ]?up\s+gate", r"zero\s+live\s+importers?",
        r"import-?tracer\s+false", r"unwired",
    ],
    "external_root_target_resolution": [
        r"external\s+(?:root|edit)\s+(?:leaf|leaves)", r"working_dir.*external",
        r"PROJECT_ROOT.*external", r"external\s+root", r"target[- ]resolution",
        r"stamp.*working_dir", r"external\s+staging\s+push", r"resolves?\s+against\s+the\s+real\s+external",
    ],
    "no_output_stream_parse": [
        r"\(no output\)", r"no_output", r"stream[- ]json\s+(?:parse|fix)",
        r"empty\s+assistant\s+message", r"_parse_autobrief_stdout", r"headless[- ]argv",
    ],
    "ast_partial_edit_truncation_or_classmethod": [
        r"partial_edit\s+(?:silently\s+)?truncat", r"large[- ]symbol\s+truncat",
        r"never\s+patch\s+class\s+methods?", r"class-?indent", r"class\s+method\s+edit",
        r"R-?ANCHOR", r"over-?edit", r"AST[- ]truncat", r"AST[- ]merge",
    ],
    "new_module_must_be_whole_file": [
        r"new\s+module\s*=?\s*single-?file", r"whole-?file\s+(?:emit|manifest|drift)",
        r"NEW-?file.*whole", r"add(?:s|ing)?\s+symbol.*patch\s+(?:path|can'?t)",
        r"top-?level\s+symbol\s+MUST\s+ride", r"new\s+symbol\s+rides?",
    ],
    "daemon_pause_clobber_hazard": [
        r"daemon\s+pause", r"orchestrator\.flag", r"autowork/pause",
        r"blind\s+clobber\s+workers", r"pause\s+(?:file|on\s+existence)",
        r"wrong\s+pause", r"git_commit\.lock", r"stale\s+.*lock.*wedge",
    ],
    "jail_sandbox_security_fix": [
        r"\bjail\b", r"bwrap", r"sandbox", r"D-?Bus", r"systemd\s+escape",
        r"fail-?closed", r"proxy\s+(?:wrap|bind)", r"EROFS", r"runaway\s+ceiling",
        r"secret\s+(?:leak|exfil)", r"cred[- ]exfil",
    ],
    "poc_writer_template_or_confirm_gap": [
        r"poc[_\s]?writer", r"CWE-?template", r"claimable\s+(?:PoC|bounty)",
        r"0/5\s+confirm", r"zero\s+(?:real\s+)?(?:vuln|confirmed)",
        r"poc_authenticity", r"detonation\s+evidence", r"source[- ]driv",
        r"coerce_finding", r"live[- ]finding",
    ],
    "stale_existing_test_assertions": [
        r"stale\s+(?:orchestrator\s+)?(?:prompt\s+)?test", r"stale\s+existing-?test",
        r"existing[- ]test\s+assertion", r"anti-?seesaw", r"union\s+of\s+(?:all\s+)?oracle",
        r"mis-?archived\s+smoke", r"hermeticiz",
    ],
    "external_build_smoke_retry": [
        r"smoke[_-]?failed", r"smoke\s+retry", r"retry\s+budget",
        r"external\s+import.*fuzz", r"diff-?fuzzer\s+can'?t\s+resolve",
    ],
    "epic_decompose_hallucination": [
        r"epic\s+hallucinat", r"hallucinat(?:e|ed|ion)", r"child\s+brief\s+admission",
        r"epic[- ]child\s+gate", r"slug-?dep\s+drift", r"committed-?module\s+dedup",
    ],
}

# ---------------------------------------------------------------------------
# INTERVENTION TYPE signatures
# ---------------------------------------------------------------------------
INTERVENTION_SIGNATURES = {
    "harness_self_fix_decision": [
        r"harness_self_fix", r'"decision"\s*:\s*"approve"', r"operator-?approved",
        r"decision\s+file", r"state/control/decisions",
    ],
    "manual_drive_recipe": [
        r"manual[- ]drive", r"manual\s+pipeline", r"drive_leaf", r"hand-?drive",
        r"PYTHONPATH=\.\s", r"planner\.cli.*stage_task", r"manual-?DRIVE\s+recipe",
    ],
    "hand_author_oracle": [
        r"hand-?author(?:ed)?\s+(?:the\s+)?(?:RED\s+)?oracle", r"oracle-?first",
        r"hand-?authorable", r"RED\s+oracle\s+committed", r"inject\s+(?:the\s+)?oracle\s+source",
        r"embed.*oracle\s+source", r"pre-?committed?\s+oracle",
    ],
    "revert_then_manual_rebuild": [
        r"revert\+?manual", r"revert.*manual-?(?:drive|rebuild)", r"FRESH\s+rebuild",
        r"fresh\s+rebuild\s+via\s+revert", r"revert(?:ed)?.*re-?land", r"reversed.*re-?land",
    ],
    "owner_hand_edit_gated": [
        r"owner\s+hand-?edit", r"hand-?edit\s+(?:applied|reversed|violation)",
        r"_NEVER_AUTO_APPROVE", r"owner-?cleared", r"§4[ab]\s+owner",
    ],
    "quarantine_or_prune_clobber": [
        r"quarantine", r"prune(?:d)?\s+(?:queued\s+)?clobber", r"neutraliz(?:e|ed)\s+clobber",
        r"decompose\s+prune", r"move\s+(?:spent\s+)?plans?\s+out", r"backlog\s+drain",
    ],
    "config_or_allowlist_hand_edit": [
        r"allowlist(?:ed)?\s+(?:the\s+)?slug", r"config\s+override", r"config_gemini_solo",
        r"flip_autowork_flags", r"posture\s+flags?\s+ON", r"edit.*config\.yaml",
    ],
    "adversarial_verification_pass": [
        r"adversarial(?:ly)?\s+(?:verif|audit|evaluat|review)", r"ground-?truth\s+sweep",
        r"falsif", r"4-?agent\s+parallel", r"verify\s+before\s+trust",
    ],
    "daemon_pause_resume_intervention": [
        r"PAUSED\s+via", r"daemon\s+(?:paused|idle|unpaused)", r"pause\s+the\s+daemon",
        r"resume\s+(?:the\s+)?daemon", r"kill\s+child", r"respawn",
    ],
    "gemini_solo_or_backend_swap": [
        r"gemini-?solo", r"GEMINI-?SOLO", r"solo\s+(?:model\s+)?mode", r"dual-?agent",
        r"tmux-?jailed", r"backend\s+(?:swap|re-?arch)", r"claude\+gemini",
    ],
}

# Specific manual-drive recipe verbatim markers, counted separately.
MANUAL_DRIVE_RECIPE_MARKERS = [
    r"PYTHONPATH=\.",
    r"planner\.cli",
    r"stage_task",
    r"orchestrator_worker\s+--task-id",
    r"drive_leaf\.py",
    r"verify_candidate",
    r"submit_code",
]


def iter_text_files():
    """Yield (relpath, text) for all text artifacts in scope."""
    seen = set()
    for d in SCAN_DIRS:
        base = os.path.join(ROOT, d)
        if not os.path.isdir(base):
            continue
        for dirpath, _dirs, files in os.walk(base):
            for fn in files:
                ext = os.path.splitext(fn)[1].lower()
                if ext not in TEXT_EXT and not fn.endswith(".json"):
                    continue
                fp = os.path.join(dirpath, fn)
                if fp in seen:
                    continue
                seen.add(fp)
                yield fp
    # root narrative docs still living at repo root
    for fn in os.listdir(ROOT):
        if any(fn.startswith(p) for p in ROOT_DOC_GLOBS) and fn.lower().endswith(".md"):
            fp = os.path.join(ROOT, fn)
            if fp not in seen:
                seen.add(fp)
                yield fp


def read(fp):
    try:
        with open(fp, "r", errors="replace") as fh:
            return fh.read()
    except Exception:
        return ""


def compile_sigs(sig_map):
    return {k: [re.compile(p, re.I) for p in pats] for k, pats in sig_map.items()}


def main():
    blocker_re = compile_sigs(BLOCKER_SIGNATURES)
    interv_re = compile_sigs(INTERVENTION_SIGNATURES)
    drive_re = [re.compile(p, re.I) for p in MANUAL_DRIVE_RECIPE_MARKERS]

    blocker_counts = Counter()          # blocker class -> # artifacts hitting it
    interv_counts = Counter()           # intervention type -> # artifacts hitting it
    blocker_files = defaultdict(list)   # blocker class -> sample files
    interv_files = defaultdict(list)

    manual_drive_files = set()          # any file containing a manual-drive marker
    files_scanned = 0
    decision_files_scanned = 0

    for fp in iter_text_files():
        text = read(fp)
        if not text.strip():
            continue
        files_scanned += 1
        rel = os.path.relpath(fp, ROOT)
        if fp.endswith(".json") and "/decisions/" in fp:
            decision_files_scanned += 1

        for cls, regs in blocker_re.items():
            if any(r.search(text) for r in regs):
                blocker_counts[cls] += 1
                if len(blocker_files[cls]) < 6:
                    blocker_files[cls].append(rel)
        for itype, regs in interv_re.items():
            if any(r.search(text) for r in regs):
                interv_counts[itype] += 1
                if len(interv_files[itype]) < 6:
                    interv_files[itype].append(rel)
        # Manual-drive recipes live in narrative docs (.md) or scratch driver
        # scripts (.py/.sh) — NOT in staged plan/brief/session JSON (those merely
        # reference stage_task as data). Restrict to avoid false positives.
        is_recipe_carrier = (
            rel.endswith((".md", ".sh"))
            or (rel.startswith("_autowork_scratch/") and rel.endswith(".py"))
        )
        if is_recipe_carrier and any(r.search(text) for r in drive_re):
            manual_drive_files.add(rel)

    # ----- decision-file forensics (each = one harness_self_fix approval) -----
    dec_dir = os.path.join(ROOT, "state", "control", "decisions")
    decision_json = []
    if os.path.isdir(dec_dir):
        for fn in sorted(os.listdir(dec_dir)):
            if not fn.endswith(".json"):
                continue
            txt = read(os.path.join(dec_dir, fn))
            decision_json.append(fn)
    decision_total = len(decision_json)

    # classify decision files by blocker class too (their `reason` names the root)
    dec_blocker = Counter()
    for fn in decision_json:
        txt = read(os.path.join(dec_dir, fn))
        for cls, regs in blocker_re.items():
            if any(r.search(txt) for r in regs) or any(r.search(fn) for r in regs):
                dec_blocker[cls] += 1

    # ----- session inventory: count archive + scratch session dirs -----
    archive_sessions = []
    abase = os.path.join(ROOT, "_autowork_archive")
    if os.path.isdir(abase):
        archive_sessions = sorted(
            d for d in os.listdir(abase)
            if os.path.isdir(os.path.join(abase, d))
        )

    out = {
        "files_scanned": files_scanned,
        "archive_session_dirs": len(archive_sessions),
        "archive_session_names": archive_sessions,
        "decision_files_total": decision_total,
        "decision_files_scanned_in_corpus": decision_files_scanned,
        "manual_drive_recipe_files": len(manual_drive_files),
        "manual_drive_recipe_file_list": sorted(manual_drive_files),
        "blocker_class_frequency": dict(blocker_counts.most_common()),
        "blocker_class_in_decision_files": dict(dec_blocker.most_common()),
        "intervention_type_frequency": dict(interv_counts.most_common()),
        "blocker_class_sample_files": {k: blocker_files[k] for k, _ in blocker_counts.most_common()},
        "intervention_type_sample_files": {k: interv_files[k] for k, _ in interv_counts.most_common()},
    }
    outpath = os.path.join(os.path.dirname(__file__), "lane3_counts.json")
    with open(outpath, "w") as fh:
        json.dump(out, fh, indent=2)
    json.dump(out, sys.stdout, indent=2)
    print(f"\n\n# wrote {outpath}", file=sys.stderr)


if __name__ == "__main__":
    main()
