# Academic Paper Summary: Sandlock
**Title**: Sandlock: Confining AI Agent Code with Unprivileged Linux Primitives  
**Authors**: Cong Wang, Yusheng Zheng  
**Publication**: arXiv:2605.26298v1 (Multikernel Technologies Inc., UCSC) - May 2026  
**PDF Path**: [sandlock_confining_agent_code.pdf](file:///home/xnihil0zer0/JanusMaskJR/autocompiler_research/sandlock_confining_agent_code.pdf)

---

## 1. Core Objectives & Scope
The paper addresses the safety threat posed by autonomous AI agents executing untrusted, model-generated shell commands and scripts directly on developer workstations. Off-the-shelf isolation tools (like Docker or gVisor) introduce high startup latencies (~100–300 ms), require root privileges, or require complex container image management. The authors present **Sandlock**, a lightweight Rust-based Linux process sandbox that offers unprivileged, sub-10ms startup containment using native Linux kernel primitives while allowing programmable, runtime-dependent security policies.

## 2. Key Contributions
1. **Split Enforcement Model**: Separates static, input-independent security policies (enforced in-kernel via Landlock and seccomp-bpf) from dynamic, runtime-dependent policies (enforced in-user-space via a seccomp user-notification supervisor).
2. **Unprivileged & Low Latency**: Runs entirely without root privileges, cgroups, or pre-provisioned namespaces. Adds only ~5 ms of startup overhead and incurs no measurable runtime performance penalty (Redis benchmark runs at native bare-metal speeds).
3. **Programmable Policies (`policy_fn`)**: Provides a TOCTOU-safe runtime callback hook (exposed to Python/Rust) allowing the host application to inspect syscall details (such as the arguments of `execve` or network connection endpoints) and adjust security policies dynamically.
4. **Copy-on-Write (COW) Workspace**: Captures all filesystem modifications in an unprivileged, seccomp-driven workspace, allowing commits or rollbacks of file changes upon execution completion.
5. **Heterogeneous Confinement Pipelines**: Supports connecting sandboxed processes via pipes where each pipeline stage runs with a different security profile (enabling kernel-enforced capability separation).

---

## 3. Methodology & System Architecture
Sandlock relies on a combination of three Linux kernel primitives:
* **Landlock LSM**: Used to define static, kernel-enforced constraints on filesystem read/write paths, TCP ports, and IPC boundaries. This operates with zero supervisor overhead.
* **seccomp-bpf**: Filters out unsafe or unused system calls and routes specific syscalls (like `connect`, `execve`, `openat`, `bind`) to the supervisor.
* **seccomp user notification & `pidfd_getfd`**: The supervisor (an async Tokio task running in the parent process) intercepts dynamic syscalls, validates their arguments in a TOCTOU-safe manner (by copying parameters to parent memory and freezing sibling threads via ptrace seize/interrupt commands), and acts on behalf of the child process.
* **Network & HTTP Mediation**: Redirects out-of-sandbox TCP/UDP requests to a local proxy to validate hostnames, ports, and even specific HTTP paths/methods.
* **Unprivileged COW Filesystem**: Sandlock uses either a seccomp-based write redirector or a custom kernel/user module (`BranchFS`) to redirect write operations to an upper scratch directory, enabling speculative execution with easy rollback.

---

## 4. Key Findings & Results
* **Performance**:
  * **Startup latency**: Sandlock starts in ~6 ms, compared to ~250–300 ms for rootless Docker and ~30 ms for bubblewrap/nsjail.
  * **Runtime throughput**: Redis GET/SET benchmarks run under Sandlock at 100% of bare-metal performance, whereas Docker achieves only ~74–77% throughput.
  * **COW Fork Performance**: Sustains ~1,900 sandboxed forks per second, making it viable for map-reduce agentic architectures.
* **Security & Confinement**: Successfully blocks unauthorised reads, out-of-allowlist network calls, fork bombs, and memory exhaustion while allowing legitimate system activities.
* **Workstation Compatibility**: Unmodified interpreters (Python, Node.js) and standard CLI tools (`make`, `pytest`, `curl`) run correctly, only requiring permissions for their respective temporary paths.

---

## 5. Relevance to Autocompilation & Safe Execution
* **Safe Agent Workstations**: Crucial for running LLM-generated code locally. Developers can run compilation, tests, and installations safely without risking their private home directories, SSH keys, or environment variables.
* **Speculative Executions**: The copy-on-write workspace is highly relevant to "self-healing" or "explore-and-commit" compilation loops where code changes are tested in isolation and committed only if they pass all builds and tests.
* **Capability Separation**: Supports designing multi-stage agent compilers where the stage analyzing untrusted inputs (e.g. parsing third-party dependency files or executing untrusted test scripts) has its network revoked, preventing prompt injection attacks from exfiltrating sensitive local keys.
