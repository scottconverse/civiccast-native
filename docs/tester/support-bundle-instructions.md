# Support Bundle Instructions

Use a support bundle when a tester hits a setup, rehearsal, source, publish, or
review problem.

## Create The Bundle

1. Open **System Health**.
2. Add a short note describing what failed.
3. Select **Create support bundle**.
4. Select **Download support bundle** and save the JSON file on the Windows
   computer.
5. Copy the downloaded filename and displayed SHA-256 into the bug report. The
   bundle may also display a Linux/WSL file path for the same data; that path
   is diagnostic context, not the file-handoff method.
6. Send the report and downloaded bundle through the private beta issue,
   discussion, or support
   channel Scott provided. Do not post bundles publicly unless a maintainer
   confirms they are safe to share.

## What It Includes

- CivicCast version.
- Platform summary.
- Station setup state.
- Backup, restore, and update status.
- Provider readiness.
- Source setup guidance.
- System Health and safe-to-broadcast state.
- Recent setup/support context.
- A tail of the installer's WSL bootstrap log, if it ran on this machine.
- A tail of each live channel's recent FFmpeg logs.

## What It Redacts

- Tokens.
- Passwords.
- Private keys.
- Provider credentials.
- Database passwords.
- Subscriber data.
- Private meeting content.
- Any log line that contains a secret-, token-, password-, key-, credential-,
  or nonce-shaped marker is dropped from the included log tails, not just
  partially masked.

If you are unsure whether a file is safe to share, do not post it publicly.

## Station Acceptance Packet

Use **Create acceptance packet** (same System Health screen) when a franchise
authority, board, or reviewer asks for evidence the station is set up and
operating. It is a redacted, hashed snapshot of station setup, safe-to-broadcast
health, and backup/restore/update/provider/source readiness — the same
underlying status the support bundle uses, reframed as a standalone record
instead of a troubleshooting dump. CivicCast displays the acceptance packet's
internal path and SHA-256 but does not provide a Windows download button for
that packet. Record both values in the private acceptance report; if the JSON
itself is required, have an authorized administrator retrieve it from the host.
