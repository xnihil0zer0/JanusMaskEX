#!/usr/bin/env bash
# scripts/flip_autowork_flags.sh — owner-controlled toggle for the three
# security-gated autonomy flags in harness/config.yaml. Preserves comments and
# file structure (targeted per-key line edit; the three keys are globally
# unique in config.yaml).
#
# THESE FLAGS REMOVE A FAIL-CLOSED DEFAULT. Flip them deliberately.
#
#   selfheal_auto_promote        (autowork)  — let the self-heal loop promote a
#                                  corrected harness fix WITHOUT operator approval.
#                                  Gate: the loop genuinely closes (proved by
#                                  tests/adversarial/test_gateb_selfheal_convergence.py)
#                                  + §5 inv 1/2/3/7. Bounded, lowest risk.
#   enable_single_agent_promotion (synthesis) — when exactly one agent is valid at
#                                  the ceiling, promote it. Gate: §5 inv 8 (a
#                                  sensitive target still requires operator approval).
#                                  Bounded.
#   auto_approve_sensitive_harness (autowork) — THE BIG ONE. Auto-approve a
#                                  harness_self_fix patch to harness/** (minus the
#                                  _NEVER_AUTO_APPROVE security core) with no human.
#                                  DO NOT ENABLE until the unattended-safety stack
#                                  is landed AND verified:
#                                    E trust-root lockdown   (INV2)
#                                    F content/capability gate(INV9)
#                                    G TOCTOU artifact pin    (INV5)
#                                    H RO-checkout validation (rollback protector)
#                                  Run with --check to see whether those are present.
#   auto_approve_ro_gate         (autowork)  — enable the RO-checkout rollback
#                                  protector (H) on the auto-approve path: gate-tests
#                                  run from a read-only parent-HEAD snapshot against
#                                  the candidate, so a self-edit cannot weaken its own
#                                  gatekeeper. SEPARATE default-off flag; enable it
#                                  WHENEVER you enable auto_approve_sensitive_harness
#                                  (auto-approve without it skips the RO gate). If the
#                                  key is absent it is treated as false; this script
#                                  inserts it under autowork: on first enable.
#
# Usage:
#   scripts/flip_autowork_flags.sh --status
#   scripts/flip_autowork_flags.sh --check
#   scripts/flip_autowork_flags.sh enable  selfheal_auto_promote
#   scripts/flip_autowork_flags.sh disable auto_approve_sensitive_harness
#   scripts/flip_autowork_flags.sh enable  enable_single_agent_promotion --dry-run
#
# A backup config.yaml.bak.<ts> is written before any change. Recovery is always
# `git checkout harness/config.yaml` (or restore the .bak).

set -euo pipefail

PROJECT_DIR="${CLAUDE_PROJECT_DIR:-$(cd "$(dirname "$0")/.." && pwd)}"
CFG="${PROJECT_DIR}/harness/config.yaml"

KEYS=(selfheal_auto_promote enable_single_agent_promotion auto_approve_sensitive_harness auto_approve_ro_gate)

# Parent YAML section for each key (for insert-if-absent).
key_section() {
  case "$1" in
    enable_single_agent_promotion) echo "synthesis" ;;
    *) echo "autowork" ;;
  esac
}

is_known_key() { local k; for k in "${KEYS[@]}"; do [[ "$k" == "$1" ]] && return 0; done; return 1; }

show_status() {
  echo "config: ${CFG}"
  for k in "${KEYS[@]}"; do
    local line; line="$(grep -E "^[[:space:]]*${k}:[[:space:]]*(true|false)" "$CFG" || true)"
    printf '  %-32s %s\n' "$k" "${line:-"(not found!)"}"
  done
}

# --check: report whether the unattended-safety stack is present in the tree.
# Heuristic markers (grep), not a guarantee — re-verify with the evidence pack
# and the full test sweep before relying on auto_approve_sensitive_harness.
do_check() {
  echo "Unattended-safety stack presence check (heuristic):"
  local ok=1
  _probe() { # name  grep-target  pattern
    if grep -rqE "$3" "$2" 2>/dev/null; then printf '  [present] %s\n' "$1"; else printf '  [ABSENT ] %s\n' "$1"; ok=0; fi
  }
  _probe "E trust-root lockdown (selfheal secret override validated)" "${PROJECT_DIR}/harness/selfheal.py" "INV2-TRUST-ROOT"
  _probe "F content/capability gate"  "${PROJECT_DIR}/harness/orchestrator.py" "_auto_approve_content_safe"
  _probe "G TOCTOU artifact pin"      "${PROJECT_DIR}/harness/orchestrator.py" "_pinned_artifact_sha|_pinned_parent_head"
  _probe "H1 RO-checkout primitive"   "${PROJECT_DIR}/harness/git_integration.py" "_verify_from_ro_parent"
  _probe "H2 RO-checkout wiring"      "${PROJECT_DIR}/harness/orchestrator.py" "_verify_from_ro_parent|_RO_GATE_TESTS"
  echo
  if [[ $ok -eq 1 ]]; then
    echo "  => all markers present. Before enabling auto_approve_sensitive_harness:"
    echo "     1) python -m pytest -q tests/   (expect the pre-existing baseline, no NEW failures)"
    echo "     2) ALSO enable auto_approve_ro_gate (the RO-checkout rollback protector) — it is a"
    echo "        SEPARATE flag and is OFF by default; auto-approve without it skips the RO gate."
  else
    echo "  => one or more pieces ABSENT. Do NOT enable auto_approve_sensitive_harness yet."
  fi
}

set_key() { # key  value(true|false)  dry(0|1)
  local key="$1" val="$2" dry="$3"
  local cur; cur="$(grep -E "^[[:space:]]*${key}:[[:space:]]*(true|false)" "$CFG" || true)"
  local absent=0; [[ -z "$cur" ]] && absent=1
  if [[ $absent -eq 1 ]]; then
    echo "note: key '${key}' is not declared in ${CFG} (treated as false by the harness); will INSERT it under '$(key_section "$key"):'."
  else
    echo "current: ${cur# }"
  fi
  if [[ "$dry" == "1" ]]; then echo "[dry-run] would set ${key} -> ${val}"; return 0; fi
  if [[ "$key" == "auto_approve_sensitive_harness" && "$val" == "true" ]]; then
    echo; echo ">>> WARNING: enabling auto_approve_sensitive_harness lets the harness modify its own"
    echo ">>> host-executed code unattended. Run --check and a full test sweep first."
    local ro; ro="$(grep -E "^[[:space:]]*auto_approve_ro_gate:[[:space:]]*true" "$CFG" || true)"
    if [[ -z "$ro" ]]; then
      echo ">>> NOTE: auto_approve_ro_gate is NOT enabled — the RO-checkout rollback protector will be"
      echo ">>>       SKIPPED. Strongly consider: $0 enable auto_approve_ro_gate"
    fi
    echo
  fi
  local ts bak; ts="$(date +%Y%m%d_%H%M%S)"; bak="${CFG}.bak.${ts}"
  cp "$CFG" "$bak"
  if [[ $absent -eq 1 ]]; then
    # Insert "  <key>: <val>" as the first entry under the parent section.
    local sect; sect="$(key_section "$key")"
    python3 - "$CFG" "$key" "$val" "$sect" <<'PY'
import re, sys
cfg, key, val, section = sys.argv[1:5]
src = open(cfg).read()
pat = re.compile(r'^(%s:[ \t]*\n)' % re.escape(section), re.M)
new, n = pat.subn(lambda m: m.group(1) + "  %s: %s\n" % (key, val), src, count=1)
if n != 1:
    sys.stderr.write("ERROR: section '%s:' not found in %s (got %d matches)\n" % (section, cfg, n)); sys.exit(3)
open(cfg, "w").write(new)
PY
    echo "inserted ${key}: ${val} under ${sect}:  (backup: ${bak})"
    echo "verify: $(grep -nE "^[[:space:]]*${key}:" "$CFG")"
    return 0
  fi
  # Targeted, comment-preserving per-key replacement.
  python3 - "$CFG" "$key" "$val" <<'PY'
import re, sys
cfg, key, val = sys.argv[1], sys.argv[2], sys.argv[3]
src = open(cfg).read()
pat = re.compile(r'^(\s*%s:\s*)(true|false)(\s*(?:#.*)?)$' % re.escape(key), re.M)
new, n = pat.subn(lambda m: m.group(1) + val + m.group(3), src)
if n != 1:
    sys.stderr.write("ERROR: expected exactly 1 match for %s, got %d\n" % (key, n)); sys.exit(3)
open(cfg, "w").write(new)
PY
  echo "set ${key} -> ${val}  (backup: ${bak})"
  echo "verify: $(grep -E "^[[:space:]]*${key}:" "$CFG")"
}

main() {
  [[ -f "$CFG" ]] || { echo "ERROR: ${CFG} not found" >&2; exit 2; }
  local action="${1:-}"; shift || true
  case "$action" in
    --status|status|"") show_status ;;
    --check|check) do_check ;;
    enable|disable)
      local key="${1:-}"; shift || true
      is_known_key "$key" || { echo "ERROR: unknown key '${key}'. Known: ${KEYS[*]}" >&2; exit 2; }
      local dry=0; [[ "${1:-}" == "--dry-run" ]] && dry=1
      local val="true"; [[ "$action" == "disable" ]] && val="false"
      set_key "$key" "$val" "$dry"
      ;;
    *) echo "usage: $0 {--status|--check|enable <key>|disable <key>} [--dry-run]"; echo "keys: ${KEYS[*]}"; exit 2 ;;
  esac
}
main "$@"
