---
interfaces: "exposes `classify_novelty(finding: dict, known_corpus: list) -> str` returning \"NOVEL\"|\"POSSIBLE_DUP\"|\"CONFIRMED_DUP\"; CONFIRMED_DUP iff some corpus entry matches finding on cwe AND file-locus AND normalized title; POSSIBLE_DUP iff normalized-title similarity OR (same cwe AND same file); else NOVEL."
working_dir: "/home/xnihil0zer0/NobleGreedv2"
---

# Title

Novelty and duplication gate (detonate -> novelty): pure classify_novelty() returning NOVEL/POSSIBLE_DUP/CONFIRMED_DUP against the prior-submission corpus, porting legacy novelty_checker.py.

# Scope

Build a pure, stdlib+ngv2-only, deterministic, total module ngv2/novelty_gate.py exposing `classify_novelty(finding: dict, known_corpus: list) -> str` that ports the legacy novelty_checker.py logic. `finding` carries at least {title: str, cwe: str, file: str} (file-locus). `known_corpus` is a list of prior-submission dicts each shaped {title: str, cwe: str, file: str}. Returns exactly one of "NOVEL" | "POSSIBLE_DUP" | "CONFIRMED_DUP". Normalization for title comparison: lowercase, collapse/strip whitespace (and treat as substring containment in either direction). File-locus match: same `file` value. Decision rule (strongest match wins):
- CONFIRMED_DUP iff SOME corpus entry matches the finding on ALL THREE: same cwe AND same file-locus AND normalized title equal.
- Else POSSIBLE_DUP iff SOME corpus entry has a similar title (case/space-normalized substring match in either direction) OR (same cwe AND same file).
- Else NOVEL.
Operator override of POSSIBLE_DUP to advance is a routing concern handled by the wiring brief, not here. Deterministic: identical (finding, corpus) always yields identical verdict; empty corpus -> NOVEL.

# Non-Goals

Do NOT implement real corpus database connections, network requests, platform/advisory API calls, embeddings, or fuzzy ML similarity — comparison is pure string/field matching over the injected `known_corpus`. Do NOT perform the FSM transition or the operator-override routing (only NOVEL/overridden-POSSIBLE_DUP advances; CONFIRMED_DUP terminates — that is ngv2_lifecycle_fsm_wiring). No subprocess, LLM, wall-clock, or randomness. The literal word integration appears here to flag that wiring this verdict into the FSM and its routing/integration is out of scope; this is a pure classifier.

# Inputs

Consumes ngv2.contracts (Finding) and the duplication logic of legacy /home/xnihil0zer0/AI-Data/NobleGreed-legacy/services/code_audit/novelty_checker.py. `finding: dict` with at least {title, cwe, file}; `known_corpus: list` of prior-submission dicts each {title, cwe, file}.

# Deliverables

ngv2/novelty_gate.py exposing `classify_novelty(finding: dict, known_corpus: list) -> str` returning "NOVEL"|"POSSIBLE_DUP"|"CONFIRMED_DUP" per the rule above. Plus a committed, non-vacuous hand-authored RED oracle (test_novelty_gate.py, importing ngv2.novelty_gate.classify_novelty) covering: a full cwe+file+title CONFIRMED_DUP match, a normalized-title-only POSSIBLE_DUP, a same-cwe+same-file POSSIBLE_DUP, an empty-corpus NOVEL, and a no-overlap NOVEL.
