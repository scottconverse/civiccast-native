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
OUT_DIR="${OUT_DIR:-$REPO_ROOT/artifacts}"

# Use the same renderer as native Windows, including its source-derived
# version header and artifact verification. Direct Pandoc invocation omitted
# the version-header override and emitted v0.0.0-unset in CI's PDF artifact.
cd "$REPO_ROOT"
if command -v uv >/dev/null 2>&1; then
  exec uv run python scripts/render_user_manual.py --out-dir "$OUT_DIR"
else
  exec python scripts/render_user_manual.py --out-dir "$OUT_DIR"
fi
