# JanusMaskJR — Agentic Auto-Compiler: Adversarial Security & Reliability Audit

This report compiles the adversarial critiques, structural vulnerabilities, and failure-mode analyses conducted by four parallel subagents regarding the proposed **Agentic Auto-Compiler** architecture and its **JavaScript/TypeScript (Node.js)** pilot extension.

---

## 1. Security & Sandboxing Audit (Security Adversary)

The proposed sandboxing model utilizes kernel-level Bubblewrap (`bwrap`) to isolate task execution. However, binding global host runtimes and maintaining persistent process pools introduces several high-severity security vectors.

### A. Sandbox Path Resolution & Directory Traversal
*   **The Danger of Global `~/.nvm` Mounting**: Bind-mounting the entire `~/.nvm` directory read-only exposes npm registry tokens, cached configuration files, and potential sensitive user credentials. Additionally, parent-directory walks (`node_modules` walking) can allow a jailed package to load packages from the host environment.
*   **Symlink Traversal**: If `~/.nvm` or other bound system paths contain symlinks pointing to sensitive host locations (e.g., `~/.ssh` or `/var/log`), a jailed process can traverse these symlinks to read host files if those files are readable by the user executing `bwrap`.
*   **Unsanitized Version Selection**: Prepending dynamic paths to the sandbox's `PATH` based on repository configuration (e.g., `.nvmrc`) can be exploited. A malicious package could set `.nvmrc` to `../../../../tmp/malicious_node` to execute a host-file hijack. Prepending relative search paths (like `./node_modules/.bin`) allows candidate scripts to hijack common tools.

### B. D-Bus and XDG Socket Escapes
*   **D-Bus Portal Escapes**: Mounting the session D-Bus socket without a filtering proxy allows a jailed process to communicate with host services like `systemd` or desktop portals. A jailed process can use D-Bus message APIs to spawn arbitrary processes or inject keystrokes outside the container, rendering the sandbox void.
*   **Keyring Socket Exposure**: Exposing the keyring socket to the synthesis path allows code to query host credential managers, exfiltrating OAuth tokens, SSH keys, or API tokens.

### C. Persistent Runner Pool Poisoning
*   **Prototype Pollution & Memory Poisoning**: Resetting the runner state by clearing Node's `require.cache` or Python's `sys.modules` does not clean mutations to the global object namespace. A malicious candidate package in Task A can mutate built-ins (e.g., `globalThis.JSON.parse = ...` or `builtins.open`). These mutations persist and will intercept or leak data during subsequent execution of Task B.
*   **Background Process Spyware**: Jailed processes can spawn background workers or threads that survive the execution task. When the next task runs in the same container/process namespace, these background workers can monitor inputs, read memory, and spy on task execution.
*   **Shared `/tmp` Residue**: Files written to `/tmp` or `/dev/shm` persist across runs, allowing task state leakage or file-injection attacks if subsequent tasks load temporary code or data.

---

## 2. AST Splicing & Tree-Sitter Parser Audit (AST Analyst)

Surgically patching code at the AST level using Tree-sitter queries is highly precise but susceptible to structural, dialectal, and formatting failures.

### A. Scope Collisions & Name Shadowing
*   **Shadowed Identifiers**: In JavaScript, variables and helper functions are frequently shadowed in closures or nested blocks. A naive S-expression query targeting `format` can match multiple local bindings, resulting in splicing the replacement code into the wrong scope or class boundary.
*   **Property Key Collisions**: Method definitions in class objects can collide with matching keys inside nested object literals (e.g., `{ update: ... }`), causing the patcher to slice an object key instead of a class method.

### B. Parser Dialect & Module Polymorphism
*   **JSX/TSX Ambiguity**: Parsing TSX code using a standard TypeScript parser fails because the `<` character is syntactically ambiguous (generic parameter constraints vs. JSX tags). The engine must match the exact file type to the correct parser (`tree-sitter-javascript`, `tree-sitter-typescript`, or `tree-sitter-tsx`).
*   **Export Syntax Diversity**: Splicing a function `foo` requires handling diverse export architectures. A single S-expression query cannot match ESM (`export function foo`), CommonJS (`exports.foo = ...` or `module.exports = { foo }`), and lexical bindings (`const foo = () => {}`) without maintaining a fallback query registry.

### C. Decorators, Anonymous Functions, and Semicolons
*   **Decorator Loss**: Splicing a class method definition range often includes its decorator nodes (e.g., `@Injectable`, `@Validate`). If the LLM-generated patch replaces the method definition but omits the decorators, the splicing engine will silently strip the decorators, breaking dependency injection or validation.
*   **Anonymous Arrow Expressions**: Replacing an arrow function expression (`() => {}`) can result in double-declaration syntax errors if the LLM output includes the variable declaration wrapper (`const foo = () => {}`). Conversely, replacing the entire variable statement risks stripping adjacent variables declared in the same line (e.g., `let a = 1, b = 2;`).
*   **Semicolon Duplication**: Automatic Semicolon Insertion (ASI) rules can cause issues. Splicing code that includes or omits trailing semicolons next to existing AST boundaries can lead to double semicolons (`;;`) or statement grouping syntax errors.

### D. Indentation Drift & Linter Autofix Cascades
*   **Template Literal Spacing**: Auto-indenting a patch to match the parent symbol's start column modifies space formatting within template strings (backticks). This alters runtime string contents, breaking test expectations.
*   **Linter Cascades**: Running `eslint --fix` or `prettier` post-patch can modify lines outside the target symbol (e.g., removing unused imports, sorting exports). This breaks git tracking and invalidates coordinates of other parallel symbol patches.

---

## 3. Fuzzing & Type-System Mapping Audit (Fuzzing Critic)

Hypothesis-driven differential fuzzing relies on converting types to input strategies and comparing outputs over IPC. JS/TS runtime behaviors introduce unique mapping friction.

### A. Type Complexity and Untyped JS
*   **Expressive TS Types**: Statically mapping TypeScript union types (`string | number[]`), intersections, utility types (`Partial<T>`), or generics (`T`) to Hypothesis strategies requires a full type-checker. Simple Tree-sitter syntax parsing cannot resolve these types.
*   **Unstructured Object Mocks**: Mapping the JS `object` type to a plain JSON dictionary strategy fails when the target function calls methods on the object (e.g., `db.query()`). Passing a plain dictionary causes immediate `TypeError` crashes, polluting the self-healing loop.
*   **Untyped JavaScript**: In plain JS, the absence of type signatures forces a generic strategy fallback. The input search space explodes, making the generation of semantically valid objects near impossible.

### B. Non-JSON JS Constructs
*   **Promises and Callbacks**: The JSON Line IPC bridge cannot serialize JS Promises or callback functions. If a function returns a Promise, the runner must explicitly `await` it. If a Promise deadlocks, the entire runner pool will hang without an isolated timeout guard.
*   **Prototype Mismatches**: Deserialized JSON objects lose prototype links. If code asserts `obj instanceof MyClass` or uses accessors (getters/setters), fuzzed inputs will fail verification.
*   **Native Classes**: JS natives like `Set`, `Map`, `Buffer`, `TypedArray`, and `RegExp` serialize to empty objects `{}` or string encodings under standard JSON serialization, losing their structure.

### C. Behavioral Equivalence Pitfalls
*   **Floating Point Mismatches**: JS and Python handle math edge cases differently (e.g., division by zero evaluates to `Infinity`/`NaN` in JS, but raises `ZeroDivisionError` in Python).
*   **Null vs. Undefined**: JavaScript distinguishes between `null` (intentional absence) and `undefined` (lack of value). Pythons maps both to `None`. Collapsing `undefined` to `null` prevents the fuzzer from testing ES6 default arguments or detecting missing-parameter exceptions.

---

## 4. Performance, Memory, & IPC Audit (Performance Auditor)

High-throughput compilation loops require low-latency execution, but process communication and caching boundaries present limits.

### A. ESM Module Cache Limitations
*   **V8 ESM Caching**: In Node.js, standard cache-clearing (`delete require.cache[path]`) **does not work** for ES modules (ESM). V8 caches loaded ES modules internally.
*   **Memory Accumulation**: To bypass V8's ESM cache, developers often append query parameters (e.g., `import(`./file.js?update=${Date.now()}`)`). This causes V8 to continuously load new module versions into the heap, leading to memory leaks and Resident Set Size (RSS) bloat during iterative compilation runs.
*   **Python Reference Leaks**: In Python, `importlib.reload()` does not update references bound via `from module import function` in other active modules, leading to stale code execution.

### B. IPC Protocol Bottlenecks
*   **JSON Serialization CPU Overhead**: High-frequency fuzzing loops sending large input batches experience CPU serialization overhead.
*   **OS Pipe Deadlocks**: Standard OS pipes have a 64KB buffer limit on Linux. If the parent and child block writing to each other simultaneously over stdout/stdin, the process deadlocks.
*   **Stdout Pollution**: Logs or diagnostic output (e.g., `console.log`) written by the candidate package interleave with the IPC JSON stream, corrupting the line protocol.

---

## 5. Audit Recommendations & Mitigation Action Plan

To harden the Agentic Auto-Compiler and implement the JS/TS extension safely, the following engineering patterns must be implemented:

### Sandbox & Execution Isolation
1.  **Ephemeral Worker Forks**: Instead of reloading modules inside a single process, the runner process should pre-warm the environment, and then use OS-level `fork()` (via `child_process.fork` in Node or `fork` in Python) to execute each batch. The child fork runs the fuzzer and terminates immediately, guaranteeing zero state pollution and no V8 ESM cache leaks.
2.  **Explicit Namespace SIGKILL**: Ensure every execution run terminates all processes in its pid namespace. Use a process-group SIGKILL (`-pid`) to kill background workers or async loops spawned by the candidate.
3.  **Strict Path and Version Pinning**: Bind-mount only the exact subpath of the active Node runtime (e.g., `~/.nvm/versions/node/v22.0.0/bin/node`). Do not mount global project trees. Enforce strict regex validations (`^v\d+\.\d+\.\d+$`) on `.nvmrc` and config version strings.
4.  **No Direct D-Bus Session Mounts**: Unshare the IPC namespace (`--unshare-ipc`) and block direct access to keyring/session sockets.

### AST Patching Reliability
1.  **Scope-Aware S-Expressions**: S-expression queries must match the target identifier while validating its parent node hierarchy (e.g., checking that a method belongs to the target class block) to avoid shadowing collisons.
2.  **Fallback Query Registry**: Maintain separate queries for ES6 exports, CommonJS exports, and variable assignments, checking each until a valid node range is resolved.
3.  **Decorator Preservation Guard**: The patching engine must identify if a node is decorated and explicitly prepend the decorators to the new code block during splicing.
4.  **Template Literal Exclusion**: AST coordinates representing template strings (`template_string` nodes) must be excluded from auto-indentation spacing rules.

### Fuzzing & IPC Hardening
1.  **Separate Logging File Descriptors**: Redirect the IPC communication to a custom file descriptor (e.g., FD 3) rather than stdout, preventing `console.log` statements from corrupting the JSON stream.
2.  **Asynchronous IPC Bridge**: The `js_runner.js` must check if the returned value is a Promise, explicitly `await` it, and wrap the run in a strict timeout guard using `Promise.race()`.
3.  **Strict Primitive Mapping**: The runner must map `undefined` to a special JSON sentinel object (e.g., `{"__sentinel__": "undefined"}`) and preserve it over the IPC line to ensure parameter defaulting is fuzzed accurately. Compare NaN/Infinity values using strict `Object.is()` wrappers.
