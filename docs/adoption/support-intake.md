# Early-Adopter Support Intake

Status: current beta adoption guidance

## Support Channels

Use GitHub Discussions or Issues for non-security questions and reproducible
bugs. Use private email for security reports as described in `SECURITY.md`.

Security reports must not be posted publicly. Include `[CivicCast Security]` in
the email subject when reporting a vulnerability.

## What To Include

For setup, installer, meeting, publish, restore, update, or channel-operation
issues, include:

- CivicCast version.
- Operating system; for Windows, the CivicCast product line (WSL public beta
  or native development line) and whether WSL2 is present.
- Installer filename and whether the SHA-256 checksum matched.
- The screen where the issue happened.
- The exact operator message, especially **Ready**, **Check before meeting**,
  **Do not broadcast yet**, **Not set up yet**, or **Needs IT help**.
- Whether this was a rehearsal, test recording, or real meeting.
- A support bundle when the operator console offers one.

## What Not To Include

Do not post passwords, staff tokens, API keys, private meeting content,
subscriber addresses, raw logs with secrets, or unredacted support bundles in a
public issue or discussion.

If you are not sure a file is safe to share, do not post it publicly. Say that a
support bundle exists and wait for a maintainer to ask for a private handoff.

## Response Expectations

Early adoption support is best-effort. Security reports are handled under the
timeline in `SECURITY.md`. Non-security bug reports are triaged by severity:

- **Cannot broadcast or install:** highest priority.
- **Data loss, secret exposure, or broken recovery:** highest priority.
- **Broken core meeting or publish flow:** high priority.
- **Confusing copy, missing docs, or narrow UI issues:** fixed when found, with
  timing based on release risk.

All confirmed issues are fixed when found unless Scott explicitly accepts a
named timing or waiver. The severity tiers above determine response order and
urgency of communication; they do not affect whether an issue gets fixed.

## Useful Links

- Early-adopter quickstart: `docs/adoption/early-adopter-quickstart.md`
- Windows trust and verification: `docs/install/windows-release-trust.md`
- Tester packet: `docs/tester/START-HERE.md`
- Known limitations: `docs/tester/known-limitations.md`
- Security policy: `SECURITY.md`
