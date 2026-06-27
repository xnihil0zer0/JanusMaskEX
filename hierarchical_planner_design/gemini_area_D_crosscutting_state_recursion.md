# Area D — Cross-Cutting Hierarchical State: Symbol/Interface Ledger, Failure Propagation, Recursion Safety

## 1. Summary
This area delivers the Level 2 runtime state engine of the Hierarchical Planner. It designs a runtime Symbol/Interface Ledger (`state/symbol_ledger.jsonl`) that acts as a trust registry for finalized function/class signatures, allowing downstream tasks to dynamically link against concrete code interfaces produced upstream. It outlines an arbitrary-depth parent/child-aware completion ledger, implements recursive failure propagation (where a failing grandchild fails its ancestor epic without deadlocking siblings), and details recursion depth budgets to prevent runaway decomposition. Critically, to ensure safety, all Level 2 features are designed to be **default-off** and **fail-closed** behind config flags.

## 2. Existing Substrate
- **`harness/config.yaml`**:
  - Contains overall parameters, including `decomposition.max_depth` ([config.yaml:L81](file:///home/xnihil0zer0/JanusMaskJR/harness/config.yaml#L81)) and `autowork` flags ([config.yaml:L42-58](file:///home/xnihil0zer0/JanusMaskJR/harness/config.yaml#L42-58)).
- **`harness/config_loader.py`**:
  - Defines parsers like `get_hooks_config` ([config_loader.py:L90-111](file:///home/xnihil0zer0/JanusMaskJR/harness/config_loader.py#L90-111)) that enforce safe type validation for YAML blocks.
- **`harness/orchestrator.py`**:
  - `_auto_commit_accepted` ([orchestrator.py:L3578](file:///home/xnihil0zer0/JanusMaskJR/harness/orchestrator.py#L3578)) executes post-acceptance code actions.
  - `prepare_task_prompt` ([orchestrator.py:L1356](file:///home/xnihil0zer0/JanusMaskJR/harness/orchestrator.py#L1356)) formats the prompt for the executing agent.
  - Lifecycle tracking and failure recovery points ([orchestrator.py:L3603-3613](file:///home/xnihil0zer0/JanusMaskJR/harness/orchestrator.py#L3603-3613)) handle quarantining/blocking crashed tasks.
- **`harness/depth_validator.py`**:
  - `check_true_depth` ([depth_validator.py:L6-75](file:///home/xnihil0zer0/JanusMaskJR/harness/depth_validator.py#L6-75)) validates task lineages.

## 3. Required Changes

| Change | File:Line Anchor | New or Modify | Viability Tag | Oracle-First? | Touches harness/? | Notes |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| Add configuration defaults for Level 2 features | `harness/config.yaml:81` | Modify | `[HAND]` | No | Yes | Add `hierarchical_planning` block (enabled: false). |
| Define configuration schema dataclass and parser | `harness/config_loader.py:113` | Modify | `[GREEN single-symbol]` | Yes | Yes | Implement `HierarchicalPlannerConfig` and `get_hierarchical_planner_config`. |
| Parse signatures and append to ledger upon code acceptance | `harness/orchestrator.py:3578` | Modify | `[YELLOW multi-symbol]` | Yes | Yes | Extract symbols from accepted files and write to `symbol_ledger.jsonl`. |
| Resolve prompt placeholders against ledger signatures | `harness/orchestrator.py:1356` | Modify | `[GREEN single-symbol]` | Yes | Yes | In `prepare_task_prompt`, replace static interfaces with ledger-validated code signatures. |
| Propagate failure state recursively up the DAG | `harness/orchestrator.py:3611` | Modify | `[YELLOW multi-symbol]` | Yes | Yes | If a task transitions to failed/blocked, mark all parent epics as failed/blocked in `impl_progress.jsonl`. |
| Enforce recursion budgets at claim/planning time | `harness/depth_validator.py:45` | Modify | `[GREEN single-symbol]` | Yes | Yes | Short-circuit and quarantine tasks whose brief decomposition depth exceeds budget. |

## 4. New Symbols / New Files

- **`harness/symbol_ledger.py`** (New Module):
  - `def record_symbols(task_id: str, files_touched: List[str], state_dir: Path) -> None:`
    - *Purpose*: Extracts AST function signatures and classes from newly accepted source files and appends them to `state/symbol_ledger.jsonl`.
  - `def resolve_interfaces(interfaces_spec: str, state_dir: Path) -> str:`
    - *Purpose*: Reads `state/symbol_ledger.jsonl` to replace placeholder interface signatures in task specifications with actual implemented signatures.
- **`harness/failure_propagator.py`** (New Module):
  - `def propagate_failure(failed_id: str, state_dir: Path, reason: str) -> List[str]:`
    - *Purpose*: Traces `parent_task` and `parent_epic` lineages upward to mark ancestors as failed/blocked, avoiding sibling deadlocks.

## 5. Data-Flow / Sequence

### 1. Symbol Registration and Dynamic Linking
```
[Task 1 Accepted (x.py)]
      │
      ▼
[AST Parser] ──► Extracts func_a(val: int) -> str
      │
      ▼
[symbol_ledger.jsonl] ◄── Appends signature
      │
      ▼
[Task 2 Staging (depends on Task 1)]
      │
      ▼
[resolve_interfaces()] ◄── Queries signature from ledger
      │
      ▼
[prepare_task_prompt()] ──► Injects exact signature: func_a(val: int) -> str
```

### 2. Failure Propagation Flow
```
[Grandchild Task 1.1.1 Fails]
             │
             ▼
[propagate_failure(task_id="1.1.1")]
             │
             ├─► Marks Child Brief "1.1" as Failed
             │
             └─► Marks Parent Epic "1" as Failed (stops siblings)
```

## 6. Dependencies & Ordering
1. **Level 1 (Prerequisite)**:
   - Level 1 static interfaces and sibling dependency planning must be fully operational (Area A, B, C).
2. **Level 2 (Sequence)**:
   - Config flag schemas must land first to ensure features are disabled during unit tests.
   - Symbol Ledger database (`symbol_ledger.jsonl`) writing and parsing.
   - Failure propagation recursion triggers in `orchestrator.py` finalizers.

## 7. Risks, Red-Zones, and Open Questions
- **AST Parsing Robustness**: The AST parser must handle partial or syntactically strange (but valid) code structures when writing to the ledger without crashing the orchestrator pipeline.
- **Fail-Safe / Default-Off**: The entire system must be gated behind `hierarchical_planning.enabled` in `config.yaml`. If this flag is false, the orchestrator and daemon must fall back to the Level 1 static specification or standard flat planning.
- **Dangling / Orphan Tasks**: When a parent epic is flagged as failed, all in-flight child/grandchild tasks must be immediately reclaimed or marked as blocked to prevent wasted token budgets.

## 8. Anchor Appendix
- [decomposition.max_depth Config](file:///home/xnihil0zer0/JanusMaskJR/harness/config.yaml#L81)
- [get_hooks_config](file:///home/xnihil0zer0/JanusMaskJR/harness/config_loader.py#L90-111)
- [_auto_commit_accepted Call](file:///home/xnihil0zer0/JanusMaskJR/harness/orchestrator.py#L3578)
- [prepare_task_prompt](file:///home/xnihil0zer0/JanusMaskJR/harness/orchestrator.py#L1356)
- [check_true_depth](file:///home/xnihil0zer0/JanusMaskJR/harness/depth_validator.py#L6-75)
- [Pipeline crash reclaiming](file:///home/xnihil0zer0/JanusMaskJR/harness/orchestrator.py#L3603-3613)
