# About this manual {#about}

This is the CivicCast User Manual for **CivicCast (Native) 1.0.0-beta.11 candidate**, the Windows version of CivicCast, a program that helps a public-access (PEG) station or a small city put its meetings on the air and on the web.

## What state this software is in

Beta.11 is being prepared for release. Its Whistle live-caption changes completed an owner-accepted 24-hour three-station lab soak. The packaged beta.11 installer has not yet completed installation verification. The previous beta.10 was published on 2 October 2026 as a GitHub pre-release; its installation evidence below is historical and does not verify beta.11. Neither version is a production release. This manual says plainly what was tested and what was not, so you can decide how much to rely on it.

- **Beta.10 installer tested and passed:** a clean install in a Windows test sandbox ran the installer, started the station, showed the staff console and the resident portal, ran a clerk workflow, produced captions, played a channel and ran a short five-minute soak. All 10 checks in the clean-install lane passed.
- **Earlier beta.10 operation evidence:** an eight-hour lab run with three channels on one machine, and about 59 hours of two channels staying on the air on one lab station. Details and limits are in [Appendix H](#app-evidence).
- **Not tested:** upgrading from an earlier release, a first install with neither the full kit nor an earlier install, and use at a real station. No human field tester has signed off. Real cable-company acceptance and physical broadcast video cards are unproven.

This manual describes the software; it does not itself establish publication or installation acceptance. The current release status is always on the project's releases page, <https://github.com/scottconverse/civiccast-native/releases>.

Every place where the software does something different from what its own on-screen help says is marked in this manual with a **Known issue (beta.10)** note. Believe the manual over the screen where the two disagree.

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

> **Known issue (beta.10):** this build behaves differently from what the screen suggests; the note says what really happens and what to do.

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

Report problems and read release notes at the project page: <https://github.com/scottconverse/civiccast-native>. The latest release and its downloads are at <https://github.com/scottconverse/civiccast-native/releases/tag/v1.0.0-beta.10>.

<!-- SOURCES: docs/releases/v1.0.0-beta.10-verification.md; docs/releases/release-truth.yaml; ops/docs-sprint/MANUAL-STYLE.md -->
