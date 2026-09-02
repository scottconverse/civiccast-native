# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
<#
.SYNOPSIS
Prune stale per-sha candidate/kit directories on the self-hosted sandbox-lab
box, keeping the sha being built AND the pinned previous-candidate baseline.

.DESCRIPTION
Two local roots on that box are keyed by <sha>:

  * C:\CivicCastTester\candidates\<sha>\ -- intermediate mirrors written by
    native-beta-candidate-artifacts.yml's build-native-beta,
    build-native-station-bundle, and assemble-native-beta-kit
    (candidate\, station-bundle\).
  * C:\CivicCastTester\kit-staging\<sha>\ -- the FINAL flat kit
    assemble-native-beta-kit writes there, which is the exact path/layout
    gate-a-station-acceptance.yml's "Reuse a locally pre-staged kit" step
    reads via Test-Path + a junction (never a copy), and never prunes from
    that side.

Without a prune, every self-hosted dispatch adds another ~20-40 GB across the
two roots that is never reclaimed. Safe to prune from a build job: the
"sandbox-lab" concurrency group (shared with gate-a-station-acceptance.yml)
guarantees no Gate A run is reading either root while a self-hosted build
executes.

WHAT MUST NEVER BE PRUNED (PR #124, 2026-09-02). The cross-version upgrade
lane (gate-a-station-acceptance.yml, "Require the pinned previous full kit
from local staging") installs the IMMUTABLE previous candidate from
C:\CivicCastTester\kit-staging\<previous sha> and fails closed when it is
absent. A keep-only-the-current-sha prune is exactly what emptied that lane
three times on 2026-09-02 (runs 33592973903 and the two after; the kit was
restored from the stick each time). The baseline's own sha is therefore kept
alongside the sha being built.

THIS SCRIPT EXISTS SO THAT RULE HAS ONE IMPLEMENTATION. Two self-hosted jobs
prune (build-native-station-bundle, which runs first and writes the largest
single mirror on the box, and build-native-beta), and a hand-copied second
copy of the keep-list is precisely how the #124 regression would come back --
a reviewer caught exactly that on feat/installer-embeds-station-index before
it merged. Both jobs call this file; neither carries its own keep-list.

.PARAMETER CurrentSha
The candidate sha being built (github.sha). Kept, never pruned.

.PARAMETER BaselinePath
Path to sandbox-lab/upgrade-baseline.json, relative to the workspace. Its
`source_sha` is kept too. A missing or malformed baseline is NOT fatal --
prune-nothing-extra is the safe direction, and tests/gate_a already fails
closed on a malformed baseline where that actually matters.

.PARAMETER Roots
Semicolon-delimited list of the per-sha roots to prune. Defaults to the two
real ones; parameterized so the behaviour can be tested against a scratch tree
rather than only asserted as text. A DELIMITED STRING rather than a
[string[]]: `pwsh -File` (how CI invokes this) passes every argument as a
literal string and never parses a comma list into an array, so a [string[]]
parameter would silently bind "a,b" as ONE path and the prune would no-op.
Semicolon is safe -- it cannot appear in a Windows path.
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$CurrentSha,

    [string]$BaselinePath = "sandbox-lab/upgrade-baseline.json",

    [string]$Roots = "C:\CivicCastTester\candidates;C:\CivicCastTester\kit-staging"
)

$ErrorActionPreference = "Stop"

if ($CurrentSha -notmatch '^[0-9a-f]{40}$') {
    throw "prune_local_candidate_roots: -CurrentSha must be a lowercase 40-character sha, got '$CurrentSha'."
}

$keep = @($CurrentSha)

if (Test-Path -LiteralPath $BaselinePath) {
    # Deliberately tolerant: a baseline this script cannot parse means "keep
    # more than strictly necessary", never "delete the pinned kit".
    try {
        $baseline = Get-Content -LiteralPath $BaselinePath -Raw | ConvertFrom-Json
        if ([string]$baseline.source_sha -match '^[0-9a-f]{40}$') {
            $keep += [string]$baseline.source_sha
            Write-Host "Keeping pinned previous candidate kit: $($baseline.source_sha) ($($baseline.candidate_label))"
        } else {
            Write-Host "::warning::$BaselinePath has no usable source_sha; pruning will keep only $CurrentSha."
        }
    } catch {
        Write-Host "::warning::Could not read $BaselinePath ($($_.Exception.Message)); pruning will keep only $CurrentSha."
    }
} else {
    Write-Host "::warning::$BaselinePath not found; pruning will keep only $CurrentSha."
}

$rootPaths = @($Roots.Split(';', [System.StringSplitOptions]::RemoveEmptyEntries))
if ($rootPaths.Count -eq 0) {
    throw "prune_local_candidate_roots: -Roots resolved to no paths."
}

Write-Host "Pruning local candidate roots, keeping: $($keep -join ', ')"

foreach ($rootPath in $rootPaths) {
    if (Test-Path -LiteralPath $rootPath) {
        Get-ChildItem -LiteralPath $rootPath -Directory -ErrorAction SilentlyContinue |
            Where-Object { $keep -notcontains $_.Name } |
            ForEach-Object {
                Write-Host "Removing stale local candidate: $($_.FullName)"
                Remove-Item -LiteralPath $_.FullName -Recurse -Force -ErrorAction SilentlyContinue
            }
    } else {
        New-Item -ItemType Directory -Force -Path $rootPath | Out-Null
    }
}
