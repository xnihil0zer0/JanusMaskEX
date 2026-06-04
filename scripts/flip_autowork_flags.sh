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

KEYS=(selfheal_auto_promote enable_single_agent_promotion auto_approve_sensitive_harness)

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
  _probe "F content/capability gate"  "${PROJECT_DIR}/harness/orchestrator.py" "_auto_approve_content_safe|content_gate|_capability_gate"
  _probe "G TOCTOU artifact pin"      "${PROJECT_DIR}/harness/orchestrator.py" "patches_sha|_pin_artifact|artifact_sha|toctou"
  _probe "H RO-checkout primitive"    "${PROJECT_DIR}/harness" "ro_checkout|_ro_checkout|git archive|readonly_checkout"
  echo
  if [[ $ok -eq 1 ]]; then
    echo "  => all markers present. STILL run: python -m pytest -q tests/ (expect baseline) before enabling auto_approve_sensitive_harness."
  else
    echo "  => one or more pieces ABSENT. Do NOT enable auto_approve_sensitive_harness yet."
  fi
}

set_key() { # key  value(true|false)  dry(0|1)
  local key="$1" val="$2" dry="$3"
  local cur; cur="$(grep -E "^[[:space:]]*${key}:[[:space:]]*(true|false)" "$CFG" || true)"
  if [[ -z "$cur" ]]; then echo "ERROR: key '${key}' not found in ${CFG}" >&2; exit 2; fi
  echo "current: ${cur# }"
  if [[ "$dry" == "1" ]]; then echo "[dry-run] would set ${key} -> ${val}"; return 0; fi
  if [[ "$key" == "auto_approve_sensitive_harness" && "$val" == "true" ]]; then
    echo; echo ">>> WARNING: enabling auto_approve_sensitive_harness lets the harness modify its own"
    echo ">>> host-executed code unattended. Run --check and a full test sweep first."
    echo
  fi
  local ts bak; ts="$(date +%Y%m%d_%H%M%S)"; bak="${CFG}.bak.${ts}"
  cp "$CFG" "$bak"
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
