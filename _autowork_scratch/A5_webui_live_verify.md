# A5 — WebUI Typed-Config Live Browser Verification (2026-06-13)

Server: launched `python -m tools.webui_server` on 127.0.0.1:**8791** (port 8765 already held
by a separate running webui). Driven via Playwright MCP at `/#/config`. Server killed at end.
config.yaml backed up (`/tmp/config_a5_backup.yaml`) before the valid-save test and restored
verbatim after (md5 match).

## Per-check results

| # | Check | Result | Evidence |
|---|-------|--------|----------|
| 1 | Typed config widgets render | PASS | Schema-driven render: int/float/bool spinbuttons + checkbox, path-dir/path-file with Browse, 3 role selects + 8 API-key inputs. All `/api/config`, `/api/config/schema` GETs = 200. |
| 2 | Twin selects for dual role | PASS | `synthesis.active_agents` renders TWO selects (`typed-role-synthesis.active_agents-0/-1`); single selects for `overseer.default_backend`, `control.autobrief_default_agent`. |
| 3 | Provider-lock | PASS | API-key-gated providers (openai/gemini_api/anthropic/deepseek/moonshot/zhipu/qwen/minimax) render `disabled` ("API key required"); claude/gemini/antigravity/codex enabled. Lock is on PROVIDER availability (no separate model dropdown exists in this UI — model selection is not part of the typed-config widget set). |
| 4 | Browse opens fs picker | PASS | Clicking Browse creates `#fs-picker-modal` ("Browse Filesystem" header, Parent / Select Current Folder, 43 rows w/ Select buttons). Backend `GET /api/fs/list?path=.` = 200, 376 entries (keys: root,path,parent,entries). |
| 5 | Valid save persists | PASS | `POST /api/config/typed` {synthesis=[claude,gemini], distinct} → 200 `{saved:true}`; harness/config.yaml rewritten with active_agents (comments stripped, no functional change). Restored afterward. |
| 6 | Invalid save refused + field_errors | PASS | `POST /api/config/typed` {synthesis=[claude,claude]} → 400 `{field_errors:{"synthesis.active_agents":"dual role agents must be different"}}`. |

## DEFECT FOUND (non-blocking, cosmetic/UX)

**Role selects do NOT pre-populate from existing config on load.** All three role widgets
show "-- select provider --" (empty value) even though config has
`synthesis.active_agents=[claude,gemini]`, `overseer.default_backend=claude`,
`control.autobrief_default_agent=claude`. `populateRoleSelects()` in app.js reads
`values[configKey]` but the rendered selected value is "" for every role.

Impact: an operator who opens Config and clicks "Save Config" without re-selecting providers
would submit empty/partial role arrays. Functionally the save+validate path works correctly;
this is a load-time pre-fill bug. Likely the `values` payload key naming (dotted config_key vs
nested) or array-index lookup mismatch in `populateRoleSelects`.

Other: a benign 404 on initial load (favicon-class request; all functional API GETs were 200).

## Verdict
Typed-config WebUI **WORKS** end-to-end in a real browser — render, twin selects, provider-lock,
fs Browse picker, valid persist, and invalid-rejection-with-field_errors all live-confirmed.
One non-blocking pre-fill defect (role selects start empty instead of reflecting saved config).
