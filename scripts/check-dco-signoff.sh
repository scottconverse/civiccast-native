#!/usr/bin/env bash
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
#
# DCO sign-off check, invoked as a commit-msg pre-commit hook.
# Verifies the commit message contains a `Signed-off-by:` trailer.

set -euo pipefail

COMMIT_MSG_FILE="${1:-.git/COMMIT_EDITMSG}"

if [[ ! -f "$COMMIT_MSG_FILE" ]]; then
  echo "DCO check: commit message file not found: $COMMIT_MSG_FILE" >&2
  exit 1
fi

# Skip merge commits and fixup commits.
if grep -qE '^(Merge|fixup!|squash!)' "$COMMIT_MSG_FILE"; then
  exit 0
fi

if ! grep -qE '^Signed-off-by: .+ <.+@.+>' "$COMMIT_MSG_FILE"; then
  echo "ERROR: Commit is missing a Developer Certificate of Origin sign-off." >&2
  echo >&2
  echo "Add the trailer:" >&2
  echo "  Signed-off-by: Your Name <your.email@example.com>" >&2
  echo >&2
  echo "Or commit with -s:" >&2
  echo "  git commit -s" >&2
  echo >&2
  echo "See https://developercertificate.org/ for the full DCO text." >&2
  exit 1
fi

exit 0
