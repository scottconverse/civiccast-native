#!/usr/bin/env bash
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

PYTHON="${PYTHON:-python}"
RELEASE_RUN_ID="${CIVICCAST_RELEASE_RUN_ID:-2026-05-19-v1.2-ndi-output}"

to_windows_path() {
  local input_path="$1"
  if command -v wslpath >/dev/null 2>&1; then
    if wslpath -w "$input_path" 2>/dev/null; then
      return
    fi
  fi
  if [[ "$input_path" =~ ^/mnt/([A-Za-z])/(.*)$ ]]; then
    local drive="${BASH_REMATCH[1]}"
    local rest="${BASH_REMATCH[2]//\//\\}"
    printf "%s:\\%s\n" "${drive^^}" "$rest"
    return
  fi
  printf "%s\n" "$input_path"
}

run_npm_script() {
  local rel_dir="$1"
  local script_name="$2"
  local evidence_rel="${3:-}"

  if command -v powershell.exe >/dev/null 2>&1 && command -v wslpath >/dev/null 2>&1 && [[ "$ROOT" == /mnt/* ]]; then
    local win_dir
    win_dir="$(to_windows_path "$ROOT/$rel_dir")"
    local ps_command
    ps_command="Set-Location -LiteralPath '$win_dir';"
    ps_command="$ps_command if (-not (Test-Path -LiteralPath 'node_modules')) { npm ci; }"
    if [[ -n "$evidence_rel" ]]; then
      local win_evidence
      win_evidence="$(to_windows_path "$ROOT/$evidence_rel")"
      ps_command="$ps_command New-Item -ItemType Directory -Force -Path '$win_evidence' | Out-Null; \$env:CIVICCAST_EVIDENCE_DIR='$win_evidence';"
    fi
    ps_command="$ps_command npm run $script_name"
    powershell.exe -NoProfile -ExecutionPolicy Bypass -Command "$ps_command"
    return
  fi

  (
    cd "$rel_dir"
    if [[ ! -d node_modules ]]; then
      npm ci
    fi
    if [[ -n "$evidence_rel" ]]; then
      mkdir -p "$ROOT/$evidence_rel"
      CIVICCAST_EVIDENCE_DIR="$ROOT/$evidence_rel" npm run "$script_name"
    else
      npm run "$script_name"
    fi
  )
}

echo "verify-release: ruff check"
"$PYTHON" -m ruff check .

echo "verify-release: ruff format check"
"$PYTHON" -m ruff format --check .

echo "verify-release: mypy"
"$PYTHON" -m mypy civiccast

echo "verify-release: pytest"
"$PYTHON" -m pytest -q --tb=short

echo "verify-release: v1.2 mTLS focused tests"
"$PYTHON" -m pytest -q --tb=short \
  tests/certs/test_local_ca.py \
  tests/certs/test_cert_rotation.py \
  tests/policy/test_v12_mtls_boundaries.py

echo "verify-release: v1.2 ActivityPub focused tests"
"$PYTHON" -m pytest -q --tb=short \
  tests/activitypub \
  tests/publish/test_broker_integration.py

echo "verify-release: v1.2 cable file-package focused tests"
"$PYTHON" -m pytest -q --tb=short \
  tests/cable \
  tests/publish/test_cable_file_package_surface.py \
  tests/publish/test_router.py

echo "verify-release: v1.2 air-gapped VM proof focused tests"
"$PYTHON" -m pytest -q --tb=short \
  tests/integration/test_airgap_vm_proof.py \
  tests/integration/test_vm_cleanroom_contract.py \
  tests/installer/test_airgap_import.py \
  tests/installer/test_model_bundle.py

echo "verify-release: operator portal build"
run_npm_script "civiccast/apps/portal-operator" "build"

echo "verify-release: operator portal a11y"
run_npm_script \
  "civiccast/apps/portal-operator" \
  "test:a11y" \
  ".agent-runs/${RELEASE_RUN_ID}/verify-release-evidence/operator"

echo "verify-release: operator portal full-stack publish"
run_npm_script \
  "civiccast/apps/portal-operator" \
  "test:fullstack" \
  ".agent-runs/${RELEASE_RUN_ID}/verify-release-evidence/operator-fullstack"

echo "verify-release: public portal build"
run_npm_script "civiccast/apps/portal-public" "build"

echo "verify-release: public portal a11y"
run_npm_script \
  "civiccast/apps/portal-public" \
  "test:a11y" \
  ".agent-runs/${RELEASE_RUN_ID}/verify-release-evidence/public"

echo "verify-release: installer app build"
run_npm_script "civiccast/apps/installer" "build"

if [[ "${OS:-}" == "Windows_NT" ]] || command -v powershell.exe >/dev/null 2>&1; then
    echo "verify-release: installer Windows package"
    run_npm_script "civiccast/apps/installer" "tauri:build"
else
    echo "verify-release: installer Windows package skipped on non-Windows host"
fi

echo "verify-release: installer app e2e"
run_npm_script \
  "civiccast/apps/installer" \
  "test:e2e" \
  ".agent-runs/${RELEASE_RUN_ID}/verify-release-evidence/installer"
"$PYTHON" -c "from pathlib import Path; p=Path('civiccast/apps/installer/test-results/.last-run.json'); p.unlink(missing_ok=True); d=p.parent; d.rmdir() if d.exists() and not any(d.iterdir()) else None"

echo "verify-release: generated API artifacts"
"$PYTHON" scripts/generate-openapi-artifacts.py --check

echo "verify-release: rendered user manual"
"$PYTHON" scripts/render_user_manual.py --check-current

echo "verify-release: policy"
"$PYTHON" scripts/policy/run_all.py --run "$RELEASE_RUN_ID"

echo "verify-release: PASS"
