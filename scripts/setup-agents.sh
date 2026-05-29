#!/usr/bin/env bash
# AGENT-ISOLATION §4: reproduce the vendored, version-pinned agent binaries
# under .agents/ (gitignored). config.yaml points all four agent commands at
# these via ${PROJECT_ROOT}. Vendoring is NOT an isolation barrier (the CWD
# relocation §3.1/§3.2 and the §1b apply-path gate are); it pins the agent
# toolchain so a host upgrade cannot silently change synthesis behavior.
set -euo pipefail

PROJ="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJ"

AGY_VERSION_EXPECTED="1.0.3"
AGY_SHA256_EXPECTED="b15ce0729e9d093ae311c78dfe7369fc75efd00f8f8c27576ba1cea216f8f00c"
CLAUDE_CODE_PIN="2.1.156"

echo "== Vendoring agy (Antigravity CLI) =="
mkdir -p .agents/agy
src="$(command -v agy || true)"
if [[ -z "$src" ]]; then
  echo "ERROR: agy not found on PATH; install it first (https://antigravity ...)." >&2
  exit 1
fi
cp "$src" .agents/agy/agy
chmod +x .agents/agy/agy
got_sha="$(sha256sum .agents/agy/agy | awk '{print $1}')"
got_ver="$(.agents/agy/agy --version 2>&1 | head -1 | tr -d '[:space:]')"
echo "  agy version: $got_ver (expected $AGY_VERSION_EXPECTED)"
echo "  agy sha256 : $got_sha"
if [[ "$got_sha" != "$AGY_SHA256_EXPECTED" ]]; then
  echo "  WARNING: agy SHA256 differs from the recorded pin ($AGY_SHA256_EXPECTED)." >&2
fi

echo "== Vendoring claude-code (pinned $CLAUDE_CODE_PIN) =="
# NOTE: this yields a node shim at
# .agents/claude-code/node_modules/.bin/claude that REQUIRES node on PATH at
# spawn time — it is NOT a self-contained binary.
mkdir -p .agents/claude-code
npm install --prefix .agents/claude-code "@anthropic-ai/claude-code@${CLAUDE_CODE_PIN}"
.agents/claude-code/node_modules/.bin/claude --version

echo "== Done. config.yaml references:"
echo "   gemini/antigravity/claude_fallback -> \${PROJECT_ROOT}/.agents/agy/agy"
echo "   claude                             -> \${PROJECT_ROOT}/.agents/claude-code/node_modules/.bin/claude"
