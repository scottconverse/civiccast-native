# Windows setup: station activation and self-test (exit 67 = "station self-test failed")  (nav id: installer-nsis-activation-selftest, section: Installer)
Source files (under `civiccast/apps/installer/src-tauri/`): `nsis-hooks-bootstrap.nsh:1393-1505`, `src/main.rs:5850-5932,5505-5706,4737-5126,5143-5200`, `src/native_activation.rs`, `src/native_distribution.rs:470-546`
Who can open it: runs inside the elevated setup.exe after the database step. No roles.

## What it is for
Turns the files laid down so far into a working station: it takes the signed station bundle, extracts the caption and AI-model packs, then actually runs the programs and models once (a self-test) before declaring the station activated. It writes `station-set.json` and `activation-self-test.json` at the install folder; the service refuses to start without them.

## Where it gets its input (`:1453-1473`)
1. `<folder of setup.exe>\station\station-index.json` (the kit): the signed index plus the model packs beside it.
2. Else `<install dir>\station\station-index.json` (a tiny copy embedded in setup.exe) with the packs taken from the pack cache `<install dir>\packs\.station-cache` (`native_distribution.rs:489-497`).
3. Neither: exit 123 with "CivicCast (Native) setup could not activate the station: no signed station index (station-index.json) was found beside setup.exe at <folder>\station, and this setup.exe does not carry the embedded copy it normally ships with. Download the CivicCast (Native) setup again from the official release page, or copy the full CivicCast kit folder (setup.exe together with its station folder) onto this machine and run setup from there."
Command: `"CivicCast Native.exe" --civiccast-activate-station --install-root "$INSTDIR" --civiccast-import-station "<index>" --cache-root "$INSTDIR\packs\.station-cache"`. Details-pane lines: "Activating the CivicCast (Native) station (K1)...", "CivicCast (Native): using the station bundle beside setup.exe (<folder>\station)." or "...using the station index embedded in setup.exe (<folder>\station)." No network is used (the hook passes no channel address).

## What activation does (`native_activation.rs:882-972,986-1045`)
1. Verifies the index signature and every pack's signature, size and SHA-256 (exit 66 on failure).
2. If a matching `station-set.json` + receipt already exist: does nothing ("already activated").
3. Free-space check: needs the sum of all pack sizes (extraction is about 1:1) plus 2 GB working room on the install drive; refuses before deleting anything with "Not enough free disk space to activate this station. The station's components need about N GB, plus 2 GB of working room, on the drive holding <folder> -- but only M GB is free. Nothing has been changed or deleted. Free up space (or install to a drive that has it) and run setup again." (`:870-879`). Unreadable free space proceeds.
4. Deletes any old extracted component folders, then extracts: captions-floor to `packs\captions-floor`, the three model packs to `components\<id>`, optional captions-large-v3 to `components\captions-large-v3`; the `core` pack is not extracted. Merges the three model packs into one store at `models\ollama`. Checks that 16 required files exist and are plain files (python, postgres, pg_ctl, ffmpeg, ollama, faster_whisper, ctranslate2, the four medium-model files, the test audio, three model manifests) (`:311-330`).
5. Runs the self-test below. Writes `activation-self-test.json` then `station-set.json` (receipt first; if the manifest write fails the receipt is removed).

## Self-test (all must pass; `main.rs:5505-5586`, `4737-5126`)
| # | Check | Pass condition | Time limit |
|---|---|---|---|
| 1 | `runtime\python.exe -I -B -c "import civiccast, ctranslate2, faster_whisper; ..."` | prints `native-core-ok`; faster_whisper 1.2.1, ctranslate2 4.8.1 | 30 s |
| 2 | `postgres.exe --version`, `pg_ctl.exe --version` | output contains "postgres" / "pg_ctl" | 30 s each |
| 3 | `ffmpeg.exe -version` | contains "ffmpeg" | 30 s |
| 4 | `ollama.exe --version` | contains "0.30.6" | 30 s |
| 5 | TSDuck `tsp.exe --version` | only if present; absent is a logged note: "Native activation: TSDuck (tsp.exe) is not staged ... udp-ts egress will run direct-from-encoder without the seamless-splice relay (#151). TSDuck is optional; continuing activation." | 30 s |
| 6 | Caption inference: CPU, int8, offline, model Large if staged else Medium, on `jfk.wav` | text contains "fellow americans" and "country" | 300 s |
| 7 | AI inference: starts a private Ollama on a free 127.0.0.1 port with the merged store, waits until ready, then asks gemma4:12b ("Reply with exactly CIVICCAST_OK and nothing else."), gemma4:e4b ("...CIVICCAST_FALLBACK_OK..."), translategemma:4b (translate "The council meeting is open." to Spanish; expects "La reunión del consejo está abierta.") | exact replies | ready within 300 s; each request up to 300 s |
All of this is CPU work on the station; the whole test can take many minutes.

## Exit codes of `--civiccast-activate-station` and what setup shows (`:1487-1505`)
| Child exit | Cause (code) | Setup exit | Dialog text (start) |
|---|---|---|---|
| 0 | activated or already activated | continue | "CivicCast (Native): station activation complete (or already activated; no-op)." |
| 66 | index or pack could not be obtained or verified | 123 | "...could not obtain the station's component packs from the signed station index it found. If you installed from a CivicCast kit folder, make sure its station folder was copied across whole. If you ran setup.exe on its own, the packs it needs must already be in this machine's pack cache from a previous install. See the installer log above for the exact underlying error -- it names either the missing pack or the signature/version check that refused one." |
| 67 | ANY error after the packs were verified: no free space, extraction failure, missing file, or a self-test failure (`main.rs:5927-5929`) | 123 | "CivicCast (Native) setup laid down the station's components, but the station's own self-test did not pass, so setup stopped rather than leave you with a station that looks installed and does not work. This is NOT a missing-files problem -- the component packs were obtained and verified. The self-test that failed is named in the installer log at C:\ProgramData\CivicCast\install-progress.log. Your recordings, database and settings in C:\ProgramData\CivicCast were not deleted." |
| 78 | embedded signing key refused | 123 | "This copy of CivicCast (Native) setup is not a valid release build: its embedded signing key was refused... Download CivicCast (Native) setup again from the official release page" |
| 64, 65 | setup program defect | 123 | "This copy of CivicCast (Native) setup is defective: its own station-activation step was invoked with arguments it does not accept..." |
| other | | 123 | "...could not activate the station from the signed station index it found (exit code N). See the installer log at C:\ProgramData\CivicCast\install-progress.log for the exact underlying error. Your recordings, database and settings in C:\ProgramData\CivicCast were not deleted." |

## Controls and what they do
None. Interactive runs show an OK-only dialog on failure; before exiting setup stops the service and sets it to manual start (best-effort, `:357-424`).

## Typical task flows
1. Good kit: activation prints the two "using the station bundle..." lines, runs the self-test (silent), then "station activation complete".
2. Exit 123: read the details pane list for the exact error line; fix; run setup again (already extracted trees are cleared and rebuilt).

## Help-text findings
- [HELP-87] SERIOUS: the exit-67 dialog says the failed self-test "is named in the installer log at install-progress.log", but activation runs with `nsExec::ExecToLog` (`:1459,1467`): the child's error line goes to the setup details pane only; install-progress.log receives just "step d4-activate-station: returned 67" (`:1475`). No "child reported" line is written (compare stage-packs, `:861`). A support person following the dialog will not find the cause. Needs a coder fix: capture and log the child's output.
- [HELP-88] SERIOUS: exit 67 is also returned for "not enough free disk space" and extraction failures (`native_activation.rs:870-879,947`), yet the dialog insists "This is NOT a missing-files problem" and blames a self-test. An operator with a full drive is told the wrong thing.
- [HELP-89] The details pane shows only "Activating the CivicCast (Native) station (K1)..." for what can be many minutes of extraction plus AI test runs. No progress, no "this takes a long time" warning. "(K1)" is an internal ticket id.
- [HELP-90] The activation step needs the full kit or a prior pack cache (HELP-77); the dialog for 66 tells the operator to copy "the full CivicCast kit folder" but the kit's folder layout is not described anywhere in the setup.
- [HELP-91] "self-test" is not explained (what is tested, that Spanish translation is exercised, that CPU is used so a slow computer needs longer).

## Screenshot plan
Details pane during activation (two "using the station bundle" lines); the exit-67 dialog (rename `jfk.wav` in a copy of the kit, or fill the drive); the exit-66 dialog (delete one model pack from the kit's station folder).

## UNVERIFIED / open questions
- UNVERIFIED: actual run time on a typical PEG box; size of each model pack; whether Large is staged by default in the kit (only if `captions-large-v3` is in the index).
- UNVERIFIED: that stderr of the child really is not copied to install-progress.log by NSIS (ExecToLog goes to the details pane; confirm by a failing run).
