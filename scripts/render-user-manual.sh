#!/usr/bin/env bash
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
#
# Render docs/USER-MANUAL.md to PDF (xelatex) and DOCX via Pandoc (per ADR 0005).
# Used by the ci-docs workflow and by operators who want to print the handbook.
#
# Requirements: pandoc 3.1+, texlive-xetex, texlive-fonts-recommended,
# texlive-latex-recommended, texlive-latex-extra. The CI image installs
# these; on Ubuntu/Debian: apt install pandoc texlive-xetex
# texlive-fonts-recommended texlive-latex-recommended texlive-latex-extra.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SOURCE="$REPO_ROOT/docs/USER-MANUAL.md"
OUT_DIR="${OUT_DIR:-$REPO_ROOT/artifacts}"

if [[ ! -f "$SOURCE" ]]; then
  echo "ERROR: $SOURCE not found." >&2
  exit 1
fi

mkdir -p "$OUT_DIR"

if ! command -v pandoc >/dev/null 2>&1; then
  echo "ERROR: pandoc is not installed. See ADR 0005 for required packages." >&2
  exit 1
fi

# Layout, fonts, and colours come from the shared defaults file so this script
# and scripts/render_user_manual.py cannot drift apart. Its relative paths
# resolve from the repository root, so run pandoc from there.
cd "$REPO_ROOT"
DEFAULTS="docs/assets/manual.pandoc.yaml"

if command -v xelatex >/dev/null 2>&1; then
  pandoc "$SOURCE" --defaults "$DEFAULTS" -o "$OUT_DIR/USER-MANUAL.pdf"
  echo "Rendered $OUT_DIR/USER-MANUAL.pdf"
else
  echo "INFO: xelatex not found; skipping PDF render. Install texlive-xetex to enable."
fi

# DOCX has no LaTeX preamble; render it with the table of contents only.
pandoc "$SOURCE" --resource-path docs --toc --toc-depth=2 -o "$OUT_DIR/USER-MANUAL.docx"
echo "Rendered $OUT_DIR/USER-MANUAL.docx"
