# Academic Paper Summary: Type-level Property Based Testing

* **Title:** Type-level Property Based Testing
* **Authors:** Thomas Ekström Hansen and Edwin Brady (University of St Andrews)
* **Venue:** Proceedings of the 9th ACM SIGPLAN International Workshop on Type-Driven Development (TyDe 2024), co-located with ICFP 2024
* **arXiv ID:** [2407.12726](https://arxiv.org/abs/2407.12726)
* **Official Repository:** [CodingCellist/tyde-24-code](https://github.com/CodingCellist/tyde-24-code)

---

## 1. Core Problem & Motivation
In standard software verification, two main paradigms exist:
1. **Type Checking / Formal Verification:** Statically proving properties about programs using dependent types or theorem provers. While powerful, this requires significant developer effort, writing complex proofs, and can lead to heavy compilation times.
2. **Property-Based Testing (PBT):** Dynamically generating random test inputs to search for counterexamples to a specified property (e.g., QuickCheck, Hypothesis). PBT is highly automated and effective at finding bugs, but it runs at runtime and does not offer compile-time guarantees.

Hansen and Brady address this division by asking: **Can we bring property-based testing into the compiler's type-checking phase?** By executing PBT at compile-time (elaboration-time), we can find bugs and verify properties during compilation, ensuring that a program only compiles if it passes its test suites, with zero runtime overhead.

---

## 2. Methodology & Key Concepts
The paper implements compile-time PBT in **Idris 2**, a dependently typed programming language where types are first-class citizens.

### A. Elaboration-Time Execution
Idris 2 supports execution of arbitrary code during elaboration (the phase where types are analyzed and code is generated). The authors exploit this by running a custom QuickCheck library within the compiler.
* If a property-based test passes, the compiler finishes compilation normally.
* If a test fails, the compiler halts compilation with an elaboration error, printing the exact counterexample (input values) that violated the property.

### B. Type Erasure & Zero Runtime Cost
Since the generators, test runners, and assertions execute entirely during elaboration, the test logic is completely erased from the final compiled binary. There is zero runtime performance penalty.

### C. State Machine Verification using Indexed State Monads (ISMs)
To model complex stateful systems (e.g., network protocols, ATMs), the authors use **Indexed State Monads**. 
* The states and valid transitions are represented at the type level.
* QuickCheck generators are written to automatically generate valid sequences of state transitions.
* The elaboration-time PBT framework runs these sequences against the implementation to verify behavioral equivalence and compliance with the state transitions.

---

## 3. Key Findings & Contributions
1. **Elaboration-Time QuickCheck:** A fully functional QuickCheck implementation in Idris 2 that runs during compile-time.
2. **Validation of Stateful Systems:** Demonstrated compilation-time PBT of:
   * A stateful ATM protocol (validating card insertion, PIN entry, withdrawal, and state resets).
   * A stateful network communication protocol.
3. **Hybrid Verification Workflow:** Developers get the best of both worlds—rapid feedback on incorrect implementations via compilation errors, combined with the power of dependent types for core invariants.

---

## 4. Relevance to JanusMaskJR (Agentic Compilation)
For the JanusMaskJR autocompiler project, this research is directly applicable in several ways:

1. **Type-Driven Strategy Generation:**
   * In JS/TS or Python, type annotations (like interfaces, Pydantic models, or type hints) represent the "shapes" of data.
   * We can translate these type annotations into QuickCheck/Hypothesis strategies. This paper shows that this strategy generation can be formally linked to state machine transitions, validating that mutated or optimized code matches the original type invariants.
2. **Proving Behavioral/Functional Equivalence:**
   * When compiling or refactoring, we want to prove that the target code behaves identically to the source code.
   * By translating type annotations into strategies, we can automatically fuzz both source and target implementations using the generated strategies to prove behavioral equivalence at build time.
3. **Build-Time Oracles:**
   * Rather than shipping heavy validation and test logic in the production bundles, we can perform differential fuzzing and type-level assertions during the compilation pipeline, catching semantic deviations before release.
