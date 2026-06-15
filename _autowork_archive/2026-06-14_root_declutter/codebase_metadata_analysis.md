# JanusMaskJR Codebase Metadata Analysis Report

This report analyzes how the JanusMaskJR harness uses metadata (briefs, plan hooks, configuration documents, and validation constraints) to direct, validate, and evaluate code synthesis and planning agents. It details the mechanisms in [harness/](file:///home/xnihil0zer0/JanusMaskJR/harness) and [overseer/](file:///home/xnihil0zer0/JanusMaskJR/overseer), designs an ablation experiment framework, and proposes a pathway to distill behavioral failures into automated static/dynamic checks.

---

## 1. Executive Summary
The JanusMaskJR harness uses a highly structured, procedurally-gated workflow. It enforces constraints on agents at multiple stages:
* **Workflow / Procedural Phase Enforcement**: Monitored by [overseer/](file:///home/xnihil0zer0/JanusMaskJR/overseer), preventing agents from taking actions (like raw edits or early git commits) inconsistent with their current procedure phase.
* **Planning & Spec Generation**: Dictated by frontmatter-aware markdown briefs and plan templates.
* **Prompt Injection & Execution Jail Isolation**: Staged in isolated CWD sandboxes where metadata files are injected into `inbox/task.json`.
* **Static Correctness Gating**: AST-level checks mapping security, reproducibility, structure, and type signature compatibility.
* **Dynamic Behavior Gating**: High-throughput type-aware differential fuzzing in sandboxed environments.

---

## 2. Metadata Architecture: Loading, Parsing, and Prompt Injection

### 2.1 Brief Status and Eligibility Rollups
The system monitors briefs and plan templates using [harness/brief_status.py](file:///home/xnihil0zer0/JanusMaskJR/harness/brief_status.py). Key functions include:
* [compute_brief_status](file:///home/xnihil0zer0/JanusMaskJR/harness/brief_status.py#L4): Scans for `brief_hooks_*.md` files and matches them against `plan_hooks_*.json` documents. It tracks which tasks are complete, in flight, queued, or blocked.
* [compute_autowork_eligibility](file:///home/xnihil0zer0/JanusMaskJR/harness/brief_status.py#L111): Determines if a brief is allowed to proceed to planning/execution by checking a promotion allowlist (`auto_promote.allowlist`) and verifying mtime age limits.
* [compute_epic_status](file:///home/xnihil0zer0/JanusMaskJR/harness/brief_status.py#L151): Coordinates the status of epic-level briefs and resolves child slug task statuses. It implements transitive failure propagation where a failure in any child slug blocks the parent epic.

### 2.2 Brief Loading and Validation
During planning, markdown briefs are loaded and parsed by [harness/planner/brief_loader.py](file:///home/xnihil0zer0/JanusMaskJR/harness/planner/brief_loader.py).
* The [PlanningBrief](file:///home/xnihil0zer0/JanusMaskJR/harness/planner/brief_loader.py#L27) dataclass stores parsed sections: `title`, `scope`, `non_goals`, `inputs`, `deliverables`, `dependencies`, and `interfaces`.
* [load_brief](file:///home/xnihil0zer0/JanusMaskJR/harness/planner/brief_loader.py#L160) validates frontmatter metadata (e.g. complexity scores, dependencies) and markdown structure, rejecting files with duplicate frontmatter keys or missing required headings.
* The brief contents are injected into planning agent prompts via [to_agent_prompt](file:///home/xnihil0zer0/JanusMaskJR/harness/planner/brief_loader.py#L42).

### 2.3 Task Inbox Staging and Prompt Injection
For code synthesis, tasks are read from plan files and written as individual `state/tasks/<task_id>.json` objects. When the orchestrator executes a task:
* The helper [_stage_inbox](file:///home/xnihil0zer0/JanusMaskJR/harness/orchestrator.py#L4348) copies `current_task_<task_id>.json` into `inbox/task.json` in the agent's work directory.
* For multi-file or partial edit tasks, [_stage_targets](file:///home/xnihil0zer0/JanusMaskJR/harness/orchestrator.py#L4412) copies the current on-disk content of each targeted file to `inbox/targets/<rel-path>` so that CWD-isolated agents have read access.
* The orchestrator's [prepare_task_prompt](file:///home/xnihil0zer0/JanusMaskJR/harness/orchestrator.py#L1499) appends the task description as a brief overview while instructing the agent to read `inbox/task.json` for detailed acceptance criteria.

### 2.4 Overseer Procedural Gates and PreToolUse Hooks
The [overseer/](file:///home/xnihil0zer0/JanusMaskJR/overseer) implements strict verification gates that prevent agents from bypassing constraints:
* **Deterministic Gates**: [overseer/gates.py](file:///home/xnihil0zer0/JanusMaskJR/overseer/gates.py) defines functions like [brief_lint](file:///home/xnihil0zer0/JanusMaskJR/overseer/gates.py#L64) (checks that briefs contain exactly one target file and no line-number citations) and [plan_preflight](file:///home/xnihil0zer0/JanusMaskJR/overseer/gates.py#L87) (enforces that plans contain non-generic task IDs and at least two regression tests).
* **PreToolUse Hooks**: [overseer/procedure_hook.py](file:///home/xnihil0zer0/JanusMaskJR/overseer/procedure_hook.py) blocks raw agent actions. For example, [evaluate](file:///home/xnihil0zer0/JanusMaskJR/overseer/procedure_hook.py#L125) and [decide](file:///home/xnihil0zer0/JanusMaskJR/overseer/procedure_hook.py#L150) block raw file writes to `brief_hooks_*.md` if the active procedure phase is prior to `BRIEF`, or block git commits if the oracle has not been proven `RED` (failing).

---

## 3. Measuring Agent Correctness and Performance

### 3.1 Static Analysis Gating via AST Enforcement
Static validation of agent submissions is managed in [harness/ast_enforcer.py](file:///home/xnihil0zer0/JanusMaskJR/harness/ast_enforcer.py) using the [validate_code](file:///home/xnihil0zer0/JanusMaskJR/harness/ast_enforcer.py#L187) entrypoint.
* **Reproducibility**: Flags non-deterministic imports (`random`, `uuid`) and calls (`time.time()`, `datetime.now()`, `os.urandom()`).
* **Security Constraints**: Bans dangerous calls (`eval()`, `exec()`, `__import__()`, `os.system()`) and flags hardcoded credentials using a regex search on assignment names.
* **Unbounded Recursion**: Warm-flags recursive function calls that lack an preceding `if` or `return` statement in the AST body.
* **Return Type Reconciliation**: Compares the implementation's return annotation against the brief's declared signature via [validate_return_type](file:///home/xnihil0zer0/JanusMaskJR/harness/ast_enforcer.py#L357), using AST normalizations to reconcile loose vs tight annotations (e.g. matching `dict` against `dict[str, Any]`).
* **Baseline Violation Diffing**: In [harness/orchestrator.py](file:///home/xnihil0zer0/JanusMaskJR/harness/orchestrator.py), [_compute_target_baseline_violations](file:///home/xnihil0zer0/JanusMaskJR/harness/orchestrator.py#L4305) analyzes the original file to compute baseline violations. These pre-existing violations are filtered out so that agents are not penalized for legacy code.

### 3.2 Dynamic Behavior Gating via Differential Fuzzing
[harness/diff_fuzzer.py](file:///home/xnihil0zer0/JanusMaskJR/harness/diff_fuzzer.py) performs type-aware input fuzzing of code submissions.
* **Type-Aware Strategy Generation**: [build_input_strategy](file:///home/xnihil0zer0/JanusMaskJR/harness/diff_fuzzer.py#L506) parses function signatures and maps annotations to Hypothesis strategies.
* **Corpus Injection**: For complex type annotations (e.g., `ast.AST` or `pathlib.Path`), the fuzzer resolves inputs via structured corpora (`_AST_STMT_CORPUS`, `_PATH_CORPUS`) instead of falling back to raw inputs, allowing the rebuild of complex AST-transform systems to be gated by differential tests.
* **Comparison Engine**: [outputs_match](file:///home/xnihil0zer0/JanusMaskJR/harness/diff_fuzzer.py#L524) checks execution outputs across float tolerances (via `math.isclose`), collection structural equivalence, and matched exceptions.
* **Fail-Closed Boundary (M4/INV-5)**: If Hypothesis generation fails or yields zero inputs, the fuzzer rejects equivalence to prevent false passes.
* **Stateful Fuzzing**: Compares classes by generating symbolic, serializable call sequences that run on both codebases in parallel sandboxes.

---

## 4. Ablation Experiment Framework Design

Ablation experiments allow us to measure the performance impact of removing specific metadata (such as briefs, explicit constraints, or diagnostic backtrace logs). 

### 4.1 Framework Implementation Strategy
We can implement an automated harness runner script inside a scratch file: [harness_ablation_runner.py](file:///home/xnihil0zer0/JanusMaskJR/harness/harness_ablation_runner.py). This runner executes trials under four ablation configurations:
1. **Full Metadata (Baseline)**: Task runs normally with all plan inputs, files_touched list, acceptance criteria, and function signatures.
2. **Brief Prose Ablation**: Empties or simplifies `spec.objective`, `spec.functional_requirements`, and `acceptance_criteria` in the task JSON.
3. **Constraint / Signature Ablation**: Strips type constraints and signature information (`function_signature`) to force the fuzzer to fall back to generic integer strategies, and skips type checks.
4. **Retry/Feedback Ablation**: Prevents the self-heal retry loop from injecting diagnostic stack traces or fuzz error logs into the corrected spec during retries.

### 4.2 Code Structure: Ablation Script
Below is the python script template to be run from the workspace to log agent success/failure rates under ablated metadata conditions:

```python
import json
import shutil
import subprocess
from pathlib import Path

def setup_ablation_task(original_task_path: Path, target_dir: Path, configuration: str):
    with open(original_task_path, 'r') as f:
        task = json.load(f)
    
    if configuration == 'no_brief_prose':
        task['spec']['functional_requirements'] = []
        task['spec']['objective'] = "Implement the function."
        task['acceptance_criteria'] = []
    elif configuration == 'no_constraints':
        if 'constraints' in task:
            task['constraints'].pop('function_signature', None)
        task['spec'].pop('interfaces', None)
    elif configuration == 'no_retry_feedback':
        # Strip traceback/fuzz error logs from retries
        if 'errors_str' in task:
            task['errors_str'] = ""
    
    # Save the ablated task to the staging area
    staged_path = target_dir / original_task_path.name
    with open(staged_path, 'w') as f:
        json.dump(task, f, indent=2)
    return staged_path

def run_trial(task_id: str, configuration: str, state_dir: Path):
    # Setup test workspace environment
    tasks_dir = state_dir / 'tasks'
    tasks_dir.mkdir(parents=True, exist_ok=True)
    
    # Clean previous runs
    processed_marker = tasks_dir / 'processed' / f'{task_id}.json'
    if processed_marker.exists():
        processed_marker.unlink()
        
    original_task = Path('epic4_handauthored_reference') / f'{task_id}.json'
    staged_task = setup_ablation_task(original_task, tasks_dir, configuration)
    
    # Dispatch task via single iteration orchestrator run
    print(f"Running trial for task={task_id} config={configuration}...")
    proc = subprocess.run([
        'python', '-m', 'harness.orchestrator', 
        '--state-dir', str(state_dir)
    ], capture_output=True, text=True)
    
    # Check outcome
    is_accepted = False
    ledger_path = state_dir / 'impl_progress.jsonl'
    if ledger_path.exists():
        with open(ledger_path, 'r') as f:
            for line in f:
                row = json.loads(line)
                if row.get('task_id') == task_id and row.get('phase') == 'accepted':
                    is_accepted = True
                    break
                    
    return {
        'task_id': task_id,
        'configuration': configuration,
        'accepted': is_accepted,
        'stdout': proc.stdout,
        'stderr': proc.stderr
    }
```

---

## 5. Distillation of Behavioral Differences into Scripted Pathways

When ablation trials show that an agent fails (e.g., introducing a security vulnerability because it lacks rules, or failing empty/boundary inputs because type constraints are absent), we can programmatically close these gaps by distilling the failures into permanent verification pathways in the harness.

### 5.1 Static Constraint Generation (AST Level)
If the agent introduces disallowed constructs when metadata is relaxed, we can dynamically compile these into permanent rule assertions in [harness/ast_enforcer.py](file:///home/xnihil0zer0/JanusMaskJR/harness/ast_enforcer.py):
* **Banned Construct Expansion**: Parse the failed submission's AST and extract used nodes. If the ablated agent called a dangerous module or function not originally explicitly locked down, compile it into `_SIDE_EFFECT_NAMES` or `_ValidationVisitor`.
* **Signature Assertions**: Automatically generate type-checking constraints on functions. If the agent implements a function signature incorrectly under ablation, write an AST-check hook that asserts the presence of type annotations.

### 5.2 Dynamic Constraint Generation (Fuzzer Level)
If the agent misses boundary conditions or raises unhandled exceptions under ablated trials:
* **Hypothesis Boundary Pre-seeding**: Identify the exact inputs that caused the divergence in [outputs_match](file:///home/xnihil0zer0/JanusMaskJR/harness/diff_fuzzer.py#L524). Integrate these inputs (such as empty collections, extreme floats, or spec-specific edge values) directly into the Hypothesis strategy definitions using `st.just()` or by appending them to the default search corpora.
* **Property Assertions**: Convert the divergence failure reasons (e.g., `length_mismatch`) into structural assertion checks inside the fuzzer execution. For example, if a list length mismatch is found, dynamically configure the fuzzer to enforce strict element-wise bounds for subsequent agent iterations.
