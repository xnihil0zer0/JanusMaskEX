#!/usr/bin/env python3
"""Normalise priority fields across plan JSON files to canonical lowercase.

Canonical vocabulary: {critical, high, medium, low}
Mapping accepted on input:
  1 -> critical,  2 -> high,  3 -> medium
  P0 -> critical, P1 -> high, P2 -> medium, P3 -> low
  Critical/High/Medium/Low -> lowercase equivalent
  critical/high/medium/low -> passthrough (idempotent)

Usage:
  impl_normalize_priority.py [--check] <path-or-glob>...
  --check    dry-run; report changes without writing

Exit codes:
  0: success (all mapped, changes written or dry-run clean)
  2: at least one file has an unmapped priority value
  3: IO / JSON parse error
"""
from __future__ import annotations

import argparse
import glob
import json
import sys
from pathlib import Path
from typing import Any

PRIORITY_MAP: dict[object, str] = {
    1: "critical",
    2: "high",
    3: "medium",
    "P0": "critical",
    "P1": "high",
    "P2": "medium",
    "P3": "low",
    "Critical": "critical",
    "High": "high",
    "Medium": "medium",
    "Low": "low",
    "critical": "critical",
    "high": "high",
    "medium": "medium",
    "low": "low",
}


def _detect_indent(text: str) -> int:
    """Heuristic: scan lines to infer 2- or 4-space indent. Defaults to 2."""
    for line in text.split("\n"):
        stripped = line.lstrip(" ")
        leading = len(line) - len(stripped)
        if leading == 4:
            return 4
        if leading == 2:
            return 2
    return 2


def _walk_tasks(obj: Any):
    """Yield every dict that looks like a task (has 'priority' key)."""
    if isinstance(obj, dict):
        if "priority" in obj:
            yield obj
        for v in obj.values():
            yield from _walk_tasks(v)
    elif isinstance(obj, list):
        for item in obj:
            yield from _walk_tasks(item)


def normalize_file(path: Path, dry_run: bool = False) -> dict:
    """Normalize priority in a single file. Returns result dict."""
    try:
        original = path.read_text(encoding="utf-8")
        plan = json.loads(original)
    except FileNotFoundError:
        return {"file": str(path), "status": "not_found"}
    except json.JSONDecodeError as exc:
        return {"file": str(path), "status": "parse_error", "error": str(exc)}

    mapped = 0
    unmapped: list[dict] = []
    for task in _walk_tasks(plan):
        pv = task.get("priority")
        if pv is None:
            continue
        canonical = PRIORITY_MAP.get(pv)
        if canonical is None:
            unmapped.append({
                "task_id": task.get("task_id", "?"),
                "priority": pv,
                "type": type(pv).__name__,
            })
            continue
        if task["priority"] != canonical:
            task["priority"] = canonical
            mapped += 1

    if unmapped:
        return {
            "file": str(path),
            "status": "unmapped_values",
            "mapped": mapped,
            "unmapped": unmapped,
            "changed": False,
        }

    indent = _detect_indent(original)
    new_text = json.dumps(plan, indent=indent, ensure_ascii=False)
    if original.endswith("\n") and not new_text.endswith("\n"):
        new_text += "\n"

    changed = original != new_text
    if changed and not dry_run:
        path.write_text(new_text, encoding="utf-8")
    return {
        "file": str(path),
        "status": "ok",
        "mapped": mapped,
        "changed": changed,
        "dry_run": dry_run,
    }


def expand_args(raw: list[str]) -> list[Path]:
    paths: set[Path] = set()
    for arg in raw:
        matches = glob.glob(arg)
        if matches:
            for m in matches:
                paths.add(Path(m))
        else:
            # Accept literal paths too; will fail in normalize_file with not_found
            paths.add(Path(arg))
    return sorted(paths)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="impl_normalize_priority.py",
        description="Normalise priority fields across plan JSONs to canonical lowercase.",
    )
    parser.add_argument("--check", action="store_true", help="dry-run; do not write")
    parser.add_argument("paths", nargs="+", help="file paths or globs to process")
    args = parser.parse_args(argv)

    paths = expand_args(args.paths)
    if not paths:
        print("no files matched", file=sys.stderr)
        return 3

    total_mapped = 0
    total_changed = 0
    errors = 0
    for p in paths:
        result = normalize_file(p, dry_run=args.check)
        status = result["status"]
        if status == "ok":
            total_mapped += result["mapped"]
            if result["changed"]:
                total_changed += 1
            marker = "~" if result["changed"] else "."
            print(f"{marker} {p}: mapped={result['mapped']} changed={result['changed']}")
        elif status == "unmapped_values":
            errors += 1
            print(f"X {p}: unmapped:")
            for um in result["unmapped"]:
                print(f"    task_id={um['task_id']}  priority={um['priority']!r} ({um['type']})")
        elif status == "parse_error":
            errors += 1
            print(f"X {p}: JSON parse error: {result['error']}")
        else:
            errors += 1
            print(f"X {p}: {status}")

    print(f"Summary: {total_mapped} priorities mapped across {total_changed} files changed")
    if args.check:
        print("(--check mode: no files written)")
    if errors:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
