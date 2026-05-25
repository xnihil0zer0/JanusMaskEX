# Hook timeout units

The `timeout` field inside each `hooks[*][].hooks[*]` entry carries
different units on the two sides of the differential-fuzzing harness:

| Side   | Files | Unit | Typical values |
|--------|-------|------|----------------|
| Claude | `.claude/settings.local.json`, `config/claude_worker_hooks.json`, `config/claude_worker_planning_hooks.json` | **seconds** (per Claude Code convention) | 5, 10, 15, 20, 30, 60, 120 |
| Gemini | `config/gemini_settings.json`, `.gemini/settings.json` | **milliseconds** (per Gemini CLI convention) | 10000, 15000, 30000 |

Resolves the drift flagged in `brief_hooks_schema_drift_02.md` (D-14 /
R-05). The field is **not** renamed so neither vendor CLI needs a
schema patch. Any future shared-config helper that reads both sides
must branch on agent and convert.
