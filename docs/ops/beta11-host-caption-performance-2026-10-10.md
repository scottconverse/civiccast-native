# HOST live-caption performance report — 2026-10-10

This is the approximately 45-hour snapshot. The later 48-hour window and its 99.88% rounded logged-coverage calculation are documented in the [48-hour report](beta11-host-caption-performance-48-hour-2026-10-10.md).

This report records the observed HOST CivicCast run under the owner-defined reporting standard in
[S11](../spec/3.0/sections/S11-captions-loudness-eas-compliance.md) and master §5.

**Run window:** approximately October 8, 2026 at 14:15 MDT through October 10, 2026 at 11:12 MDT
(about 45 hours).

**Scope:** three active channels: Public, Government, and Education. The metric measures discarded
caption-input audio coverage. It does not measure transcript word accuracy. Correct captions that
arrive late count as successful coverage.

**Observed discarded input:** 635 seconds total across approximately 45 hours × 3 channels:

| Channel | Discarded caption-input audio |
|---|---:|
| Public | 235 seconds |
| Government | 195 seconds |
| Education | 205 seconds |
| **Total** | **635 seconds** |

Using approximately 486,000 active channel-audio seconds (45 × 3 × 3,600), the observed result is:

`100 × (1 − 635 ÷ 486,000) ≈ 99.87%`

The run recorded 15 catchups. Separate failure diagnostics recorded 3 Whistle primary failures
(each written twice, for 6 warning lines) and 16 Whisper fallback failure attempts (8 timeouts and
8 allocation errors). The fallback attempts include retries; they are not 16 distinct outages and
do not add audio seconds to the 635-second discarded-input total. This approximately 99.87% result
meets the owner's 99% professional-level reporting benchmark and 98% professional contractual
reporting benchmark. Those are the owner's CivicCast reporting benchmarks; neither is a hard
release minimum.

Future run reports should include the run window, each channel's active-audio denominator and
discarded-input seconds, the aggregate denominator and result, and failure and retry counts as
separate figures. Count each discarded audio interval once even if it appears in multiple failed
attempts. Any proposed caption-performance blocker requires consultation with Scott; release below
98% is the owner's decision.

This is a report of observed HOST runtime behavior. It is not a release-candidate proof or a release
readiness verdict.
