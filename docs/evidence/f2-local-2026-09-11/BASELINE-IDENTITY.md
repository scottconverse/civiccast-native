# F2 beta.5 baseline identity investigation

Read-only investigation on 2026-09-11. No baseline bytes or pins were changed,
and no workflow or service was started.

## Conclusion

The authoritative retained station index for published beta.5 candidate source
`148c8d2172dd6b63cbbb856b429b68aa020dc421`, build run `34405681086`, is:

`4860825284077fad4c0807cf78816b08a5be4d7c6aa4259bf92b1125d184849a`

The currently pinned value:

`044a9c8b5879644e526f58c4826fe1b21f59b8291a98794b6dd205c826e9d059`

belongs to the earlier candidate `39d852e5149e3320a2c8ab4e70aa40ed55632ef1`.
It is a stale cross-candidate copy, not a second encoding of the beta.5 index.

## Evidence

- GitHub build run: <https://github.com/scottconverse/civiccast-native/actions/runs/34405681086>
  concluded success, with `headSha=148c8d2172dd6b63cbbb856b429b68aa020dc421`.
  Its station-bundle job built, signed, verified, and mirrored the station bundle;
  its assembly job co-located that mirror into the final local kit.
- The build's original durable candidate mirror
  `C:\CivicCastTester\candidates\148c8d...\station-bundle\station\station-index.json`,
  retained `kit-staging\148c8d...`, and retained `kit-safe\148c8d...` all have
  the same file timestamp (`2026-09-09 15:25:01 -06:00`) and SHA-256 `486082...`.
- Both beta.5 `SHA256SUMS.txt` manifests name `486082...` for
  `station/station-index.json`.
- The file whose SHA-256 is `044a9c...` still exists at
  `C:\CivicCastTester\kit-safe\39d852e5...\station\station-index.json`; that
  candidate's own `SHA256SUMS.txt` names `044a9c...`.
- The two signed index envelopes have identical product version and pack byte
  identities. They differ in `created_epoch` and the resulting Ed25519
  signature: candidate `39d852e5` used epoch `1788975116`; candidate `148c8d21`
  used epoch `1788988983`. This explains why the whole-file hashes differ.
- Git history shows commit `a2ccfc98bc257afd196d4b541ec1dbabce258e0f`
  repinned every beta.5 identity field to `148c8d21` but inserted the earlier
  candidate's `044a9c...` station-index hash. The same stale value had already
  been copied into beta.5 release evidence in commit `834d68f5`.
- Published release: <https://github.com/scottconverse/civiccast-native/releases/tag/v1.0.0-beta.5>
  is a currently published prerelease record targeting full SHA `148c8d2172dd6b63cbbb856b429b68aa020dc421`,
  published September 9, 2026 at 10:14 PM Mountain. The published `setup.exe` digest is
  `775b9a3e63a94183f1c065bb4168d03c0aeb2d72d608c1dbed5c875a94e05842`,
  exactly matching the retained kit.
- The retained installer is 289,302,104 bytes and has valid Authenticode from
  `CN=Scott Converse, O=Scott Converse, L=Longmont, S=co, C=US`, certificate
  thumbprint `43D8CFB8A94035C646A9AEBEE49FE93D888EC5D4`, with a Microsoft timestamp.

The public release does not publish `station-index.json` as an individual asset;
therefore GitHub supplies current source/build and installer metadata, while
the original build mirror plus two independently retained manifests supply the
station-index byte identity. The workflow's successful station-bundle verification
proves the signed envelope was accepted during build. No public signing key was
read from credentials, so this investigation did not independently re-run the
Ed25519 verification.

## Smallest correction

Change `station_index_sha256` in `sandbox-lab/upgrade-baseline.json` from
`044a9c...` to the full `486082...` value above. Keep source SHA, build run,
Gate A run, installer hash, and product version unchanged. Update the two stale
documentary copies in:

- `docs/releases/v1.0.0-beta.5-verification.md`
- `docs/releases/2026-09-04-beta5-release-notes.md`

The note should state that `044a9c...` belonged to candidate `39d852e5` and that
`486082...` is bound by the original `148c8d21` candidate mirror and both retained
SHA256SUMS manifests. Do not regenerate or re-sign the station index: the retained
beta.5 bytes already match their manifests and the successful build provenance.

Root verification: all three retained148c8d21 indices hash486082...; earlier39d852e5 hashes044a9c.... Release API explicitly reports immutable=false. Its current source SHA and setup.exe digest match the retained beta.5 build. Root accepted the single-pin correction based on these combined sources; release immutability is not claimed.
