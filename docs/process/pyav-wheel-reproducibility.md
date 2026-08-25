# PyAV wheel byte-exact reproducibility — hosted vs. self-hosted

`scripts/build_native_pyav_wheel.py` compiles CivicCast's pinned LGPL-only
PyAV wheel from source (PyAV + a minimal FFmpeg build) and, on success,
asserts the compiled wheel's **byte-exact** size and SHA-256 match a
reviewed reference (`EXPECTED_WHEEL_BYTES` / `EXPECTED_WHEEL_SHA256`). Every
input the build downloads first — the pinned `uv` executable, the FFmpeg
source archive, the MSYS2 base, the PyAV sdist — is verified against its own
pinned hash and that check is **always strict**, on every build lane. This
document is only about the *output* check: the compiled wheel itself.

## Why the same pinned toolchain can still produce different bytes

The toolchain the build compiles with (MSVC Build Tools, node, python, uv)
is byte-identical across machines: `scripts/provision_native_build_toolchain.py`
downloads the exact pinned artifacts named in
`native-windows-build-toolchain.lock.json`, verified by SHA-256, regardless
of which physical machine runs the provisioning step.

That does not make the *compiled output* byte-identical across machines.
MSVC's linker and compiler can embed build-machine-dependent state into the
binary even with an identical toolchain: absolute scratch/build paths
(`$RUNNER_TEMP` differs per machine and per run), PDB paths, and similar
build-environment artifacts. The FFmpeg DLLs PyAV links against have been
observed to differ in *content* at *identical sizes* between two build runs
that used the same reviewed SDK — see the standing project note on this
(`/pyav-wheel-pin-unreproducible` in Scott's working memory): the fix is to
pin the SDK identity tightly (already done, via the toolchain lock) and
**not** chase this with more compiler flags — `/Brepro`, `/pathmap`, and a
pinned `nasm` are already set, and adding more has not closed the gap.

## What changed for the self-hosted build lane

`native-beta-candidate-artifacts.yml`'s `build_target: self-hosted` path
(see `docs/ops/gate-a.md` and the workflow's own header) runs the exact same
pack-build scripts on a different physical machine than the `windows-latest`
hosted runners the reviewed hash was captured against. To avoid failing a
release candidate purely because of the machine it happened to compile on —
while never weakening the *input* verification — the self-hosted lane passes
`--advisory-pyav-wheel-hash` down the call chain:

- `scripts/build_native_pyav_wheel.py --advisory-wheel-hash`
- `scripts/build_native_app_payload.py --advisory-pyav-wheel-hash`
- `scripts/build_native_app_payload_pack.py --advisory-pyav-wheel-hash`

With this flag, `verify_artifact()`'s mismatch on the **final compiled
wheel only** (the `candidate` / `output` call sites in `build()`) logs a
`::warning::` naming the actual vs. expected bytes/hash and continues,
instead of raising `PyAvWheelBuildError`. Every other `verify_artifact()`
call in the file — all four pinned downloads — has no `advisory` argument
and stays a hard failure on every lane, self-hosted included.

Letting the *build* step accept a wheel with different bytes only matters if
the *install* step that consumes that wheel can also accept it.
`scripts/build_native_app_payload.py`'s `install_pinned_dependencies()`
normally runs one `uv pip install --require-hashes -r requirements-native-app.txt`
against the full lock, which pins `av==18.0.0`'s hash to the hosted-reviewed
reference — the same hash `verify_artifact()` just logged a warning about
instead of enforcing. `install_pinned_dependencies()` therefore takes the
same `advisory_pyav_wheel_hash` flag `build()` receives (and
`build_native_app_payload_pack.py` forwards it): when set, `av` installs from
the wheelhouse by its verified-unique filename with no hash check of its own
(the source-level hash checks — uv, FFmpeg source, MSYS2 base, PyAV sdist —
already ran strictly, and the wheel is this same build's own freshly-compiled
output), while every OTHER dependency still installs `--require-hashes`
against the unmodified reviewed lock via a second, filtered invocation. When
unset, install behavior is unchanged: the single unified `--require-hashes`
install of the full lock.

The hosted lane (`build_target: hosted`, the default, and every
`push`-triggered candidate build on the release branch) never passes this
flag: hosted builds keep the byte-exact assertion as a hard failure at both
the build and the install step, exactly as before this change.

## The independent post-build provenance sweep needs the SAME flag, separately

Getting the self-hosted-built `av` wheel through the *build* and *install*
steps above is not the end of the chain. `scripts/build_native_app_payload_pack.py`'s
`build_app_payload_pack()` runs `scripts/verify_native_app_payload.py`'s
`check_app_payload_verification()` — an INDEPENDENT deny-by-default re-check
of the fully assembled payload tree, from scratch, after the build finishes.
It re-derives file ownership from the retained `WHEELS/*.whl` files by the
SAME reviewed byte-hash pin `install_pinned_dependencies()` uses — a
completely separate code path that previously had no advisory posture of its
own. Candidate run 32822175257 got through the build and install steps
(#30's fix) and still failed here: `"WHEELS/av-18.0.0-cp311-abi3-win_amd64.whl
is not an authorized retained dependency wheel"` plus every one of `av`'s
installed files reported `"is named by no wheel RECORD"` (the wheel was never
authorized, so none of its members were ever added to the ownership map this
sweep builds).

`check_app_payload_verification()` (and `build_app_payload_pack()`, which
calls it) now also takes `advisory_pyav_wheel_hash`, forwarded from the same
CLI flag. `_retained_dependency_wheel_provenance()` in
`verify_native_app_payload.py`: on a byte-hash miss for `av` specifically
(its name/version pin against the reviewed lock is UNAFFECTED and still a
hard failure), it authorizes the wheel by **build provenance** instead of by
wheel byte hash — re-asserting the two upstream inputs the wheel was
compiled FROM, which (unlike the compiled output) are always hash-verified,
hard-fail, on every lane. Those two identities are read back out of the
wheel's own embedded `<dist-info>/FFMPEG-PROVENANCE.json` (`ffmpeg_provenance()`
in `build_native_pyav_wheel.py` now records `pyav_sdist_sha256`/`bytes`
alongside the FFmpeg source archive's, which it already recorded) and
re-checked against the SAME `PYAV_SDIST_SHA256`/`BYTES` and
`FFMPEG_SOURCE_SHA256`/`BYTES` constants — never trusted unchecked. Once
authorized this way, the existing per-member ownership walk needs no further
change: it already anchors every installed byte to the IN-RUN wheel's own
bytes and members (never the reviewed reference's), which is what resolves
the RECORD mismatch — a self-hosted `av` wheel's RECORD was never wrong, it
was simply never reached because the wheel was never authorized in the first
place.

Every OTHER retained wheel, and `av` itself when `advisory_pyav_wheel_hash`
is unset (the hosted lane, always), is unaffected: still hash-pinned exactly
as before this layer gained the fallback.

## What this does and does not prove

A self-hosted candidate build whose PyAV wheel hash triggered the advisory
warning is **not** proof the wheel is wrong — the runtime probe
(`run_runtime_probe`) still executes the compiled wheel and decodes real
audio frames as part of the same build, and the license/provenance gate
(`verify_native_app_payload.py`'s deny-by-default sweep, described above)
still runs unconditionally and still authorizes `av` only by re-verifying
real upstream build-input hashes, never by skipping the check. It **is** a
signal that this specific candidate's PyAV wheel bytes were not
independently reproduced against the hosted-reviewed reference, which is
worth carrying into release-candidate review notes for that run.
