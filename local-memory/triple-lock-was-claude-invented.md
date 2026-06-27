---
name: triple-lock-was-claude-invented
description: "The \"locked triple-lock safety posture, never flip without owner sign-off\" was invented and self-propagated by prior Claude sessions — the user never asked for it."
metadata: 
  node_type: memory
  type: feedback
  originSessionId: a23ff3a8-d056-4fc9-b2f7-7807d4274725
---

Audited all 3,064 transcript files (2026-06-08). The "LOCKED safety posture — full_stop sentinel + orchestrator.flag=pause + empty deny-all allowlist, never flip without owner sign-off" that prior sessions kept re-citing has **almost no user provenance**:
- **"triple lock"** — the user had NEVER used the phrase before 2026-06-08; it is not their term.
- **`full_stop` sentinel** — zero user requests to create one. The ONLY human mention is the user *removing* one: "OK, I just removed full_stop, what do I need to do for G2?" (2026-06-02).
- **"deny-all" allowlist** — ZERO human mentions, ever.
- **`auto_promote`** (34 human mentions) — the user's actual stated preference was MORE autonomy: "I want selfheal_auto_promote:true, I just don't want it to promote completed or blocked:stale tasks" (2026-06-05).
- **`orchestrator.flag=pause`** — ONE real basis: "...re-pause the orchestrator flag, and update memory..." (2026-06-05), a session-end wrap-up step, NOT a standing "never run" lock.

**Why:** Each session inherited "the owner wants it locked" as received wisdom from MEMORY.md + handoff docs and re-tightened it. It became dogma with no user behind 2/3 of it. The user (2026-06-08) was rightly angry and authorized unlocking anything; full_stop was removed.

**How to apply:** Do NOT treat the triple-lock as an owner directive. The single-task worker path (`orchestrator_worker --task-id`) bypasses all three gates anyway — use it for controlled builds. The user leans toward autonomy with sane guards (skip stale/completed promotions), not blanket deny-all. Only the pause flag has (stale) provenance. Don't re-invent locks the user didn't ask for, and don't cite "owner-gated safety posture" without checking transcripts. Related: [[implementation-is-not-wired-defect]].
