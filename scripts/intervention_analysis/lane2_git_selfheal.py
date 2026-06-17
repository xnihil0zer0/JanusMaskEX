#!/usr/bin/env python3
"""Lane 2 forensic analysis: quantify manual interventions in the JanusMask
factory pipeline from git history + runtime state ledgers.

Re-runnable. Emits JSON counts to stdout and to
scripts/intervention_analysis/lane2_results.json.

Usage: python3 scripts/intervention_analysis/lane2_git_selfheal.py
"""
import json
import os
import re
import subprocess
import sys
from collections import Counter, defaultdict
from datetime import datetime

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
STATE = os.path.join(REPO, "state", "control", "autowork")

# ---------------------------------------------------------------------------
# Commit classification
# ---------------------------------------------------------------------------
# Order matters: first matching rule wins. AUTOMATED rules are checked first
# only where unambiguous; intervention rules take precedence when they overlap.

# (label, kind, regex) -- kind in {"auto", "intervention"}
RULES = [
    # ---- AUTOMATED pipeline output: highest precedence. An "Integrate validated
    #      code" commit means the full dual-agent pipeline ran & passed, even if
    #      the PAYLOAD slug is a fix/wire-up. Classify as auto; the fix-payload
    #      subset is tracked separately below. ----
    ("Integrate validated code", "auto", r"^Integrate validated code"),
    # ---- MANUAL INTERVENTION classes (checked before generic auto) ----
    ("revert/undo", "intervention", r"\b(revert|undo|reverse|reversed|roll ?back|rolled back|un-?land)\b"),
    ("owner hand-edit", "intervention", r"\b(owner )?hand[- ]?(edit|land|author|apply|appl)"),
    ("manual drive", "intervention", r"\bmanual[- ]?(drive|driv|pipeline|land)"),
    ("clobber neutralize/guard", "intervention", r"\bclobber\b|neutrali[sz]e|anti-?clobber|anti-?seesaw|seesaw|time ?bomb"),
    ("declutter/archive sweep", "intervention", r"\b(declutter|archive|retire|prune|sweep|stale|cleanup|clean up|tidy|housekeep)"),
    ("config/flag flip", "intervention", r"\b(flag|config|posture|enable|disable|default-?on|default-?off|flip|toggle|allowlist|pin)\b"),
    ("blocker/deadlock unblock", "intervention", r"\b(unblock|deadlock|blocked|wedge|stuck|blocker|fail-?clos)"),
    ("bugfix/defect", "intervention", r"\b(bugfix|fix|defect|root-?cause|root cause|repair|patch|correct|hotfix)\b"),
    ("wire-up/orphan", "intervention", r"\bwire[- ]?up|wire_up|orphan|unwired|re-?wire"),
    # ---- AUTOMATED pipeline output (remaining) ----
    ("RED oracle", "auto", r"\bRED oracle|RED wiring|RED oracles"),
    ("Test/oracle commit", "auto", r"^(test|Test|Add oracle|Add test|Track test|Track tests|Track generated|Track smoke|Track run_pytest)"),
    # oracle / brief authoring scaffolding (hand-written contracts, but not a
    # pipeline integration and not a remediation of a broken pipeline)
    ("oracle/brief authoring", "auto", r"^(Oracle:|brief\d|brief_|.*: oracle \(RED|phase2\(|Add brief|Tighten .*brief|.*: oracle$|.*oracle \(RED on HEAD\))"),
    ("skeleton/scaffold", "auto", r"^(skeleton|scaffold|stub)"),
    ("docs/README", "auto", r"^(docs|README|doc:)"),
]

COMPILED = [(label, kind, re.compile(rx, re.IGNORECASE)) for (label, kind, rx) in RULES]


def classify(subject, body):
    text = subject + "\n" + (body or "")
    for label, kind, rx in COMPILED:
        if rx.search(text):
            return label, kind
    return "other/unclassified", "auto"


def get_commits():
    # NUL-delimited records, TAB-separated fields, body last (may contain newlines)
    fmt = "%H%x09%ai%x09%s%x09%b%x1e"
    out = subprocess.check_output(
        ["git", "-C", REPO, "log", "--format=" + fmt], text=True
    )
    commits = []
    for rec in out.split("\x1e"):
        rec = rec.strip("\n")
        if not rec:
            continue
        parts = rec.split("\t", 3)
        if len(parts) < 3:
            continue
        sha, date, subject = parts[0], parts[1], parts[2]
        body = parts[3] if len(parts) > 3 else ""
        commits.append({"sha": sha, "date": date, "subject": subject, "body": body})
    return commits


def analyze_commits():
    commits = get_commits()
    label_counts = Counter()
    kind_counts = Counter()
    by_day = defaultdict(lambda: {"auto": 0, "intervention": 0})
    examples = defaultdict(list)
    REMEDIATION_PAYLOAD = re.compile(r"fix|clobber|wire|unblock|orphan|guard|repair|defect|deadlock", re.I)
    auto_remediation_payload = 0  # auto-integrations whose SLUG is remediation work
    for c in commits:
        label, kind = classify(c["subject"], c["body"])
        label_counts[label] += 1
        kind_counts[kind] += 1
        if label == "Integrate validated code" and REMEDIATION_PAYLOAD.search(c["subject"]):
            auto_remediation_payload += 1
        day = c["date"][:10]
        by_day[day][kind] += 1
        if len(examples[label]) < 3:
            examples[label].append(c["subject"][:90])
    total = len(commits)
    return {
        "total_commits": total,
        "kind_counts": dict(kind_counts),
        "intervention_pct": round(100.0 * kind_counts["intervention"] / total, 1) if total else 0,
        "auto_integrate_remediation_payload": auto_remediation_payload,
        "label_counts": dict(label_counts.most_common()),
        "examples": dict(examples),
        "by_day": {d: by_day[d] for d in sorted(by_day)},
    }


# ---------------------------------------------------------------------------
# Self-healing history
# ---------------------------------------------------------------------------
def analyze_selfheal():
    path = os.path.join(STATE, "self_healing_history.jsonl")
    if not os.path.exists(path):
        return {"error": "no self_healing_history.jsonl"}
    outcomes = Counter()
    files = Counter()
    by_task = defaultdict(list)
    rows = 0
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            rows += 1
            outcomes[rec.get("outcome", "?")] += 1
            for ft in rec.get("files_touched", []) or []:
                files[ft] += 1
            by_task[rec.get("task_id", "?")].append(rec.get("outcome", "?"))
    # retry chains: tasks that appear more than once (heal attempts)
    retried = {t: seq for t, seq in by_task.items() if len(seq) > 1}
    return {
        "events": rows,
        "outcome_counts": dict(outcomes.most_common()),
        "top_files_touched": dict(files.most_common(15)),
        "distinct_tasks": len(by_task),
        "retried_tasks": len(retried),
        "retried_examples": {t: seq for t, seq in list(retried.items())[:10]},
    }


# ---------------------------------------------------------------------------
# Allowlist churn
# ---------------------------------------------------------------------------
def _read_entries(path):
    ents = set()
    try:
        with open(path) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#"):
                    ents.add(line)
    except OSError:
        pass
    return ents


def analyze_allowlist():
    files = []
    for fn in os.listdir(STATE):
        if fn.startswith("auto_promote.allowlist"):
            files.append(os.path.join(STATE, fn))
    all_entries = set()
    per_file = {}
    for p in files:
        ents = _read_entries(p)
        per_file[os.path.basename(p)] = sorted(ents)
        all_entries |= ents
    current = _read_entries(os.path.join(STATE, "auto_promote.allowlist"))
    return {
        "snapshot_files": len(files),
        "distinct_entries_ever": len(all_entries),
        "current_active_entries": len(current),
        "entries_ever": sorted(all_entries),
        "per_snapshot_counts": {k: len(v) for k, v in per_file.items()},
    }


# ---------------------------------------------------------------------------
# Quarantine / plan_attempts / selfheal_skip
# ---------------------------------------------------------------------------
def analyze_blocker_dirs():
    res = {}
    for sub in ("quarantine", "selfheal_skip", "plan_attempts", "selfheal_provenance"):
        d = os.path.join(STATE, sub)
        if os.path.isdir(d):
            res[sub] = {"count": len(os.listdir(d)), "names": sorted(os.listdir(d))[:40]}
        else:
            res[sub] = {"count": 0, "names": []}
    # parse plan_attempts contents for failure reasons
    pa = os.path.join(STATE, "plan_attempts")
    reasons = Counter()
    attempt_counts = []
    if os.path.isdir(pa):
        for fn in os.listdir(pa):
            try:
                with open(os.path.join(pa, fn)) as f:
                    data = json.load(f)
            except Exception:
                continue
            if isinstance(data, dict):
                n = data.get("attempts") or data.get("count")
                if isinstance(n, int):
                    attempt_counts.append((fn, n))
                for key in ("reason", "last_reason", "blocker", "status", "outcome"):
                    if key in data:
                        reasons[str(data[key])[:60]] += 1
            elif isinstance(data, list):
                attempt_counts.append((fn, len(data)))
    res["plan_attempt_reasons"] = dict(reasons.most_common(20))
    res["plan_attempt_counts"] = sorted(attempt_counts, key=lambda x: -x[1])[:20]
    return res


def main():
    result = {
        "generated": datetime.now().isoformat(),
        "commits": analyze_commits(),
        "selfheal": analyze_selfheal(),
        "allowlist": analyze_allowlist(),
        "blocker_dirs": analyze_blocker_dirs(),
    }
    out_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "lane2_results.json")
    with open(out_path, "w") as f:
        json.dump(result, f, indent=2)
    print(json.dumps(result, indent=2))
    print("\n# written to", out_path, file=sys.stderr)


if __name__ == "__main__":
    main()
