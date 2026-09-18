# Blackwell caption word confirmation — engineering report v1

## What changed

The old live-caption rule could put words on air merely because two audio windows overlapped. It did not establish that the words themselves were heard twice. A first repair that required a repeated phrase was safer, but real saved audio exposed long missing-caption gaps. That first repair was not accepted as sufficient.

The current source asks the installed Whisper model for actual word timestamps. It compares repeated words from different audio windows, requires real overlap between their observed times, and counts each window once. Words heard only once do not gain confirmation from neighboring words. Confirmed phrases become one caption update per window. An ASCII `...` marks an interior omission; it is an editorial omission marker, not recognized speech. No artificial word timestamps were created.

Unconfirmed live words remain visible in the review workflow, including at channel stop. They are not put on air by the new timed-word stop path. The older/offline stop behavior is unchanged. Existing minimum-confirmation settings were not relaxed. The separate tap change uses the full preceding five-second segment so the ten-second audio window advances five seconds.

## What was checked

- Original unsafe behavior: six specific regression assertions failed before the first repair.
- Independent reviewer found and reproduced duplicate-prefix and first-observation confidence defects during development. Both have failing-before/passing-after regression checks.
- Word-confirmation, first-window growth, zero-duration words, window identity, three-observation counting, and real timestamp offsets have regression coverage.
- A real worker-level stop test exposed two missing review-result propagation steps. Both were corrected; unconfirmed words persist for human review without entering the active caption track.
- Current caption test suite: **374 passed, 1 skipped** in 34.24 seconds. The skip requires an external PostgreSQL server. Ruff passed; mypy passed on the five changed caption source modules; changed-file diff whitespace check passed.
- Independent final review found no additional blocker within this source change. The reviewer replayed both final saved-hypothesis sets and reproduced all 23 cue objects exactly, rechecked review-only stop persistence, and ran a 100-window synthetic stream: at most 10 retained word states, 495 unique emitted words, and no output on replaying an already-observed window. These are bounded checks, not an installed-service or long-soak result.

## Real GPU replay, not an installed-service test

Two different sets of 24 saved five-second speech WAV files were replayed through the installed CUDA model and the current repository source. Both actual model device and compute type were asserted as **cuda / float16**. Every input file hash, raw model word result, hypothesis, and emitted cue is preserved in the JSON receipts beside this report.

Each 120-second replay produced **23 caption updates**: the first window has no earlier observation to confirm it. The last audio tail remains pending until a later observation or review-only flush. This is substantially better than the earlier phrase-only attempts, including one that emitted only five captions in the same two minutes.

The first clip's largest gap between emitted cue intervals was 2.29 seconds; the second's was 3.32 seconds. This is not a word-error-rate or completeness score. Recognition disagreements and unmatched words are deliberately withheld. The second clip still contains a short, 0.48-second cue reading “points by.” Its source timing was not stretched to hide that limitation. The separate output-pagination review must address display behavior honestly.

## Files to inspect

- **blackwell-final-word-replay-A.json** — speech files 002410 through 002433.
- **blackwell-final-word-replay-B.json** — speech files 008830 through 008853; full recorded source hashes match the current source candidate.
- **blackwell-lexical-replay.py** — reproducible isolated replay runner; takes output filename and first WAV number.
- Earlier retained attempts include `blackwell-lexical-replay.json`, `blackwell-lexical-replay-speech.json`, `blackwell-lexical-replay-speech-third.json`, grouped fourth/fifth/sixth receipts, word-time inspection seventh, and word-alignment eighth/ninth/tenth receipts. The first two selections were silence, and the fifth had speech only near its beginning. Those were not presented as successful sustained-speech proof.

The A replay's recorded worker hash precedes the final one-line flush-result counter propagation. Its ASR, model, and stabilizer bytes are identical to the final candidate. B records all current module hashes. The final stabilizer SHA-256 is `EB624ED4FD2C27407CE0AA4FC20A094FF3D99E5668FFEF936DDD41B5BAF8E537`.

## What this does NOT prove

This is source-level logic and isolated preserved-audio GPU evidence. It is **not** proof that the running CivicCast service loaded these files, that three concurrent caption channels meet their deadline, that the emitted transport stream displays every caption correctly, that the public installer contains this candidate, or that a long soak passed. Those checks remain with the release owner. No service was restarted or installed product file changed by this work, and no commit, merge, tag, or release was performed by this subtask.
