#!/usr/bin/env bash
# Documentation checks, the same commands CI runs (009 proposal P4).
#   scripts/check-docs.sh          Markdown lint (same tool version as CI) and the doc index check
#   scripts/check-docs.sh index    the doc index check only (CI runs this; Markdown lint runs as an action)
set -euo pipefail
cd "$(dirname "$0")/.."
index_check() {
  for f in $(find 000-docs -name '*.md' ! -name '000-INDEX.md' | sort); do
    grep -q "$(basename "$f")" 000-docs/000-INDEX.md || { echo "missing from index: $f"; exit 1; }
  done
  echo "doc index: every filed doc is listed"
}
if [ "${1:-all}" != "index" ]; then
  npx --yes markdownlint-cli2@0.23.2 "**/*.md"   # keep in step with the CI action's bundled version
fi
index_check
