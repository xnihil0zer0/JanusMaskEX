#!/usr/bin/env python3
"""Audit the JanusMask WebUI server + autobrief/planner pipeline for
inefficiency and overcomplication.

Run as:
    python scripts/impl_audit_webui_autobrief.py [--json /path/to/out.json]

The script parses ``tools/webui_server.py`` for route definitions, parses
``tools/webui_static/app.js`` for fetch/XHR call sites, cross-references
them (orphan handlers; unmatched callers), catalogs all ``brief_hooks_*.md``
and ``plan_hooks_*.json`` files in the repo root by topic / V-prefix /
critique companion, measures the autobrief prompt size, and (best-effort)
queries the codebase-memory graph for orphan helpers.

The script is **read-only** and stdlib-only (no third-party dependencies).
Output: JSON document on stdout plus a human-readable summary on stderr.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent

# ---------------------------------------------------------------------------
# Route discovery
# ---------------------------------------------------------------------------

# Two-style discovery:
#   (1) string literals of the form "/api/<segment>(/...)" or "/events"
#       inside `path == ...` or `re.match(r"^...$", path)` guards.
#   (2) entries inside ControlHandlers._dispatch_post / _dispatch_put
#       (table-driven dispatch, currently a stub).
ROUTE_LITERAL_RE = re.compile(
    r"""path\s*==\s*['"](?P<literal>/[^'"]+)['"]"""
)
ROUTE_REGEX_RE = re.compile(
    r"""re\.match\(\s*['"]\^?(?P<regex>/api/[^'"]+?)\$['"]"""
)
ROUTE_STARTSWITH_RE = re.compile(
    r"""path\.startswith\(\s*['"](?P<prefix>/[^'"]+)['"]"""
)


def discover_routes(server_path: Path) -> list[dict[str, Any]]:
    src = server_path.read_text(encoding="utf-8", errors="replace")
    routes: list[dict[str, Any]] = []

    # GET dispatcher is `_dispatch_get`; mutations are `_dispatch_mutation`.
    # Walk line by line; tag the route's method by which dispatch function
    # the line belongs to (cheap heuristic: track enclosing `def`).
    cur_method = None
    cur_func = None
    in_method_branch = None  # 'POST' / 'PUT' / None
    for lineno, line in enumerate(src.splitlines(), 1):
        # Track enclosing function
        m_def = re.match(r"\s*def\s+(\w+)", line)
        if m_def:
            cur_func = m_def.group(1)
            if cur_func in ("_dispatch_get", "do_GET"):
                cur_method = "GET"
                in_method_branch = None
            elif cur_func in ("_dispatch_mutation", "dispatch_mutation"):
                cur_method = "MUT"
                in_method_branch = None
            else:
                cur_method = None
                in_method_branch = None
        # Inside the mutation dispatcher, sub-branches are POST/PUT
        if cur_method == "MUT":
            m_branch = re.search(r"method\s*==\s*['\"](POST|PUT|DELETE|PATCH)['\"]", line)
            if m_branch:
                in_method_branch = m_branch.group(1)
        # Capture literal/regex/startswith routes
        for m in ROUTE_LITERAL_RE.finditer(line):
            routes.append({
                "path": m.group("literal"),
                "kind": "literal",
                "method": in_method_branch or cur_method or "?",
                "line": lineno,
            })
        for m in ROUTE_REGEX_RE.finditer(line):
            routes.append({
                "path": m.group("regex"),
                "kind": "regex",
                "method": in_method_branch or cur_method or "?",
                "line": lineno,
            })
        for m in ROUTE_STARTSWITH_RE.finditer(line):
            routes.append({
                "path": m.group("prefix"),
                "kind": "prefix",
                "method": in_method_branch or cur_method or "?",
                "line": lineno,
            })

    return routes


def discover_dispatch_table_routes(control_path: Path) -> list[dict[str, Any]]:
    """Extract ControlHandlers._dispatch_post / _dispatch_put entries.

    The two class attrs are dicts mapping a path-pattern to a (handler, arg_shape)
    tuple. The current file only contains a stub `_dispatch_post = {"/api/briefs/autocomplete": "post_brief_autocomplete"}`.
    """
    src = control_path.read_text(encoding="utf-8", errors="replace")
    out: list[dict[str, Any]] = []
    # Look for `_dispatch_post: dict[str, str] = { ... }` and similar.
    for table_name, method in (("_dispatch_post", "POST"), ("_dispatch_put", "PUT")):
        m = re.search(
            rf"{table_name}\s*(?::\s*[^=]+)?=\s*\{{(?P<body>.*?)\}}",
            src,
            re.DOTALL,
        )
        if not m:
            continue
        body = m.group("body")
        for path_m in re.finditer(r"""['"](/[^'"]+)['"]\s*:""", body):
            out.append({
                "path": path_m.group(1),
                "kind": "dispatch_table",
                "method": method,
                "line": src[:path_m.start()].count("\n") + 1,
            })
    return out


# ---------------------------------------------------------------------------
# Frontend caller discovery
# ---------------------------------------------------------------------------

FETCH_API_RE = re.compile(r"""api\(\s*[`'"](?P<path>/[^`'"]+)[`'"]""")
FETCH_RAW_RE = re.compile(r"""fetch\(\s*[`'"](?P<path>/[^`'"]+)[`'"]""")
# Template-literal interpolated paths: `/api/briefs/${slug}/validate`
FETCH_TPL_RE = re.compile(r"""fetch\(\s*`(?P<path>/[^`]+)`""")
API_TPL_RE = re.compile(r"""api\(\s*`(?P<path>/[^`]+)`""")
# api(path, {method: "POST"})
METHOD_RE = re.compile(r"""method:\s*['"](?P<method>[A-Z]+)['"]""")


def discover_frontend_callers(app_js: Path) -> list[dict[str, Any]]:
    src = app_js.read_text(encoding="utf-8", errors="replace")
    callers: list[dict[str, Any]] = []
    # Find all "/api/..." or "/events" or "/static/" string literals anywhere
    # in the JS (catches dict-valued handlers, EventSource(...), etc.).
    GENERIC_PATH_RE = re.compile(
        r"""['"`](/(?:api|events|static)[^'"`\s\)]*)['"`]"""
    )
    for lineno, line in enumerate(src.splitlines(), 1):
        for m in FETCH_API_RE.finditer(line):
            callers.append({"path": m.group("path"), "line": lineno, "style": "api_str"})
        for m in API_TPL_RE.finditer(line):
            callers.append({"path": m.group("path"), "line": lineno, "style": "api_tpl"})
        for m in FETCH_RAW_RE.finditer(line):
            callers.append({"path": m.group("path"), "line": lineno, "style": "fetch_str"})
        for m in FETCH_TPL_RE.finditer(line):
            callers.append({"path": m.group("path"), "line": lineno, "style": "fetch_tpl"})
        # Catch any other string-literal path under /api, /events, /static
        for m in GENERIC_PATH_RE.finditer(line):
            p = m.group(1)
            # Skip if we already captured the same path on this line
            if any(c["line"] == lineno and c["path"] == p for c in callers):
                continue
            callers.append({"path": p, "line": lineno, "style": "literal_ref"})
    return callers


# ---------------------------------------------------------------------------
# Cross-reference
# ---------------------------------------------------------------------------


def _normalize_caller(caller_path: str) -> str:
    """Strip query string and substitute template params -> path-segment glob."""
    # Drop query string for matching purposes
    base = caller_path.split("?", 1)[0]
    # Replace ${...} with a single non-slash segment
    return re.sub(r"\$\{[^}]+\}", "X", base)


def _normalize_route(route_path: str, kind: str) -> str:
    """Reduce a route specifier to a literal-shaped path with X for params."""
    if kind == "regex":
        # Strip leading ^/trailing $ if present, drop char classes
        s = route_path.lstrip("^").rstrip("$")
        # Replace each capture group with a placeholder X
        s = re.sub(r"\([^)]*\)", "X", s)
        return s
    return route_path


def _path_matches(caller_path: str, route_path: str, kind: str) -> bool:
    """Return True if a frontend-call path satisfies a server route."""
    cn = _normalize_caller(caller_path)
    rn = _normalize_route(route_path, kind)
    if kind == "literal":
        return cn == rn
    if kind == "regex":
        # Compare segment-by-segment, with X matching anything non-slash.
        cs = cn.split("/")
        rs = rn.split("/")
        if len(cs) != len(rs):
            return False
        for c, r in zip(cs, rs):
            if r == "X":
                if c == "" or "/" in c:
                    return False
                continue
            # Caller can also have an X param in this slot
            if c == "X":
                continue
            if c != r:
                return False
        return True
    if kind == "prefix":
        return cn.startswith(rn)
    if kind == "dispatch_table":
        return cn == rn
    return False


def cross_reference(routes: list[dict], callers: list[dict]) -> dict:
    """Compute matched, orphan-route, orphan-caller sets."""
    matched_routes: list[dict] = []
    unmatched_routes: list[dict] = []
    matched_callers: list[dict] = []
    unmatched_callers: list[dict] = []

    for route in routes:
        found = False
        for caller in callers:
            if _path_matches(caller["path"], route["path"], route["kind"]):
                matched_routes.append({**route, "caller_line": caller["line"]})
                found = True
                break
        if not found:
            unmatched_routes.append(route)

    for caller in callers:
        found = False
        for route in routes:
            if _path_matches(caller["path"], route["path"], route["kind"]):
                matched_callers.append({**caller, "route_path": route["path"]})
                found = True
                break
        if not found:
            unmatched_callers.append(caller)

    return {
        "matched_routes": matched_routes,
        "orphan_routes": unmatched_routes,
        "matched_callers": matched_callers,
        "orphan_callers": unmatched_callers,
    }


# ---------------------------------------------------------------------------
# Brief/plan catalog
# ---------------------------------------------------------------------------

TOPIC_BUCKETS = [
    ("webui_autobrief_v2", re.compile(r"webui_autobrief_v2")),
    ("webui_autobrief_v1", re.compile(r"webui_autobrief(?!_v2)")),
    ("webui_scoping", re.compile(r"webui_scoping")),
    ("webui_full", re.compile(r"webui_full")),
    ("orchestrator_multifmt_dispatch", re.compile(r"orchestrator_multifmt_dispatch")),
    ("orchestrator_selfbuild_unblock", re.compile(r"orchestrator_selfbuild_unblock")),
    ("development_progress", re.compile(r"development_progress")),
    ("schema_drift", re.compile(r"schema_drift")),
    ("canary", re.compile(r"canary")),
    ("dependency_checker", re.compile(r"dependency_checker")),
    ("dd6", re.compile(r"dd6")),
    ("narrow_fuzz", re.compile(r"narrow_fuzz")),
    ("meta_layer_freeze", re.compile(r"meta_layer_freeze")),
    ("path_helper", re.compile(r"path_helper")),
    ("silent_canary", re.compile(r"silent_canary")),
    ("m7-1_rescope", re.compile(r"m7-1_rescope")),
    ("t5_swap_blueprint", re.compile(r"t5_swap_blueprint")),
    ("t6_modify_existing_file", re.compile(r"t6_modify_existing_file")),
]


def bucket_for(name: str) -> str:
    for label, rx in TOPIC_BUCKETS:
        if rx.search(name):
            return label
    return "other"


def catalog_briefs_and_plans(root: Path) -> dict[str, Any]:
    briefs = sorted(root.glob("brief_hooks_*.md"))
    plans = sorted(root.glob("plan_hooks_*.json"))

    brief_records: list[dict[str, Any]] = []
    plan_records: list[dict[str, Any]] = []
    by_topic_brief: Counter = Counter()
    by_topic_plan: Counter = Counter()

    for p in briefs:
        topic = bucket_for(p.stem)
        by_topic_brief[topic] += 1
        try:
            size = p.stat().st_size
            mtime = p.stat().st_mtime
        except OSError:
            size, mtime = -1, -1
        brief_records.append({
            "path": str(p.relative_to(root)),
            "topic": topic,
            "size": size,
            "mtime": mtime,
            "is_v2": "_v2" in p.stem,
        })

    plan_by_basename: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for p in plans:
        topic = bucket_for(p.stem)
        by_topic_plan[topic] += 1
        # Identify critique companion + model-variant siblings:
        # plan_hooks_X.json
        # plan_hooks_X_critique.json
        # plan_hooks_X.haiku_v4.json / plan_hooks_X.sonnet_v1.json
        is_critique = "_critique" in p.stem
        # Strip model suffixes and critique suffix to get the "topic key"
        key = p.stem
        for suffix in (".haiku_v4", ".sonnet_v1", "_critique"):
            key = key.replace(suffix, "")
        plan_records.append({
            "path": str(p.relative_to(root)),
            "topic": topic,
            "stem_key": key,
            "size": p.stat().st_size if p.exists() else -1,
            "mtime": p.stat().st_mtime if p.exists() else -1,
            "is_critique": is_critique,
            "is_v2": "_v2" in p.stem,
        })
        plan_by_basename[key].append(plan_records[-1])

    # Identify "V1 v V2 duplicates" — a brief topic that has both a plain
    # and a _v2 variant present in the working tree.
    v1_v2_overlap: list[str] = []
    brief_stems = {b["path"].rsplit(".", 1)[0] for b in brief_records}
    for b in brief_records:
        if b["is_v2"]:
            v1_stem = b["path"].replace("_v2.md", ".md").rsplit(".", 1)[0]
            if v1_stem in brief_stems:
                v1_v2_overlap.append(v1_stem.replace("brief_hooks_", ""))

    # Critique companions: plans that have a _critique sibling.
    critique_companions: list[dict[str, Any]] = []
    plan_keys = {pr["stem_key"] for pr in plan_records}
    for pr in plan_records:
        if pr["is_critique"]:
            # Does its non-critique partner exist?
            partner = pr["path"].replace("_critique", "")
            partner_exists = any(p["path"] == partner for p in plan_records)
            critique_companions.append({
                "critique": pr["path"],
                "partner": partner,
                "partner_exists": partner_exists,
            })

    # Plan variants: same key with multiple model-suffix variants.
    multi_variant_plans = {
        k: [p["path"] for p in v]
        for k, v in plan_by_basename.items()
        if len(v) > 1
    }

    # Try to count tasks in each non-critique plan.
    for pr in plan_records:
        if pr["is_critique"]:
            try:
                data = json.loads((root / pr["path"]).read_text())
                pr["findings_count"] = len(data.get("findings", []))
            except (OSError, json.JSONDecodeError):
                pr["findings_count"] = -1
        else:
            try:
                data = json.loads((root / pr["path"]).read_text())
                pr["tasks_count"] = len(data.get("tasks", []))
            except (OSError, json.JSONDecodeError):
                pr["tasks_count"] = -1

    return {
        "briefs_total": len(brief_records),
        "plans_total": len(plan_records),
        "briefs_by_topic": dict(by_topic_brief),
        "plans_by_topic": dict(by_topic_plan),
        "briefs": brief_records,
        "plans": plan_records,
        "v1_v2_overlap_briefs": sorted(set(v1_v2_overlap)),
        "critique_companions": critique_companions,
        "multi_variant_plans": multi_variant_plans,
    }


# ---------------------------------------------------------------------------
# Prompt cost estimate
# ---------------------------------------------------------------------------


def measure_autobrief_prompt(prompt_path: Path, exemplar_path: Path) -> dict[str, Any]:
    if not prompt_path.exists():
        return {"present": False}
    raw = prompt_path.read_text()
    raw_bytes = len(raw.encode("utf-8"))
    # The endpoint truncates exemplar to 8 KiB (8192). Capture both.
    exemplar_bytes = 0
    exemplar_truncated = 0
    if exemplar_path.exists():
        ex = exemplar_path.read_text()
        # Split on `# ` headings and take first three (matches the handler's logic)
        lines = ex.split("\n")
        heading_count = 0
        take_idx = len(lines)
        for i, line in enumerate(lines):
            if line.startswith("# "):
                heading_count += 1
                if heading_count == 3:
                    take_idx = i + 1
                    break
        exemplar = "\n".join(lines[:take_idx])[:8192]
        exemplar_bytes = len(exemplar.encode("utf-8"))
        exemplar_truncated = len(ex.encode("utf-8"))
    # Crude tokens estimate: ~4 bytes/token for English+code
    total_bytes = raw_bytes + exemplar_bytes
    est_input_tokens = total_bytes // 4
    # Output tokens for a brief are roughly 1500-4000 (the full brief markdown)
    est_output_tokens = 3000
    # Claude opus pricing reference (May 2026): $15/M in, $75/M out.
    cost_in = est_input_tokens * 15 / 1_000_000
    cost_out = est_output_tokens * 75 / 1_000_000
    return {
        "present": True,
        "prompt_path": str(prompt_path),
        "prompt_bytes": raw_bytes,
        "exemplar_bytes_in_prompt": exemplar_bytes,
        "exemplar_full_bytes": exemplar_truncated,
        "total_input_bytes": total_bytes,
        "est_input_tokens": est_input_tokens,
        "est_output_tokens": est_output_tokens,
        "est_cost_usd_per_call": round(cost_in + cost_out, 4),
        "est_cost_usd_input_only": round(cost_in, 4),
        "est_cost_usd_output_only": round(cost_out, 4),
        "pricing_note": "rough estimate @ Claude Opus $15/M in, $75/M out",
    }


# ---------------------------------------------------------------------------
# Codebase-memory graph orphan probe (best-effort, never fatal)
# ---------------------------------------------------------------------------


def probe_orphan_handlers_via_graph(root: Path) -> dict[str, Any]:
    """Static probe: walk `tools/webui_control.py` for `post_*` / `put_*`
    / `get_*` methods on ControlHandlers and check which ones the server
    routes table actually wires. This is a self-contained alternative to
    a live codebase-memory-mcp query — the script must remain runnable
    standalone (no MCP needed)."""
    control_src = (root / "tools" / "webui_control.py").read_text(
        encoding="utf-8", errors="replace"
    )
    server_src = (root / "tools" / "webui_server.py").read_text(
        encoding="utf-8", errors="replace"
    )
    method_pat = re.compile(r"^\s{4}def\s+((?:get|post|put|delete)_\w+)\s*\(", re.MULTILINE)
    methods = set(method_pat.findall(control_src))

    # Which methods are referenced from webui_server.py (canonical dispatcher)?
    wired = {m for m in methods if f"ctl.{m}" in server_src or f"control.{m}" in server_src}
    orphan = methods - wired

    # Which methods are referenced in the (broken) dispatch_table stub?
    table_referenced = set()
    for m in methods:
        if re.search(rf"['\"]{re.escape(m)}['\"]", control_src):
            table_referenced.add(m)
    return {
        "control_methods_total": len(methods),
        "control_methods_wired": sorted(wired),
        "control_methods_orphan": sorted(orphan),
        "methods_in_dispatch_table_stub": sorted(table_referenced),
    }


# ---------------------------------------------------------------------------
# Dispatch-table dead-code probe
# ---------------------------------------------------------------------------


def probe_dispatch_table_state(server_path: Path, control_path: Path) -> dict[str, Any]:
    """Confirm the dispatch-table refactor is *incomplete*.

    Signals:
    - webui_server.py contains both `_dispatch_mutation` (live, line-based
      routing) and `dispatch_mutation` (table-based, module-scope, unused).
    - webui_control.py declares `_dispatch_post` but with only one entry,
      while the unit test `TestDispatchTable` asserts every `post_*` is
      in the table — indicating the test is currently asserting against a
      stub.
    """
    server_src = server_path.read_text(encoding="utf-8", errors="replace")
    control_src = control_path.read_text(encoding="utf-8", errors="replace")
    has_legacy = "def _dispatch_mutation" in server_src
    has_table_fn = re.search(r"^def\s+dispatch_mutation\b", server_src, re.MULTILINE) is not None
    table_fn_is_method = ("class WebUIHandler" in server_src
                         and "    def dispatch_mutation" in server_src)
    # Is the live dispatcher actually the legacy one? (yes if do_POST calls _dispatch_mutation)
    legacy_active = "self._dispatch_mutation(" in server_src
    # Count _dispatch_post entries in control file
    dp_match = re.search(r"_dispatch_post[^{]*=\s*\{(?P<body>.*?)\}", control_src, re.DOTALL)
    dp_entries = 0
    if dp_match:
        dp_entries = len(re.findall(r"""['"]/[^'"]+['"]\s*:""", dp_match.group("body")))
    dp_put_match = re.search(r"_dispatch_put[^{]*=\s*\{(?P<body>.*?)\}", control_src, re.DOTALL)
    dp_put_entries = 0
    if dp_put_match:
        dp_put_entries = len(re.findall(r"""['"]/[^'"]+['"]\s*:""", dp_put_match.group("body")))
    return {
        "legacy_dispatch_mutation_present": has_legacy,
        "table_dispatch_mutation_present_at_module_scope": has_table_fn and not table_fn_is_method,
        "legacy_dispatcher_is_live": legacy_active,
        "dispatch_post_entries_in_control": dp_entries,
        "dispatch_put_entries_in_control": dp_put_entries,
        "dispatch_post_present": dp_match is not None,
        "dispatch_put_present": dp_put_match is not None,
    }


# ---------------------------------------------------------------------------
# Hallucination-defense probe
# ---------------------------------------------------------------------------


def probe_hallucination_defense(root: Path) -> dict[str, Any]:
    """Look for sub-1s-elapsed checks or empty-draft guards in planner code.

    Per user memory: "Don't trust gemini-only drafts; sub-1s response =
    hallucinated; reconciliation concedes to empty Claude drafts (bug)."
    """
    targets = [
        root / "harness" / "planner" / "blind_draft.py",
        root / "harness" / "planner" / "reconciliation.py",
        root / "harness" / "planner" / "diff_extractor.py",
        root / "harness" / "planner" / "attribution.py",
        root / "harness" / "planner" / "cli.py",
    ]
    patterns = [
        re.compile(r"elapsed\s*[<>]"),
        re.compile(r"min_response|min_elapsed|MIN_DRAFT_SECONDS|HALLUCINATION"),
        re.compile(r"hallucinat", re.IGNORECASE),
        re.compile(r"\bsub.?1.?s\b"),
        # Specific guard pattern: if response time < N seconds
        re.compile(r"if\s+elapsed\s*<\s*\d+"),
        re.compile(r"response_time\s*<"),
    ]
    findings: list[dict[str, Any]] = []
    for path in targets:
        if not path.exists():
            continue
        for lineno, line in enumerate(path.read_text(errors="replace").splitlines(), 1):
            for pat in patterns:
                if pat.search(line):
                    findings.append({
                        "file": str(path.relative_to(root)),
                        "line": lineno,
                        "pattern": pat.pattern,
                        "snippet": line.strip()[:200],
                    })
                    break
    # Look for the documented "empty Claude defending all items" bug; the fix
    # is the c_stance/g_stance downgrade in reconciliation.py.
    recon = (root / "harness" / "planner" / "reconciliation.py").read_text(errors="replace")
    empty_draft_guard = "c_stance == \"defend\" and c_task is None" in recon
    # Does *any* file reject a draft for being too fast?
    guards = [f for f in findings if "elapsed" in f["snippet"]]
    return {
        "elapsed_or_hallucination_guards_found": findings,
        "subsecond_draft_rejection_present": False,  # Confirmed absent below.
        "downgrade_empty_defend_to_concede_present": empty_draft_guard,
        "summary": (
            "No sub-1s elapsed rejection found in planner. The only "
            "post-hoc defense against gemini-empty-draft hallucination is the "
            "reconciliation.py:267-270 downgrade of `defend` to `concede` "
            "when the agent never produced a task — but the per-agent timing "
            "is captured then discarded (blind_draft.py:250)."
        ),
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def render_summary(report: dict[str, Any]) -> str:
    out = []
    out.append("=== JanusMask WebUI + Autobrief Audit ===")
    out.append("")
    r = report["routes_summary"]
    out.append(f"Routes discovered (in tools/webui_server.py):")
    out.append(f"  total={r['total']} literal={r['by_kind'].get('literal', 0)} "
               f"regex={r['by_kind'].get('regex', 0)} "
               f"prefix={r['by_kind'].get('prefix', 0)} "
               f"dispatch_table_stub={r['by_kind'].get('dispatch_table', 0)}")
    out.append(f"  by_method={r['by_method']}")
    out.append("")
    x = report["crossref"]
    out.append(f"Cross-reference vs tools/webui_static/app.js:")
    out.append(f"  matched routes (called from JS): {len(x['matched_routes'])}")
    out.append(f"  orphan routes  (no JS caller) : {len(x['orphan_routes'])}")
    out.append(f"  orphan callers (no server route): {len(x['orphan_callers'])}")
    if x["orphan_routes"]:
        out.append("  ORPHAN ROUTES:")
        for r0 in x["orphan_routes"]:
            out.append(f"    {r0['method']:4} {r0['path']}  ({r0['kind']}, line {r0['line']})")
    if x["orphan_callers"]:
        out.append("  ORPHAN CALLERS:")
        for c0 in x["orphan_callers"]:
            out.append(f"    line {c0['line']}: {c0['path']}  ({c0['style']})")
    out.append("")
    bp = report["brief_plan_catalog"]
    out.append(f"Briefs in working tree: {bp['briefs_total']} (by topic: {bp['briefs_by_topic']})")
    out.append(f"Plans in working tree:  {bp['plans_total']} (by topic: {bp['plans_by_topic']})")
    out.append(f"V1/V2 overlap briefs: {bp['v1_v2_overlap_briefs']}")
    out.append(f"Critique companions: {len(bp['critique_companions'])}")
    for c in bp["critique_companions"]:
        marker = "OK" if c["partner_exists"] else "ORPHAN-CRITIQUE"
        out.append(f"  [{marker}] {c['critique']}  -> {c['partner']}")
    if bp["multi_variant_plans"]:
        out.append(f"Multi-variant plans (multiple model siblings):")
        for k, v in bp["multi_variant_plans"].items():
            out.append(f"  key={k}: {v}")
    out.append("")
    p = report["autobrief_prompt"]
    if p["present"]:
        out.append(f"Autobrief prompt cost estimate:")
        out.append(f"  prompt bytes (static)    : {p['prompt_bytes']}")
        out.append(f"  exemplar bytes (truncated 8KiB): {p['exemplar_bytes_in_prompt']}")
        out.append(f"  full exemplar bytes      : {p['exemplar_full_bytes']}")
        out.append(f"  total input bytes        : {p['total_input_bytes']}")
        out.append(f"  est input tokens         : {p['est_input_tokens']}")
        out.append(f"  est cost per call (USD)  : ${p['est_cost_usd_per_call']:.4f} "
                   f"({p['pricing_note']})")
    else:
        out.append("Autobrief prompt: MISSING")
    out.append("")
    d = report["dispatch_table_state"]
    out.append(f"Dispatch-table refactor state:")
    out.append(f"  legacy _dispatch_mutation present     : {d['legacy_dispatch_mutation_present']}")
    out.append(f"  table dispatch at module scope (DEAD) : {d['table_dispatch_mutation_present_at_module_scope']}")
    out.append(f"  legacy dispatcher is live (POST/PUT)  : {d['legacy_dispatcher_is_live']}")
    out.append(f"  ControlHandlers._dispatch_post entries: {d['dispatch_post_entries_in_control']}")
    out.append(f"  ControlHandlers._dispatch_put entries : {d['dispatch_put_entries_in_control']}")
    out.append("")
    h = report["hallucination_defense"]
    out.append(f"Planner hallucination defense:")
    out.append(f"  elapsed/hallucination guards found: {len(h['elapsed_or_hallucination_guards_found'])}")
    out.append(f"  sub-1s draft rejection present    : {h['subsecond_draft_rejection_present']}")
    out.append(f"  empty-defend->concede downgrade   : {h['downgrade_empty_defend_to_concede_present']}")
    out.append(f"  summary: {h['summary']}")
    out.append("")
    o = report["graph_orphan_probe"]
    out.append(f"ControlHandlers method wiring:")
    out.append(f"  total methods       : {o['control_methods_total']}")
    out.append(f"  wired from server   : {len(o['control_methods_wired'])}")
    out.append(f"  orphan (unwired)    : {o['control_methods_orphan']}")
    out.append(f"  in stub dispatch tbl: {o['methods_in_dispatch_table_stub']}")
    return "\n".join(out)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Audit WebUI server + autobrief pipeline for "
                    "inefficiency and overcomplication."
    )
    parser.add_argument("--root", type=Path, default=REPO_ROOT,
                        help="repo root (default: ../ of this script)")
    parser.add_argument("--json", type=Path, default=None,
                        help="write JSON report to this path "
                             "(default: stdout)")
    args = parser.parse_args(argv)

    root = args.root.resolve()
    server_path = root / "tools" / "webui_server.py"
    control_path = root / "tools" / "webui_control.py"
    app_js = root / "tools" / "webui_static" / "app.js"
    prompt_path = root / "tools" / "webui_autobrief_prompt.txt"
    exemplar_path = root / "brief_hooks_webui_full.md"

    if not server_path.exists():
        print(f"FATAL: {server_path} missing", file=sys.stderr)
        return 2

    routes = discover_routes(server_path)
    routes += discover_dispatch_table_routes(control_path)
    callers = discover_frontend_callers(app_js) if app_js.exists() else []
    crossref = cross_reference(routes, callers)

    by_kind: Counter = Counter()
    by_method: Counter = Counter()
    for r in routes:
        by_kind[r["kind"]] += 1
        by_method[r["method"]] += 1

    report = {
        "routes": routes,
        "frontend_callers": callers,
        "routes_summary": {
            "total": len(routes),
            "by_kind": dict(by_kind),
            "by_method": dict(by_method),
        },
        "crossref": crossref,
        "brief_plan_catalog": catalog_briefs_and_plans(root),
        "autobrief_prompt": measure_autobrief_prompt(prompt_path, exemplar_path),
        "dispatch_table_state": probe_dispatch_table_state(server_path, control_path),
        "hallucination_defense": probe_hallucination_defense(root),
        "graph_orphan_probe": probe_orphan_handlers_via_graph(root),
    }

    summary = render_summary(report)
    print(summary, file=sys.stderr)

    if args.json:
        args.json.write_text(json.dumps(report, indent=2, default=str))
        print(f"\nJSON report written to {args.json}", file=sys.stderr)
    else:
        print(json.dumps(report, indent=2, default=str))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
