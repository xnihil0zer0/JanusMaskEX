# Provenance-Injection Design Review #1 — INTERNAL PROVENANCE (JM harness + NGv2)

Adversarial review. Every claim verified against source at file:line. No code modified.

Scope of lens: provenance of *code we produced* (JM harness + NGv2 pipeline modules) surfaced to a worker that EDITS existing code.

---

## (1) Verdict Table

| # | Design claim | Verdict | Evidence (file:line) |
|---|---|---|---|
| C1 | `symbol_ledger.py` is signature-only today | **CONFIRM** | `harness/symbol_ledger.py:69-79` (`_signature_of` renders `name(args)->ret` only); `:94-108` (`_extract_signatures` returns `dict[name -> signature]`); `:110-140` (`record_symbols` returns `dict[str,str]`, no date/task/oracle/importer). `grep` for `task_id|origin|date|commit_sha|importer` in the file = zero hits. |
| C2 | `record_symbols` keys off `phase==accepted` + `auto_commit` rows | **CONFIRM** | `harness/symbol_ledger.py:66` (`row.get('phase')=='accepted' and row.get('event')=='auto_commit'`); reads `state/impl_progress.jsonl` lazily every call `:46-67, :120-140`. |
| C3 | `resolve_interfaces` string-replaces named symbols | **CONFIRM** | `harness/symbol_ledger.py:142-164` — builds `\b(name1|name2|...)\b` regex (`:160`) and `pattern.sub` rewrites bare names to signatures (`:162-164`). Returns input unchanged on any miss (`:154-158`). |
| C4 | The ledger IS wired live (flag + staging call site) | **CONFIRM** | Flag `hierarchical_planning.symbol_ledger: true` at `harness/config.yaml:96,100` (ON). Call site: `harness/planner/staging.py:105` → `_maybe_resolve_interfaces` (`:16-46`), gated on `cfg['hierarchical_planning']['symbol_ledger']` (`:39`), invokes `resolve_interfaces` (`:41-42`). |
| C5 | Worker edit-prompt has no provenance block today | **CONFIRM** | `harness/orchestrator.py:1365-1419` (`prepare_task_prompt`). The current-source-of-edited-file is surfaced only as a path (`inbox/targets/<rel>`, `:1400`); no date/origin/oracle/importer text anywhere in the prompt body. |
| C6 | Edited code is staged at `inbox/targets` (current source, not HEAD) | **CONFIRM** | `harness/orchestrator.py:3988-4019` `_stage_targets`; for `test_authoring` with `mutation_target` it also stages the module-under-test (`:4014-4018`). Prompt references it at `:1400`. |
| C7 | Verification auto-scopes to test files that IMPORT the touched module → non-importing oracle regression sails through | **CONFIRM, with a partial mitigation the summary omits** | `harness/orchestrator.py:2758-2765` rewrites an unscoped pytest cmd to `get_relevant_test_files(...)`. Scoper logic `harness/test_scoper.py:91-179`: relevance = import-set intersection (`:152-160`) **PLUS** a `test_<stem>.py` naming-convention fallback (`:162-164`). So a non-importing oracle named `test_<module>.py` IS still run; a non-importing oracle with a *different* name (fixture/conftest-driven, integration test exercising the symbol indirectly) is **NOT** run. The gap is real but narrower than "any non-importing test." |
| C8 | `impl_progress.jsonl` reliably maps symbol→task | **REFUTE (file→task only; never symbol→task)** | Accepted rows carry `task_id` + `files` (list of paths) + `commit_sha`, e.g. `{"phase":"accepted","task_id":"impl-source-localize","event":"auto_commit","commit_sha":"d2a3...","files":["ngv2/source_localize.py"]}`. 949/949 accepted/auto_commit rows have `files`; NONE carries per-symbol granularity. The ledger maps **file→task**, and `record_symbols` then re-derives symbols by re-parsing the file at call time (`symbol_ledger.py:127-139`). A symbol cannot be attributed to a task without re-parsing — and even then, only the *last* accepted touch of the file is known, not which task authored a given function. |
| C9 | `mutation_target` (the locking-oracle link) is available to build symbol→oracle | **REFINE — exists transiently per-task, but is NOT persisted** | `mutation_target` lives in task.json and is consumed at the mutation gate `harness/orchestrator.py:2836-2861`, but the accepted/auto_commit ledger row does **NOT** record it (verified: `grep accepted ... mutation` returns only the touched test file path, never the `mutation_target` field). `grep mutation_target` in `test_scoper.py`/`symbol_ledger.py` = zero. **There is no symbol→locking-oracle index anywhere today** — the design's "locking oracle files" field would have to be captured at commit time (cheap: it's right there in `task` at line 2836). |
| C10 | No existing reverse-dependency / importer-count tooling | **REFUTE — full reverse import graph already exists** | `harness/wire_up.py` builds `importers: dict[module->set[importer]]` at `:170-173` from `module_import_graph` (`harness/rebuild/discover.py:125`). `WireResult.importers` (`wire_up.py:28-34`) and `sweep_modules` (`:150-200`) already classify wired/orphan_cluster/orphan and expose direct importers. **Importer count is a one-line lookup over an already-built graph** — the ledger does not need to store it. |

Net: every *mechanical* claim about today's state is CONFIRMED. The two design *premises* that are weakest — "the ledger is the right place to add this" and "this reduces regressions" — are where the design falls down (see §2–§3).

---

## (2) Strongest Objection

**The design optimizes for a failure mode the empirical data says is rare-to-nonexistent, and it does so on the wrong substrate.**

Causal chain, scrutinized:

1. The stated goal is *reducing regressions* in accepted/gated symbols. But the supplied empirical finding — NGv2 full-suite = **34 fail / 1970 pass, all 34 missing-toolchain, zero real regressions** — and the dominant-error class being **pre-commit GATE false-rejects of good code**, both say regressions are not the bottleneck. The pipeline already runs a mutation gate (`orchestrator.py:2836-2861`) and a verification gate (`:2758-2825`) that *reject* before commit. A regression only escapes if (a) it's a real behavior change AND (b) no oracle in the auto-scoped set catches it. That intersection is empirically tiny.

2. Of the three design legs, **only leg 3 (test-scoper) touches the actual escape path.** Legs 1+2 (ledger fields + prose block) are upstream of the gate and can only *influence the LLM's intent* — they cannot *block* a regression. A regression that the LLM introduces despite the prose block still has to be caught by a test, which lands you back at leg 3.

3. Leg 2 is the weakest of all: it is **prose appended to an already-large prompt** (`prepare_task_prompt` is ~55 lines of dispatch instructions, `orchestrator.py:1400-1418`). There is no evidence in this codebase that LLM editors *heed* "preserve behavior" prose — the codebase's own design philosophy is the opposite: it does not trust prose, it builds **hard gates** (mutation gate fail-closed at `:2839`, AST enforcer, wire-up gate `config.yaml:64`). Adding a soft "please preserve" hint contradicts the harness's own demonstrated thesis that *gates beat prompts*. The memory file `dont-conflate-built-with-works.md` and the owner directive `fixes-are-permanent-and-reusable.md` reinforce this: prose-nudges are explicitly disfavored.

4. The substrate is wrong twice over:
   - **{date, origin}** is already free from **git** — every auto-commit is `Integrate validated code for {task_id}` (`harness/commit_message_formatter.py:8,21`; **679/679** auto-commits follow this; produced centrally). `git log -1 --format='%ci %s' -- <file>` yields date+origin task_id with zero new storage and zero staleness risk. The ledger, by contrast, re-derives from a 21 MB / 105 k-line append-only file (`state/impl_progress.jsonl`) on **every** `resolve_interfaces` call (`symbol_ledger.py:53`, full `read_text` + splitlines), and attributes only the *last* file touch, not the authoring task (C8).
   - **importer count** is already free from **wire_up.py** (`importers` dict, `:170-173`). Storing it in the ledger would *duplicate* a live graph and immediately go stale on the next edit.

So the design adds a new field-bearing schema to the ledger to carry (a) data git already has more accurately, (b) data wire_up already computes more cheaply, and (c) a prose hint that the harness's own architecture says won't hold — to defend against a class of failure the data says barely occurs.

---

## (3) Better Alternative(s) — concrete injection points

### A. If you want regression protection, harden leg 3 ONLY, and make it a gate not a hint.

The single real escape path is C7: a locking oracle that neither imports the module nor follows `test_<stem>` naming. Two concrete fixes, both gate-grade:

- **A1 — Persist the symbol→oracle link at commit, then union it into scoping.** At `orchestrator.py:2836`, `task['mutation_target']` and `files_touched` (the oracle file) are both in hand. Write them into the accepted row (one extra key, e.g. `"locks": {"<dotted.module>": ["tests/...py"]}`). Then in the scoper rewrite at `:2758-2765`, union `get_relevant_test_files(...)` with the persisted locking-oracle set for any touched module. This closes the exact gap, is fail-toward-running-more-tests (safe), and reuses the existing per-task `mutation_target` (C9). Injection points: `orchestrator.py:2830/2843`-style `write_jsonl_row` call near `:2834`, and `:2760`.
- **A2 — Reverse the existing import graph for scoping, not just naming.** `test_scoper.get_relevant_test_files` already does forward import matching. Add the wire_up importer graph (`harness/wire_up.py:170-173`) so a test that imports a *helper* which imports the touched module is pulled in transitively. Cheap (graph already built by `sweep_modules`).

### B. If you want {date, origin} surfaced to the editor (legs 1+2 intent), source it from git, not the ledger.

In `prepare_task_prompt` (`orchestrator.py:1365`), for each `files_touched` target, shell `git log -1 --format='%cs %s' -- <rel>` and emit a one-line "this file last changed YYYY-MM-DD for task <id>" note. This is O(files) cheap, never stale, needs zero ledger schema change, and leans on the 679/679 commit-message convention (`commit_message_formatter.py:8`). Keep it to one line per file — do NOT add a "preserve behavior" paragraph (see §2.3).

### C. importer count: read it live, don't store it.

If a "load-bearing" signal is wanted in the prompt, call `wire_up.sweep_modules`/`WireResult.importers` (`wire_up.py:28-34, 150-200`) at prompt-build time and emit "N live importers." One lookup, no new persisted field, no staleness.

---

## (4) Minimal-Viable Version (what I'd keep)

Drop legs 1 and 2 entirely as proposed (new ledger schema + "preserve behavior" prose). Keep a **single gate-grade change** = **A1**:

1. At auto-commit (`orchestrator.py:~2834`), persist `mutation_target → oracle-file` into the accepted ledger row (data already in `task`).
2. At verify-scoping (`orchestrator.py:2758-2765`), union the persisted locking-oracle(s) for each touched module into the pytest target set.

That is the only piece that touches the real regression-escape path, it is fail-safe (runs *more* oracles), it reuses existing data, and it adds no prose the LLM can ignore. Total surface: ~1 new key on write + ~3 lines on read.

Everything else the design proposes is either already free elsewhere (git for date/origin — `commit_message_formatter.py:8`; wire_up for importer count — `wire_up.py:170`), or is a prompt-bloat hint at odds with this harness's gate-over-prose architecture, defending a regression class the data (34/34 missing-toolchain, zero real regressions) shows is near-empty. Given that, even A1 is a low-priority hardening, not a necessity — the honest verdict is that **internal provenance is largely not worth building**; if anything is, it's A1, and only because it costs almost nothing.
