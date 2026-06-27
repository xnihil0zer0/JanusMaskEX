
## Brief tighten pass (2026-06-12)
- model-backends: 225 -> 72 lines. Dropped embedded code skeletons (oracle carries contract); kept interfaces line, BackendSpec(kind,provider_id,...) contract, BACKEND_REGISTRY provider list, 3-task plan shape.
- config-schema: 88 -> 69 lines. Tightened cross-field prose; kept both KNOWN-BUG-TO-FIX contracts (role-value propagation, save-key nesting), 2-task plan shape.
- Both: added the consolidated AST-CREDENTIAL GATE block (ast_enforcer.py:78, OVERSEER_KEY/key cause + impl & oracle-author rules) near top.
- Invariants verified: 5 bare headings, meta_task_type:harness_self_fix, dependencies:[], interfaces line, "integration" in Non-Goals.
