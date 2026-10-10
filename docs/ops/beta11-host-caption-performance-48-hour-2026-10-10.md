# Beta 11 host live-caption performance — 48 hours — 2026-10-10

This report extends the approximately 45-hour HOST snapshot in [the earlier report](beta11-host-caption-performance-2026-10-10.md). It records one host runtime observed as healthy `1.0.0-beta.11`; it is not a package qualification or a Beta 12 soak.

**Run window:** October 8, 2026 at 14:14:47 MDT through October 10, 2026 at 14:14:47 MDT (48 hours).

**Scope:** Public, Government, and Education channels; three nominally continuous channel streams. The milestone snapshot checked the service at 14:15:20 MDT, about 33 seconds after the window endpoint. At that check all three channels were `on_air`, within capacity, and had caption VTT ages of 1.6–3.6 seconds. The [raw milestone snapshot](evidence/beta11-host-48-hour-milestone-2026-10-10.json) records the observed host version, service state, channel states, and timestamp.

## Logged discarded caption input

The host application log and rotations `.1` through `.6` contain 15 caption-input discard batches in the window:

| Channel | Batches | Discarded caption-input audio |
|---|---:|---:|
| Public | 6 | 235 seconds |
| Government | 5 | 195 seconds |
| Education | 4 | 205 seconds |
| **Total** | **15** | **635 seconds** |

The nominal denominator is 48 × 3 channels × 3,600 = 518,400 channel-seconds. Retained input was 518,400 − 635 = 517,765 channel-seconds, so the logged caption-input coverage calculation is:

`100 × (1 − 635 ÷ 518,400) = 99.877507716%` (**99.88% rounded to two decimals**).

The [15 counted catch-up log records](evidence/beta11-host-48-hour-caption-discard-events-2026-10-10.txt) preserve the source lines used for these sums: Public 235 seconds, Government 195, and Education 205, totaling 635. The separate startup record for a finished broadcast is excluded because it has no discarded duration and is not an input-loss event in this run.

This is logged caption-input audio coverage using a nominal continuous three-channel denominator, not a frame-by-frame measure of active audio or proof of uninterrupted delivery. Correct captions that arrive late count as successful coverage. Retries and fallback attempts are not additional lost time; each logged discarded interval is counted once. The measure does not assess transcript word accuracy, establish legal compliance, or qualify an installer.

The independent observer recorded 144 healthy application checkpoints from October 8 at 14:27 MDT through October 10 at 14:07 MDT, with 144 VTT-age samples per channel. The largest sampled ages were 5.36 seconds for Public, 6.09 for Government, and 5.30 for Education; the largest checkpoint gap was 20.55 minutes. These periodic samples cannot rule out brief interruptions between checks.

## Reproduction

The counted source lines were selected from `C:\ProgramData\CivicCast\logs\control_plane-app.log` and its `.1` through `.6` rotations with this filter, then limited to the run timestamps above and summed once by channel:

```powershell
$files = Get-ChildItem 'C:\ProgramData\CivicCast\logs' -File -Filter 'control_plane-app.log*' |
  Where-Object { $_.Name -match '^control_plane-app\.log(?:\.[1-6])?$' }
Select-String -Path $files.FullName -Pattern 'civiccast\.captions\.tap_worker:.*(discard|catch.?up)' -CaseSensitive:$false
```

Content-reload settlement messages were excluded because they do not report caption-input loss. A startup warning for a finished broadcast had no duration and was outside the active run. Retry/fallback warning lines were tracked separately and not added to discarded seconds. The 45-hour report recorded the same 635 seconds; no additional caption-input discard batch was found between that report's approximate 11:12 MDT cutoff and this window's endpoint.
