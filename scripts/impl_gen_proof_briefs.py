#!/usr/bin/env python3
"""Generate the session #25 DOGFOOD-PROOF brief+plan pairs.

Each pair adds one additive module-level constant to harness/__init__.py
(the proven AW15-18 / G29 dogfood pattern: additive constant, meta_task_type
harness_self_fix, AST-walk verification_command). These exist solely to give
the autowork daemon real work to auto_commit when driven from the WebUI.
No adversarial test — the vcmd is the acceptance gate.
"""
from __future__ import annotations
import json
import pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent

PROOFS = [
    ("autowork_allowlist_schema_version", "AUTOWORK_ALLOWLIST_SCHEMA_VERSION", 1,
     "versions the state/control/autowork/auto_promote.allowlist on-disk format"),
    ("autowork_eligibility_schema_version", "AUTOWORK_ELIGIBILITY_SCHEMA_VERSION", 1,
     "versions the compute_autowork_eligibility() return-dict shape"),
    ("webui_controls_schema_version", "WEBUI_CONTROLS_SCHEMA_VERSION", 1,
     "versions the WebUI autowork control-surface contract"),
]

BRIEF_TMPL = """---
title: {slug} — add {const} constant to harness/__init__.py
---

# Title

{slug}: add the module-level constant `{const} = {val}` to
`harness/__init__.py`. {desc}.

# Scope

Single additive top-level assignment in `harness/__init__.py`. No other file,
no existing line changed. Mirrors the AW15-18 additive-constant dogfood pattern.

# Non-Goals

- Do NOT modify any existing constant or the `__version__` / docstring lines.
- Do NOT touch any other file.
- Do NOT add imports.

# Inputs

- `harness/__init__.py` (module-level constants only).

# Deliverables

- `harness/__init__.py` defines `{const} = {val}` at module top level,
  with every pre-existing statement preserved (AST-merge additive).
- Meta-task type: `harness_self_fix`.
- Verification command:
  `python -c "import ast, pathlib; tree=ast.parse(pathlib.Path('harness/__init__.py').read_text()); names=[t.id for n in ast.iter_child_nodes(tree) if isinstance(n, ast.Assign) for t in n.targets if isinstance(t, ast.Name)]; assert '{const}' in names, names; print('{slug} OK')"`
"""

PLAN_TMPL = {
    "vcmd": "python -c \"import ast, pathlib; tree=ast.parse(pathlib.Path('harness/__init__.py').read_text()); names=[t.id for n in ast.iter_child_nodes(tree) if isinstance(n, ast.Assign) for t in n.targets if isinstance(t, ast.Name)]; assert '{const}' in names, names; print('{slug} OK')\"",
}


def main() -> int:
    for slug, const, val, desc in PROOFS:
        brief = ROOT / f"brief_hooks_{slug}.md"
        plan = ROOT / f"plan_hooks_{slug}.json"
        brief.write_text(BRIEF_TMPL.format(slug=slug, const=const, val=val, desc=desc), encoding="utf-8")
        vcmd = PLAN_TMPL["vcmd"].format(const=const, slug=slug)
        plan_obj = {
            "tasks": [{
                "task_id": slug,
                "title": f"{slug}: add {const} to harness/__init__.py",
                "priority": "low",
                "dependencies": [],
                "files_touched": ["harness/__init__.py"],
                "meta_task_type": "harness_self_fix",
                "acceptance_criteria": [
                    f"harness/__init__.py defines {const} = {val} at module top level; all pre-existing statements preserved.",
                ],
                "spec_author": None,
                "estimated_complexity": "trivial",
                "verification_command": vcmd,
                "spec": {
                    "objective": f"Add the additive module-level constant {const} = {val} to harness/__init__.py. {desc}.",
                    "functional_requirements": [
                        f"Add a single top-level assignment: {const} = {val}.",
                        "Preserve every pre-existing module statement (__version__, docstring, and all existing constants).",
                    ],
                    "interfaces": f"One new module-level int constant {const}.",
                    "edge_cases": ["AST merge must keep all existing constants; this is purely additive."],
                    "non_goals": ["Do not modify existing constants or add imports."],
                    "implementation_notes": "Mirror the AW15-18 / G29 additive-constant dogfood pattern.",
                },
                "test_spec": {"unit_tests": [], "integration_tests": [], "property_tests": [],
                              "regression_tests": [], "minimum_test_count": 0,
                              "test_data_requirements": "None; vcmd AST-walk is the gate."},
                "token_budget_ratio": {"implementation_tokens": 200, "test_tokens": 0,
                                       "note": "Single additive constant."},
                "attribution_metadata": {"proposed_by": "reconciled", "reconciled": True,
                                         "diff_resolution": "reconciled"},
                "_debug_stamping_reason": "Session #25 DOGFOOD-PROOF brief (WebUI-driven daemon auto_commit).",
            }],
            "source_brief_path": str(brief),
        }
        plan.write_text(json.dumps(plan_obj, indent=2) + "\n", encoding="utf-8")
        print(f"wrote {brief.name} + {plan.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
