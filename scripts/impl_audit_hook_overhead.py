#!/usr/bin/env python3
"""Audit the JanusMask hook/meta-hook overhead.

Parses .claude/settings.local.json, walks every scripts/impl_*.{py,sh},
benchmarks each hook with a benign input, estimates injected-context token
cost, and surfaces accreted scope_exception scripts. Output is both
human-readable (stdout) and JSON (--json or implicit dump alongside).

Safe to run repeatedly: never writes the ledger, never appends rows, never
mutates settings. Reads only.

Usage:
    python3 scripts/impl_audit_hook_overhead.py
    python3 scripts/impl_audit_hook_overhead.py --json /tmp/audit.json
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import os
import pathlib
import re
import subprocess
import sys
import time
from collections import Counter, defaultdict


PROJECT_DIR = pathlib.Path(__file__).resolve().parent.parent
SCRIPTS_DIR = PROJECT_DIR / "scripts"
LEDGER_PATH = PROJECT_DIR / "state" / "impl_progress.jsonl"
SETTINGS_FILES = [
    PROJECT_DIR / ".claude" / "settings.local.json",
    PROJECT_DIR / ".claude" / "settings.json",
]

# Hook scripts that are safe to dry-run with empty stdin (idempotent /
# read-only). Anything that appends ledger rows or mutates state is
# excluded; we measure import-load cost only.
BENCH_SAFE = {
    "impl_pre_write.py",
    "impl_pre_bash.py",
    "impl_pre_compact.py",
    "impl_stop_gate.py",
    "impl_context_emit.py",
    "impl_session_start.sh",
    "impl_prompt_context.sh",
    # impl_post_write.py would append a "write" row — skip live timing.
}


def _read_text(p: pathlib.Path) -> str:
    try:
        return p.read_text(encoding="utf-8")
    except OSError:
        return ""


def _content_hash(p: pathlib.Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()[:16]


def _count_external_calls(src: str) -> dict:
    """Tally subprocess + filesystem + network touchpoints in a script.

    Heuristic regex pass — fast enough to run over the whole scripts/ tree.
    """
    return {
        "subprocess": len(re.findall(r"\bsubprocess\.(?:run|Popen|check_output|call)\b", src)),
        "os_system": len(re.findall(r"\bos\.system\b", src)),
        "open_calls": len(re.findall(r"\bopen\s*\(", src))
        + len(re.findall(r"\.read_text\s*\(", src))
        + len(re.findall(r"\.write_text\s*\(", src))
        + len(re.findall(r"\.read_bytes\s*\(", src)),
        "pathlib_glob": len(re.findall(r"\.glob\s*\(", src))
        + len(re.findall(r"\.rglob\s*\(", src)),
        "ledger_load": len(re.findall(r"\bload_ledger\s*\(", src)),
        "ledger_append": len(re.findall(r"\bappend_impl_progress_event\b", src))
        + len(re.findall(r"\bwrite_jsonl_row\b", src)),
    }


def _bench_script(p: pathlib.Path) -> dict:
    """Run a script once with empty-ish stdin; record wall-clock time."""
    if p.name not in BENCH_SAFE:
        return {"skipped": True, "reason": "not in BENCH_SAFE"}
    # Pick a benign stdin per known shape.
    stdin = "{}"
    args: list[str] = []
    if p.name == "impl_context_emit.py":
        args = ["prompt"]
    elif p.name == "impl_pre_write.py":
        stdin = json.dumps({
            "tool_name": "Write",
            "tool_input": {"file_path": "/tmp/_audit_probe.py", "content": "x=1\n"},
        })
    elif p.name == "impl_pre_bash.py":
        stdin = json.dumps({"tool_input": {"command": "ls -la"}})
    cmd: list[str]
    if p.suffix == ".sh":
        cmd = ["bash", str(p)] + args
    else:
        cmd = [sys.executable, str(p)] + args
    runs = []
    env = dict(os.environ)
    env.setdefault("CLAUDE_PROJECT_DIR", str(PROJECT_DIR))
    for _ in range(3):
        t0 = time.perf_counter()
        try:
            proc = subprocess.run(
                cmd,
                input=stdin,
                text=True,
                capture_output=True,
                timeout=30,
                cwd=str(PROJECT_DIR),
                env=env,
            )
            rc = proc.returncode
            err = (proc.stderr or "")[-200:]
        except (OSError, subprocess.TimeoutExpired) as e:
            rc = -1
            err = repr(e)
        runs.append({"elapsed_ms": (time.perf_counter() - t0) * 1000, "rc": rc, "stderr_tail": err})
    return {
        "skipped": False,
        "runs": runs,
        "median_ms": sorted(r["elapsed_ms"] for r in runs)[len(runs) // 2],
    }


def _classify_suffix(name: str) -> str:
    """Bucket impl_* script names by purpose suffix (heuristic)."""
    for suf in (
        "_scope_exception",
        "_scope_exceptions",
        "_unblock",
        "_carve_out",
        "_temp",
        "_fix",
        "_handler_test_fixes",
        "_blocker9_fix",
    ):
        if name.endswith(suf + ".py") or name.endswith(suf + ".sh"):
            return suf
    # Core / persistent hook scripts.
    core_set = {
        "impl_common.py",
        "impl_context_emit.py",
        "impl_pre_write.py",
        "impl_pre_bash.py",
        "impl_post_write.py",
        "impl_pre_compact.py",
        "impl_stop_gate.py",
        "impl_phase_gate.py",
        "impl_session_start.sh",
        "impl_prompt_context.sh",
        "impl_dispatch_once.sh",
        "impl_drain_capture.py",
        "impl_outbox_watcher.py",
        "impl_plan_to_queue.py",
        "impl_normalize_priority.py",
        "impl_retry_drain.py",
        "impl_audit_scope_exceptions.py",
    }
    if name in core_set:
        return "_core"
    return "_other"


def _parse_hooks(settings_path: pathlib.Path) -> list[dict]:
    """Return [{event, matcher, command, timeout, script_basename}]."""
    if not settings_path.exists():
        return []
    try:
        data = json.loads(settings_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        return [{"_parse_error": str(e), "_file": str(settings_path)}]
    out: list[dict] = []
    hooks = data.get("hooks") or {}
    for event, blocks in hooks.items():
        if not isinstance(blocks, list):
            continue
        for block in blocks:
            matcher = block.get("matcher", "")
            for h in block.get("hooks", []) or []:
                cmd = h.get("command", "")
                # Try to identify the underlying script basename.
                m = re.search(r"impl_[a-z0-9_]+\.(?:py|sh)", cmd)
                script = m.group(0) if m else None
                out.append({
                    "event": event,
                    "matcher": matcher,
                    "command": cmd,
                    "timeout": h.get("timeout"),
                    "script": script,
                })
    return out


def _ledger_stats() -> dict:
    if not LEDGER_PATH.exists():
        return {"present": False}
    raw = LEDGER_PATH.read_text(encoding="utf-8", errors="replace")
    lines = [l for l in raw.splitlines() if l.strip()]
    events = Counter()
    for l in lines:
        try:
            r = json.loads(l)
        except json.JSONDecodeError:
            continue
        ev = r.get("event") or "<unknown>"
        events[ev] += 1
    return {
        "present": True,
        "size_bytes": len(raw),
        "row_count": len(lines),
        "events_top10": dict(events.most_common(10)),
        "scope_exception_rows": events.get("scope_exception", 0),
        "scope_revoke_rows": events.get("scope_revoke", 0),
    }


def _context_block_cost() -> dict:
    """Run the two emitter modes and measure char/token estimate."""
    out: dict = {}
    emit_script = SCRIPTS_DIR / "impl_context_emit.py"
    env = dict(os.environ)
    env.setdefault("CLAUDE_PROJECT_DIR", str(PROJECT_DIR))
    for mode in ("session_start", "prompt"):
        try:
            proc = subprocess.run(
                [sys.executable, str(emit_script), mode],
                input="{}", text=True, capture_output=True, timeout=10,
                cwd=str(PROJECT_DIR), env=env,
            )
            stdout = proc.stdout
        except (OSError, subprocess.TimeoutExpired) as e:
            stdout = f"<emit failed: {e}>\n"
        chars = len(stdout)
        out[mode] = {
            "chars": chars,
            "tokens_approx": chars // 4,
            "lines": stdout.count("\n"),
            "first_200_chars": stdout[:200],
        }
    return out


def _settings_dead_keys(hook_entries: list[dict]) -> dict:
    """Cross-check settings permissions vs. anything hooks actually read.

    The PreToolUse hooks only consult ledger + on-disk paths; they do NOT
    consult settings.permissions.allow. The list there is purely a
    permission-prompt allowlist consumed by Claude Code's own permission
    layer — it never reaches our hook scripts. We surface this so the
    operator can prune entries that no longer match real usage.
    """
    perms: list[str] = []
    for sp in SETTINGS_FILES:
        if not sp.exists():
            continue
        try:
            data = json.loads(sp.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        perms.extend((data.get("permissions") or {}).get("allow") or [])
    # Sanity: which perm strings reference tools we actually saw used in
    # recent ledger or hook scripts? We do a very loose grep here.
    repo_blob_paths = list(SCRIPTS_DIR.glob("impl_*.py")) + list(SCRIPTS_DIR.glob("impl_*.sh"))
    repo_blob = "\n".join(_read_text(p) for p in repo_blob_paths)
    # Plus the ledger tail (last 500 rows of detail strings).
    ledger_tail = ""
    if LEDGER_PATH.exists():
        ledger_tail = "\n".join(LEDGER_PATH.read_text(encoding="utf-8", errors="replace").splitlines()[-500:])
    referenced = []
    unreferenced = []
    for p in perms:
        token = p
        # Pull a useful substring from forms like "WebFetch(domain:foo)".
        m = re.match(r"^[A-Za-z_]+\(.*?:(.+?)\)$", p)
        if m:
            token = m.group(1)
        # Just check whether the token appears anywhere in repo / ledger.
        if token in repo_blob or token in ledger_tail:
            referenced.append(p)
        else:
            unreferenced.append(p)
    return {
        "total_perms": len(perms),
        "referenced_in_repo_or_ledger": len(referenced),
        "unreferenced_count": len(unreferenced),
        "unreferenced": unreferenced,
        "hook_scripts_in_settings": [h.get("script") for h in hook_entries if h.get("script")],
    }


def _expected_base_sha_status() -> dict:
    """Is impl_common.EXPECTED_BASE_SHA still pinned to a current SHA?

    A stale pin means every SessionStart + UserPromptSubmit prompt carries
    a "DRIFT; acknowledge via scope_exception row" string that is purely
    noise.
    """
    common_src = _read_text(SCRIPTS_DIR / "impl_common.py")
    m = re.search(r'EXPECTED_BASE_SHA\s*=\s*"([a-f0-9]+)"', common_src)
    pinned = m.group(1) if m else None
    try:
        head = subprocess.run(
            ["git", "-C", str(PROJECT_DIR), "rev-parse", "HEAD"],
            capture_output=True, text=True, timeout=5,
        ).stdout.strip()
    except (OSError, subprocess.TimeoutExpired):
        head = ""
    return {
        "pinned": pinned,
        "current_head": head,
        "drift": bool(pinned and head and not head.startswith(pinned)),
    }


def _inventory_impl_scripts() -> dict:
    rows: list[dict] = []
    by_suffix: dict[str, list[str]] = defaultdict(list)
    by_hash: dict[str, list[str]] = defaultdict(list)
    paths = sorted(
        list(SCRIPTS_DIR.glob("impl_*.py")) + list(SCRIPTS_DIR.glob("impl_*.sh"))
    )
    for p in paths:
        src = _read_text(p)
        suffix = _classify_suffix(p.name)
        h = _content_hash(p)
        loc = len([l for l in src.splitlines() if l.strip() and not l.strip().startswith("#")])
        # Is this script registered in any settings hook?
        is_wired = False  # filled in by caller
        ext = _count_external_calls(src)
        bench = _bench_script(p)
        rows.append({
            "name": p.name,
            "loc_nonblank_noncomment": loc,
            "raw_lines": len(src.splitlines()),
            "bytes": len(src),
            "sha256_16": h,
            "suffix_bucket": suffix,
            "external_calls": ext,
            "bench": bench,
            "wired_in_settings": is_wired,
            "mtime": int(p.stat().st_mtime),
        })
        by_suffix[suffix].append(p.name)
        by_hash[h].append(p.name)
    # Duplicates: identical content under different names.
    dupes = {h: names for h, names in by_hash.items() if len(names) > 1}
    # "Trivial stub" detection: any non-core script with <= 4 raw lines is a
    # ledger-fingerprint or comment-only file (the working tree has several).
    trivial: list[dict] = []
    for r in rows:
        if r["suffix_bucket"] != "_core" and r["raw_lines"] <= 4:
            trivial.append({"name": r["name"], "raw_lines": r["raw_lines"], "bytes": r["bytes"]})
    return {
        "by_suffix_counts": {k: len(v) for k, v in by_suffix.items()},
        "by_suffix_names": {k: v for k, v in by_suffix.items()},
        "duplicate_content": dupes,
        "trivial_stub_scripts": trivial,
        "scripts": rows,
    }


def _hook_chain_analysis(hook_entries: list[dict]) -> dict:
    """Identify which hooks call into which, and the chain depth."""
    chains: dict[str, list[str]] = {}
    for h in hook_entries:
        script = h.get("script")
        if not script:
            continue
        target = SCRIPTS_DIR / script
        if not target.exists():
            continue
        src = _read_text(target)
        # Look for invocations of other impl_*.py via exec/subprocess.
        called = sorted(set(re.findall(r"impl_[a-z0-9_]+\.(?:py|sh)", src)))
        called = [c for c in called if c != script]
        chains[script] = called
    return chains


def render_summary(report: dict) -> str:
    lines: list[str] = []
    lines.append("=" * 72)
    lines.append("JanusMask hook-overhead audit summary")
    lines.append("=" * 72)
    # Settings hooks
    lines.append("")
    lines.append(f"Settings file inspected: {report['settings_files_seen']}")
    lines.append(f"Registered hook entries: {len(report['hook_entries'])}")
    for h in report["hook_entries"]:
        lines.append(
            f"  {h.get('event'):<16} matcher={h.get('matcher'):<22}"
            f" timeout={h.get('timeout')} -> {h.get('script')}"
        )
    # Ledger
    lines.append("")
    ls = report["ledger_stats"]
    if ls.get("present"):
        lines.append(
            f"Ledger: {ls['row_count']} rows, {ls['size_bytes']/1024:.1f} KiB; "
            f"SE={ls['scope_exception_rows']}, REVOKE={ls['scope_revoke_rows']}"
        )
        lines.append(f"  top events: {ls['events_top10']}")
    # Context cost
    lines.append("")
    cc = report["context_cost"]
    lines.append("Injected meta-hook context per turn:")
    for mode in ("session_start", "prompt"):
        c = cc.get(mode, {})
        lines.append(
            f"  {mode:<14} {c.get('chars',0):>5} chars  "
            f"~{c.get('tokens_approx',0):>4} tokens  ({c.get('lines',0)} lines)"
        )
    # Drift
    d = report["base_sha_status"]
    lines.append("")
    lines.append(
        f"EXPECTED_BASE_SHA pinned to {d.get('pinned')!r}; current HEAD "
        f"{d.get('current_head','')[:12]}; DRIFT={d.get('drift')}"
    )
    if d.get("drift"):
        lines.append(
            "  -> every SessionStart + UserPromptSubmit emits a DRIFT warning;"
            " stale pin is noise."
        )
    # Inventory
    inv = report["inventory"]
    lines.append("")
    lines.append("impl_*.{py,sh} inventory by suffix bucket:")
    for bucket, n in sorted(inv["by_suffix_counts"].items(), key=lambda kv: -kv[1]):
        lines.append(f"  {bucket:<22} {n}")
        for name in inv["by_suffix_names"][bucket]:
            lines.append(f"    - {name}")
    if inv["duplicate_content"]:
        lines.append("")
        lines.append("Identical-content scripts (sha256 collision):")
        for h, names in inv["duplicate_content"].items():
            lines.append(f"  {h}: {names}")
    if inv["trivial_stub_scripts"]:
        lines.append("")
        lines.append("Trivial stub scripts (<=4 raw lines, non-core):")
        for s in inv["trivial_stub_scripts"]:
            lines.append(f"  - {s['name']} ({s['raw_lines']} lines, {s['bytes']} B)")
    # Bench: only the wired hooks
    lines.append("")
    lines.append("Wired-hook runtime (median of 3 runs, ms):")
    wired_scripts = {h["script"] for h in report["hook_entries"] if h.get("script")}
    for r in inv["scripts"]:
        if r["name"] not in wired_scripts:
            continue
        b = r["bench"] or {}
        if b.get("skipped"):
            lines.append(f"  {r['name']:<32} SKIPPED ({b.get('reason')})")
        else:
            lines.append(f"  {r['name']:<32} {b.get('median_ms', 0):>6.1f} ms")
    # Chain
    if report["hook_chains"]:
        lines.append("")
        lines.append("Hook-script call graph (which impl_*.py invokes which):")
        for src, targets in report["hook_chains"].items():
            if not targets:
                continue
            lines.append(f"  {src} -> {targets}")
    # Permissions
    sk = report["settings_dead_keys"]
    lines.append("")
    lines.append(
        f"Settings permissions.allow: {sk['total_perms']} entries; "
        f"{sk['unreferenced_count']} unreferenced in repo+ledger tail"
    )
    if sk["unreferenced_count"]:
        for p in sk["unreferenced"]:
            lines.append(f"  - {p}")
    return "\n".join(lines) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", default="", help="optional path to write the full JSON report")
    args = ap.parse_args()

    hook_entries: list[dict] = []
    settings_seen: list[str] = []
    for sp in SETTINGS_FILES:
        if sp.exists():
            settings_seen.append(str(sp.relative_to(PROJECT_DIR)))
            hook_entries.extend(_parse_hooks(sp))

    inv = _inventory_impl_scripts()
    wired = {h.get("script") for h in hook_entries if h.get("script")}
    for r in inv["scripts"]:
        r["wired_in_settings"] = r["name"] in wired

    report = {
        "schema_version": 1,
        "project_dir": str(PROJECT_DIR),
        "settings_files_seen": settings_seen,
        "hook_entries": hook_entries,
        "hook_chains": _hook_chain_analysis(hook_entries),
        "ledger_stats": _ledger_stats(),
        "context_cost": _context_block_cost(),
        "base_sha_status": _expected_base_sha_status(),
        "inventory": inv,
        "settings_dead_keys": _settings_dead_keys(hook_entries),
    }

    summary = render_summary(report)
    sys.stdout.write(summary)
    if args.json:
        pathlib.Path(args.json).write_text(json.dumps(report, indent=2), encoding="utf-8")
        sys.stdout.write(f"\nJSON report: {args.json}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
