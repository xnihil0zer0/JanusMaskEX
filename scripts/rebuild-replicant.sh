#!/usr/bin/env bash
# Clean-room AST-rebuild CLI: strip a target into an output repo and reconstruct
# every unit blind via the dual-agent pipeline, then assert the output suite is
# green. Run from the JanusMask repo root.
#
#   scripts/rebuild-replicant.sh mathlib [OUTPUT_DIR] [STASH_DIR] [--only UNIT]
#   scripts/rebuild-replicant.sh path/to/descriptor.json OUTPUT_DIR STASH_DIR --source-root DIR
#
# Defaults keep all throwaway state OUTSIDE /tmp (vendored tests hardcode /tmp
# as a sandbox base) and OUTSIDE the repo.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

TARGET="${1:?usage: rebuild-replicant.sh <target|descriptor.json> [output_dir] [stash_dir] [--only UNIT] [--source-root DIR]}"
shift || true

# Positional output/stash if the next args are not flags.
OUTPUT=""
STASH=""
if [[ "${1:-}" != "" && "${1:-}" != --* ]]; then OUTPUT="$1"; shift; fi
if [[ "${1:-}" != "" && "${1:-}" != --* ]]; then STASH="$1"; shift; fi

SLUG="$(basename "$TARGET" .json)"
OUTPUT="${OUTPUT:-$HOME/.cache/jr-rebuild/${SLUG}_out}"
STASH="${STASH:-$HOME/.cache/jr-rebuild/${SLUG}_stash}"

exec python -m harness.rebuild.loop \
  --target "$TARGET" \
  --output "$OUTPUT" \
  --stash "$STASH" \
  "$@"
