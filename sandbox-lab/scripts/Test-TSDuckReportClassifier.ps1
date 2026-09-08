# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'TSDuckReportClassifier.ps1')
function Assert-True { param([string] $Name, [bool] $Value) if (-not $Value) { throw "Assertion failed: $Name" } }
function Assert-Throws { param([string] $Name, [scriptblock] $Action) try { & $Action; throw "Assertion failed: $Name did not throw" } catch { if ($_.Exception.Message -like 'Assertion failed:*') { throw } } }

# Sanitized shape from the retained beta.5 soak report: PAT, PMT, video, audio.
$report = @'
{"pids":[{"id":0,"packets":{"discontinuities":0}},{"id":32,"packets":{"discontinuities":1}},{"id":65,"packets":{"discontinuities":2}},{"id":66,"packets":{"discontinuities":0}}],"services":[{"id":1}],"ts":{"packets":{"total":42674,"invalid-syncs":0,"transport-errors":0}}}
'@ | ConvertFrom-Json
$metrics = Get-TSDuckReportMetrics $report
Assert-True 'nested total extracted' ($metrics.packets_total -eq 42674)
Assert-True 'nested error counters extracted' ($metrics.invalid_syncs -eq 0 -and $metrics.transport_errors -eq 0)
Assert-True 'all PID discontinuities are summed' ($metrics.pid_discontinuities -eq 3)
Assert-True 'nonzero PID discontinuity fails the stream proof' ((Get-TSDuckMetricsVerdict $metrics) -eq 'fail-stream-errors')
$clean = @'
{"pids":[{"packets":{"discontinuities":0}}],"ts":{"packets":{"total":922337203685477580,"invalid-syncs":0,"transport-errors":0}}}
'@ | ConvertFrom-Json
Assert-True 'large nested counters remain Int64 and pass when clean' ((Get-TSDuckMetricsVerdict (Get-TSDuckReportMetrics $clean)) -eq 'pass')
$zeroPackets = @'
{"pids":[{"packets":{"discontinuities":0}}],"ts":{"packets":{"total":0,"invalid-syncs":0,"transport-errors":0}}}
'@ | ConvertFrom-Json
Assert-True 'zero packet evidence fails rather than passing' ((Get-TSDuckMetricsVerdict (Get-TSDuckReportMetrics $zeroPackets)) -eq 'fail-zero-packets')
$missing = '{"pids":[],"ts":{"packets":{"total":1,"invalid-syncs":0,"transport-errors":0}}}' | ConvertFrom-Json
Assert-Throws 'empty PID list is not treated as zero discontinuities' { Get-TSDuckReportMetrics $missing }
$malformed = '{"pids":[{"packets":{"discontinuities":0}}],"ts":{"packets":{"total":1,"invalid-syncs":0}}}' | ConvertFrom-Json
Assert-Throws 'absent transport errors is not treated as zero' { Get-TSDuckReportMetrics $malformed }
$nullValue = '{"pids":[{"packets":{"discontinuities":0}}],"ts":{"packets":{"total":1,"invalid-syncs":null,"transport-errors":0}}}' | ConvertFrom-Json
Assert-Throws 'null nested counter is not treated as zero' { Get-TSDuckReportMetrics $nullValue }
$negative = '{"pids":[{"packets":{"discontinuities":-1}}],"ts":{"packets":{"total":1,"invalid-syncs":0,"transport-errors":0}}}' | ConvertFrom-Json
Assert-Throws 'negative nested counter is rejected' { Get-TSDuckReportMetrics $negative }
$nonInteger = '{"pids":[{"packets":{"discontinuities":"one"}}],"ts":{"packets":{"total":1,"invalid-syncs":0,"transport-errors":0}}}' | ConvertFrom-Json
Assert-Throws 'noninteger nested counter is rejected' { Get-TSDuckReportMetrics $nonInteger }
Write-Host 'PASS: TSDuck nested metrics are strict and aggregate per-PID discontinuities.'
