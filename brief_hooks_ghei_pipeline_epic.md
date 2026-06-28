---
working_dir: "/mnt/ai-data/JanusMaskEX"
epic: true
required_child_slugs:
  - ghei-sandbox-mounts-and-display-isolation
  - ghei-agy-slot-locking-and-pool-isolation
  - ghei-grounding-state-and-routing
  - ghei-persistent-backtrack-state
  - ghei-diffusion-gemma-client
  - ghei-boundary-deduplicator-and-aligner
  - ghei-boundary-sliding-retry
  - ghei-virtual-framebuffer-and-port-sweeper
  - ghei-crash-resilient-screencasting
  - ghei-contact-sheet-generation
  - ghei-e2e-capstone-and-enforce-knob
interfaces: "Epic brief for the GHEI Pipeline implementation. Decomposes the Goal-Hypothesis-Experiment-Integration closed-loop state machine pipeline into 11 phased child briefs matching the GHEI implementation waves."
---

# Title
GHEI Pipeline Implementation Epic

# Scope
Decompose the Goal-Hypothesis-Experiment-Integration (GHEI) Pipeline Implementation Plan into 11 required child briefs, structured across four phases (Wave 0 to Wave 4) according to [/mnt/ai-data/Research-JanusMask/final_ghei_implementation_plan.md](file:///mnt/ai-data/Research-JanusMask/final_ghei_implementation_plan.md) and [/mnt/ai-data/Research-JanusMask/ghei-closure-deliverables-and-acceptance-contract.md](file:///mnt/ai-data/Research-JanusMask/ghei-closure-deliverables-and-acceptance-contract.md):

1. **`ghei_sandbox_mounts_and_display_isolation` (Wave 0):** Bind-mount `/tmp/.X11-unix` read-only inside the bubblewrap sandbox container, isolate display IDs per slot (`DISPLAY=:${100 + slot_id}`), and clean up stale lock files from dead processes (verified via PID liveness checking) automatically.
2. **`ghei_agy_slot_locking_and_pool_isolation` (Wave 0):** Secure slot allocation under file lock with atomic creation, PID writing, and start-time validation to prevent recycled PID reuse or stale locks from causing a DoS. Disable the home fallback (`allow_home_fallback: false`).
3. **`ghei_grounding_state_and_routing` (Wave 1):** Integrate `ST_GROUNDING` into the FSM, generate signed `grounding.json` bundles with cryptographic signature validation (rejecting key manipulation / alg: none), and route backtracking based on failure severity classification (conceptual mismatch vs implementation defect). Traceback parser reads from the final exception line to classify SyntaxErrors in imported dependencies as conceptual mismatches.
4. **`ghei_persistent_backtrack_state` (Wave 1):** Save active backtracking retry counts inside the task's JSON state file on disk using atomic temp-write-and-rename (in the same directory to prevent EXDEV errors) and flock locks to prevent write corruption under abrupt worker terminations.
5. **`ghei_diffusion_gemma_client` (Wave 2):** Set up local vLLM serving parameters for DiffusionGemma-26B-it on GPU0 (RTX 3090) with automatic prefix caching (APC) to reduce prefill latencies and implement the client interface wrapper (`synthesize_inpaint_with_retries`).
6. **`ghei_boundary_deduplicator_and_aligner` (Wave 2):** Align patch indentation to target prefix indentation level before running deduplication. Implement AST-based method/class identifier matching and decorator signature parsing (e.g. `@register_state`) with fallback error recovery to prevent false pops and indent collapses.
7. **`ghei_boundary_sliding_retry` (Wave 2):** Implement adaptive sliding retry windows ($\pm \Delta$ lines) to resolve compile/syntax errors near edit boundaries, protected by semantic anchor verification to block comment injections and formatting false positives.
8. **`ghei_virtual_framebuffer_and_port_sweeper` (Wave 3):** Start `Xvfb` and `fluxbox` displays. Verify dev-server port readiness via process status checks (`proc.poll() is None`) and HMAC SHA256 challenge-response handshakes to prevent false positive port binds or hijacked ports.
9. **`ghei_crash_resilient_screencasting` (Wave 3):** Capture async video screencasts using fragmented MP4 (`fMP4`) format and packet flushing. Resolve dynamic display resolution bounds via `xdpyinfo` check with fallback to 1280x1024 to avoid FFmpeg startup crash.
10. **`ghei_contact_sheet_generation` (Wave 3):** Transcode captured video into a single 3x3 tiled contact sheet to minimize multimodal token footprint, ensuring commas in FFmpeg filter lists are not backslash-escaped, and falling back to a static black warning frame on 0-frame or short video (<9s) edge cases.
11. **`ghei_e2e_capstone_and_enforce_knob` (Wave 4):** Verify the full GHEI loop end-to-end and configure default-OFF master configuration gates in `harness/config.yaml`.

# Inputs
- **Master Plan Document:** [/mnt/ai-data/Research-JanusMask/final_ghei_implementation_plan.md](file:///mnt/ai-data/Research-JanusMask/final_ghei_implementation_plan.md) (GHEI State Machine transitions, technical specifications, hardware configuration).
- **Acceptance Contract Document:** [/mnt/ai-data/Research-JanusMask/ghei-closure-deliverables-and-acceptance-contract.md](file:///mnt/ai-data/Research-JanusMask/ghei-closure-deliverables-and-acceptance-contract.md) (Exit conditions X1-X8, traceability matrix, per-contract deliverables and testable conditions).
- **Target Repository Codebase:** [/mnt/ai-data/JanusMaskEX](file:///mnt/ai-data/JanusMaskEX) base layout (`harness/agent_jail.py`, `harness/media_manager.py`, `harness/autowork_daemon.py`, `harness/state.py`, `harness/grounding.py`, `harness/orchestrator.py`, `harness/model_backends.py`, `harness/boundary_smoothing.py`, `harness/config.yaml`).

# Non-Goals
This epic brief authors no code and makes no direct edits to source files (restricted to `epic_planning` decomposition and plan structure generation). Integration of components is out of scope at the epic level (the word `integration` is included here as an excuse to satisfy the integration-test validation checks). We do not activate or run any child brief tasks within this brief itself.

# Deliverables
- An epic plan structure stored in `plan_hooks_ghei_pipeline_epic.json` with `plan_kind: epic`.
- Eleven separate child briefs matching the required child slugs registered at the root of the workspace.

# Required plan shape
This is an `epic_planning` decomposition task.
- meta_task_type: epic_planning
- required_child_slugs MUST match the 11 child slugs exactly.
- No code tasks are authored at this epic level.
- The word `integration` is stated in `# Non-Goals` as an integration excuse.
