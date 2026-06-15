---
interfaces: "creates the NEW standalone module ngv2/artifact_harvester.py -- a deterministic stage-output parser exposing a PURE core parse_stage_artifact(filename: str, content: str, phase: str) -> dict | None that classifies one stage-output file into a contract-shaped artifact dict (kinds poc | report), plus a THIN I/O wrapper harvest_stage_artifacts(phase: str, output_dir: str) -> list[dict] that lists and reads files in output_dir and collects the non-None pure-core results; reachable by being importable into the NobleGreed conductor ingest path, with the committed oracle tests/ngv2/test_artifact_harvester_wired.py proving it GREEN"
dependencies: []
working_dir: "/home/xnihil0zer0/NobleGreedv2"
---

# Title

ngv2/artifact_harvester.py -- NEW deterministic parser that turns a pipeline stage's output FILES into contract-shaped artifact dicts ready for SessionDB insertion, so the conductor ingests stage output with zero hand-copying. An audit found that between stages an agent or human must hand-COPY artifacts between output directories (e.g. _e2e_run/llm_confirm_out -> the package step): generated PoC scripts, detonation reports, and submission documents are not auto-ingested. This module deterministically PARSES one stage-output file at a time into a contract-shaped dict (a PoC artifact or a report artifact), and a thin wrapper sweeps a stage's output directory and collects them -- so the conductor can ingest a stage's output without any agent intervention.

# Scope

CREATE the NEW single-file module `ngv2/artifact_harvester.py` (NGv2 external-target task -- `working_dir` = /home/xnihil0zer0/NobleGreedv2). The module has TWO functions:

PURE CORE (the primary contract, fuzzable and byte-stable) -- `parse_stage_artifact(filename: str, content: str, phase: str) -> dict | None`. It classifies ONE file deterministically from its filename suffix and content ONLY (no disk, no network, no clock, no randomness). Rules, evaluated in order:
- `filename` ends with `"_poc.py"` -> `{"kind": "poc", "language": "python", "source": content, "filename": filename}`.
- `filename` ends with `"_poc.js"` -> `{"kind": "poc", "language": "javascript", "source": content, "filename": filename}`.
- `filename` ends with `"_submission.md"` -> `{"kind": "report", "format": "markdown", "markdown": content, "filename": filename}`.
- `filename` ends with `"_report.json"` OR `filename == "detonation_report.json"` -> parse `content` as JSON; on success return `{"kind": "report", "verdict": <parsed.get("verdict")>, "data": <parsed>, "filename": filename}`; on `json.JSONDecodeError` (invalid JSON) return `None` (FAIL-CLOSED -- never emit a malformed report artifact).
- otherwise (any other filename) -> `None`.
The `phase` argument is accepted as context (it may be carried by the wrapper) but does NOT change the classification; classification is driven purely by `filename` suffix and `content`.

THIN WRAPPER (non-fuzzed glue, allowed I/O) -- `harvest_stage_artifacts(phase: str, output_dir: str) -> list[dict]`. List the files directly in `output_dir`, read each file's text, call `parse_stage_artifact(filename, content, phase)` for each, and collect every non-`None` result into a list. This wrapper is the ONLY part permitted to touch the filesystem; it contains NO classification logic of its own (it merely delegates to the pure core).

The pure core is the primary acceptance contract and the fuzzed deliverable; the wrapper is thin I/O. The module is reachable/wired by being importable into the NobleGreed conductor ingest path (the conductor can `from ngv2.artifact_harvester import harvest_stage_artifacts` to ingest a stage's output directory). The committed oracle `tests/ngv2/test_artifact_harvester_wired.py` is the authoritative acceptance contract and proves the module is importable and that the pure core behaves as specified.

# Non-Goals

Do NOT execute, import, or detonate any harvested PoC source -- this module only PARSES file text into dicts; running untrusted PoC code is explicitly OUT OF SCOPE. Wiring this harvester INTO the live NobleGreed conductor or SessionDB (the actual call site that inserts the harvested dicts) is a separate downstream EDIT leaf and is OUT OF SCOPE here -- integration with the conductor, SessionDB, the package step, or any other existing module is NOT part of this leaf. Because this is a self-contained parser with no live call site of its own, the integration-test requirement is excused (the literal word integration appears here per the loader's non-goals rule). Do NOT author or modify any test other than the committed oracle. Do NOT add network, clock, randomness, subprocess, or logging; the only I/O is the wrapper's directory listing + file reads. Do NOT import any third-party package or any sibling `ngv2/**` leaf (only `json`, `os`, and `typing` from the stdlib). Do NOT introduce any eval/exec/`__import__`/os.system/subprocess CALL or any decorator (the AST enforcer bans them).

# Inputs

The committed authoritative oracle `tests/ngv2/test_artifact_harvester_wired.py` (currently RED -- the module does not yet exist) is the fixed acceptance contract; do NOT rebuild or re-author it. It imports `parse_stage_artifact` (and references `harvest_stage_artifacts` for the wiring/contract assertion) from `ngv2.artifact_harvester` and pins the per-kind dict shapes described in Scope. The Python `json`, `os`, and `typing` stdlib modules are the ONLY dependencies. The NGv2 contracts in `ngv2/contracts.py` (the `PoC` dataclass: `finding_id`/`language`/`code`/`entrypoint`; the `LiveTestReport` dataclass: `poc_finding_id`/`verdict`/`exit_code`/`stdout`/`stderr`/`duration_ms`) are the downstream shapes the harvested dicts feed; they are a fixed reference input -- do NOT modify them. The existing conductor ingest path (the consumer that will later import this harvester) is a fixed downstream input -- do NOT modify it here.

# Deliverables

The NEW file `ngv2/artifact_harvester.py` containing BOTH functions with the EXACT signatures:
- `parse_stage_artifact(filename: str, content: str, phase: str) -> dict | None` -- the PURE core, classifying one file per the ordered rules in Scope and returning the exact dict shapes: a `poc` artifact `{"kind": "poc", "language": "python"|"javascript", "source": content, "filename": filename}`; a markdown `report` artifact `{"kind": "report", "format": "markdown", "markdown": content, "filename": filename}`; a JSON `report` artifact `{"kind": "report", "verdict": <parsed.get("verdict")>, "data": <parsed>, "filename": filename}`; or `None`.
- `harvest_stage_artifacts(phase: str, output_dir: str) -> list[dict]` -- the THIN I/O wrapper that lists `output_dir`, reads each file, calls the pure core, and collects the non-`None` results.

The behavior that proves it done -- AT LEAST these concrete edge cases for the pure core (mirrored as the oracle's cases and as regression/property tests):
- (a) `parse_stage_artifact("x_poc.py", "<python source>", phase)` -> `{"kind": "poc", "language": "python", "source": "<python source>", "filename": "x_poc.py"}`.
- (b) `parse_stage_artifact("x_poc.js", "<js source>", phase)` -> `kind == "poc"`, `language == "javascript"`.
- (c) `parse_stage_artifact("huntr_x_submission.md", "<markdown>", phase)` -> `kind == "report"`, `format == "markdown"`, `markdown == "<markdown>"`.
- (d) `parse_stage_artifact("detonation_report.json", '{"verdict": "confirmed"}', phase)` -> `kind == "report"`, `verdict == "confirmed"`, `data == {"verdict": "confirmed"}`.
- (e) `parse_stage_artifact("notes.txt", "anything", phase)` -> `None`.
- (f) `parse_stage_artifact("x_report.json", "{not valid json", phase)` -> `None` (FAIL-CLOSED on invalid JSON).

Plan shape: EXACTLY ONE impl task with `task_id` VERBATIM `ngv2_artifact_harvester`, `meta_task_type: validation`, `priority: high`, `dependencies: []`, `working_dir: "/home/xnihil0zer0/NobleGreedv2"`, `files_touched: ["ngv2/artifact_harvester.py"]` ONLY, WHOLE-FILE single-file emission. The pure core `parse_stage_artifact` is the fuzzed contract; the wrapper `harvest_stage_artifacts` is thin I/O glue. `verification_command: python3 -m pytest -q tests/ngv2/test_artifact_harvester_wired.py` (CWD-relative, NO `cd`). The committed `tests/ngv2/test_artifact_harvester_wired.py` is the authoritative oracle and the `*_wired` reachability proof; make it GREEN. `spec.functional_requirements` CONSOLIDATED to at most 5 entries; `test_spec.unit_tests` MUST enumerate AT LEAST as many entries as `spec.functional_requirements`; `test_spec.regression_tests` MUST list at least two entries naming the committed-oracle cases for edge cases (d) and (f) above. Verified GREEN by `python3 -m pytest -q tests/ngv2/test_artifact_harvester_wired.py`.
