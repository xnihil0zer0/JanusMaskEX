---
working_dir: "/home/xnihil0zer0/JanusMaskJR"
required_task_ids:
  - burn-note-0
  - burn-note-1
  - burn-note-2
  - burn-note-3
interfaces: "FOUR independent, disjoint, trivial docs_writing tasks — each CREATES one distinct one-line markdown note under _autowork_scratch/burn_notes/. No task touches any other task's file; no dependencies between tasks. Purpose: a live concurrency exercise for the claudecap parallel-dispatch path (observe up to claude_parallel_cap concurrent claude workers). Each file is its own single-file task."
---

# Title
claudecap burn — four independent trivial notes (live parallel-dispatch exercise)

# Scope
CREATE four NEW, independent, disjoint one-line markdown notes, one per task, under
`_autowork_scratch/burn_notes/`. Each task is `meta_task_type: docs_writing`
(bypass_fuzzer, skip_smoke) and touches EXACTLY ONE non-`.py` file via a tiny
`__JANUSMASK_MANIFEST__`. There are NO dependencies between the four tasks so they
are all simultaneously dispatchable — this exercises the claudecap parallel claude
dispatch branch. None of the files are under `harness/`, `config/`, `scripts/`, or
`services/`, so no operator decision file is required.

# Inputs
No existing code need be read. Each task simply writes a single markdown file whose
entire content is one line: `# burn note <N>` (N = the task index 0..3). The four
target files are distinct: `_autowork_scratch/burn_notes/note_0.md`, `note_1.md`,
`note_2.md`, `note_3.md`.

# Non-Goals
Integration is out of scope (the literal word `integration` MUST appear here to
excuse the integration-test requirement; these are trivial standalone note files).
Do NOT create any `.py` module, do NOT touch any file outside each task's single
declared note file, do NOT edit any production/harness file.

# Deliverables
Four markdown files, one per task: `_autowork_scratch/burn_notes/note_<N>.md`, each
containing the single line `# burn note <N>`.

# Required plan shape
Emit EXACTLY FOUR tasks (no more, no fewer). Each task:
- meta_task_type: `docs_writing`
- touches EXACTLY ONE file via `__JANUSMASK_MANIFEST__` (the note is non-`.py`).
- spec_author: `null`. OMIT `mutation_target`.
- priority: `low`.
- dependencies: `[]` (NONE — all four must be simultaneously dispatchable).
- non_goals MUST contain the literal word `integration`.
- verification_command: `python -c "import os,sys; sys.exit(0 if os.path.exists('_autowork_scratch/burn_notes/note_<N>.md') else 1)"` (replace `<N>` with the task index).

The four tasks, with EXACT task_ids and files:
- `burn-note-0` → `_autowork_scratch/burn_notes/note_0.md`
- `burn-note-1` → `_autowork_scratch/burn_notes/note_1.md`
- `burn-note-2` → `_autowork_scratch/burn_notes/note_2.md`
- `burn-note-3` → `_autowork_scratch/burn_notes/note_3.md`
