#!/usr/bin/env python3
"""
Lane 1: Parse EXTERNAL Claude Code supervisor session transcripts and quantify
manual INTERVENTIONS into the JanusMask factory pipeline, by TYPE and COUNT.

Re-runnable. Streams JSONL line-by-line (robust to malformed lines / huge files).

Usage:
    python3 lane1_parse_transcripts.py [GLOB ...] \
        [--out summary.json] [--examples N]

Default globs are the external operator-driven session dirs:
    /home/xnihil0zer0/.claude/projects/-home-xnihil0zer0-JanusMaskJR/*.jsonl
    /home/xnihil0zer0/.claude/projects/-home-xnihil0zer0/*.jsonl

It deliberately IGNORES the internal jailed-agent dirs
(*.cache-jm-cleanroom-*, *-out-*, *-replicant, TA-*) which are not interventions.
"""
import sys, os, json, glob, re, argparse, collections

DEFAULT_GLOBS = [
    "/home/xnihil0zer0/.claude/projects/-home-xnihil0zer0-JanusMaskJR/*.jsonl",
    "/home/xnihil0zer0/.claude/projects/-home-xnihil0zer0/*.jsonl",
]

# ---------------------------------------------------------------------------
# Classification rules. Order matters: first matching category wins.
# Each rule: (category, predicate(tool_name, input_dict) -> bool)
# ---------------------------------------------------------------------------

def _txt(inp):
    """Flatten the salient text of a tool input for regex matching."""
    if not isinstance(inp, dict):
        return ""
    parts = []
    for k in ("command", "file_path", "path", "old_string", "new_string",
              "content", "pattern", "query", "description"):
        v = inp.get(k)
        if isinstance(v, str):
            parts.append(v)
    return "\n".join(parts)

def _cmd(inp):
    return inp.get("command", "") if isinstance(inp, dict) else ""

def _fp(inp):
    if not isinstance(inp, dict):
        return ""
    return inp.get("file_path") or inp.get("path") or ""

# --- predicates ---

def is_daemon_control(name, inp):
    c = _cmd(inp)
    fp = _fp(inp)
    if name == "Bash":
        if re.search(r"\b(pkill|kill\b|kill -)\b.*(autowork|daemon|orchestrator)", c):
            return True
        if re.search(r"pkill\b.*(autowork|orchestrator|run-autowork)", c):
            return True
        if re.search(r"run-autowork\.sh", c):
            return True
        if re.search(r"\bkill\s+-?\d", c) and re.search(r"autowork|daemon|orchestr", c):
            return True
        # pause/resume via control files
        if re.search(r"(touch|rm)\b[^\n]*state/control/autowork/pause", c):
            return True
        if re.search(r"(touch|rm)\b[^\n]*(orchestrator\.flag|full_stop)", c):
            return True
        if re.search(r"\bnohup\b.*autowork", c):
            return True
    if name in ("Edit", "Write"):
        if re.search(r"orchestrator\.flag|state/control/autowork/pause|full_stop", fp):
            return True
    return False

def is_manual_pipeline(name, inp):
    c = _cmd(inp)
    if name != "Bash":
        return False
    return bool(re.search(
        r"(planner\.cli|stage_task|orchestrator_worker|-m\s+ngv2|python\s+-m\s+harness|"
        r"_e2e_run|run_hunt|blind_draft|collect_agent_draft|drive\.py)", c))

def is_state_cleanup(name, inp):
    c = _cmd(inp)
    fp = _fp(inp)
    pat = (r"state/output/[^\s]*\.(patches|files)\.json|state/sessions/|state/plans/|"
           r"\.processed\b|processed\b|git_commit\.lock|\.lock\b|state/output/")
    if name == "Bash":
        if re.search(r"\b(rm|mv|cp)\b", c) and re.search(pat, c):
            return True
        if re.search(r"git_commit\.lock", c):
            return True
    if name in ("Edit", "Write") and re.search(pat, fp):
        return True
    return False

def is_git_recovery(name, inp):
    c = _cmd(inp)
    if name != "Bash":
        return False
    if re.search(r"\bgit\s+(revert|reset|checkout\s+--|checkout\s+HEAD|cherry-pick|"
                 r"commit\s+--amend|reset\s+--hard|restore|stash)\b", c):
        return True
    # manual force commit of pipeline output
    if re.search(r"\bgit\s+commit\b.*-m\s*['\"].*(Integrate validated|hand-land|"
                 r"manual|revert)", c, re.I):
        return True
    return False

def is_allowlist_config(name, inp):
    fp = _fp(inp)
    c = _cmd(inp)
    pat = r"auto_promote\.allowlist|config/[\w./-]*\.yaml|allowlist|\.flag\b"
    if name in ("Edit", "Write") and re.search(pat, fp):
        # but flag/pause files already caught by daemon_control upstream
        return True
    if name == "Bash" and re.search(r"flip_autowork_flags|allowlist|config/.*\.yaml", c):
        if re.search(r"\b(echo|>>|>|sed|cat\s*>)\b", c) or "flip_autowork" in c:
            return True
    return False

def is_plan_brief(name, inp):
    c = _cmd(inp)
    fp = _fp(inp)
    if name == "Bash":
        if re.search(r"(mv|cp|rm|mkdir)\b.*(brief|_autowork_archive|state/plans|"
                     r"state/briefs|\.brief\.json|EPIC_|PROVENANCE_)", c):
            return True
        if re.search(r"_autowork_archive", c):
            return True
    if name in ("Edit", "Write"):
        if re.search(r"brief|EPIC_|PROVENANCE_|state/plans|state/briefs", fp):
            return True
    return False

def is_oracle_authoring(name, inp):
    fp = _fp(inp)
    if name in ("Write", "Edit"):
        base = os.path.basename(fp)
        if re.match(r"test_.*\.py$", base) or base.endswith("_test.py"):
            return True
    return False

def is_clobber_neutralize(name, inp):
    # Only count actual code/state/test/Bash actions, NOT .md notetaking that
    # merely mentions the word "clobber".
    fp = _fp(inp)
    if name in ("Edit", "Write") and re.search(r"\.md$", fp):
        return False
    t = _txt(inp).lower()
    if name in ("Edit", "Write", "Bash"):
        if ("clobber" in t or "neutraliz" in t or "blind worker" in t
                or "anti-seesaw" in t or "clobber-guard" in t):
            return True
    return False

# normal (non-intervention) exploration tools
EXPLORATION_TOOLS = {"Read", "Grep", "Glob", "LS", "WebFetch", "WebSearch",
                     "NotebookRead", "TodoWrite", "Task"}

# Read-only shell verbs: a Bash command whose every statement starts with one of
# these (after stripping cd-prefix / env-vars) is treated as exploration, not an
# intervention.
RO_VERBS = {
    "ls", "cat", "grep", "find", "head", "tail", "wc", "echo", "printf", "true",
    "pgrep", "ps", "stat", "file", "du", "df", "diff", "comm", "sort", "uniq",
    "awk", "cut", "tr", "jq", "tree", "which", "type", "date", "pwd", "env",
    "sleep", "timeout", "for", "while", "until", "if", "do", "done", "then",
    "fi", "set", "test", "[", "{", "(", "source", ".", "export", "read",
    "basename", "dirname", "realpath", "column", "less", "more", "nl", "tee",
    "xargs", "git",  # git is RO unless a mutating subcommand is present (handled)
    "python", "python3", "pytest",  # python invocations handled by signal scan
    "bash", "sh",
}

GIT_MUTATE = re.compile(
    r"\bgit\s+(add|commit|push|merge|rebase|tag\s|branch\s+-[dD]|"
    r"clean\b|rm\b|mv\b|init\b|remote\s+add)")

# signals that an uncategorised Bash command is still a real operation
def bash_op_signal(c):
    """Return a sub-label if this Bash command performs a mutating/run action."""
    if GIT_MUTATE.search(c):
        if re.search(r"git\s+push", c):
            return "git_push"
        return "git_mutate"
    if re.search(r"\bagy\b|--dangerously-skip-permissions", c):
        return "agy_spawn"
    if re.search(r"\b(pytest|python\s+-m\s+pytest|-m\s+pytest)\b", c):
        return "test_run"
    if re.search(r"\bnohup\b", c):
        return "background_launch"
    if re.search(r"^\s*(rm|mv|cp|mkdir|chmod|chown|ln)\b", c) or \
       re.search(r"[;&|]\s*(rm|mv|cp|mkdir|chmod)\b", c):
        return "fs_mutate"
    if re.search(r"\bpip\s+install|pip3\s+install|venv|virtualenv\b", c):
        return "env_setup"
    if re.search(r">>?\s*\S", c) and not re.search(r">\s*/dev/null|2>&1|>&2", c):
        return "file_write_redirect"
    return None

def is_readonly_bash(c):
    """True if every ;-separated statement is a read-only verb and no op-signal."""
    if bash_op_signal(c):
        return False
    # strip cd prefix
    statements = re.split(r"[;\n]|&&|\|\|", c)
    saw = False
    for st in statements:
        st = st.strip()
        if not st:
            continue
        st = re.sub(r"^cd\s+\S+\s*", "", st)
        st = re.sub(r"^\w+=\S+\s+", "", st)  # leading env var
        st = re.sub(r"^(PYTHONPATH=\S+|[A-Z_]+=\S+)\s+", "", st)
        m = re.match(r"([^\s|]+)", st)
        if not m:
            continue
        verb = os.path.basename(m.group(1))
        saw = True
        if verb not in RO_VERBS and not verb.startswith("/"):
            return False
        if verb.startswith("/") and not re.search(r"python|pytest", verb):
            return False
    return saw

RULES = [
    ("DAEMON_CONTROL", is_daemon_control),
    ("MANUAL_PIPELINE_DRIVING", is_manual_pipeline),
    ("STATE_SIDECAR_CLEANUP", is_state_cleanup),
    ("GIT_RECOVERY", is_git_recovery),
    ("CLOBBER_NEUTRALIZE", is_clobber_neutralize),
    ("ALLOWLIST_CONFIG_EDIT", is_allowlist_config),
    ("ORACLE_TEST_AUTHORING", is_oracle_authoring),
    ("PLAN_BRIEF_SHEPHERDING", is_plan_brief),
]

def classify(name, inp):
    """Return (category, is_intervention)."""
    for cat, pred in RULES:
        try:
            if pred(name, inp):
                return cat, True
        except Exception:
            continue
    if name in EXPLORATION_TOOLS:
        return "EXPLORATION_READONLY", False
    # Remaining Bash that isn't a named-category intervention
    if name == "Bash":
        c = _cmd(inp)
        sig = bash_op_signal(c)
        if sig == "git_push":
            return "GIT_PUSH", True
        if sig == "git_mutate":
            return "GIT_RECOVERY", True
        if sig == "agy_spawn":
            return "AGY_SPAWN", True
        if sig == "test_run":
            return "MANUAL_TEST_RUN", True
        if sig in ("background_launch",):
            return "DAEMON_CONTROL", True
        if sig in ("fs_mutate", "file_write_redirect", "env_setup"):
            return "OTHER_FS_OP", True
        if is_readonly_bash(c):
            return "EXPLORATION_READONLY", False
        return "OTHER_BASH", True
    # Remaining Edit/Write that aren't named-category interventions.
    if name in ("Edit", "Write", "MultiEdit", "NotebookEdit"):
        fp = _fp(inp)
        # Plan/handoff/memory markdown = operator notetaking, not factory intervention
        if re.search(r"\.md$", fp) and not re.search(r"brief|EPIC_|PROVENANCE_", fp):
            return "DOC_NOTETAKING", False
        # editing production harness/ngv2/config python = manual hand-edit
        if re.search(r"\.(py|yaml|yml|json|toml|sh|cfg)$", fp):
            return "MANUAL_PRODUCTION_EDIT", True
        return "OTHER_EDIT", True
    return "OTHER", False

def repr_command(name, inp, maxlen=200):
    if name == "Bash":
        s = _cmd(inp)
    elif name in ("Edit", "Write", "MultiEdit", "NotebookEdit"):
        s = "%s %s" % (name, _fp(inp))
    else:
        s = "%s %s" % (name, _txt(inp)[:120])
    s = " ".join(s.split())
    return s[:maxlen]

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("globs", nargs="*", default=DEFAULT_GLOBS)
    ap.add_argument("--out", default=os.path.join(os.path.dirname(__file__),
                                                  "lane1_summary.json"))
    ap.add_argument("--examples", type=int, default=12)
    args = ap.parse_args()
    globs = args.globs if args.globs else DEFAULT_GLOBS

    files = []
    for g in globs:
        files.extend(sorted(glob.glob(g)))
    # exclude internal jailed-agent dirs defensively
    files = [f for f in files if not re.search(
        r"cache-jm-cleanroom|-out-|-replicant|/TA-", f)]

    cat_counts = collections.Counter()
    cat_examples = collections.defaultdict(collections.Counter)  # cat -> cmd -> n
    tool_counts = collections.Counter()
    total_tool_use = 0
    sessions = set()
    bad_lines = 0
    # per-session-date timeline: date -> {interventions, total_tool}
    date_stats = collections.defaultdict(lambda: {"interventions": 0, "tool_use": 0})
    raw_other = collections.Counter()  # for OTHER_BASH top commands
    ngv2_interventions = collections.Counter()  # category -> n where NGv2 touched

    for path in files:
        sid = os.path.splitext(os.path.basename(path))[0]
        sessions.add(sid)
        try:
            fh = open(path, "r", errors="replace")
        except Exception:
            continue
        with fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except Exception:
                    bad_lines += 1
                    continue
                if obj.get("type") != "assistant":
                    continue
                msg = obj.get("message")
                if not isinstance(msg, dict):
                    continue
                ts = obj.get("timestamp", "")
                date = ts[:10] if isinstance(ts, str) else ""
                for c in msg.get("content", []):
                    if not isinstance(c, dict) or c.get("type") != "tool_use":
                        continue
                    name = c.get("name", "?")
                    inp = c.get("input", {})
                    total_tool_use += 1
                    tool_counts[name] += 1
                    cat, is_int = classify(name, inp)
                    cat_counts[cat] += 1
                    rc = repr_command(name, inp)
                    cat_examples[cat][rc] += 1
                    if cat in ("OTHER_BASH", "OTHER_EDIT", "OTHER_FS_OP"):
                        raw_other[rc] += 1
                    if is_int and re.search(r"ngv2|NobleGreedv2|nobel|NobleGreed",
                                            _txt(inp), re.I):
                        ngv2_interventions[cat] += 1
                    if date:
                        date_stats[date]["tool_use"] += 1
                        if is_int:
                            date_stats[date]["interventions"] += 1

    NON_INTERVENTION = {"EXPLORATION_READONLY", "DOC_NOTETAKING", "OTHER"}
    total_interventions = sum(n for c, n in cat_counts.items()
                              if c not in NON_INTERVENTION)
    total_exploration = (cat_counts.get("EXPLORATION_READONLY", 0)
                         + cat_counts.get("DOC_NOTETAKING", 0))

    summary = {
        "files_analyzed": len(files),
        "sessions": len(sessions),
        "malformed_lines_skipped": bad_lines,
        "total_tool_use": total_tool_use,
        "total_interventions": total_interventions,
        "total_exploration_readonly": total_exploration,
        "intervention_pct": round(100.0 * total_interventions / total_tool_use, 2)
                            if total_tool_use else 0,
        "category_counts": dict(cat_counts.most_common()),
        "tool_counts": dict(tool_counts.most_common()),
        "examples_by_category": {
            cat: [{"cmd": cmd, "n": n}
                  for cmd, n in cat_examples[cat].most_common(args.examples)]
            for cat in cat_counts
        },
        "top_other_raw": [{"cmd": c, "n": n} for c, n in raw_other.most_common(30)],
        "ngv2_touching_interventions": dict(ngv2_interventions.most_common()),
        "ngv2_intervention_total": sum(ngv2_interventions.values()),
        "timeline": {d: date_stats[d] for d in sorted(date_stats)},
    }

    with open(args.out, "w") as f:
        json.dump(summary, f, indent=2)

    # console digest
    print("files=%d sessions=%d tool_use=%d interventions=%d (%.1f%%) bad=%d" % (
        len(files), len(sessions), total_tool_use, total_interventions,
        summary["intervention_pct"], bad_lines))
    print("--- categories ---")
    for cat, n in cat_counts.most_common():
        print("  %-26s %6d" % (cat, n))
    print("wrote", args.out)

if __name__ == "__main__":
    main()
