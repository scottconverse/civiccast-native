# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Keep the sandbox TSDuck JSON parser wired and strict."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DRIVER = (ROOT / "sandbox-lab/scripts/In-Sandbox-Soak.ps1").read_text(encoding="utf-8")
CLASSIFIER = (ROOT / "sandbox-lab/scripts/TSDuckReportClassifier.ps1").read_text(encoding="utf-8")
RUNNER = (ROOT / "sandbox-lab/Run-SandboxSoak.ps1").read_text(encoding="utf-8")


def test_tsduck_nested_packet_schema_is_strict_and_wired() -> None:
    assert "TSDuckReportClassifier.ps1" in DRIVER
    assert "Get-TSDuckReportMetrics $j" in DRIVER
    assert "$result.verdict = Get-TSDuckMetricsVerdict $metrics" in DRIVER
    assert "-Name 'total'" in CLASSIFIER
    assert "-Name 'invalid-syncs'" in CLASSIFIER
    assert "-Name 'transport-errors'" in CLASSIFIER
    assert "pid_discontinuities" in CLASSIFIER
    assert "return 'fail-stream-errors'" in CLASSIFIER
    assert "return 'pass'" in CLASSIFIER
    assert "[int] $Metrics" not in CLASSIFIER
    assert "[int]$result.packets_total" not in DRIVER
    assert "TSDuckReportClassifier.ps1" in RUNNER


def test_tsduck_timeouts_remain_failed_probes() -> None:
    start = DRIVER.index("function Test-TsProof")
    block = DRIVER[
        start : DRIVER.index(
            "# ----------------------------------------------------------------", start
        )
    ]
    assert "'fail-timed-out'" in block
    assert "Stop-Process -Id $proc.Id" in block
