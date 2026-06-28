---
working_dir: "/home/xnihil0zer0/AI-Data/Drizzlet"
epic: true
required_child_slugs:
  - p01_math_frameworks
  - p02_base_rigidbody_physics
  - p03_double_buffered_level_streamer
  - p04_genome_morphology_engine
---

# Title
Wave 0 Foundations Epic

# Scope
Decompose Wave 0 foundations of Drizzlet into 4 child briefs:
1. `p01_math_frameworks`: Math core (quaternion swing-twist, Caputo fractional derivative solver, Xoshiro128**/MurmurHash3).
2. `p02_base_rigidbody_physics`: Verlet physics, active ragdoll PD joint loops, and QP-CBF solver.
3. `p03_double_buffered_level_streamer`: Chunk coordinates, custom RLE serialization, and MAPV level validation.
4. `p04_genome_morphology_engine`: 128-bit genome parsing and skeletal DAG morphological assembly.

# Inputs
The Drizzlet development docs:
- `docs/drizzlet-closure-deliverables-and-acceptance-contract.md`
- `DESIGN_DOCUMENT.md`
- `docs/locomotion_level.md`
- `docs/ecosystem.md`

# Non-Goals
Integration testing of all components is out of scope. Do not combine all systems into a single runner at this stage.

# Deliverables
- Child brief `brief_hooks_p01_math_frameworks.md` written to the repo root.
- Child brief `brief_hooks_p02_base_rigidbody_physics.md` written to the repo root.
- Child brief `brief_hooks_p03_double_buffered_level_streamer.md` written to the repo root.
- Child brief `brief_hooks_p04_genome_morphology_engine.md` written to the repo root.
