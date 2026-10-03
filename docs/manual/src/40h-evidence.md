# Appendix H: Measured evidence and known limits {#app-evidence}

This appendix lists what was measured, on which build, and what the measurements do not show. It is written to be read before you decide to run beta.10 on a real station. The complete record is in the release's verification file, `docs/releases/v1.0.0-beta.10-verification.md`, and the evidence under `ops/beta10-oversight/` in the repository.

## H.1 Which build each result comes from

| Evidence | Build | What it covers |
| --- | --- | --- |
| Clean-install Gate A lane, 10 of 10 criteria | The **published** beta.10 installer and packs (commit `b6520847`) | Install, first start, console and portal render, clerk workflow, captions, playout, 5-minute soak, install progress, completion |
| Eight-hour watched run, 3 channels | Earlier internal build `C16`; the four key engine files are identical to the published source | Playout, program changes, loudness, preparation times, caption drops |
| About 59 hours of uptime, 2 channels | Earlier internal build `C15`, **not** the published build | Long-run stability of the engine |

No long run was done on the published installer. The published build contains the later fixes (including the watchdog that ends a stuck program change) and the installer fixes.

## H.2 Eight-hour watched run (2026-10-01 16:30 to 2026-10-02 00:30, Mountain time)

One lab station, three channels (education, government, public) airing real programs at the same time, captions embedded in the output.

| Measure | Result |
| --- | --- |
| Station service | One process for the whole 8 hours; no restart, no crash |
| Slate or filler after startup | None |
| Station errors and watchdog firings | 0 and 0 |
| Verification checks | 41 run, 40 passed, 1 raw failure (explained below) |
| Loudness | 16 of 16 four-minute windows passed on all three channels (target -16 LUFS, plus or minus 1) |
| Program changes | 50 watched, no holes, no errors; picture gap at most 0.033 s, sound gap at most 0.041 s |
| Preparation of upcoming programs | 51 logged; the longest took 389 s, inside the lead time of about 11 minutes |
| Disk | 46 GB of the 60 GB conform-cache budget used; 810 GB free |

The one raw failure was a check that the education playlist advanced between two samples. It was judged a sampling blip by the run's own records, but a hiccup of under five seconds cannot be ruled out by direct observation, and the raw failure stands in the record.

## H.3 About 59 hours of two channels on the air (the "accidental soak")

After a planned run ended on 2026-09-29, the lab station was left running. The station service started on 2026-09-29 at 02:59 and was still running, with no restart, when it was checked on 2026-10-01 at 14:10, which is about 59 hours. Roughly 51 of those hours were after the planned run ended and were not being watched.

- **Government and public channels:** 27 of 28 programs and 111 of 112 seamless program changes went through. Both channels stayed on the air to the end of the period, with no slate, no filler and no crash.
- **Education channel:** it got stuck in a program change on 2026-09-30 at about 03:44 and then showed black picture and silence for about 34 hours until the service was restarted. The watchdog that now ends that kind of stuck program change was built afterwards and is in the published build. The exact stall has not recurred since.
- **Caption audio:** both channels discarded some live-caption audio under load (government 9 events, 150 seconds; education 8 events, 170 seconds; public 10 events, 230 seconds).
- **One caption file error:** the government channel logged one isolated "permission denied" error while renaming a caption file.

**How to state this fairly.** The same playout engine has run two channels on one lab station for more than two days. That is not the same as saying beta.10 has done so, because the long run used an earlier build. It is two channels on one station, not two stations, and it was assessed from service logs, program-change records and sampled output, not by inspecting every second of video.

## H.4 Known limits of this build

1. **Live-caption audio can be dropped under heavy load.** The caption worker falls behind during long first-time media preparations and then skips ahead, so some spoken audio gets no caption. Captions stay on the air. In the eight-hour run there were 13 catch-up discards; on a quiet machine the total was about 160 seconds of audio over two channels. Stations that need loss-free captions should weigh this. A fix is planned and is not in this build.
2. **Two program-change first attempts aborted and recovered** on the government channel during the eight-hour run, each in about 3 seconds with no visible effect on air.
3. **One single-frame video drop** (0.033 s) at a join inside a program.
4. **Quiet source material is reported, not leveled** when it is too quiet for the loudness control's maximum lift.
5. **Eleven playout-engine unit tests fail** in the same way on the published tree and the installed tree; they were failing before this build and are unexplained.
6. **An unexplained rebuild of a long cached program** was seen in the previous internal run and is unresolved.
7. **Upgrades are not proven.** Installing beta.10 over an earlier release was not tested.
8. **A first install with neither the full kit (installer plus its `packs` and `station` folders) nor an earlier install is not proven.** The installer's own screens say models are downloaded later; the code requires the kit. See [Chapter 10](#ch-installing).
9. **Several staff-console screens describe behavior the code does not have.** These are listed as Known issues in Part I and are collected for the next release.

## H.5 What is not proven

- No human field tester has signed off, and the software has not been run at a real station.
- No 24-hour or 72-hour soak was run on the published build.
- Physical broadcast video cards (DeckLink SDI capture and output), real cable-operator headend acceptance and sustained production use at a real PEG station are unproven.

## H.6 How to use this evidence

Treat beta.10 as a build you can try, watch and report on. Run it alongside your existing process, keep your current way of airing meetings available, and read the Known issues for the screens you will use. If you rely on captions for legal compliance, plan a manual check of captions on the material that matters.

<!-- SOURCES: docs/releases/v1.0.0-beta.10-verification.md; ops/beta10-oversight/OVERSIGHT-LOG.md entries 2026-10-01 14:12 and 14:22; ops/beta10-oversight/verdicts/rung-8h-c16-20261001-163004--VERDICT-NOTE.md -->
