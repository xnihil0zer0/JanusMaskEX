# System Process Outline

This document describes how the verification, testing, and state machine pipelines function, along with their respective authorship boundaries. Refer to [README.md](file:///home/xnihil0zer0/JanusMaskJR/README.md) for full context.

---

## 1. Authorship Roles (Who Authors What)

To prevent conflicts of interest (such as code authorizing its own correctness), the system enforces a strict division of authorship:

*   **The Operator (Human):** Authors the high-level **feature specification** (describing goals, scope, non-goals, and deliverables) and manually creates critical integration tests or system-wide constraints where needed.
*   **The Test-Authoring Agent:** For any task that modifies or adds code, a dedicated agent is tasked with writing the functional test (the **oracle**). 
    *   This agent is given the task specifications and interface requirements but is **completely isolated** from the agents writing the actual implementation.
    *   The test-authoring process runs in a scrubbed environment with its own isolated workspace.
*   **The Implementation Agents (Dual-Agent Synthesis):** Two separate agents independently write the production code to solve the task. They are blind to each other's work and cannot modify the pre-committed tests (oracles) to make their implementations pass.

---

## 2. The Step-by-Step State Machine Pipeline

### Stage A: Specification & Planning
1.  **Parsing:** The pipeline validates the syntax and structure of the operator's feature specification.
2.  **Dual Planning:** Two planning processes independently draft task lists.
3.  **Consolidation:** The system structural-diffs, reconciles, and merges the drafts into a single normalized plan.
4.  **Security/Shape Check:** A validator checks the plan structure (e.g., ensuring tasks that edit code have corresponding test-authoring tasks).

### Stage B: Task Allocation & Queue Management
1.  **Allowlist Promotion:** A background coordinator checks the allowlist; only tasks from approved feature specifications are promoted.
2.  **Dependency Tracking:** Tasks wait in a pending state until all declared prerequisites are completed successfully.
3.  **Atomic Lock:** A worker locks a task by renaming/moving its state record to prevent parallel execution.

### Stage C: Test Pre-Verification (Oracle Validation)
Before any implementation begins, the generated oracle test must prove it is valid:
1.  **The Stub Test:** The test-authoring agent generates the test file.
2.  **Non-Vacuity Check:** The system executes the test against a stubbed/empty implementation (which just raises a placeholder error).
3.  **Approval Gate:** The test is accepted and pre-committed *only* if it **fails** against the stub. This ensures the test is capable of catching missing logic and cannot be trivially bypassed.

### Stage D: Dual-Agent Synthesis
1.  **Generation:** The two implementation agents independently write candidate code.
2.  **Sandbox Isolation:** The code generation processes run inside a secure container where the repository is mounted read-only, preventing the agents from directly modifying active code.

### Stage E: Multi-Tiered Verification Gates
The candidate implementations must pass several automated testing tiers:
1.  **Static & AST Checks:** The code is checked for syntax errors, and parsed to block non-deterministic logic (e.g., random functions, clock time) and forbidden/unsafe execution commands.
2.  **The Oracle Test:** The candidates are run against the pre-committed test written in Stage C. They must pass this test completely.
3.  **Differential Fuzzing:** 
    *   A property-based testing tool generates a large volume of randomized, type-safe inputs.
    *   Both candidates run on these inputs inside a sandbox that blocks system calls, networks, and sub-processes.
    *   If their outputs differ on even a single input, the check fails.
4.  **Integration/Reachability Check:** The system verifies that the new code is reachable and properly integrated from system entry points or configuration files.

### Stage F: Staging & Finalization
1.  **Staging Merge:** Passing code is merged into an isolated staging directory.
2.  **Parent snapshot comparison:** The system diffs the staged branch against a read-only snapshot of the parent branch to ensure no unauthorized files were changed.
3.  **Write Policies:**
    *   *Standard code* is automatically committed.
    *   *Sensitive code* (system internals) is only committed if a signed operator approval file is present (or under automatic approval if strict verification guards are met).
    *   *Irreducible code* (the security/sandboxing core) cannot be modified automatically and must be hand-edited by the owner.
4.  **State Finish/Rollback:**
    *   *Pass:* The changes are merged into the main branch and marked completed.
    *   *Fail:* The changes are discarded, the live tree is rolled back, and the task is moved to a blocked state for retries or self-healing.

---

## 3. System-Level Testing Modes

When verifying the entire codebase, the testing harness uses three execution tiers:
1.  **Impact-Selected Testing:** The fastest loop, which identifies and runs only the tests affected by the latest code changes.
2.  **Parallel Screening:** Runs tests concurrently across multiple processes to quickly catch regressions, although it can be prone to timing variations.
3.  **Authoritative Serial Verification:** The final gate. It runs all tests sequentially in a strict, zero-concurrency environment to ensure no timing or state conflicts cause false results.
4.  **Hermetic Testing Invariant:** All tests must run in isolated temporary folders. The test suites redirect all state writes and database instances to temporary scopes to avoid modifying the live repository during a test run.
