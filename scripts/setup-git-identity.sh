#!/usr/bin/env bash
# setup-git-identity.sh — one-time project-local git identity setup.
#
# Sets project-local (not global) git user.name and user.email so commits
# made in this repo work without per-machine global config. Identity resolves
# in this order (first non-empty wins), so a fresh clone at any path / under
# any operator lands auto-commits under the RIGHT author (REPL-7):
#
#   1. $GIT_AUTHOR_NAME / $GIT_AUTHOR_EMAIL  (env)
#   2. positional args:  setup-git-identity.sh "Name" "email@host"
#   3. existing  git config --global user.name / user.email
#
# This is only needed once. Re-running is idempotent.

set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/.."

NAME="${GIT_AUTHOR_NAME:-${1:-$(git config --global user.name || true)}}"
EMAIL="${GIT_AUTHOR_EMAIL:-${2:-$(git config --global user.email || true)}}"

if [ -z "$NAME" ] || [ -z "$EMAIL" ]; then
  echo "ERROR: could not resolve a git identity." >&2
  echo "  Provide one of:" >&2
  echo "    export GIT_AUTHOR_NAME='You'  GIT_AUTHOR_EMAIL='you@host'" >&2
  echo "    scripts/setup-git-identity.sh 'You' 'you@host'" >&2
  echo "    git config --global user.name 'You' && git config --global user.email 'you@host'" >&2
  exit 1
fi

git config user.name "$NAME"
git config user.email "$EMAIL"

echo "Project-local git identity set:"
echo "  name:  $(git config user.name)"
echo "  email: $(git config user.email)"
echo ""
echo "This only affects $(pwd). Global config unchanged."
