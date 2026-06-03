# Title

Method D: Stateful/Rule-Based Differential Property-Based Testing for the JanusMaskJR Validation Harness

## Scope

Integrate Method D stateful, rule-based differential property-based testing (PBT) into the JanusMaskJR validation pipeline to verify state-dependent classes (such as caches, state machines, and transactional models). Currently, tasks of taxonomy type `state_machine` bypass fuzzing (`bypass_fuzzer: True`).

Method D replaces this bypass by modeling the class under test as a state machine. It will:
1. Parse the class interface under test using AST to extract public method and constructor signatures.
2. Generate action sequences using Hypothesis, yielding instantiation arguments and a list of method calls (method name + arguments).
3. Execute the generated action sequences step-by-step on both candidate implementations (Code A and Code B) inside isolated sandboxed subprocesses (`Sandbox` / `BatchRunner`).
4. Perform step-by-step trace comparison (checking return values and exception matching via `outputs_match` / `_deep_compare`).
5. Shrink any divergent sequence trace using Hypothesis's shrinking engine.
6. Feed the minimal shrunk trace to the cross-examination system (`cross_examiner.py`) to provide precise debugging feedback to review agents.

## Non-goals

- Do NOT use native Hypothesis `RuleBasedStateMachine` subclasses, as they are complex to serialize across subprocess jail boundaries and make shrinking fragile. Generate symbolic command lists (action sequences) instead.
- Do NOT break or modify the module-level importability of [harness/diff_fuzzer.py](file:///home/xnihil0zer0/JanusMaskJR/harness/diff_fuzzer.py) (imported module-level by [harness/orchestrator.py](file:///home/xnihil0zer0/JanusMaskJR/harness/orchestrator.py) lines 24-25 and [harness/orchestrator_worker.py](file:///home/xnihil0zer0/JanusMaskJR/harness/orchestrator_worker.py)); all additions must be strictly additive, backward-compatible, and have valid syntax.
- Do NOT refactor or modify existing orchestrator functions in [harness/orchestrator.py](file:///home/xnihil0zer0/JanusMaskJR/harness/orchestrator.py).
- Do NOT alter credential, environment, or nondeterminism gates, which must remain strict.
- Do NOT set a `working_dir` front-matter key; this plan operates as a self-build task on this repository.

## Inputs

- [method_d_report.md](file:///home/xnihil0zer0/JanusMaskJR/method_d_report.md) — Technical report describing the stateful testing mechanism, dynamic command sequences, and interface parsing.
- [harness/sandbox.py](file:///home/xnihil0zer0/JanusMaskJR/harness/sandbox.py) — Jail execution environment defining [Sandbox](file:///home/xnihil0zer0/JanusMaskJR/harness/sandbox.py#L1279) and [BatchRunner](file:///home/xnihil0zer0/JanusMaskJR/harness/sandbox.py#L1459).
- [harness/diff_fuzzer.py](file:///home/xnihil0zer0/JanusMaskJR/harness/diff_fuzzer.py) — Stateless fuzzer containing annotation strategy parsing helpers [_strategy_for_annotation](file:///home/xnihil0zer0/JanusMaskJR/harness/diff_fuzzer.py#L242) and [_ast_node_to_strategy](file:///home/xnihil0zer0/JanusMaskJR/harness/diff_fuzzer.py#L155), output comparator [outputs_match](file:///home/xnihil0zer0/JanusMaskJR/harness/diff_fuzzer.py#L390), [_deep_compare](file:///home/xnihil0zer0/JanusMaskJR/harness/diff_fuzzer.py#L418), [_generate_inputs](file:///home/xnihil0zer0/JanusMaskJR/harness/diff_fuzzer.py#L591), and types [FuzzResult](file:///home/xnihil0zer0/JanusMaskJR/harness/diff_fuzzer.py#L40) and [FuzzFailure](file:///home/xnihil0zer0/JanusMaskJR/harness/diff_fuzzer.py#L30).
- [harness/rebuild/harvest.py](file:///home/xnihil0zer0/JanusMaskJR/harness/rebuild/harvest.py) — Harvest utilities containing [_class_is_stateful](file:///home/xnihil0zer0/JanusMaskJR/harness/rebuild/harvest.py) to gate class-level eligibility.
- [harness/planner/taxonomies.py](file:///home/xnihil0zer0/JanusMaskJR/harness/planner/taxonomies.py) — Policy registry defining [META_TASK_POLICY](file:///home/xnihil0zer0/JanusMaskJR/harness/planner/taxonomies.py#L1) and [BYPASS_FUZZER_TYPES](file:///home/xnihil0zer0/JanusMaskJR/harness/planner/taxonomies.py#L3).
- [harness/cross_examiner.py](file:///home/xnihil0zer0/JanusMaskJR/harness/cross_examiner.py) — Cross-examination module defining [serialize_failure](file:///home/xnihil0zer0/JanusMaskJR/harness/cross_examiner.py#L156) and [prepare_exam_packets](file:///home/xnihil0zer0/JanusMaskJR/harness/cross_examiner.py#L224).

## Deliverables

1. **`extract_class_interface(code, class_name)` in [harness/diff_fuzzer.py](file:///home/xnihil0zer0/JanusMaskJR/harness/diff_fuzzer.py)**: Implement an AST parsing utility to extract parameter annotation mappings for the constructor (`__init__`) and public methods of a target class, discarding private methods (except `__init__`) and reusing the existing AST type parser. ADDITIVE new top-level function. Depends on: none.
2. **`build_stateful_strategy(interface)` in [harness/diff_fuzzer.py](file:///home/xnihil0zer0/JanusMaskJR/harness/diff_fuzzer.py)**: Construct a Hypothesis search strategy yielding a tuple `(init_args, list_of_method_calls)` where `list_of_method_calls` is a sequence of `(method_name, args)` calls, utilizing [_strategy_for_annotation](file:///home/xnihil0zer0/JanusMaskJR/harness/diff_fuzzer.py#L242). ADDITIVE new strategy function. Depends on: #1.
3. **`execute_stateful_trace(...)` sandboxed trace executor in [harness/sandbox.py](file:///home/xnihil0zer0/JanusMaskJR/harness/sandbox.py)**: Define a trace replay execution stub that executes inside the existing jail (reusing [Sandbox](file:///home/xnihil0zer0/JanusMaskJR/harness/sandbox.py#L1279) or [BatchRunner](file:///home/xnihil0zer0/JanusMaskJR/harness/sandbox.py#L1459)) to instantiate the class under test with `init_args`, replay the sequential trace, and return a serialized list of per-step results/exceptions. ADDITIVE new function. Depends on: #2.
4. **`stateful_differential_fuzz(code_a, code_b, class_name, config, session_id)` in [harness/orchestrator.py](file:///home/xnihil0zer0/JanusMaskJR/harness/orchestrator.py)**: Implement a differential stateful fuzz runner that generates action sequences, dispatches them to sandboxed instances for execution, compares results step-by-step using [outputs_match](file:///home/xnihil0zer0/JanusMaskJR/harness/diff_fuzzer.py#L390), shrinks divergent action sequences upon failure, and returns a [FuzzResult](file:///home/xnihil0zer0/JanusMaskJR/harness/diff_fuzzer.py#L40). STRICTLY ADDITIVE new top-level function only (do not touch or refactor other functions in [harness/orchestrator.py](file:///home/xnihil0zer0/JanusMaskJR/harness/orchestrator.py) due to its size; append it safely via a localized patch block). Depends on: #1, #2, #3.
5. **Taxonomy flip in [harness/planner/taxonomies.py](file:///home/xnihil0zer0/JanusMaskJR/harness/planner/taxonomies.py)**: Edit [META_TASK_POLICY](file:///home/xnihil0zer0/JanusMaskJR/harness/planner/taxonomies.py#L1) for `'state_machine'` to set `bypass_fuzzer: False` (keeping the key so [BYPASS_FUZZER_TYPES](file:///home/xnihil0zer0/JanusMaskJR/harness/planner/taxonomies.py#L3) resolves correctly) and append `stateful_fuzz: True` to enable routing stateful tasks through the stateful differential fuzz path. ADDITIVE/edit. Depends on: #4.
6. **Equivalence, counterexample-shrinking, and cross-examination wiring in [harness/cross_examiner.py](file:///home/xnihil0zer0/JanusMaskJR/harness/cross_examiner.py)**: Update [serialize_failure](file:///home/xnihil0zer0/JanusMaskJR/harness/cross_examiner.py#L156) and [prepare_exam_packets](file:///home/xnihil0zer0/JanusMaskJR/harness/cross_examiner.py#L224) to support stateful traces and feed the minimal shrunken failure traces (action sequences with step inputs and divergent outputs) into the feedback packets prepared for Claude and Gemini agents. ADDITIVE. Depends on: #4, #5.
