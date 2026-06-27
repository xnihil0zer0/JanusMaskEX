---
interfaces: "creates NEW data/ngv2/reachability_rules/sink_classes.json — rules-as-data sink-class catalog (id/cwe/lang/patterns/specs) covering CWE-22/78/94/502/918, mapping each class to its bundled .ql specs"
dependencies: []
meta_task_type: data_model
spec_author: "Phase-III BUILD-PREP agent (JanusMask)"
spec_reviewed_by: "owner (CodeQL CLI use APPROVED 2026-06-12)"
---

# Title

data/ngv2/reachability_rules/sink_classes.json — NEW rules-as-data sink-class catalog for the Stage-1 prefilter and Stage-2 spec selection.

# Scope

CREATE the NEW data file `data/ngv2/reachability_rules/sink_classes.json`: a JSON object with a `sink_classes` list. Each entry has `id`, `cwe`, `lang`, `patterns[]` (line-level regexes) and `specs[]` (the bundled `data/ngv2/taint_specs/*.ql` files that prove that class). It covers the dominant paid-bounty CWEs the corpus demands: 502 (deserialization), 78 (command injection), 94 (code injection), 22 (path traversal), 918 (SSRF).

DISPATCH DIRECTIVE — PATCH FORMAT (MANDATORY — WHOLE-FILE): this is a NEW single data file, so emit the COMPLETE file for `data/ngv2/reachability_rules/sink_classes.json` BYTE-FOR-BYTE exactly as follows (rules-as-data — no Python):

```json
{
  "schema_version": 1,
  "sink_classes": [
    {
      "id": "deserialization",
      "cwe": "CWE-502",
      "lang": "python",
      "patterns": [
        "\\bc?_?pickle\\.loads?\\b",
        "\\btorch\\.load\\b",
        "\\byaml\\.load\\b",
        "\\bjoblib\\.load\\b",
        "\\bmarshal\\.loads?\\b"
      ],
      "specs": [
        "cwe502_pickle_load.ql",
        "cwe502_torch_load.ql",
        "cwe502_yaml_load.ql",
        "cwe502_joblib_load.ql",
        "cwe502_numpy_load.ql"
      ]
    },
    {
      "id": "command_injection",
      "cwe": "CWE-78",
      "lang": "python",
      "patterns": [
        "\\bos\\.system\\s*\\(",
        "\\bsubprocess\\.(?:call|run|Popen|check_output)\\s*\\("
      ],
      "specs": ["cwe78_subprocess.ql"]
    },
    {
      "id": "code_injection",
      "cwe": "CWE-94",
      "lang": "python",
      "patterns": [
        "\\beval\\s*\\(",
        "\\bexec\\s*\\("
      ],
      "specs": ["cwe94_eval_exec.ql"]
    },
    {
      "id": "path_traversal",
      "cwe": "CWE-22",
      "lang": "python",
      "patterns": [
        "\\bopen\\s*\\(",
        "\\bos\\.path\\.join\\s*\\(",
        "\\bsend_file\\s*\\("
      ],
      "specs": ["cwe22_path_traversal.ql"]
    },
    {
      "id": "ssrf",
      "cwe": "CWE-918",
      "lang": "python",
      "patterns": [
        "\\brequests\\.(?:get|post|put|patch|delete|head|request)\\s*\\(",
        "\\bhttpx\\.(?:get|post|put|patch|delete|head|request|stream)\\s*\\(",
        "\\burllib\\.request\\.urlopen\\s*\\("
      ],
      "specs": ["cwe918_ssrf.ql"]
    }
  ]
}
```

# Required plan shape

EXACTLY ONE impl task. Use this task_id VERBATIM: `task_id`: `ngv2_sink_classes_data`. meta_task_type=`data_model`. priority: high. dependencies: []. working_dir: "/home/xnihil0zer0/NobleGreedv2". files_touched: `["data/ngv2/reachability_rules/sink_classes.json"]` ONLY. partial_edit semantics: WHOLE-FILE single-file emission — copy the DISPATCH DIRECTIVE block (including full file content) VERBATIM into `implementation_notes`. verification_command: `python3 -m pytest -q tests/ngv2/test_sink_classes_data_wired.py` (CWD-relative — NO `cd`). The committed RED oracle tests/ngv2/test_sink_classes_data_wired.py is authoritative — make it GREEN (3 tests); do NOT author new tests. `test_spec.regression_tests` (≥2 named committed cases): `test_sink_classes_cover_required_cwes_no_dupes`, `test_deser_class_maps_to_bundled_502_specs`. `test_spec.edge_cases` (≥2, reflected in test names): `test_sink_class_entries_are_well_formed`, `test_deser_class_maps_to_bundled_502_specs` — including the integration-style coverage case `test_deser_class_maps_to_bundled_502_specs`.

# Non-Goals

Do NOT add Python code — this is pure rules-as-data consumed by the Stage-1 scanners. Do NOT touch any module or other data file. Do NOT remove any of the pinned required CWEs/frameworks/boundaries. Catalog INTEGRATION into the live scan path is the consuming module's leaf, not this data leaf.

# Inputs

The committed oracle tests/ngv2/test_sink_classes_data_wired.py (RED — file absent). It pins: all of {CWE-22,78,94,502,918} present; no duplicate ids; required keys per entry; every pattern compiles; and the CWE-502 class maps to the bundled cwe502_pickle_load.ql + cwe502_torch_load.ql specs.

# Deliverables

The NEW data file `data/ngv2/reachability_rules/sink_classes.json` exactly as pinned, verified GREEN by `python3 -m pytest -q tests/ngv2/test_sink_classes_data_wired.py` (3 passed).
