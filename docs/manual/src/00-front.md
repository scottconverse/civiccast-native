# About this manual {#about}

This is the CivicCast User Manual for **CivicCast (Native) 1.0.0-beta.12**, the Windows version of CivicCast, a program that helps a public-access (PEG) station or a small city put its meetings on the air and on the web.

## What state this software is in

This manual describes **Beta 12**, the native Windows release. Start with the complete download helper in [Chapter 10](#ch-installing), then create the station administrator on the station computer. Whistle provides CPU live captioning; Whisper supplies fallback and recorded captions. The [Beta 12 verification record](https://github.com/scottconverse/civiccast-native/blob/main/docs/releases/v1.0.0-beta.12-verification.md) identifies the signed package and actual installation observations. A separate Beta 11 host run measured **99.88% live caption-input coverage across three channels over 48 hours**; that result belongs to that run. Earlier history remains in the evidence appendix and dated verification records.

This manual describes the software; it does not itself establish publication or installation acceptance. The current release status is always on the project's releases page, <https://github.com/scottconverse/civiccast-native/releases>.

A **historical beta.10 observation** describes behavior or evidence from the superseded release. A **Known issue (version)** names the version in which the behavior was checked. The label alone does not say whether it remains true now: follow any explicit later-version status in the note, and check the current screen and release record when the behavior affects an on-air decision. Beta.11 findings are not Beta.12 verification results.

## Who Reads What

| If you are... | Read |
| --- | --- |
| A volunteer, camera operator, video editor, records clerk or PEG station employee | **Part I** (chapters 1 to 8): what to click, what you will see, what to do when something looks wrong |
| The IT person at a small city who installs and runs CivicCast | **Part II** (chapters 9 to 15): planning, installing, configuring, running, securing, troubleshooting |
| An IT reviewer, integrator or the curious | **Part III** (chapter 16): how the system is built, with diagrams |
| Anyone looking something up | **Part IV**, the appendices: commands, web interface, settings, files and ports, status words, roles, checklists, evidence, glossary, licenses, release history |

## Where the older guide names went

Earlier releases split this manual into separate guides. Their names are still used in other documents, so here is where each one now lives in the CivicCast User Manual.

- **Admin Quick Guide** (also the Admin Guide): Part II, chapters 9 to 15, and Appendices A to F.
- **Meeting Operator Quick Guide** (also the Meeting Operator Guide): Part I, chapters 3 and 4.
- **Records Clerk Quick Guide** (also the Records Clerk Guide): Part I, chapters 5 and 6.
- **Technical Operations Reference**: Part II, chapters 11 to 15, Part III (chapter 16) and Appendices A to E.

## How to read the notes in this manual

> **Note:** background you may need.

> **Tip:** a faster or safer way to do something.

> **Warning:** something that can change what is on the air, delete data, or cannot be undone.

> **Known issue (version):** behavior checked in the named version differs from what the screen suggests; the note gives its scope and a safe next step. A note that says it remains in Beta.12 describes a current limitation; an older label alone is historical.

> **For IT staff:** a pointer from the non-technical part to the technical chapter that has the detail.

## Words used throughout

- **Station** means the Windows computer running CivicCast and everything it controls.
- **Staff console** (also called the *operator console*) is the web page staff use to run the station. It opens at the station's address followed by `/operator/`.
- **Resident portal** is the public web page where residents watch live programs, browse recordings and read the schedule.
- **Channel** is one program stream, like a cable channel. A station can run several.
- **Asset** is one recording or media file stored in CivicCast.
- Times typed into some screens are **UTC** (universal time), not local time. The chapters say so wherever it matters.

## How this manual was made

The manual was written from the product's own code and from a screen-by-screen inventory of the staff console, the resident portal and the installer, then checked against that code. Screens were photographed on a lab station that holds sample (mock) data only. Where the code could not settle a question, the manual says nothing rather than guessing. The version of the software this manual describes is shown on the cover; if you run a different version, details may differ.

## Where to get help and report problems

Report problems and read release notes at the project page: <https://github.com/scottconverse/civiccast-native>. Check <https://github.com/scottconverse/civiccast-native/releases> for current downloads and publication status, then read the verification record for the exact package you use. The [Beta.12 verification record](https://github.com/scottconverse/civiccast-native/blob/main/docs/releases/v1.0.0-beta.12-verification.md) covers the current package; the [Beta.11 record](https://github.com/scottconverse/civiccast-native/blob/main/docs/releases/v1.0.0-beta.11-verification.md) remains available for that superseded package.

<!-- SOURCES: docs/releases/v1.0.0-beta.12-verification.md; docs/releases/v1.0.0-beta.11-verification.md (historical host evidence); docs/releases/v1.0.0-beta.10-verification.md (historical appendix only); docs/releases/release-truth.yaml; ops/docs-sprint/MANUAL-STYLE.md -->
