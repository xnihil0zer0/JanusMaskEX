__JANUSMASK_MANIFEST__ = {
    'README.md': r"""__JANUSMASK_MANIFEST__ = {"README.md": r'''# JanusMask — Autonomous Code-Generation Factory

JanusMask compiles a plain-English **brief** into *verified* working code. Two independent
LLM agents (Claude + Gemini) each draft a candidate blind to the other; a result is accepted
only when the two are proven **differentially equivalent** under a property-based fuzzer, are
AST-valid, pass a pre-committed pytest oracle, and are reachable from a live entry point — then
it is committed through an isolated git worktree behind a read-only-parent gate.

A self-driving **daemon** promotes briefs, runs the planner, stages tasks, dispatches workers,
retries failures, and self-heals — all behind an explicit operator control surface. The system
builds **its own harness** through this same pipeline, and builds/edits **external repos** (e.g.
`/home/xnihil0zer0/NobleGreedv2`) through an isolated staging worktree.

**Design principle: correctness is enforced by *withholding and checking*, never by prompting.**
The LLMs only *propose*; pure deterministic verifiers *decide*.

This README is an **operator reference for running the pipeline completely hands-off**, for both
**internal** (factory fixing its own `harness/**`) and **external** (factory building another repo)
work. It documents the real system as it runs today — including the places that still need a human
(see [Gaps / steps still requiring a human](#gaps--steps-still-requiring-a-human)).

---

## Table of contents

1. [What the system is — lifecycle](#1-what-the-system-is--lifecycle)
2. [Requirements / prerequisites](#2-requirements--prerequisites)
3. [How to start it hands-off](#3-how-to-start-it-hands-off)
4. [How to feed work: authoring a brief](#4-how-to-feed-work-authoring-a-brief)
5. [External projects (`working_dir`)](#5-external-projects-working_dir)
6. [Pause / resume / stop](#6-pause--resume--stop)
7. [Monitoring (autonomous)](#7-monitoring-autonomous)
8. [Configuration reference](#8-configuration-reference)
9. [`meta_task_type` taxonomy](#9-meta_task_type-taxonomy)
10. [Submission formats](#10-submission-formats-what-the-agent-emits)
11. [Troubleshooting](#11-troubleshooting)
12. [Gaps / steps still requiring a human](#12-gaps--steps-still-requiring-a-human)
13. [State directory layout](#13-state-directory-layout)
14. [Glossary](#14-glossary)

---

## 1. What the system is — lifecycle
