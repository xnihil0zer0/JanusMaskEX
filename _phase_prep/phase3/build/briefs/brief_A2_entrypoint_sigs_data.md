---
interfaces: "creates NEW data/ngv2/reachability_rules/entrypoint_sigs.json — rules-as-data entry-point signature catalog (framework/kind/attacker_boundary/signature_regex) covering web routes, CLIs, and the G6 MFF model-load boundary"
dependencies: []
meta_task_type: data_model
spec_author: "Phase-III BUILD-PREP agent (JanusMask)"
spec_reviewed_by: "owner (CodeQL CLI use APPROVED 2026-06-12)"
---

# Title

data/ngv2/reachability_rules/entrypoint_sigs.json — NEW rules-as-data entry-point catalog (web routes + CLIs + G6 MFF model-load boundaries).

# Scope

CREATE the NEW data file `data/ngv2/reachability_rules/entrypoint_sigs.json`: a JSON object with an `entrypoints` list. Each entry has `framework`, `kind` (route|cli|model_load), `attacker_boundary` (network|cli|model_file) and `signature_regex[]`. Covers FastAPI/Flask/Django/aiohttp/tornado routes, click/argparse CLIs, and — folding Gap G6 — an `mff`/`model_load`/`model_file` entry for torch.load/pickle.load/joblib/keras/safetensors/from_pretrained/load_pretrained_model so MFF loaders are treated as attacker boundaries (the model FILE is the attacker input).

DISPATCH DIRECTIVE — PATCH FORMAT (MANDATORY — WHOLE-FILE): this is a NEW single data file, so emit the COMPLETE file for `data/ngv2/reachability_rules/entrypoint_sigs.json` BYTE-FOR-BYTE exactly as follows (rules-as-data — no Python):

```json
{
  "schema_version": 1,
  "entrypoints": [
    {
      "framework": "fastapi",
      "kind": "route",
      "attacker_boundary": "network",
      "signature_regex": [
        "@\\w+\\.(?:get|post|put|delete|patch|options|head|websocket)\\s*\\(",
        "\\bAPIRouter\\s*\\("
      ]
    },
    {
      "framework": "flask",
      "kind": "route",
      "attacker_boundary": "network",
      "signature_regex": [
        "@\\w+\\.route\\s*\\(",
        "\\.add_url_rule\\s*\\("
      ]
    },
    {
      "framework": "django",
      "kind": "route",
      "attacker_boundary": "network",
      "signature_regex": [
        "\\bre_path\\s*\\(",
        "\\burlpatterns\\b",
        "\\bpath\\s*\\("
      ]
    },
    {
      "framework": "aiohttp",
      "kind": "route",
      "attacker_boundary": "network",
      "signature_regex": [
        "@routes\\.(?:get|post|put|delete|patch|head|view)\\s*\\(",
        "\\.router\\.add_(?:get|post|put|delete|route)\\s*\\("
      ]
    },
    {
      "framework": "tornado",
      "kind": "route",
      "attacker_boundary": "network",
      "signature_regex": [
        "\\bclass\\s+\\w+\\s*\\(\\s*tornado\\.web\\.RequestHandler\\b"
      ]
    },
    {
      "framework": "click",
      "kind": "cli",
      "attacker_boundary": "cli",
      "signature_regex": [
        "@click\\.command\\s*\\(",
        "@\\w+\\.command\\s*\\("
      ]
    },
    {
      "framework": "argparse",
      "kind": "cli",
      "attacker_boundary": "cli",
      "signature_regex": [
        "\\bargparse\\.ArgumentParser\\s*\\("
      ]
    },
    {
      "framework": "mff",
      "kind": "model_load",
      "attacker_boundary": "model_file",
      "signature_regex": [
        "\\btorch\\.load\\s*\\(",
        "\\bpickle\\.load\\s*\\(",
        "\\bjoblib\\.load\\s*\\(",
        "\\bkeras\\.models\\.load_model\\s*\\(",
        "\\bload_model\\s*\\(",
        "\\bsafetensors[\\w.]*\\.load(?:_file)?\\s*\\(",
        "\\.from_pretrained\\s*\\(",
        "\\bload_pretrained_model\\s*\\("
      ]
    }
  ]
}
```

# Required plan shape

EXACTLY ONE impl task. Use this task_id VERBATIM: `task_id`: `ngv2_entrypoint_sigs_data`. meta_task_type=`data_model`. priority: high. dependencies: []. working_dir: "/home/xnihil0zer0/NobleGreedv2". files_touched: `["data/ngv2/reachability_rules/entrypoint_sigs.json"]` ONLY. partial_edit semantics: WHOLE-FILE single-file emission — copy the DISPATCH DIRECTIVE block (including full file content) VERBATIM into `implementation_notes`. verification_command: `python3 -m pytest -q tests/ngv2/test_entrypoint_sigs_data_wired.py` (CWD-relative — NO `cd`). The committed RED oracle tests/ngv2/test_entrypoint_sigs_data_wired.py is authoritative — make it GREEN (3 tests); do NOT author new tests. `test_spec.regression_tests` (≥2 named committed cases): `test_entrypoint_sigs_schema_and_framework_coverage`, `test_g6_mff_model_load_boundary_present`. `test_spec.edge_cases` (≥2, reflected in test names): `test_each_signature_regex_compiles`, `test_g6_mff_model_load_boundary_present` — including the integration-style coverage case `test_g6_mff_model_load_boundary_present`.

# Non-Goals

Do NOT add Python code — this is pure rules-as-data consumed by the Stage-1 scanners. Do NOT touch any module or other data file. Do NOT remove any of the pinned required CWEs/frameworks/boundaries. Catalog INTEGRATION into the live scan path is the consuming module's leaf, not this data leaf.

# Inputs

The committed oracle tests/ngv2/test_entrypoint_sigs_data_wired.py (RED — file absent). It pins: fastapi/flask/django/click/argparse frameworks and route/cli/model_load kinds present; every signature regex compiles; and the G6 model_load/model_file boundary present naming torch + pickle loaders.

# Deliverables

The NEW data file `data/ngv2/reachability_rules/entrypoint_sigs.json` exactly as pinned, verified GREEN by `python3 -m pytest -q tests/ngv2/test_entrypoint_sigs_data_wired.py` (3 passed).
