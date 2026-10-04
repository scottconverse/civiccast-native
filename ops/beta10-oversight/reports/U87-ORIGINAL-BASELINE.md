# U87 original beta.5 baseline recovery - v1

Verdict: exact original baseline bytes restored and verified locally. This is
not an installed upgrade or cross-version Gate A PASS. Lane: Critical, artifact
provenance/installation prerequisite. Root independently reviewed pin/docs,
installer signature and98contract tests before this receipt.

Restored directory:
`C:\CivicCastTester\kit-staging\148c8d2172dd6b63cbbb856b429b68aa020dc421`.
Destination did not exist; created and COPY-populated, no overwrite, deletion,
installer execution, helper/VM/service operation, build, commit or push.
The source deb2 kit was read-only and remains unchanged.

## Byte identities and recovery

Original release installer from
`C:\CivicCastTester\baseline-recovery-beta5-20261004\setup.exe`:
SHA256 `775b9a3e63a94183f1c065bb4168d03c0aeb2d72d608c1dbed5c875a94e05842`,
Authenticode `Valid`, ProductVersion `1.0.0-beta.5`. Copied to kit root as
`CivicCast (Native)_1.0.0-beta.5_x64-setup.exe`.

Original index recovered by root through archive extraction, NOT execution:
`embedded\station\station-index.json`, SHA256
`4860825284077fad4c0807cf78816b08a5be4d7c6aa4259bf92b1125d184849a`.
Original embedded `core.ccpack`,1518bytes, SHA256
`96a7ec7492b88f0c0816c3bcf909e5314e260a033a69b375b773610af5807b4e`.
Both copied into destination `station\`.

Four model packs independently hashed before COPY from
`C:\CivicCastTester\kit-staging\deb2adfa9dab7e41c5d9a64fcd2bebb95b26723d\station`;
each size and SHA256 matched the original signed index. All five destination
station packs were independently rehashed after COPY and matched again:

| File | Bytes | SHA256 |
| --- | ---: | --- |
| captions-floor.ccpack |1530926015|9d586209d5a29805c3c7ccea237a3dbaba99bb428161b14db44810b4ccaba0c5|
| summary-gemma4-12b.ccpack |7556514014|7d4d792ed812b4fc302cbdfc2f25fcc1ef68f1ac78cdbc82a7e5b6fddf177284|
| summary-gemma4-e4b.ccpack |9608355569|57a4802ec3ef57b7edca10e5ca1a26224704e82c837e50f46f74373a094fdd62|
| translation-translategemma-4b.ccpack |3298881303|ecd5fb3215e77f820166e62a12263cd1883997222cbfabfdf30b16e28af9fe49|

Five original installer packs from `release-packs\` COPY into destination
`packs\`. Before and after COPY, each matched original release SHA256SUMS:

| File | SHA256 |
| --- | --- |
| native-app-payload.ccpack |759e199fb46b40b0fadf104525f525e4c1773af3d869dd36029d5cf013424784|
| native-cuda-runtime.ccpack |2ab2b2cc8acfc2b363ec3b8fff0af26c667a4808494943d8d9bd0c00ecf5580e|
| native-ffmpeg-runtime.ccpack |2a26749b01d460ebd7aa2716c0714ea6d4ce9bc8d89ecdae56485b145eb91afb|
| native-ollama-runtime.ccpack |192ad0d56abc649afda9a8f353c0454d52b0bcea4c143eb2899d538a2d341629|
| native-server-binaries.ccpack |d6db43ae266b294aca6ea077b66047021e9dfa5e4ecafff0b7ebb9d307bdb127|

Destination SHA256SUMS retains these original digests, with relative filenames
updated to the actual kit layout. Original downloaded checksum file is unchanged.
Gate A's existing local admission was reproduced: exactly one setup, pinned
installer/index hashes, installer ProductVersion and index version all match.
No new validator or harness was added.

## Signature and historical contract boundary

`gh variable get CIVICCAST_PACK_PUBLIC_KEY_BASE64 --repo scottconverse/civiccast-native`
returned the existing production PUBLIC key. Its32decoded bytes verified the
original Ed25519 signature over existing `native_distribution.canonical_json`
manifest bytes. Full envelope bytes are canonical. Exact148c8d source
`scripts/build_native_station_bundle.py` required tuple and
`native_activation.rs::REQUIRED_COMPONENTS` match the recovered manifest:
core, captions-floor, summary-gemma4-12b, summary-gemma4-e4b,
translation-translategemma-4b. large-v3 is optional in the historical activation.

Disclosed check failure: current and exact148c8d Python
`native_distribution.verify_distribution_index` use a DIFFERENT legacy
large-v3-required contract. Direct invocation failed with
`NativeDistributionError: native distribution required component set is incomplete: captions-large-v3`.
This unrelated API was not weakened or represented as PASS. Signature verification
and historical production station-contract comparison passed independently.

## Pin/docs and existing tests

`upgrade-baseline.json` restores original486082... pin; notes correct the previous
unrecoverable claim and retain reconstructed attempt2/job105485113314/owner
receipt8d5730a... as superseded history. Successful original build attempt1,
sourceSHA, installer hash and version checks are unchanged. Gate A docs match.
Existing immutable-identity contract test now pins original index and recovered
installer provenance explicitly; no test was removed or relaxed.

Commands from `C:\Dev\Claude\civiccast-u73`:

`& 'C:\Dev\Claude\security-python-f23ca5a7f58f\.venv\Scripts\python.exe' -m pytest tests/gate_a/test_gate_a_harness_contract.py -q`

Baseline `98 passed in 2.08s`.
RED same executable/module with `-k immutable_candidate_identity`, output saved
`U87-ORIGINAL-BASELINE-red.txt`: `1 failed, 97 deselected in 1.80s` (ff7c vs486).
GREEN `98 passed in 2.59s`, saved `U87-ORIGINAL-BASELINE-green.txt`.

`& 'C:\Dev\Claude\security-python-f23ca5a7f58f\.venv\Scripts\python.exe' -m pytest tests/gate_a -q`
`227 passed in 10.83s`, saved `U87-ORIGINAL-BASELINE-affected.txt`.

`& 'C:\Dev\Claude\security-python-f23ca5a7f58f\.venv\Scripts\python.exe' -m ruff check tests/gate_a/test_gate_a_harness_contract.py`
`All checks passed!`

`& 'C:\Dev\Claude\security-python-f23ca5a7f58f\.venv\Scripts\python.exe' -m ruff format --check tests/gate_a/test_gate_a_harness_contract.py`
`1 file already formatted`

`git diff --check`: exit0, no output.

proved: original signed index, installer,5station pack size/hash and5release pack
hash identities at restored local destination; sensitive existing-contract
RED/GREEN and affected tests; lane: Critical. Installed acceptance remains unrun.
