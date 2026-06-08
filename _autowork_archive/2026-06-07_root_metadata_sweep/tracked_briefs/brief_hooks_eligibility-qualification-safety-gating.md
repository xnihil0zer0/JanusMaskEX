---
interfaces: "ngv2.bounty_gate decides GO/SKIP/UNKNOWN for owner/repo + CWE + severity from an injected bounty-data dict passed as keyword `bounties` (no disk/network/clock/random in the tested surface). ngv2.batch_qualify takes an injected qualifier seam (never calls the real target_qualify). ngv2.target_qualify takes all fs/clock/network as injected seams. ngv2.safety_framework is a state machine with an injected-seam shell (no clock/network/subprocess/global on-disk state in tested paths). All exact signatures are frozen by the committed oracles tests/test_<leaf>.py."
working_dir: "/home/xnihil0zer0/NobleGreedv2"
epic: true
child_epics: true
---

# Title

Target eligibility/qualification & safety/permission gating super-epic

# Scope

EPIC (epic: true, child_epics: true), working_dir /home/xnihil0zer0/NobleGreedv2. This non-leaf super-epic will be re-planned into sub-epics and leaves. It owns the deterministic target-qualification/eligibility recon gates and the safety/permission/integrity gating tooling. Natural sub-seams for the recursive planner: (a) economic/recon eligibility & qualification (qualify, bounty, complexity, framework/language/deser recon, huntr cache, batch shell), (b) safety/permission/prompt-integrity gating (permission model, bash validation, prompt integrity & hints, safety state machine). It rebuilds EXACTLY these 13 leaf modules, each a NEW single-file, whole-file, stdlib-only (or injected-seam) ngv2/*.py module, IMPL-only, pinned by its committed oracle tests/test_<leaf>.py and verified with `python -m pytest tests/test_<leaf>.py -q`: ngv2/target_qualify.py [pure; all fs/clock/network replaced by injected seams], ngv2/bounty_gate.py [pure; GO/SKIP/UNKNOWN from injected `bounties` dict keyword], ngv2/repo_complexity.py [pure, gate pure_fuzz], ngv2/web_framework_detect.py [pure; os/re/pathlib], ngv2/language_patterns.py [pure CWE-tagged regex DB], ngv2/deser_detect.py [pure CWE-502 scanner, gate pure_fuzz], ngv2/huntr_eligible_cache.py [pure; eligibility via fetched bounties cache], ngv2/batch_qualify.py [orchestration-glue; INJECTED qualifier seam, never calls real target_qualify/network], ngv2/permission_model.py [pure graduated permission model], ngv2/bash_validator.py [pure; inspects command STRING only], ngv2/prompt_integrity.py [SHA-256 integrity registry], ngv2/safety_framework.py [stateful safety state machine with injected-seam shell], ngv2/prompt_hints.py [pure append-only 'Operational Hints' markdown manager].

# Non-Goals

Does NOT author tests (oracles already committed). NO real network/clock/filesystem in tested surfaces (use injected seams), NO subprocess execution (bash_validator inspects strings only; batch_qualify uses an injected qualifier callable, never the real target_qualify or network), NO real LLM/model calls, NO GPU/training, NO live huntr.com HTTP/Playwright, NO MCP processes. NO third-party imports (stdlib only). NO leaf may import a sibling Epic-4 leaf — in particular batch_qualify must NOT import ngv2.target_qualify, it consumes an injected qualifier. Does NOT build any leaf belonging to the analysis, orchestration, or knowledge-tools super-epics.

# Inputs

The external NobleGreedv2 repo at working_dir /home/xnihil0zer0/NobleGreedv2 with the committed Epic-1/2/3 spine (ngv2.contracts etc.). The 13 committed authoritative oracles tests/test_<leaf>.py for the modules listed in scope. The legacy NobleGreed corpus at /mnt/ai-data/NobleGreed-legacy (services/qualify_target.py, services/prompt_integrity.py, etc.) is the durable design source to distil; only the committed oracle is authoritative per build. No sibling-super-epic symbols are consumed.

# Deliverables

13 NEW single-file whole-file ngv2/*.py modules (the leaf roster in scope), each IMPL-only and pinned by its committed oracle, each verified with `python -m pytest tests/test_<leaf>.py -q`, organized under a sub-epic hierarchy the recursive planner decomposes. ngv2.bounty_gate accepts the injected bounty data as the keyword argument `bounties` and returns GO/SKIP/UNKNOWN. ngv2.batch_qualify accepts an injected qualifier callable seam. Every brief at every level below this one carries working_dir /home/xnihil0zer0/NobleGreedv2. This super-epic produces NO symbol consumed by a sibling super-epic.
