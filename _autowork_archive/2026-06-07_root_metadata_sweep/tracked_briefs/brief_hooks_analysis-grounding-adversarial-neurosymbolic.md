---
interfaces: "ngv2.pattern_scanner exposes module-level VULN_PATTERNS, LANG_EXTENSIONS and functions scan_file, scan_directory. ngv2.fp_patterns takes an injected `now` string seam (no datetime.now()). ngv2.codeql_runner / ngv2.joern_runner / ngv2.mff_scorer / ngv2.z3_bridge accept their external dependency (codeql CLI runner / joern runner / file-crafter+subprocess parser callables / optional solver callable) as injected parameters and never invoke the real binary. ngv2.backtrack is driven by an injected verification callable. All exact signatures are frozen by the committed oracles tests/test_<leaf>.py."
working_dir: "/home/xnihil0zer0/NobleGreedv2"
epic: true
child_epics: true
---

# Title

Static analysis, grounding & adversarial/neurosymbolic verification super-epic

# Scope

EPIC (epic: true, child_epics: true), working_dir /home/xnihil0zer0/NobleGreedv2. This non-leaf super-epic will be re-planned (decomposed further into sub-epics and then leaves) through the normal pipeline. It owns the deterministic static-analysis, grounding, adversarial-evasion, and neurosymbolic-verification tooling around the committed spine. Natural sub-seams for the recursive planner: (a) grounding/static scanners + the merge layer + taint-spec library, (b) adversarial root-cause/scoring/variant generation including the model-file-format (MFF) family, (c) neurosymbolic/AST policy verification with injected solver/verification seams. It rebuilds EXACTLY these 17 leaf modules, each a NEW single-file, whole-file, stdlib-only (or injected-seam) ngv2/*.py module, IMPL-only, pinned by its committed oracle tests/test_<leaf>.py and verified with `python -m pytest tests/test_<leaf>.py -q`: ngv2/pattern_scanner.py [pure], ngv2/fp_patterns.py [pure, injected `now` string seam], ngv2/portfolio_scanner.py [pure], ngv2/pre_analysis.py [orchestration-glue, merges semgrep adapter + regex pattern scanner], ngv2/taint_spec_library.py [pure], ngv2/codeql_runner.py [injected-seam around CodeQL CLI, never invokes real codeql], ngv2/joern_runner.py [injected-seam Joern CPG wrapper], ngv2/root_cause.py [pure], ngv2/adversarial_scorer.py [pure], ngv2/variant_generator.py [pure], ngv2/mff_root_cause.py [pure], ngv2/mff_variant_generator.py [pure; pickle/struct/zlib/lzma/bz2/zipfile/json/io/os/pathlib; NEVER executes any payload], ngv2/mff_scorer.py [injected-seam; file-crafting + subprocess parser supplied as injected callables], ngv2/ast_constraint.py [pure, ast], ngv2/ast_verifier.py [pure, ast], ngv2/backtrack.py [stateful retry shell over an injected verification seam], ngv2/z3_bridge.py [injected-seam; optional injected solver callable, never imports real z3].

# Non-Goals

Does NOT author tests (oracles already committed). NO live exploit execution, NO real LLM/model/SMT calls, NO real codeql/joern/z3 binaries or imports, NO GPU/training, NO live huntr.com HTTP/Playwright, NO MCP processes. NO third-party imports (stdlib only; injected seams for any external dependency). NO leaf may import a sibling Epic-4 leaf. Does NOT build any leaf belonging to the eligibility/safety-gating, orchestration, or knowledge-tools super-epics. mff_variant_generator/mff_scorer must never actually execute/deserialize a model-file payload; codeql_runner/joern_runner/z3_bridge/backtrack/mff_scorer must drive only injected/scripted seams.

# Inputs

The external NobleGreedv2 repo at working_dir /home/xnihil0zer0/NobleGreedv2, holding the committed Epic-1/2/3 spine (ngv2.contracts.Finding/PoC/LiveTestReport etc., plus state_machine, detonation, grounding, poc_runner, report, pipeline, and the committed ngv2.semgrep_adapter pattern this domain's pre_analysis merges with). The 17 committed authoritative oracles tests/test_<leaf>.py for the modules listed in scope. The legacy NobleGreed corpus at /mnt/ai-data/NobleGreed-legacy (services/code_audit/fp_filter.py and related) is the durable design source to distil; only the committed oracle is authoritative per build. No sibling-super-epic symbols are consumed (no inputs from other children).

# Deliverables

17 NEW single-file whole-file ngv2/*.py modules (the leaf roster in scope), each IMPL-only and pinned by its committed oracle, each verified with `python -m pytest tests/test_<leaf>.py -q`, organized under a sub-epic hierarchy the recursive planner decomposes. ngv2.pattern_scanner exposes VULN_PATTERNS, LANG_EXTENSIONS, scan_file, scan_directory. Every brief at every level below this one carries working_dir /home/xnihil0zer0/NobleGreedv2. This super-epic produces NO symbol consumed by a sibling super-epic.
