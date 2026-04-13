#!/usr/bin/env bash
# Generate PlantUML class and package diagrams for the wound_ontology package.
#
# Prerequisites:
#   pip install pylint            # ships pyreverse
#   VS Code extension: jebbs.plantuml  (Alt+D to preview a .puml file)
#
# Usage:
#   bash scripts/generate_uml.sh          # full diagram
#   bash scripts/generate_uml.sh --all    # include 3rd-party dependencies

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
OUT_DIR="$REPO_ROOT/docs/uml"
SRC="$REPO_ROOT/src/wound_ontology"

mkdir -p "$OUT_DIR"

echo "Running pyreverse on $SRC …"

# --output plantuml  → .puml files
# --project          → prefix for output file names
# --colorized        → colour-code by layer
# --max-color-depth 3
# --filter-mode      → PUB_ONLY hides private/protected members by default;
#                      change to ALL to show everything

pyreverse \
  --output plantuml \
  --project wound_ontology \
  --colorized \
  --filter-mode PUB_ONLY \
  --output-directory "$OUT_DIR" \
  "$SRC"

echo ""
echo "Generated:"
ls -lh "$OUT_DIR"/*.plantuml 2>/dev/null || echo "  (no .plantuml files found — check pyreverse output above)"
echo ""
echo "Open docs/uml/classes_wound_ontology.plantuml in VS Code and press Alt+D to preview."
