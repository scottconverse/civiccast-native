# 1.3.1 - Private Beta Finish Pass

Public framing: **Private beta installer finish**.

Release-note line:

> v1.3.1 makes the v1.3 Windows private beta easier to download, explain,
> verify, install, and support before broader v1.4 feature work starts.

## Scope

v1.3.1 is a finish pass for the v1.3.0 operator-first beta. It does not expand
the product surface. It cleans up release identity, install instructions,
support instructions, and proof so private testers use the GitHub Release setup
executable rather than repository source archives, Git LFS files, or local
developer artifacts.

## Deliverables

1. README, tester docs, known limitations, and release notes agree that v1.3.x
   is a private beta Windows installer release.
2. Installation instructions point to the GitHub Release `.exe` asset and warn
   against using repository ZIPs, tester handoff files, or Git LFS artifacts for
   normal installation.
3. Release assets include the Windows setup executable, checksum file, release
   manifest, and a short Windows install guide.
4. SmartScreen and Authenticode status are stated plainly: unsigned private beta
   builds may show unknown-publisher warnings.
5. First-run wording keeps WSL2 details behind the installer path where
   possible, while preserving honest IT-help boundaries for admin approval,
   virtualization, WSL2, Ubuntu, and reboot cases.
6. Support loop is clear: create a support bundle, include path and SHA-256,
   and never paste secrets, recovery codes, provider credentials, resident data,
   or private meeting content.
7. Final smoke proof starts from the published GitHub Release `.exe`, not from
   local `artifacts/`, `tester-handoff/`, or Git LFS-backed files.

## Non-Goals

- Broad external-provider live proof.
- Full granular RBAC or SSO.
- Public repository/download launch.
- Authenticode signing requirement.
- Hosted or managed deployment packaging.

## Verification

- Docs links resolve from README, docs index, tester packet, and user manual.
- `docs/USER-MANUAL.md` renders to PDF and DOCX.
- Generated API docs and TypeScript types remain current if version metadata
  changes touch generated output.
- Installer build metadata reports v1.3.1.
- The GitHub Release asset smoke proof records the downloaded URL, file size,
  SHA-256, SmartScreen/signing observation, and installer-to-dashboard outcome.

## Follow-On Queue

v1.3.2 should handle public distribution posture: public download location,
repo or release visibility decision, Authenticode signing or explicit unsigned
policy, and a cleaner support intake path for people outside the private repo.

v1.4 should remain the feature follow-on for broader external-provider live
proof and more granular role enforcement.
