# Academic Research: Prompt Distillation, Behavior Distillation, and Automated Harness/Verification Synthesis

This report reviews and synthesizes key academic literature, frameworks, and methodologies concerning how to:
1. Distill agent rules, heuristics, and behaviors from LLM traces.
2. Perform prompt distillation/compression.
3. Automatically synthesize checkers, verifiers, and test harnesses from execution traces.
4. Apply these concepts, alongside DeepMind's **AlphaProof Nexus** evolutionary architecture, to develop a concrete methodology for **"Harness Distillation"** (formalizing lost heuristics between high-metadata and low-metadata execution runs into scripted verification gates).

---

## 1. Literature Review

### A. Behavior Distillation & Rule Extraction
Behavior distillation refers to extracting policies, heuristics, or reasoning patterns from a larger model (or search process) into either smaller models or explicit symbolic representations.

*   **MCTS Trajectory Distillation (e.g., AlphaLLM-CPL):** In search-guided reinforcement learning loops, search traces from Monte-Carlo Tree Search (MCTS) are synthesized and distilled into step-by-step reasoning tokens. Rather than learning just final outcomes, models are trained to mimic step-level value functions and search paths.
*   **Neurosymbolic Extraction:** Methods exist to map the policy or tool-use trajectories of LLM agents into deterministic structures like decision trees, graph state-machines, or Answer-Set Programming (ASP) specifications.
*   **Separation of Concerns (e.g., Parlant, Explicit Rules Engines):** Instead of encoding all behavioral rules in prompts, modern agent loops split heuristics into runtime-enforced symbolic constraints, ensuring that mandatory validation steps cannot be bypassed or "hallucinated" away by the LLM.

### B. Prompt Distillation & Compression
Prompt distillation and compression focus on minimizing context overhead and preserving performance:
*   **Prompt Distillation:** Teacher models with highly optimized system prompts generate task trajectories that train student models to replicate reasoning behaviors without needing long prefix prompts.
*   **Prompt Compression (e.g., LLMLingua):** Focuses on dropping redundant tokens, semantic components, or non-essential execution details via token entropy budgets. In agent loops, compression preserves essential structural indicators (such as `[THOUGHT]`, `[ACT]`, `[OBSERVATION]`) while shedding verbosity.

### C. Automated Harness & Checker Synthesis
*   **PrefixGuard & Trace Monitors:** Monitors are induced from agent execution traces to create online guardrails. If an agent's current trace starts deviating from patterns observed in successful runs, the monitor triggers an intervention.
*   **AutoHarness & AgentFlow:** These frameworks generate domain-specific language (DSL) graphs or Python scripts to run alongside agents. They parse execution histories, dynamically creating assertions and validation scripts that prevent repetitive agent mistakes.
*   **KNighter:** Demonstrates high-precision static checker synthesis from historical bug/patch traces, refining checkers iteratively to minimize false positives.

---

## 2. Analysis of AlphaProof Nexus (DeepMind, May 2026)
*Reference paper: [AlphaProof Nexus](https://arxiv.org/html/2605.22763v1)*

AlphaProof Nexus achieves research-level math theorem-proving by framing formal proof-search as an evolutionary optimization problem over **proof sketches** (Lean code with `sorry` placeholders).

### Key Architectural Elements:
1.  **Population Database of Sketches:** Instead of single-shot dual-agent agreements, the orchestrator maintains a persistent population of candidate proof sketches.
2.  **Tournament-Based Matchmaking:** Flash models (Gemini 3.0 Flash) sample sets of $P=7$ sketches and rank them pairwise based on proof plausibility, strategy clarity, and novelty.
3.  **Elo-Based Rating:** Rather than a binary "passes compilation" signal, tournament rankings are processed using a Plackett-Luce distribution and Gibbs sampling to assign continuous Elo scores to sketches.
4.  **Selection (P-UCB):** Parent sketches are sampled from the elite top-64 candidates using a Predictive Upper Confidence Bound (P-UCB) formula to balance exploitation of high-Elo sketches with exploration of under-sampled lineages:
    $$\text{Score} = q + c \frac{\sqrt{\sum V_i}}{v+1}$$
5.  **Global Goal Caching:** Subgoals across the population are hashed. If any subagent solves a goal, the tactic sequence is instantly shared with all other lineages attempting that goal.

---

## 3. Harness Distillation Methodology

### The Objective
In agent systems, running with **rich metadata** (AST diffs, compilation logs, runtime trace trees) results in high-quality code generations but suffers from high cost and latency. Running with **poor metadata** (plain prompts, simple test failures) is fast and cheap but leads to subtle regression failures, bypasses (e.g., stubs, mock returns), and loss of safety constraints.

**Harness Distillation** is the automated process of:
1.  Isolating the behavior difference between successful runs (with rich metadata) and failed runs (without metadata).
2.  Identifying the exact heuristic or rule that was lost when metadata was ablated.
3.  Translating that lost heuristic into a deterministic, static test harness gate or static analyzer.

```
+---------------------------------------+
|  Successful Run (Rich Metadata)       |
+---------------------------------------+
                   |
                   v (Ablation / Diff)
+---------------------------------------+
|  Failed Run (Low/No Metadata)         |
+---------------------------------------+
                   |
                   v (Analyze Trace Diff)
+---------------------------------------+
|  Identify Lost Rule/Heuristic          |
+---------------------------------------+
                   |
                   v (Synthesize Checker)
+---------------------------------------+
|  Static Verification Gate (Harness)   |
+---------------------------------------+
```

### The Concrete Step-by-Step Procedure

#### Step 1: Trace Differential Extraction
For a given set of development tasks, execute the generator agent under two conditions:
*   **Trace A (Rich):** Agent has access to comprehensive AST checkers, compilation step-feedback, and differential fuzzing.
*   **Trace B (Ablated):** Agent runs with a minimal prompt containing only code context and standard error outputs.
Extract the execution steps, code diffs, tool calls, and parser outcomes from both traces.

#### Step 2: Heuristic Gap Analysis
Pass the trace diffs to an LLM evaluator to isolate the root cause of failures in Trace B. The evaluator identifies the "lost rule." Common examples include:
*   *Mocking/Bypassing:* Agent wrote `return True` or raised `NotImplementedError` in a helper method to pass a shallow type checker.
*   *AST Bleeding:* Agent changed code outside the designated target blocks.
*   *Import Drops:* Agent redefined imports in a helper function, dropping module aliases needed by other parts of the codebase.

#### Step 3: Harness Code Synthesis
Using the extracted heuristic, the synthesis engine writes a static checker or validation rule in Python.
For example, if the agent bypassed logic by returning a static boolean constant in ablated runs, the synthesis engine generates an **AST Vacuity Checker**:

```python
import ast

class ASTVacuityChecker(ast.NodeVisitor):
    def __init__(self):
        self.errors = []
        
    def visit_FunctionDef(self, node):
        # Check if the body only returns a constant or raises an error
        if len(node.body) == 1:
            stmt = node.body[0]
            if isinstance(stmt, ast.Return) and isinstance(stmt.value, ast.Constant):
                self.errors.append(f"Function {node.name} returned a static constant: {stmt.value.value}")
            elif isinstance(stmt, ast.Raise) and isinstance(stmt.exc, ast.Name) and stmt.exc.id == 'NotImplementedError':
                self.errors.append(f"Function {node.name} contains a NotImplementedError stub.")
        self.generic_visit(node)
```

#### Step 4: Verification Integration
This checker is dynamically registered as a pre-commit gate or execution gate in the agent sandboxed environment, programmatically turning a fluid "heuristic" into a hard, fast, and deterministic boundary.

---

## 4. Implementation Guidelines for JanusMaskJR

To operationalize this methodology in the repository:
1.  **Harness Scripts:** Store all synthesized validation rules in [harness/](file:///home/xnihil0zer0/JanusMaskJR/harness/).
2.  **Dynamic Gate Registration:** Introduce a plugin-based hook architecture in [overseer/](file:///home/xnihil0zer0/JanusMaskJR/overseer/) that reads rules from [autocompiler_research/](file:///home/xnihil0zer0/JanusMaskJR/autocompiler_research/) and appends them to the active verification pipeline before committing code to production branches.
