// SPDX-License-Identifier: Apache-2.0
// Copyright (c) The CivicCast Authors

//! Offline-first / online-fallback delivery of required native component
//! packs (`.ccpack` files) into `$INSTDIR\packs`, per the owner-approved
//! sub-300 MB bootstrap architecture
//! (`.agent-runs/native-windows/specs/plan-sub-300mb-bootstrap.md`: "the
//! bootstrap exe carries NO station packs; packs are delivered separately;
//! an offline/air-gapped install path is mandatory"). Wired into
//! `NSIS_HOOK_POSTINSTALL` in `nsis-hooks-native.nsh` between the D2
//! install-time re-verification of the laid tree and D4 database/messaging
//! provisioning (`--civiccast-provision`), because
//! `civiccast.native.provision.__main__.resolve_provision_paths`'s
//! `server_pack_path` default (`$INSTDIR\packs\native-server-binaries.ccpack`)
//! must exist and verify before the provisioning engine's own
//! `PACK_VERIFIED` phase can pass.
//!
//! ## Decision matrix (per required component)
//!
//! | destination state | offline source state | action                    |
//! |--------------------|-----------------------|----------------------------|
//! | verified present    | (irrelevant)          | `AlreadySatisfied` (no copy, no re-download -- D5's idempotency posture) |
//! | absent               | verified offline      | `CopyFromOffline`         |
//! | corrupt               | verified offline      | `ReplaceCorruptFromOffline` |
//! | absent or corrupt    | absent or invalid     | `NeedsOnlineOrAbort`       |
//!
//! Every `NeedsOnlineOrAbort` component is retried through the existing
//! online channel-acquire machinery (`native_distribution::
//! acquire_online_distribution`, reused verbatim -- never forked). No
//! channel index URL is pinned anywhere in this codebase today (grepped:
//! `--civiccast-acquire-channel` always takes an operator-supplied URL, no
//! default), so an invocation with no `--channel-url` returns a typed
//! [`OnlineAttemptOutcome::NotAvailable`] rather than attempting a network
//! call that has nowhere configured to go -- exactly the task's explicit
//! allowance ("if the channel manifest infrastructure isn't deployable yet,
//! this branch is allowed to return a typed NOT_AVAILABLE"). Components still
//! unresolved after the online attempt produce a loud abort naming every
//! missing component and the ONE remedy that exists -- side-loading the pack
//! file(s) ([`build_pack_delivery_abort_message`]). It deliberately does not
//! offer a network/download remedy: with no channel index URL pinned, a
//! connected machine hits exactly the same abort as an air-gapped one
//! (chain F-min2, 2026-08-01).
//!
//! ## Reuse, not a fork
//!
//! Signature + byte-inventory verification is always
//! `native_packs::verify_pack` / `native_packs::embedded_pack_trust` --
//! never re-implemented here. A pack is verified (component identity,
//! product version, compatible core, every file's SHA-256) BEFORE it is
//! copied, and the COPY is re-verified after landing (D2's own posture:
//! "verify before laying files; corrupt => loud failure", applied to a
//! side-loaded/downloaded pack the same way it already applies to the
//! embedded application payload in `native_install_verify.rs`).

use std::collections::BTreeMap;
use std::fs::{self, File};
use std::io;
use std::path::{Path, PathBuf};

use serde::Serialize;

use crate::native_distribution;
use crate::native_install_verify;
use crate::native_packs::{self, PackTrust, VerifiedPack};

/// The required-pack set is ALWAYS an input to [`stage_required_packs`], never
/// a hard-coded list inside this module -- this constant is only the CLI's
/// own default when the caller (today, `nsis-hooks-bootstrap.nsh`) passes no
/// `--require-component` flag at all. A later work package that turns on a
/// caption-pack (or summary/translation) requirement flag adds to the list
/// the CALLER passes; this module never needs to change to support that.
///
/// `native-app-payload` joined this default set in the WP2 app-payload-pack
/// gap closure (2026-07-30): before it, no build target produced an
/// application-payload pack at all, so widening this list to require one
/// would have turned every bootstrap install into an unconditional abort
/// (see `wp2-hook-migration-2026-07-30.md` §2). `scripts/
/// build_native_app_payload_pack.py` now builds that pack, and
/// [`ensure_pack_extracted`] special-cases its extraction destination to
/// `$INSTDIR\runtime` (see that function's doc) so the interpreter lands
/// exactly where D4 provisioning/service-registration already hard-code it.
///
/// `native-ffmpeg-runtime` joined this default set for the same class of
/// reason, one step later: nothing built an FFmpeg pack at all, so a native
/// install shipped no `ffmpeg.exe`/`ffprobe.exe` anywhere -- while
/// `native_activation.rs`'s `validate_staged_runtime_layout` and `main.rs`'s
/// staged-runtime self-test BOTH pin `dependencies/ffmpeg/bin/ffmpeg.exe`,
/// and the product shells out to those tools for the recording/packaging/
/// slate paths. `scripts/build_native_ffmpeg_pack.py` now builds that pack,
/// and [`pack_extraction_destination`] maps it to `$INSTDIR\dependencies\
/// ffmpeg` so its `bin/`-rooted payload lands on exactly the pinned path.
///
/// The private native-beta candidate carries both dependency sidecars beside
/// the installer. They are required here, not left as merely downloadable
/// artifacts: staging is the only elevated path that can land their verified
/// payloads under `$INSTDIR\dependencies` before LocalSystem starts the
/// supervisor. Omitting either component lets setup report an installed product
/// while the product later degrades on an absent executable.
pub const DEFAULT_REQUIRED_COMPONENTS: &[&str] = &[
    "native-server-binaries",
    APP_PAYLOAD_COMPONENT,
    FFMPEG_RUNTIME_COMPONENT,
    OLLAMA_RUNTIME_COMPONENT,
];

/// The pack "component" identity for the signed native-app-payload pack
/// (CPython 3.12 embeddable + the `civiccast` wheel + hash-pinned
/// dependency wheels), matching `civiccast.native.app_payload.
/// APP_PAYLOAD_COMPONENT` on the Python side exactly (a drift-guard test
/// below pins the literal string both sides must agree on).
pub const APP_PAYLOAD_COMPONENT: &str = "native-app-payload";

/// The pack "component" identity for the signed native-ffmpeg-runtime pack
/// (the `ffmpeg.exe`/`ffprobe.exe` command-line tools plus the minimal PE
/// import closure of FFmpeg shared libraries they need), matching
/// `scripts.build_native_ffmpeg_pack.FFMPEG_RUNTIME_COMPONENT` on the Python
/// side exactly (a drift-guard test below pins the literal string both sides
/// must agree on, the same way `APP_PAYLOAD_COMPONENT` already is).
pub const FFMPEG_RUNTIME_COMPONENT: &str = "native-ffmpeg-runtime";

/// The product-owned Ollama runtime sidecar. Its payload is rooted at
/// `ollama.exe` and bridged to `$INSTDIR\dependencies\ollama`, matching the
/// supervisor and activation validator's existing absolute path contract.
pub const OLLAMA_RUNTIME_COMPONENT: &str = "native-ollama-runtime";

/// The pack "component" identity for the signed native-cuda-runtime pack
/// (cuBLAS + cuDNN Windows runtime DLLs, `scripts/build_native_cuda_pack.py`),
/// matching `scripts.build_native_cuda_pack.CUDA_RUNTIME_COMPONENT` on the
/// Python side exactly (a drift-guard test below pins the literal string
/// both sides must agree on, the same way `FFMPEG_RUNTIME_COMPONENT` already
/// is).
///
/// OWNER RULING (Scott Converse, 2026-08-15): capable stations get GPU
/// caption acceleration. `station_runtime.resolve_cuda_bin_dir`'s presence
/// gate already ships (a prior work package on this same branch); this
/// component is the pack it looks for. Deliberately OPTIONAL --
/// [`DEFAULT_OPTIONAL_COMPONENTS`], never [`DEFAULT_REQUIRED_COMPONENTS`]: a
/// station with no NVIDIA GPU, or an operator who declines the download,
/// must install and run identically to today, captioning on CPU.
pub const CUDA_RUNTIME_COMPONENT: &str = "native-cuda-runtime";

/// Components staged OPTIONALLY (see [`stage_optional_packs`]): absent is a
/// normal, silently-recorded outcome (setup continues without them, and
/// every consumer -- e.g. `station_runtime.resolve_cuda_bin_dir` -- already
/// treats "not staged" as a legitimate, non-fatal state); PRESENT is
/// verified exactly as strictly as any required pack. "Optional means may be
/// absent, never may be untrusted."
///
/// Distinct from [`DEFAULT_REQUIRED_COMPONENTS`] by more than just severity:
/// a required component missing at the end of staging is a loud installer
/// abort ([`build_pack_delivery_abort_message`]); an optional component
/// missing is not reported as an error at all, only recorded in
/// [`OptionalPackStagingReport::skipped_absent`].
pub const DEFAULT_OPTIONAL_COMPONENTS: &[&str] = &[CUDA_RUNTIME_COMPONENT];

// ---------------------------------------------------------------------------
// Pure decision matrix
// ---------------------------------------------------------------------------

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum DestPackState {
    Absent,
    Verified,
    Corrupt(String),
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum OfflineSourceState {
    Absent,
    Verified,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum StagingAction {
    AlreadySatisfied,
    CopyFromOffline,
    ReplaceCorruptFromOffline,
    NeedsOnlineOrAbort,
}

/// Pure: the ENTIRE per-component staging decision, taking only the already-
/// classified destination/source states -- no filesystem or network access.
/// See the module doc's decision-matrix table.
pub fn decide_offline_staging_action(
    dest: &DestPackState,
    source: &OfflineSourceState,
) -> StagingAction {
    match dest {
        DestPackState::Verified => StagingAction::AlreadySatisfied,
        DestPackState::Absent => match source {
            OfflineSourceState::Verified => StagingAction::CopyFromOffline,
            OfflineSourceState::Absent => StagingAction::NeedsOnlineOrAbort,
        },
        DestPackState::Corrupt(_) => match source {
            OfflineSourceState::Verified => StagingAction::ReplaceCorruptFromOffline,
            OfflineSourceState::Absent => StagingAction::NeedsOnlineOrAbort,
        },
    }
}

/// Mirrors [`StagingAction`], but for an OPTIONAL component: an absent
/// destination with no offline source is [`SkipAbsent`](Self::SkipAbsent)
/// (a normal outcome -- never [`StagingAction::NeedsOnlineOrAbort`]'s loud
/// abort trigger), while a PRESENT-but-corrupt destination with no remedy is
/// [`CorruptWithNoRemedy`](Self::CorruptWithNoRemedy) -- a hard failure, not
/// a skip. "Optional means may be absent, never may be untrusted": a
/// tampered or corrupted optional pack must never be silently treated the
/// same as one that was simply never obtained.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum OptionalStagingAction {
    AlreadySatisfied,
    CopyFromOffline,
    ReplaceCorruptFromOffline,
    SkipAbsent,
    CorruptWithNoRemedy,
}

/// Pure: the ENTIRE per-optional-component staging decision. See
/// [`OptionalStagingAction`]'s doc for how this differs from
/// [`decide_offline_staging_action`] on the two cells where a required and
/// an optional component's treatment must diverge.
pub fn decide_optional_staging_action(
    dest: &DestPackState,
    source: &OfflineSourceState,
) -> OptionalStagingAction {
    match dest {
        DestPackState::Verified => OptionalStagingAction::AlreadySatisfied,
        DestPackState::Absent => match source {
            OfflineSourceState::Verified => OptionalStagingAction::CopyFromOffline,
            OfflineSourceState::Absent => OptionalStagingAction::SkipAbsent,
        },
        DestPackState::Corrupt(_) => match source {
            OfflineSourceState::Verified => OptionalStagingAction::ReplaceCorruptFromOffline,
            OfflineSourceState::Absent => OptionalStagingAction::CorruptWithNoRemedy,
        },
    }
}

/// Pure: which required components remain missing given the offline decision
/// for each and, for the ones that needed it, whether the online attempt
/// satisfied them. `online_satisfied` names components the online attempt
/// actually landed and re-verified.
pub fn missing_after_all_attempts(
    needs_online: &[String],
    online_satisfied: &[String],
) -> Vec<String> {
    needs_online
        .iter()
        .filter(|component| !online_satisfied.contains(component))
        .cloned()
        .collect()
}

/// Pure: the operator-facing loud-abort message, naming every missing
/// component and the concrete fix (per hook error conventions -- every
/// operator-facing abort in this product names the concrete fix).
///
/// It used to name TWO remedies, the second being "connect this machine to the
/// network so setup can download them". That path does not exist: no channel
/// index URL is pinned anywhere in this codebase, so
/// [`attempt_online_pack_acquire`] can only return a typed
/// [`OnlineAttemptOutcome::NotAvailable`], and a networked machine gets
/// exactly the same abort as an air-gapped one. Chain F-min removed that
/// sentence from the NSIS dialog; it is removed here too because chain F-min2
/// made `nsis-hooks-bootstrap.nsh` capture this string and write it verbatim
/// into `install-progress.log` and the wizard detail pane -- leaving it here
/// would have put the false remedy straight back in front of the operator
/// through the child instead of the dialog.
///
/// The component list is why the hook persists this at all: it is the ONLY
/// place the missing-component names exist, and the failure dialog promises
/// the operator will find them in the installer log.
pub fn build_pack_delivery_abort_message(missing_components: &[String]) -> String {
    format!(
        "CivicCast (Native) setup could not obtain the following required native component \
         pack(s): {}. The matching pack file(s) are published alongside the installer -- on \
         the same release page, or on the same distribution medium setup came from. Obtain \
         them, place them in a 'packs' folder next to the installer, and run setup again.",
        missing_components.join(", ")
    )
}

// ---------------------------------------------------------------------------
// Online attempt (thin I/O over the existing acquire-channel machinery)
// ---------------------------------------------------------------------------

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum OnlineAttemptOutcome {
    /// Nothing was missing; the online path was never invoked.
    NotAttempted,
    /// No channel index URL is configured for this build/invocation -- the
    /// channel manifest infrastructure is not deployable yet. Not an error:
    /// a typed, expected outcome the caller falls through to a loud abort
    /// from (naming the offline remedy too).
    NotAvailable(String),
    /// A channel URL was supplied but acquisition failed (network, signature,
    /// or index-contract error).
    Failed(String),
    /// The online index was acquired; these required components were found
    /// in it, downloaded, verified, and committed to `$INSTDIR\packs`.
    /// Components not present in the index (e.g. one whose identity the
    /// online distribution's own required-component set does not carry) are
    /// simply absent from this list, not an error on their own.
    Satisfied(Vec<String>),
}

/// Attempt to satisfy `missing_components` through the existing online
/// channel-acquire machinery (`native_distribution::acquire_online_distribution`,
/// called directly -- never duplicated). Returns a typed
/// [`OnlineAttemptOutcome::NotAvailable`] rather than attempting a network
/// call when no channel URL is configured, per the task's explicit
/// allowance.
#[allow(clippy::too_many_arguments)]
pub fn attempt_online_pack_acquire(
    missing_components: &[String],
    channel_url: Option<&str>,
    channel: &str,
    cache_root: &Path,
    dest_dir: &Path,
    trust: &PackTrust,
    expected_product_version: &str,
    expected_compatible_core: &str,
) -> OnlineAttemptOutcome {
    if missing_components.is_empty() {
        return OnlineAttemptOutcome::NotAttempted;
    }
    let Some(url) = channel_url else {
        return OnlineAttemptOutcome::NotAvailable(
            "no channel index URL is configured for this build; online native component pack \
             acquisition is not deployable yet"
                .to_string(),
        );
    };
    let acquired = match native_distribution::acquire_online_distribution(
        url,
        cache_root,
        trust,
        channel,
        expected_product_version,
        expected_compatible_core,
    ) {
        Ok(acquired) => acquired,
        Err(error) => return OnlineAttemptOutcome::Failed(error),
    };

    let mut satisfied = Vec::new();
    for component in missing_components {
        let Some(pack) = acquired
            .packs
            .iter()
            .find(|candidate| &candidate.component == component)
        else {
            continue;
        };
        let destination = dest_dir.join(format!("{component}.ccpack"));
        if commit_pack_file(
            &pack.cached_path,
            &destination,
            trust,
            component,
            expected_product_version,
            expected_compatible_core,
        )
        .is_ok()
        {
            satisfied.push(component.clone());
        }
    }
    OnlineAttemptOutcome::Satisfied(satisfied)
}

// ---------------------------------------------------------------------------
// Thin I/O: classification + commit
// ---------------------------------------------------------------------------

/// Verify every `*.ccpack` file directly inside `source_dir` (the documented
/// air-gapped side-load location, `<installer_dir>\packs\`) BEFORE trusting
/// any of it, and index the ones that verify by their MANIFEST-DECLARED
/// component identity (never by filename -- an operator may have renamed the
/// file). Entries are processed in sorted filename order for determinism; if
/// two valid files claim the same component, the first (alphabetically)
/// wins and the rest are ignored, matching a "first verified wins" rule
/// rather than an ambiguous silent overwrite.
pub fn discover_offline_pack_sources(
    source_dir: &Path,
    trust: &PackTrust,
    expected_product_version: &str,
    expected_compatible_core: &str,
) -> BTreeMap<String, PathBuf> {
    let mut found = BTreeMap::new();
    let Ok(entries) = fs::read_dir(source_dir) else {
        return found;
    };
    let mut candidates: Vec<PathBuf> = entries
        .filter_map(|entry| entry.ok())
        .map(|entry| entry.path())
        .filter(|path| {
            path.is_file()
                && path
                    .extension()
                    .and_then(|value| value.to_str())
                    .is_some_and(|value| value.eq_ignore_ascii_case("ccpack"))
        })
        .collect();
    candidates.sort();
    for path in candidates {
        if let Ok(verified) = native_packs::verify_pack(
            &path,
            trust,
            None,
            Some(expected_product_version),
            Some(expected_compatible_core),
        ) {
            found.entry(verified.component).or_insert(path);
        }
    }
    found
}

/// Classify the destination pack for one required component: absent, present
/// and verified, or present and corrupt (re-verification failed -- reason
/// captured for the report/log, matching D5 Repair's "re-verify current tree
/// against the signed manifest" posture applied to a single pack file).
pub fn classify_dest_pack_state(
    destination: &Path,
    trust: &PackTrust,
    component: &str,
    expected_product_version: &str,
    expected_compatible_core: &str,
) -> DestPackState {
    if !destination.is_file() {
        return DestPackState::Absent;
    }
    match native_packs::verify_pack(
        destination,
        trust,
        Some(component),
        Some(expected_product_version),
        Some(expected_compatible_core),
    ) {
        Ok(_) => DestPackState::Verified,
        Err(error) => DestPackState::Corrupt(error),
    }
}

/// Copy `source` to `destination` via a `.ccpack.partial` staging file (never
/// a direct in-place write a half-finished copy could be read from), then
/// re-verify the LANDED COPY -- not the source -- against the SAME identity
/// expectations. A failed re-verification removes the partial/landed file
/// rather than leaving a half-trusted pack on disk.
pub fn commit_pack_file(
    source: &Path,
    destination: &Path,
    trust: &PackTrust,
    component: &str,
    expected_product_version: &str,
    expected_compatible_core: &str,
) -> Result<VerifiedPack, String> {
    let parent = destination
        .parent()
        .ok_or_else(|| format!("Pack destination has no parent: {}", destination.display()))?;
    fs::create_dir_all(parent)
        .map_err(|error| format!("Could not create native pack destination directory: {error}"))?;
    let partial = destination.with_extension("ccpack.partial");
    let _ = fs::remove_file(&partial);
    copy_file_durably(source, &partial)
        .map_err(|error| format!("Could not stage native component pack copy: {error}"))?;
    fs::rename(&partial, destination).map_err(|error| {
        let _ = fs::remove_file(&partial);
        format!("Could not activate staged native component pack copy: {error}")
    })?;
    native_packs::verify_pack(
        destination,
        trust,
        Some(component),
        Some(expected_product_version),
        Some(expected_compatible_core),
    )
    .map_err(|error| {
        let _ = fs::remove_file(destination);
        format!("Copied native component pack failed re-verification (removed): {error}")
    })
}

fn copy_file_durably(source: &Path, destination: &Path) -> io::Result<()> {
    let mut input = File::open(source)?;
    let mut output = File::create(destination)?;
    io::copy(&mut input, &mut output)?;
    output.sync_all()
}

// ---------------------------------------------------------------------------
// Extraction (closes the gap `commit_pack_file` deliberately left open: a
// verified RAW `.ccpack` at `$INSTDIR\packs\<component>.ccpack` is not yet
// the EXTRACTED tree `civiccast.native.provision.__main__.
// resolve_provision_paths`' `initdb_path` default expects,
// `$INSTDIR\packs\<component>\payload\bin\initdb.exe` -- see
// `wp2-pack-delivery-reconciliation-2026-07-29.md`'s "Scope note on
// extraction", which explicitly disclosed this as left open, not invented
// here.)
// ---------------------------------------------------------------------------

/// The extraction destination for one required component's pack.
///
/// Every component's RAW `.ccpack` lands at `dest_dir\<component>.ccpack`
/// (`dest_dir` is always `$INSTDIR\packs`, see [`stage_required_packs`]) --
/// that convention is unconditional and unaffected by this function. Its
/// EXTRACTED tree's destination, however, is not uniform:
///
/// * `native-app-payload` extracts to `$INSTDIR\runtime` -- the fixed path
///   `native_service_registration.rs`'s `provision_command` and
///   `service_registration_command` already hard-code for the embedded
///   interpreter they shell out to (`install_root.join("runtime").join(
///   "python.exe")`). Those two call sites are the "hook invocations" this
///   bridge exists to satisfy; changing them instead of the extraction
///   mapping would mean re-deriving a `packs\native-app-payload\payload\`
///   path in two places that have no other reason to know about the pack
///   layout convention. Bridging here keeps that convention a pure
///   implementation detail of pack delivery.
/// * `native-ffmpeg-runtime` extracts to `$INSTDIR\dependencies\ffmpeg` --
///   the SAME class of bridge, for the same reason. `native_activation.rs`'s
///   `validate_staged_runtime_layout` and `main.rs`'s staged-runtime
///   self-test both pin `dependencies/ffmpeg/bin/ffmpeg.exe` literally, and
///   the supervisor's own child-process environment resolves the media tools
///   from that directory. Because the pack's payload is rooted at `bin/`
///   (see `scripts/build_native_ffmpeg_pack.py`), mapping the component here
///   lands `ffmpeg.exe` at exactly `$INSTDIR\dependencies\ffmpeg\bin\
///   ffmpeg.exe`. The alternative -- leaving it on the generic rule and
///   re-pointing every consumer at `packs\native-ffmpeg-runtime\payload\
///   bin\` -- would move a pack-layout implementation detail into the
///   activation validator, the runtime self-test, and the supervisor
///   environment, which is precisely what bridging here exists to prevent.
/// * `native-cuda-runtime` extracts to `$INSTDIR\dependencies\cuda` -- the
///   SAME class of bridge again, mirrored one-for-one from
///   `native-ffmpeg-runtime`'s. `station_runtime.cuda_bin_dir` computes
///   `<root>\dependencies\cuda\bin` as this component's staging location,
///   and its `resolve_cuda_bin_dir` presence gate checks exactly that path
///   for `cublas64_12.dll`/`cudnn64_9.dll`. Because the pack's payload is
///   rooted at `bin/` (see `scripts/build_native_cuda_pack.py`), mapping the
///   component here lands those DLLs at exactly
///   `dependencies/cuda/bin/cublas64_12.dll`. Unlike the two bridges above,
///   this component is staged OPTIONALLY (see [`stage_optional_packs`]) --
///   the bridge itself is unaffected by that distinction, since a present
///   pack still needs a real destination to extract to.
/// * every other component (today, `native-server-binaries`) keeps the
///   generic `dest_dir\<component>\payload\` convention
///   `resolve_provision_paths`'s `initdb_path` default already depends on.
///
/// Returns an error only if `dest_dir` has no parent directory (defensive;
/// in practice `dest_dir` is always `$INSTDIR\packs`, which always has a
/// parent).
pub fn pack_extraction_destination(dest_dir: &Path, component: &str) -> Result<PathBuf, String> {
    let install_root_for = |component: &str| -> Result<&Path, String> {
        dest_dir.parent().ok_or_else(|| {
            format!(
                "Pack destination directory has no parent for component {component}: {}",
                dest_dir.display()
            )
        })
    };
    if component == APP_PAYLOAD_COMPONENT {
        return Ok(install_root_for(component)?.join("runtime"));
    }
    if component == FFMPEG_RUNTIME_COMPONENT {
        return Ok(install_root_for(component)?
            .join("dependencies")
            .join("ffmpeg"));
    }
    if component == OLLAMA_RUNTIME_COMPONENT {
        return Ok(install_root_for(component)?
            .join("dependencies")
            .join("ollama"));
    }
    if component == CUDA_RUNTIME_COMPONENT {
        return Ok(install_root_for(component)?
            .join("dependencies")
            .join("cuda"));
    }
    Ok(dest_dir.join(component).join("payload"))
}

/// A capability seam gating one thing only: the destructive rebuild of an
/// extracted component tree inside [`ensure_pack_extracted`].
///
/// This exists because of a confirmed, live hazard, not as defensive
/// boilerplate: the CivicCastSupervisor service runs as LocalSystem out of
/// exactly the tree [`ensure_pack_extracted`] deletes on its corrupt-tree
/// path (`fs::remove_dir_all(&extraction_dir)`), and keeps long-lived
/// `postgres.exe`/`nats-server.exe` children whose binaries live under that
/// same tree. `native_service_registration::stop_native_service`'s own doc
/// comment already says callers "MUST call this first" before any such
/// rebuild -- but a doc comment enforces nothing, and the standalone D5
/// repair path (`native_repair.rs`) called into the destructive rebuild with
/// no stop call anywhere in its chain. Making the caller supply a
/// `&dyn TreeRebuildAuthority` turns that prose obligation into a compiled
/// dependency: [`ensure_pack_extracted`] cannot reach `remove_dir_all`
/// without first obtaining (or being refused) this authorization, and the
/// production implementation (`native_service_registration::
/// ServiceQuiescenceAuthority`) is the ONLY thing standing between a repair
/// run and deleting a live database's binaries out from under it.
pub trait TreeRebuildAuthority {
    /// Called immediately before a destructive rebuild of `component`'s
    /// extracted tree. Returning `Err` must prevent the deletion entirely --
    /// the tree is left exactly as it was found.
    fn authorize_rebuild(&self, component: &str) -> Result<(), String>;
}

/// Ensure the verified, extracted payload of the pack at `pack_file` is laid
/// down at its component's extraction destination -- see
/// [`pack_extraction_destination`] for the exact per-component rule. For
/// every component except `native-app-payload` this is
/// `<dest_dir>\<component>\payload\`, the location `resolve_provision_paths`
/// expects (its `initdb_path` default is exactly
/// `<install_root>\packs\native-server-binaries\payload\bin\initdb.exe`,
/// i.e. `<dest_dir>\<component>\payload\` joined with each manifest-declared
/// payload-relative path).
///
/// Idempotent (D5's posture, mirrored from the raw-pack staging above): if a
/// tree already exists at the destination and re-verifies -- via
/// `native_install_verify::verify_component_pack_tree`, which re-opens
/// `pack_file` fresh and re-hashes every extracted file, never trusting a
/// prior run's word for it -- it is accepted with zero re-extraction, and
/// `authority` is NEVER consulted on this path (a healthy repair must not
/// stop a running service). A missing OR corrupt (fails re-verification for
/// ANY reason: missing file, wrong bytes, unexpected extra file) destination
/// is, if it exists on disk, cleared ONLY after `authority.authorize_rebuild`
/// grants it -- see [`TreeRebuildAuthority`] for why this gate exists -- and
/// then rebuilt from scratch via `native_packs::verify_and_extract_pack`,
/// which itself verifies the pack, extracts every file to a `.partial`
/// staging path, byte- and hash-checks each landed file before activating
/// it, and finally re-walks the whole extracted tree
/// (`verify_extracted_tree`) -- fail closed on any mismatch, exactly D2's
/// "verify before laying files; corrupt => loud failure" applied to the
/// extracted tree, not merely the raw archive.
pub fn ensure_pack_extracted(
    pack_file: &Path,
    dest_dir: &Path,
    component: &str,
    trust: &PackTrust,
    expected_product_version: &str,
    expected_compatible_core: &str,
    authority: &dyn TreeRebuildAuthority,
) -> Result<PathBuf, String> {
    let extraction_dir = pack_extraction_destination(dest_dir, component)?;
    if native_install_verify::verify_component_pack_tree(
        pack_file,
        &extraction_dir,
        trust,
        Some(component),
        Some(expected_product_version),
        Some(expected_compatible_core),
    )
    .is_ok()
    {
        return Ok(extraction_dir);
    }
    if extraction_dir.exists() {
        // The gate: see `TreeRebuildAuthority`'s doc for why this call is
        // load-bearing, not defensive boilerplate. It runs ONLY here, on the
        // destructive path, immediately before the deletion it exists to
        // prevent -- never on the already-verified idempotent return above.
        authority.authorize_rebuild(component).map_err(|reason| {
            format!("Refused to rebuild the extracted pack tree for {component}: {reason}")
        })?;
        fs::remove_dir_all(&extraction_dir).map_err(|error| {
            format!("Could not clear a stale/corrupt extracted pack tree for {component}: {error}")
        })?;
    }
    native_packs::verify_and_extract_pack(
        pack_file,
        &extraction_dir,
        trust,
        Some(component),
        Some(expected_product_version),
        Some(expected_compatible_core),
    )
    .map_err(|error| format!("Could not extract native component pack {component}: {error}"))?;
    Ok(extraction_dir)
}

// ---------------------------------------------------------------------------
// Orchestration
// ---------------------------------------------------------------------------

#[derive(Debug, Clone, Default, Serialize)]
pub struct PackStagingReport {
    pub required_components: Vec<String>,
    pub already_present: Vec<String>,
    pub copied_from_offline: Vec<String>,
    pub replaced_from_offline: Vec<String>,
    pub satisfied_online: Vec<String>,
    pub extracted: Vec<String>,
}

/// Top-level entry point invoked by the `--civiccast-stage-packs` CLI
/// subcommand. Offline-first (see the module doc's decision matrix), then
/// an online attempt when a channel is configured, then a loud side-load
/// remedy if any required component remains unsatisfied.
#[allow(clippy::too_many_arguments)]
pub fn stage_required_packs(
    installer_dir: &Path,
    instdir: &Path,
    trust: &PackTrust,
    required_components: &[String],
    expected_product_version: &str,
    expected_compatible_core: &str,
    channel_url: Option<&str>,
    channel: &str,
    authority: &dyn TreeRebuildAuthority,
) -> Result<PackStagingReport, String> {
    let dest_dir = instdir.join("packs");
    let source_dir = installer_dir.join("packs");
    let offline_sources = discover_offline_pack_sources(
        &source_dir,
        trust,
        expected_product_version,
        expected_compatible_core,
    );

    let mut report = PackStagingReport {
        required_components: required_components.to_vec(),
        ..Default::default()
    };
    let mut needs_online: Vec<String> = Vec::new();

    for component in required_components {
        let destination = dest_dir.join(format!("{component}.ccpack"));
        let dest_state = classify_dest_pack_state(
            &destination,
            trust,
            component,
            expected_product_version,
            expected_compatible_core,
        );
        let source_state = if offline_sources.contains_key(component) {
            OfflineSourceState::Verified
        } else {
            OfflineSourceState::Absent
        };
        match decide_offline_staging_action(&dest_state, &source_state) {
            StagingAction::AlreadySatisfied => report.already_present.push(component.clone()),
            StagingAction::CopyFromOffline => {
                let source_path = offline_sources
                    .get(component)
                    .expect("CopyFromOffline implies a verified offline source");
                commit_pack_file(
                    source_path,
                    &destination,
                    trust,
                    component,
                    expected_product_version,
                    expected_compatible_core,
                )?;
                report.copied_from_offline.push(component.clone());
            }
            StagingAction::ReplaceCorruptFromOffline => {
                let source_path = offline_sources
                    .get(component)
                    .expect("ReplaceCorruptFromOffline implies a verified offline source");
                commit_pack_file(
                    source_path,
                    &destination,
                    trust,
                    component,
                    expected_product_version,
                    expected_compatible_core,
                )?;
                report.replaced_from_offline.push(component.clone());
            }
            StagingAction::NeedsOnlineOrAbort => needs_online.push(component.clone()),
        }
    }

    let mut still_missing = needs_online.clone();
    if !needs_online.is_empty() {
        let cache_root = instdir.join("packs").join(".acquire-cache");
        let outcome = attempt_online_pack_acquire(
            &needs_online,
            channel_url,
            channel,
            &cache_root,
            &dest_dir,
            trust,
            expected_product_version,
            expected_compatible_core,
        );
        if let OnlineAttemptOutcome::Satisfied(satisfied) = &outcome {
            report.satisfied_online = satisfied.clone();
            still_missing = missing_after_all_attempts(&needs_online, satisfied);
        }
    }

    if !still_missing.is_empty() {
        return Err(build_pack_delivery_abort_message(&still_missing));
    }

    // Every required component's raw pack is now confirmed present and
    // verified at `dest_dir\<component>.ccpack` (already-present, freshly
    // copied/replaced from offline, or landed by the online fallback above --
    // `still_missing` being empty proves every branch reached one of those
    // outcomes). Close the extraction gap for each one so
    // `resolve_provision_paths`' `initdb_path` convention
    // (`packs\<component>\payload\...`) is satisfied before this CLI returns.
    for component in required_components {
        let pack_file = dest_dir.join(format!("{component}.ccpack"));
        ensure_pack_extracted(
            &pack_file,
            &dest_dir,
            component,
            trust,
            expected_product_version,
            expected_compatible_core,
            authority,
        )?;
        report.extracted.push(component.clone());
    }

    Ok(report)
}

/// Report for [`stage_optional_packs`]. Deliberately its OWN type, not a
/// reuse of [`PackStagingReport`]: an optional run's "nothing went wrong"
/// outcome legitimately includes components in `skipped_absent`, which has
/// no analogue on the required path (there, absent-with-no-remedy is a
/// hard `Err`, never a report field) -- giving the two paths distinct report
/// shapes means a caller can never accidentally read `skipped_absent` as if
/// it meant something on a required-pack report, or vice versa.
#[derive(Debug, Clone, Default, Serialize)]
pub struct OptionalPackStagingReport {
    pub optional_components: Vec<String>,
    pub already_present: Vec<String>,
    pub copied_from_offline: Vec<String>,
    pub replaced_from_offline: Vec<String>,
    pub skipped_absent: Vec<String>,
    pub extracted: Vec<String>,
}

/// Offline-only staging for OPTIONAL components (see [`DEFAULT_OPTIONAL_
/// COMPONENTS`]'s doc for the required/optional distinction). No online
/// acquisition attempt: an optional component with no offline side-loaded
/// source is simply recorded absent and setup continues -- there is nothing
/// here for a network fetch to be a *remedy* for the way it is for a
/// required component's loud abort.
///
/// Verification is NOT weakened by optionality: a present destination (or a
/// present offline source) is verified through the exact same
/// [`classify_dest_pack_state`]/[`commit_pack_file`] machinery
/// [`stage_required_packs`] uses, and a destination that is present but
/// fails verification with no offline remedy available is a hard `Err` --
/// never silently folded into `skipped_absent`. "Optional means may be
/// absent, never may be untrusted."
pub fn stage_optional_packs(
    installer_dir: &Path,
    instdir: &Path,
    trust: &PackTrust,
    optional_components: &[String],
    expected_product_version: &str,
    expected_compatible_core: &str,
    authority: &dyn TreeRebuildAuthority,
) -> Result<OptionalPackStagingReport, String> {
    let dest_dir = instdir.join("packs");
    let source_dir = installer_dir.join("packs");
    let offline_sources = discover_offline_pack_sources(
        &source_dir,
        trust,
        expected_product_version,
        expected_compatible_core,
    );

    let mut report = OptionalPackStagingReport {
        optional_components: optional_components.to_vec(),
        ..Default::default()
    };

    for component in optional_components {
        let destination = dest_dir.join(format!("{component}.ccpack"));
        let dest_state = classify_dest_pack_state(
            &destination,
            trust,
            component,
            expected_product_version,
            expected_compatible_core,
        );
        let source_state = if offline_sources.contains_key(component) {
            OfflineSourceState::Verified
        } else {
            OfflineSourceState::Absent
        };
        match decide_optional_staging_action(&dest_state, &source_state) {
            OptionalStagingAction::AlreadySatisfied => {
                report.already_present.push(component.clone())
            }
            OptionalStagingAction::CopyFromOffline => {
                let source_path = offline_sources
                    .get(component)
                    .expect("CopyFromOffline implies a verified offline source");
                commit_pack_file(
                    source_path,
                    &destination,
                    trust,
                    component,
                    expected_product_version,
                    expected_compatible_core,
                )?;
                report.copied_from_offline.push(component.clone());
            }
            OptionalStagingAction::ReplaceCorruptFromOffline => {
                let source_path = offline_sources
                    .get(component)
                    .expect("ReplaceCorruptFromOffline implies a verified offline source");
                commit_pack_file(
                    source_path,
                    &destination,
                    trust,
                    component,
                    expected_product_version,
                    expected_compatible_core,
                )?;
                report.replaced_from_offline.push(component.clone());
            }
            OptionalStagingAction::SkipAbsent => {
                report.skipped_absent.push(component.clone());
            }
            OptionalStagingAction::CorruptWithNoRemedy => {
                return Err(format!(
                    "optional native component pack {component} is present but failed \
                     verification, and no valid offline replacement is available -- an \
                     untrusted optional pack is never silently skipped. Remove the corrupt \
                     file at {} or side-load a valid replacement.",
                    destination.display()
                ));
            }
        }
    }

    // Extract every optional component that IS now present and verified at
    // dest_dir (already-present, freshly copied/replaced) -- mirroring
    // `stage_required_packs`'s own extraction pass. A component recorded in
    // `skipped_absent` has no pack file on disk to extract at all.
    for component in optional_components {
        if report.skipped_absent.contains(component) {
            continue;
        }
        let pack_file = dest_dir.join(format!("{component}.ccpack"));
        ensure_pack_extracted(
            &pack_file,
            &dest_dir,
            component,
            trust,
            expected_product_version,
            expected_compatible_core,
            authority,
        )?;
        report.extracted.push(component.clone());
    }

    Ok(report)
}

#[cfg(test)]
mod tests {
    use super::*;
    use base64::engine::general_purpose::STANDARD as BASE64;
    use base64::Engine as _;
    use ed25519_dalek::{Signer, SigningKey};
    use serde_json::json;
    use sha2::{Digest, Sha256};
    use std::cell::RefCell;
    use std::io::Write as _;
    use zip::write::SimpleFileOptions;
    use zip::{CompressionMethod, ZipWriter};

    // ---- TreeRebuildAuthority fakes ----

    /// A permissive fake that grants every rebuild -- used by every test
    /// below that predates the [`TreeRebuildAuthority`] gate and is not
    /// itself testing the gate; preserves those tests' original meaning
    /// (verifying extraction/idempotency/repair behavior) without them also
    /// having to care about the authorization seam.
    struct AllowAllAuthority;

    impl TreeRebuildAuthority for AllowAllAuthority {
        fn authorize_rebuild(&self, _component: &str) -> Result<(), String> {
            Ok(())
        }
    }

    /// Records every component it was asked to authorize a rebuild for,
    /// always granting it -- proves the destructive path actually CONSULTS
    /// the authority (not merely that it *could*).
    #[derive(Default)]
    struct RecordingAuthority {
        calls: RefCell<Vec<String>>,
    }

    impl TreeRebuildAuthority for RecordingAuthority {
        fn authorize_rebuild(&self, component: &str) -> Result<(), String> {
            self.calls.borrow_mut().push(component.to_string());
            Ok(())
        }
    }

    /// Refuses every rebuild -- proves a refusal actually PREVENTS the
    /// deletion, not just that the caller received an error.
    struct RefusingAuthority {
        reason: &'static str,
    }

    impl TreeRebuildAuthority for RefusingAuthority {
        fn authorize_rebuild(&self, _component: &str) -> Result<(), String> {
            Err(self.reason.to_string())
        }
    }

    /// Panics if ever consulted -- wired into the idempotent/already-verified
    /// path test so that path calling into the authority at all (even to
    /// grant) would fail the test loudly, not silently.
    struct PanicIfConsultedAuthority;

    impl TreeRebuildAuthority for PanicIfConsultedAuthority {
        fn authorize_rebuild(&self, component: &str) -> Result<(), String> {
            panic!(
                "authorize_rebuild must never be consulted on the idempotent \
                 already-verified path (component={component})"
            );
        }
    }

    // ---- pure decision matrix ----

    #[test]
    fn already_verified_destination_is_always_satisfied_regardless_of_source() {
        for source in [OfflineSourceState::Verified, OfflineSourceState::Absent] {
            assert_eq!(
                decide_offline_staging_action(&DestPackState::Verified, &source),
                StagingAction::AlreadySatisfied
            );
        }
    }

    #[test]
    fn absent_destination_with_verified_source_copies() {
        assert_eq!(
            decide_offline_staging_action(&DestPackState::Absent, &OfflineSourceState::Verified),
            StagingAction::CopyFromOffline
        );
    }

    #[test]
    fn corrupt_destination_with_verified_source_replaces() {
        assert_eq!(
            decide_offline_staging_action(
                &DestPackState::Corrupt("tampered".to_string()),
                &OfflineSourceState::Verified
            ),
            StagingAction::ReplaceCorruptFromOffline
        );
    }

    #[test]
    fn absent_destination_with_no_source_needs_online_or_abort() {
        assert_eq!(
            decide_offline_staging_action(&DestPackState::Absent, &OfflineSourceState::Absent),
            StagingAction::NeedsOnlineOrAbort
        );
    }

    #[test]
    fn corrupt_destination_with_no_source_needs_online_or_abort() {
        assert_eq!(
            decide_offline_staging_action(
                &DestPackState::Corrupt("bad hash".to_string()),
                &OfflineSourceState::Absent
            ),
            StagingAction::NeedsOnlineOrAbort
        );
    }

    #[test]
    fn missing_after_all_attempts_subtracts_online_satisfied_components() {
        let needed = vec!["a".to_string(), "b".to_string(), "c".to_string()];
        let satisfied = vec!["b".to_string()];
        assert_eq!(
            missing_after_all_attempts(&needed, &satisfied),
            vec!["a".to_string(), "c".to_string()]
        );
    }

    #[test]
    fn missing_after_all_attempts_is_empty_when_everything_was_satisfied() {
        let needed = vec!["a".to_string()];
        let satisfied = vec!["a".to_string()];
        assert!(missing_after_all_attempts(&needed, &satisfied).is_empty());
    }

    #[test]
    fn abort_message_names_every_missing_component_and_only_the_real_remedy() {
        let message = build_pack_delivery_abort_message(&[
            "native-server-binaries".to_string(),
            "native-app-payload".to_string(),
        ]);
        // The component list is the whole reason nsis-hooks-bootstrap.nsh
        // captures this string into install-progress.log (chain F-min2).
        assert!(message.contains("native-server-binaries"));
        assert!(message.contains("native-app-payload"));
        // The one remedy that exists.
        assert!(message.to_lowercase().contains("'packs' folder"));
        assert!(message.to_lowercase().contains("next to the installer"));
        assert!(message.to_lowercase().contains("run setup again"));
        // The one that does not. No channel index URL is pinned anywhere in
        // this codebase, so a networked machine gets this same abort; telling
        // the operator to connect one sends them to fix nothing. This
        // assertion previously demanded the OPPOSITE (`contains("network")`),
        // which is how the false remedy stayed green for the whole program.
        let lowered = message.to_lowercase();
        for forbidden in ["network", "download", "internet", "online"] {
            assert!(
                !lowered.contains(forbidden),
                "abort message offers a remedy that does not exist: {forbidden:?} in {message:?}"
            );
        }
    }

    // ---- online NOT_AVAILABLE typed branch (no network attempted) ----

    #[test]
    fn online_attempt_is_not_attempted_when_nothing_is_missing() {
        let trust = PackTrust {
            key_id: "k".to_string(),
            public_key: SigningKey::from_bytes(&[1_u8; 32]).verifying_key(),
        };
        let outcome = attempt_online_pack_acquire(
            &[],
            None,
            "beta",
            Path::new("unused"),
            Path::new("unused"),
            &trust,
            "1.0.0",
            "1.0.0",
        );
        assert_eq!(outcome, OnlineAttemptOutcome::NotAttempted);
    }

    #[test]
    fn online_attempt_returns_typed_not_available_without_a_channel_url() {
        let trust = PackTrust {
            key_id: "k".to_string(),
            public_key: SigningKey::from_bytes(&[1_u8; 32]).verifying_key(),
        };
        let outcome = attempt_online_pack_acquire(
            &["native-server-binaries".to_string()],
            None,
            "beta",
            Path::new("unused"),
            Path::new("unused"),
            &trust,
            "1.0.0",
            "1.0.0",
        );
        match outcome {
            OnlineAttemptOutcome::NotAvailable(reason) => {
                assert!(reason.to_lowercase().contains("channel"));
            }
            other => panic!("expected NotAvailable, got {other:?}"),
        }
    }

    // ---- integration-shaped: real signed pack fixtures ----

    fn sha256_hex(bytes: &[u8]) -> String {
        let mut digest = Sha256::new();
        digest.update(bytes);
        format!("{:x}", digest.finalize())
    }

    fn scratch_dir(name: &str) -> PathBuf {
        let root = std::env::temp_dir().join(format!(
            "civiccast-native-pack-staging-{name}-{}",
            std::process::id()
        ));
        let _ = fs::remove_dir_all(&root);
        fs::create_dir_all(&root).expect("create scratch dir");
        root
    }

    fn build_signed_pack(
        pack_path: &Path,
        signing_key: &SigningKey,
        component: &str,
        payload: &[(&str, &[u8])],
    ) {
        let mut files_json = Vec::new();
        let mut total_bytes = 0_u64;
        for (name, bytes) in payload {
            files_json.push(json!({
                "path": name,
                "bytes": bytes.len(),
                "sha256": sha256_hex(bytes),
            }));
            total_bytes += bytes.len() as u64;
        }
        // Source-bound components must carry the source SHA the verifier
        // enforces in production (SOURCE_BOUND_COMPONENTS in native_packs.rs);
        // the app payload additionally pins civiccast_source_head to it.
        let test_source_sha = "a".repeat(40);
        let metadata_value = if component == "native-app-payload" {
            json!({
                "source_sha": test_source_sha,
                "civiccast_source_head": test_source_sha,
            })
        } else if component == "native-server-binaries" {
            json!({ "source_sha": test_source_sha })
        } else {
            json!({})
        };
        let manifest_value = json!({
            "schema_version": 1,
            "product": "civiccast-native",
            "component": component,
            "product_version": "1.0.0-rc15",
            "compatible_core": "1.0.0-rc15",
            "signing_key_id": "test-key",
            "file_count": payload.len(),
            "total_bytes": total_bytes,
            "files": files_json,
            "metadata": metadata_value,
        });
        let manifest_bytes = native_packs::canonical_json(&manifest_value)
            .expect("canonicalize test manifest")
            .into_bytes();
        let signature = signing_key.sign(&manifest_bytes);
        let signature_b64 = BASE64.encode(signature.to_bytes());

        let file = fs::File::create(pack_path).expect("create pack file");
        let mut writer = ZipWriter::new(file);
        let options = SimpleFileOptions::default().compression_method(CompressionMethod::Stored);
        writer
            .start_file("manifest.json", options)
            .expect("start manifest entry");
        writer.write_all(&manifest_bytes).expect("write manifest");
        writer
            .start_file("manifest.sig", options)
            .expect("start signature entry");
        writer
            .write_all(signature_b64.as_bytes())
            .expect("write signature");
        for (name, bytes) in payload {
            writer
                .start_file(format!("payload/{name}"), options)
                .expect("start payload entry");
            writer.write_all(bytes).expect("write payload bytes");
        }
        writer.finish().expect("finish pack zip");
    }

    fn trust_for(signing_key: &SigningKey) -> PackTrust {
        PackTrust {
            key_id: "test-key".to_string(),
            public_key: signing_key.verifying_key(),
        }
    }

    #[test]
    fn discover_offline_pack_sources_finds_a_valid_pack_by_its_manifest_component() {
        let root = scratch_dir("discover-clean");
        let signing_key = SigningKey::from_bytes(&[7_u8; 32]);
        let trust = trust_for(&signing_key);
        let source_dir = root.join("packs");
        fs::create_dir_all(&source_dir).expect("mkdir packs");
        build_signed_pack(
            &source_dir.join("whatever-filename-the-operator-used.ccpack"),
            &signing_key,
            "native-server-binaries",
            &[("bin/initdb.exe", b"pretend-initdb-bytes")],
        );

        let found = discover_offline_pack_sources(&source_dir, &trust, "1.0.0-rc15", "1.0.0-rc15");
        assert!(
            found.contains_key("native-server-binaries"),
            "component must be discovered by manifest identity, not filename"
        );

        let _ = fs::remove_dir_all(&root);
    }

    #[test]
    fn discover_offline_pack_sources_ignores_a_tampered_pack() {
        let root = scratch_dir("discover-tampered");
        let signing_key = SigningKey::from_bytes(&[7_u8; 32]);
        let trust = trust_for(&signing_key);
        let source_dir = root.join("packs");
        fs::create_dir_all(&source_dir).expect("mkdir packs");
        let pack_path = source_dir.join("native-server-binaries.ccpack");
        build_signed_pack(
            &pack_path,
            &signing_key,
            "native-server-binaries",
            &[("bin/initdb.exe", b"pretend-initdb-bytes")],
        );
        // Flip a byte in the ZIP's payload after signing -- a tampered
        // side-loaded pack, exactly the scenario D2 must reject.
        let mut bytes = fs::read(&pack_path).expect("read pack");
        let last = bytes.len() - 1;
        bytes[last] ^= 0xFF;
        fs::write(&pack_path, &bytes).expect("rewrite tampered pack");

        let found = discover_offline_pack_sources(&source_dir, &trust, "1.0.0-rc15", "1.0.0-rc15");
        assert!(
            found.is_empty(),
            "a tampered pack must never be trusted as an offline source"
        );

        let _ = fs::remove_dir_all(&root);
    }

    #[test]
    fn end_to_end_offline_staging_copies_and_reverifies_a_missing_required_component() {
        let root = scratch_dir("e2e-copy");
        let signing_key = SigningKey::from_bytes(&[7_u8; 32]);
        let trust = trust_for(&signing_key);
        let installer_dir = root.join("installer");
        let instdir = root.join("instdir");
        fs::create_dir_all(installer_dir.join("packs")).expect("mkdir installer packs");
        build_signed_pack(
            &installer_dir
                .join("packs")
                .join("native-server-binaries.ccpack"),
            &signing_key,
            "native-server-binaries",
            &[("bin/initdb.exe", b"pretend-initdb-bytes")],
        );

        let report = stage_required_packs(
            &installer_dir,
            &instdir,
            &trust,
            &["native-server-binaries".to_string()],
            "1.0.0-rc15",
            "1.0.0-rc15",
            None,
            "beta",
            &AllowAllAuthority,
        )
        .expect("offline staging with a valid side-loaded pack must succeed");

        assert_eq!(report.copied_from_offline, vec!["native-server-binaries"]);
        assert!(report.already_present.is_empty());
        assert!(
            instdir
                .join("packs")
                .join("native-server-binaries.ccpack")
                .is_file(),
            "the pack must be staged at the established install-root convention"
        );
        assert_eq!(report.extracted, vec!["native-server-binaries"]);
        let extracted_initdb = instdir
            .join("packs")
            .join("native-server-binaries")
            .join("payload")
            .join("bin")
            .join("initdb.exe");
        assert_eq!(
            fs::read(&extracted_initdb).expect("extracted initdb.exe must exist"),
            b"pretend-initdb-bytes",
            "the extracted tree must land exactly where resolve_provision_paths expects it \
             (packs\\<component>\\payload\\bin\\initdb.exe)"
        );

        // Idempotency: running again must accept the already-staged, still-
        // verified copy without re-copying.
        let second = stage_required_packs(
            &installer_dir,
            &instdir,
            &trust,
            &["native-server-binaries".to_string()],
            "1.0.0-rc15",
            "1.0.0-rc15",
            None,
            "beta",
            &AllowAllAuthority,
        )
        .expect("a re-run over an already-verified pack must succeed");
        assert_eq!(second.already_present, vec!["native-server-binaries"]);
        assert!(second.copied_from_offline.is_empty());
        assert_eq!(second.extracted, vec!["native-server-binaries"]);

        let _ = fs::remove_dir_all(&root);
    }

    // ---- extraction gap: tamper / missing / idempotent / clean ----

    #[test]
    fn ensure_pack_extracted_creates_a_missing_tree_from_the_verified_pack() {
        let root = scratch_dir("extract-missing");
        let signing_key = SigningKey::from_bytes(&[7_u8; 32]);
        let trust = trust_for(&signing_key);
        let pack_file = root.join("native-server-binaries.ccpack");
        build_signed_pack(
            &pack_file,
            &signing_key,
            "native-server-binaries",
            &[
                ("bin/initdb.exe", b"pretend-initdb-bytes"),
                ("bin/pg_ctl.exe", b"pretend-pg-ctl-bytes"),
            ],
        );
        let dest_dir = root.join("instdir").join("packs");

        let extraction_dir = ensure_pack_extracted(
            &pack_file,
            &dest_dir,
            "native-server-binaries",
            &trust,
            "1.0.0-rc15",
            "1.0.0-rc15",
            &AllowAllAuthority,
        )
        .expect("extraction of a missing tree must succeed");

        assert_eq!(
            extraction_dir,
            dest_dir.join("native-server-binaries").join("payload")
        );
        assert_eq!(
            fs::read(extraction_dir.join("bin").join("initdb.exe")).expect("read initdb.exe"),
            b"pretend-initdb-bytes"
        );
        assert_eq!(
            fs::read(extraction_dir.join("bin").join("pg_ctl.exe")).expect("read pg_ctl.exe"),
            b"pretend-pg-ctl-bytes"
        );

        let _ = fs::remove_dir_all(&root);
    }

    #[test]
    fn ensure_pack_extracted_is_idempotent_and_does_not_rewrite_an_already_verified_tree() {
        let root = scratch_dir("extract-idempotent");
        let signing_key = SigningKey::from_bytes(&[7_u8; 32]);
        let trust = trust_for(&signing_key);
        let pack_file = root.join("native-server-binaries.ccpack");
        build_signed_pack(
            &pack_file,
            &signing_key,
            "native-server-binaries",
            &[("bin/initdb.exe", b"pretend-initdb-bytes")],
        );
        let dest_dir = root.join("instdir").join("packs");

        let first = ensure_pack_extracted(
            &pack_file,
            &dest_dir,
            "native-server-binaries",
            &trust,
            "1.0.0-rc15",
            "1.0.0-rc15",
            &AllowAllAuthority,
        )
        .expect("first extraction must succeed");
        let extracted_file = first.join("bin").join("initdb.exe");
        let first_modified = fs::metadata(&extracted_file)
            .expect("stat extracted file")
            .modified()
            .expect("mtime");

        // A distinct, observable delay so a rewrite (vs. a true no-op) would
        // change the mtime we compare against below.
        std::thread::sleep(std::time::Duration::from_millis(50));

        let second = ensure_pack_extracted(
            &pack_file,
            &dest_dir,
            "native-server-binaries",
            &trust,
            "1.0.0-rc15",
            "1.0.0-rc15",
            &AllowAllAuthority,
        )
        .expect("re-running extraction over an already-verified tree must succeed");
        let second_modified = fs::metadata(second.join("bin").join("initdb.exe"))
            .expect("stat extracted file after second run")
            .modified()
            .expect("mtime");

        assert_eq!(
            first_modified, second_modified,
            "an already-verified extracted tree must not be rewritten"
        );

        let _ = fs::remove_dir_all(&root);
    }

    #[test]
    fn ensure_pack_extracted_replaces_a_tampered_extracted_file() {
        let root = scratch_dir("extract-tamper");
        let signing_key = SigningKey::from_bytes(&[7_u8; 32]);
        let trust = trust_for(&signing_key);
        let pack_file = root.join("native-server-binaries.ccpack");
        build_signed_pack(
            &pack_file,
            &signing_key,
            "native-server-binaries",
            &[("bin/initdb.exe", b"pretend-initdb-bytes")],
        );
        let dest_dir = root.join("instdir").join("packs");

        let extraction_dir = ensure_pack_extracted(
            &pack_file,
            &dest_dir,
            "native-server-binaries",
            &trust,
            "1.0.0-rc15",
            "1.0.0-rc15",
            &AllowAllAuthority,
        )
        .expect("first extraction must succeed");
        let extracted_file = extraction_dir.join("bin").join("initdb.exe");
        fs::write(&extracted_file, b"TAMPERED-not-the-real-binary")
            .expect("tamper the extracted file");

        let repaired_dir = ensure_pack_extracted(
            &pack_file,
            &dest_dir,
            "native-server-binaries",
            &trust,
            "1.0.0-rc15",
            "1.0.0-rc15",
            &AllowAllAuthority,
        )
        .expect("a tampered extracted tree must be repaired, not left corrupt");

        assert_eq!(
            fs::read(repaired_dir.join("bin").join("initdb.exe")).expect("read repaired file"),
            b"pretend-initdb-bytes",
            "the tampered file must be replaced with the verified pack's real bytes"
        );

        let _ = fs::remove_dir_all(&root);
    }

    #[test]
    fn ensure_pack_extracted_replaces_a_tree_with_an_unexpected_extra_file() {
        // An extra file the pack never declared is exactly as much a
        // corruption signal as a wrong hash -- `verify_extracted_tree`
        // rejects it, and `ensure_pack_extracted` must clear + rebuild rather
        // than silently leaving the stray file in place.
        let root = scratch_dir("extract-extra-file");
        let signing_key = SigningKey::from_bytes(&[7_u8; 32]);
        let trust = trust_for(&signing_key);
        let pack_file = root.join("native-server-binaries.ccpack");
        build_signed_pack(
            &pack_file,
            &signing_key,
            "native-server-binaries",
            &[("bin/initdb.exe", b"pretend-initdb-bytes")],
        );
        let dest_dir = root.join("instdir").join("packs");

        let extraction_dir = ensure_pack_extracted(
            &pack_file,
            &dest_dir,
            "native-server-binaries",
            &trust,
            "1.0.0-rc15",
            "1.0.0-rc15",
            &AllowAllAuthority,
        )
        .expect("first extraction must succeed");
        fs::write(
            extraction_dir.join("bin").join("unexpected-stowaway.exe"),
            b"should never survive",
        )
        .expect("plant an unexpected extra file");

        let repaired_dir = ensure_pack_extracted(
            &pack_file,
            &dest_dir,
            "native-server-binaries",
            &trust,
            "1.0.0-rc15",
            "1.0.0-rc15",
            &AllowAllAuthority,
        )
        .expect("a tree with an unexpected extra file must be rebuilt");

        assert!(
            !repaired_dir
                .join("bin")
                .join("unexpected-stowaway.exe")
                .exists(),
            "the rebuilt tree must not carry over the stray file"
        );
        assert_eq!(
            fs::read(repaired_dir.join("bin").join("initdb.exe")).expect("read initdb.exe"),
            b"pretend-initdb-bytes"
        );

        let _ = fs::remove_dir_all(&root);
    }

    #[test]
    fn corrupt_staged_pack_is_replaced_from_a_valid_offline_source() {
        let root = scratch_dir("e2e-replace");
        let signing_key = SigningKey::from_bytes(&[7_u8; 32]);
        let trust = trust_for(&signing_key);
        let installer_dir = root.join("installer");
        let instdir = root.join("instdir");
        fs::create_dir_all(installer_dir.join("packs")).expect("mkdir installer packs");
        build_signed_pack(
            &installer_dir
                .join("packs")
                .join("native-server-binaries.ccpack"),
            &signing_key,
            "native-server-binaries",
            &[("bin/initdb.exe", b"pretend-initdb-bytes")],
        );
        let dest_dir = instdir.join("packs");
        fs::create_dir_all(&dest_dir).expect("mkdir dest packs");
        fs::write(
            dest_dir.join("native-server-binaries.ccpack"),
            b"not a real pack at all",
        )
        .expect("write corrupt destination pack");

        let report = stage_required_packs(
            &installer_dir,
            &instdir,
            &trust,
            &["native-server-binaries".to_string()],
            "1.0.0-rc15",
            "1.0.0-rc15",
            None,
            "beta",
            &AllowAllAuthority,
        )
        .expect("a corrupt destination pack must be replaced from a valid offline source");

        assert_eq!(report.replaced_from_offline, vec!["native-server-binaries"]);

        let _ = fs::remove_dir_all(&root);
    }

    #[test]
    fn missing_component_with_no_offline_source_and_no_channel_url_loud_aborts_naming_the_component(
    ) {
        let root = scratch_dir("e2e-abort");
        let signing_key = SigningKey::from_bytes(&[7_u8; 32]);
        let trust = trust_for(&signing_key);
        let installer_dir = root.join("installer"); // no packs/ subdirectory at all
        let instdir = root.join("instdir");

        let error = stage_required_packs(
            &installer_dir,
            &instdir,
            &trust,
            &["native-server-binaries".to_string()],
            "1.0.0-rc15",
            "1.0.0-rc15",
            None,
            "beta",
            &AllowAllAuthority,
        )
        .expect_err("a missing required pack with no remedy available must loud-abort");
        // End to end, through the real staging path: the abort names the
        // component. `nsis-hooks-bootstrap.nsh` captures this exact string and
        // writes it into install-progress.log (chain F-min2), so this is the
        // text that keeps the failure dialog's "see the installer log for the
        // exact missing component(s)" promise.
        assert!(error.contains("native-server-binaries"));
        assert!(error.to_lowercase().contains("'packs' folder"));
        // This assertion used to be `contains("network")`. A machine WITH a
        // network reaches this same abort -- no channel index URL is pinned in
        // this codebase, so the online attempt returns a typed NotAvailable --
        // and telling the operator to connect one sends them to fix nothing.
        for forbidden in ["network", "download", "internet", "online"] {
            assert!(
                !error.to_lowercase().contains(forbidden),
                "abort message offers a remedy that does not exist: {forbidden:?} in {error:?}"
            );
        }

        let _ = fs::remove_dir_all(&root);
    }

    #[test]
    fn a_tampered_side_loaded_pack_is_rejected_and_the_component_still_loud_aborts() {
        let root = scratch_dir("e2e-tampered-abort");
        let signing_key = SigningKey::from_bytes(&[7_u8; 32]);
        let trust = trust_for(&signing_key);
        let installer_dir = root.join("installer");
        let instdir = root.join("instdir");
        fs::create_dir_all(installer_dir.join("packs")).expect("mkdir installer packs");
        let pack_path = installer_dir
            .join("packs")
            .join("native-server-binaries.ccpack");
        build_signed_pack(
            &pack_path,
            &signing_key,
            "native-server-binaries",
            &[("bin/initdb.exe", b"pretend-initdb-bytes")],
        );
        let mut bytes = fs::read(&pack_path).expect("read pack");
        let last = bytes.len() - 1;
        bytes[last] ^= 0xFF;
        fs::write(&pack_path, &bytes).expect("rewrite tampered pack");

        let error = stage_required_packs(
            &installer_dir,
            &instdir,
            &trust,
            &["native-server-binaries".to_string()],
            "1.0.0-rc15",
            "1.0.0-rc15",
            None,
            "beta",
            &AllowAllAuthority,
        )
        .expect_err(
            "a tampered side-loaded pack must never be copied, never satisfy the requirement",
        );
        assert!(error.contains("native-server-binaries"));
        assert!(
            !instdir
                .join("packs")
                .join("native-server-binaries.ccpack")
                .exists(),
            "a tampered pack must never be copied into the install tree"
        );

        let _ = fs::remove_dir_all(&root);
    }

    #[test]
    fn commit_pack_file_rejects_and_removes_a_copy_that_fails_reverification() {
        // Simulate corruption occurring DURING the copy by committing a pack
        // built for a DIFFERENT expected component than what the caller
        // demands -- the copy lands, then re-verification (component
        // mismatch) must fail closed and remove the file.
        let root = scratch_dir("commit-reverify-fails");
        let signing_key = SigningKey::from_bytes(&[7_u8; 32]);
        let trust = trust_for(&signing_key);
        let source_path = root.join("source.ccpack");
        build_signed_pack(
            &source_path,
            &signing_key,
            "native-server-binaries",
            &[("bin/initdb.exe", b"pretend-initdb-bytes")],
        );
        let destination = root.join("dest").join("native-server-binaries.ccpack");

        let error = commit_pack_file(
            &source_path,
            &destination,
            &trust,
            "some-other-component",
            "1.0.0-rc15",
            "1.0.0-rc15",
        )
        .expect_err("a component mismatch must fail re-verification");
        assert!(error.to_lowercase().contains("re-verification"));
        assert!(
            !destination.exists(),
            "a failed re-verification must remove the landed copy"
        );

        let _ = fs::remove_dir_all(&root);
    }

    // ---- WP2 app-payload-pack gap closure: the layout bridge ----

    #[test]
    fn default_required_components_install_all_candidate_runtime_sidecars() {
        assert_eq!(
            DEFAULT_REQUIRED_COMPONENTS,
            &[
                "native-server-binaries",
                APP_PAYLOAD_COMPONENT,
                FFMPEG_RUNTIME_COMPONENT,
                OLLAMA_RUNTIME_COMPONENT,
            ]
        );
        assert_eq!(APP_PAYLOAD_COMPONENT, "native-app-payload");
        assert_eq!(OLLAMA_RUNTIME_COMPONENT, "native-ollama-runtime");
    }

    // ---- FFmpeg-pack gap closure: the second layout bridge ----

    #[test]
    fn ffmpeg_runtime_component_matches_the_python_builders_literal() {
        // Cross-language drift guard, same shape as APP_PAYLOAD_COMPONENT's
        // above: `scripts.build_native_ffmpeg_pack.FFMPEG_RUNTIME_COMPONENT`
        // must be this exact string, or the pack this crate downloads and the
        // pack that builder produces would carry different identities and the
        // signed-manifest component check would reject every delivery.
        assert_eq!(FFMPEG_RUNTIME_COMPONENT, "native-ffmpeg-runtime");
    }

    #[test]
    fn pack_extraction_destination_bridges_the_ffmpeg_component_to_dependencies_ffmpeg() {
        let dest_dir = Path::new(r"C:\Program Files\CivicCast Native\packs");
        assert_eq!(
            pack_extraction_destination(dest_dir, FFMPEG_RUNTIME_COMPONENT).expect("bridge"),
            Path::new(r"C:\Program Files\CivicCast Native\dependencies\ffmpeg")
        );
    }

    #[test]
    fn pack_extraction_destination_bridges_the_ollama_component_to_dependencies_ollama() {
        let dest_dir = Path::new(r"C:\Program Files\CivicCast Native\packs");
        assert_eq!(
            pack_extraction_destination(dest_dir, OLLAMA_RUNTIME_COMPONENT).expect("bridge"),
            Path::new(r"C:\Program Files\CivicCast Native\dependencies\ollama")
        );
    }

    #[test]
    fn every_other_component_keeps_the_generic_payload_convention() {
        // The two bridges above are exceptions, not a new general rule: a
        // component with no explicit mapping must still land under
        // `<dest_dir>\<component>\payload\`, which is what
        // `resolve_provision_paths`' initdb_path default depends on.
        let dest_dir = Path::new(r"C:\Program Files\CivicCast Native\packs");
        assert_eq!(
            pack_extraction_destination(dest_dir, "native-server-binaries").expect("generic"),
            dest_dir.join("native-server-binaries").join("payload")
        );
    }

    #[test]
    fn pack_extraction_destination_bridges_the_app_payload_component_to_runtime() {
        let dest_dir = Path::new(r"C:\Program Files\CivicCast Native\packs");
        let extraction_dir =
            pack_extraction_destination(dest_dir, APP_PAYLOAD_COMPONENT).expect("bridge resolves");
        assert_eq!(
            extraction_dir,
            Path::new(r"C:\Program Files\CivicCast Native\runtime"),
            "the app payload must land where native_service_registration.rs's \
             provision_command/service_registration_command already hard-code \
             the embedded interpreter: $INSTDIR\\runtime\\python.exe"
        );
    }

    #[test]
    fn pack_extraction_destination_keeps_the_generic_packs_component_payload_convention_for_every_other_component(
    ) {
        let dest_dir = Path::new(r"C:\Program Files\CivicCast Native\packs");
        let extraction_dir = pack_extraction_destination(dest_dir, "native-server-binaries")
            .expect("bridge resolves");
        assert_eq!(
            extraction_dir,
            Path::new(r"C:\Program Files\CivicCast Native\packs\native-server-binaries\payload"),
            "non-app-payload components must be unaffected by the bridge"
        );
    }

    #[test]
    fn ensure_pack_extracted_lands_the_app_payload_component_at_runtime_not_packs_payload() {
        let root = scratch_dir("extract-app-payload-bridge");
        let signing_key = SigningKey::from_bytes(&[7_u8; 32]);
        let trust = trust_for(&signing_key);
        let pack_file = root.join("native-app-payload.ccpack");
        build_signed_pack(
            &pack_file,
            &signing_key,
            APP_PAYLOAD_COMPONENT,
            &[("python.exe", b"pretend-python-exe-bytes")],
        );
        let dest_dir = root.join("instdir").join("packs");

        let extraction_dir = ensure_pack_extracted(
            &pack_file,
            &dest_dir,
            APP_PAYLOAD_COMPONENT,
            &trust,
            "1.0.0-rc15",
            "1.0.0-rc15",
            &AllowAllAuthority,
        )
        .expect("app-payload extraction must succeed");

        assert_eq!(extraction_dir, root.join("instdir").join("runtime"));
        assert_eq!(
            fs::read(extraction_dir.join("python.exe")).expect("read python.exe"),
            b"pretend-python-exe-bytes",
            "the embedded interpreter must land at $INSTDIR\\runtime\\python.exe, \
             the exact path native_service_registration.rs hard-codes"
        );
        assert!(
            !dest_dir
                .join(APP_PAYLOAD_COMPONENT)
                .join("payload")
                .exists(),
            "the app payload must NOT also land at the generic packs\\<component>\\payload\\ path"
        );

        let _ = fs::remove_dir_all(&root);
    }

    #[test]
    fn end_to_end_offline_staging_lands_every_default_required_component_where_each_is_expected() {
        let root = scratch_dir("e2e-all-defaults");
        let signing_key = SigningKey::from_bytes(&[7_u8; 32]);
        let trust = trust_for(&signing_key);
        let installer_dir = root.join("installer");
        let instdir = root.join("instdir");
        fs::create_dir_all(installer_dir.join("packs")).expect("mkdir installer packs");
        build_signed_pack(
            &installer_dir
                .join("packs")
                .join("native-server-binaries.ccpack"),
            &signing_key,
            "native-server-binaries",
            &[("bin/initdb.exe", b"pretend-initdb-bytes")],
        );
        build_signed_pack(
            &installer_dir
                .join("packs")
                .join("native-app-payload.ccpack"),
            &signing_key,
            APP_PAYLOAD_COMPONENT,
            &[("python.exe", b"pretend-python-exe-bytes")],
        );
        build_signed_pack(
            &installer_dir
                .join("packs")
                .join("native-ffmpeg-runtime.ccpack"),
            &signing_key,
            FFMPEG_RUNTIME_COMPONENT,
            &[("bin/ffmpeg.exe", b"pretend-ffmpeg-exe-bytes")],
        );
        build_signed_pack(
            &installer_dir
                .join("packs")
                .join("native-ollama-runtime.ccpack"),
            &signing_key,
            OLLAMA_RUNTIME_COMPONENT,
            &[("ollama.exe", b"pretend-ollama-exe-bytes")],
        );

        let required: Vec<String> = DEFAULT_REQUIRED_COMPONENTS
            .iter()
            .map(|component| component.to_string())
            .collect();
        assert_eq!(
            required.len(),
            4,
            "server, app, FFmpeg, and Ollama sidecars"
        );
        let report = stage_required_packs(
            &installer_dir,
            &instdir,
            &trust,
            &required,
            "1.0.0-rc15",
            "1.0.0-rc15",
            None,
            "beta",
            &AllowAllAuthority,
        )
        .expect("staging every default required component must succeed");

        assert_eq!(
            report.copied_from_offline.len(),
            DEFAULT_REQUIRED_COMPONENTS.len()
        );
        assert_eq!(report.extracted.len(), DEFAULT_REQUIRED_COMPONENTS.len());
        assert_eq!(
            fs::read(
                instdir
                    .join("packs")
                    .join("native-server-binaries")
                    .join("payload")
                    .join("bin")
                    .join("initdb.exe")
            )
            .expect("read initdb.exe"),
            b"pretend-initdb-bytes"
        );
        assert_eq!(
            fs::read(instdir.join("runtime").join("python.exe")).expect("read python.exe"),
            b"pretend-python-exe-bytes",
            "a real bootstrap install must now find $INSTDIR\\runtime\\python.exe"
        );
        assert_eq!(
            fs::read(
                instdir
                    .join("dependencies")
                    .join("ffmpeg")
                    .join("bin")
                    .join("ffmpeg.exe")
            )
            .expect("read ffmpeg.exe"),
            b"pretend-ffmpeg-exe-bytes"
        );
        assert_eq!(
            fs::read(
                instdir
                    .join("dependencies")
                    .join("ollama")
                    .join("ollama.exe")
            )
            .expect("read ollama.exe"),
            b"pretend-ollama-exe-bytes"
        );

        let _ = fs::remove_dir_all(&root);
    }

    #[test]
    fn ffmpeg_pack_still_stages_correctly_when_explicitly_required() {
        // Proves the "ready to re-enable with a one-line change" claim in
        // DEFAULT_REQUIRED_COMPONENTS's dated doc comment: the ffmpeg
        // staging/extraction path itself is untouched and still fully
        // functional -- only the DEFAULT required set changed. A caller
        // that explicitly requires FFMPEG_RUNTIME_COMPONENT (the same
        // --require-component escape hatch nsis-hooks-bootstrap.nsh could
        // pass once the pack is published) still gets it staged and
        // extracted to the exact pinned path.
        let root = scratch_dir("e2e-ffmpeg-explicit-require");
        let signing_key = SigningKey::from_bytes(&[7_u8; 32]);
        let trust = trust_for(&signing_key);
        let installer_dir = root.join("installer");
        let instdir = root.join("instdir");
        fs::create_dir_all(installer_dir.join("packs")).expect("mkdir installer packs");
        // Payload rooted at `bin/`, exactly as
        // `scripts/build_native_ffmpeg_pack.py` builds it -- so the assertion
        // below is really testing the pack layout + the extraction bridge
        // composing to the pinned path, not a path this test hand-built.
        build_signed_pack(
            &installer_dir
                .join("packs")
                .join("native-ffmpeg-runtime.ccpack"),
            &signing_key,
            FFMPEG_RUNTIME_COMPONENT,
            &[("bin/ffmpeg.exe", b"pretend-ffmpeg-exe-bytes")],
        );

        let required = vec![FFMPEG_RUNTIME_COMPONENT.to_string()];
        let report = stage_required_packs(
            &installer_dir,
            &instdir,
            &trust,
            &required,
            "1.0.0-rc15",
            "1.0.0-rc15",
            None,
            "beta",
            &AllowAllAuthority,
        )
        .expect("explicitly staging ffmpeg must still succeed");

        assert_eq!(report.copied_from_offline.len(), 1);
        assert_eq!(report.extracted.len(), 1);
        assert_eq!(
            fs::read(
                instdir
                    .join("dependencies")
                    .join("ffmpeg")
                    .join("bin")
                    .join("ffmpeg.exe")
            )
            .expect("read ffmpeg.exe"),
            b"pretend-ffmpeg-exe-bytes",
            "a real bootstrap install must now find \
             $INSTDIR\\dependencies\\ffmpeg\\bin\\ffmpeg.exe -- the exact path \
             native_activation::validate_staged_runtime_layout and main.rs's \
             staged-runtime self-test both pin"
        );
        assert!(
            !instdir
                .join("packs")
                .join(FFMPEG_RUNTIME_COMPONENT)
                .join("payload")
                .exists(),
            "the ffmpeg runtime must NOT also land at the generic \
             packs\\<component>\\payload\\ path"
        );

        let _ = fs::remove_dir_all(&root);
    }

    // ---- TreeRebuildAuthority gate: the destructive-rebuild guard ----

    #[test]
    fn ensure_pack_extracted_consults_the_authority_before_rebuilding_a_corrupt_tree() {
        let root = scratch_dir("authority-consulted");
        let signing_key = SigningKey::from_bytes(&[7_u8; 32]);
        let trust = trust_for(&signing_key);
        let pack_file = root.join("native-server-binaries.ccpack");
        build_signed_pack(
            &pack_file,
            &signing_key,
            "native-server-binaries",
            &[("bin/initdb.exe", b"pretend-initdb-bytes")],
        );
        let dest_dir = root.join("instdir").join("packs");

        ensure_pack_extracted(
            &pack_file,
            &dest_dir,
            "native-server-binaries",
            &trust,
            "1.0.0-rc15",
            "1.0.0-rc15",
            &AllowAllAuthority,
        )
        .expect("first extraction must succeed");
        let extraction_dir = dest_dir.join("native-server-binaries").join("payload");
        fs::write(
            extraction_dir.join("bin").join("initdb.exe"),
            b"TAMPERED-not-the-real-binary",
        )
        .expect("tamper the extracted file to force the destructive path");

        let authority = RecordingAuthority::default();
        ensure_pack_extracted(
            &pack_file,
            &dest_dir,
            "native-server-binaries",
            &trust,
            "1.0.0-rc15",
            "1.0.0-rc15",
            &authority,
        )
        .expect("a corrupt tree must still be repaired once the authority grants the rebuild");

        assert_eq!(
            authority.calls.into_inner(),
            vec!["native-server-binaries".to_string()],
            "the destructive path must consult the authority exactly once, naming the component"
        );

        let _ = fs::remove_dir_all(&root);
    }

    #[test]
    fn ensure_pack_extracted_refuses_and_leaves_the_corrupt_tree_byte_for_byte_unchanged_when_the_authority_refuses(
    ) {
        let root = scratch_dir("authority-refuses");
        let signing_key = SigningKey::from_bytes(&[7_u8; 32]);
        let trust = trust_for(&signing_key);
        let pack_file = root.join("native-server-binaries.ccpack");
        build_signed_pack(
            &pack_file,
            &signing_key,
            "native-server-binaries",
            &[("bin/initdb.exe", b"pretend-initdb-bytes")],
        );
        let dest_dir = root.join("instdir").join("packs");

        ensure_pack_extracted(
            &pack_file,
            &dest_dir,
            "native-server-binaries",
            &trust,
            "1.0.0-rc15",
            "1.0.0-rc15",
            &AllowAllAuthority,
        )
        .expect("first extraction must succeed");
        let extraction_dir = dest_dir.join("native-server-binaries").join("payload");
        let tampered_bytes = b"TAMPERED-not-the-real-binary".to_vec();
        fs::write(extraction_dir.join("bin").join("initdb.exe"), &tampered_bytes)
            .expect("tamper the extracted file to force the destructive path");

        // Snapshot the ENTIRE tree's bytes before the refused call -- this is
        // what proves the guard works: not that the call "failed", but that
        // the on-disk tree the service's children may still be reading from
        // is provably untouched, byte for byte.
        let before = fs::read(extraction_dir.join("bin").join("initdb.exe"))
            .expect("read tampered tree before the refused call");
        assert_eq!(before, tampered_bytes, "sanity: tamper landed before the call");

        let authority = RefusingAuthority {
            reason: "CivicCastSupervisor could not be confirmed stopped (test double)",
        };
        let error = ensure_pack_extracted(
            &pack_file,
            &dest_dir,
            "native-server-binaries",
            &trust,
            "1.0.0-rc15",
            "1.0.0-rc15",
            &authority,
        )
        .expect_err("a refusing authority must prevent the rebuild entirely");

        assert!(
            error.contains("native-server-binaries"),
            "refusal error must name the component: {error}"
        );
        assert!(
            error.contains("CivicCastSupervisor could not be confirmed stopped (test double)"),
            "refusal error must carry the authority's own refusal reason: {error}"
        );

        let after = fs::read(extraction_dir.join("bin").join("initdb.exe"))
            .expect("the tree must still exist after a refused rebuild");
        assert_eq!(
            after, before,
            "a refused rebuild must leave the existing tree byte-for-byte unchanged"
        );

        let _ = fs::remove_dir_all(&root);
    }

    #[test]
    fn ensure_pack_extracted_never_consults_the_authority_on_the_already_verified_idempotent_path()
    {
        let root = scratch_dir("authority-idempotent-skip");
        let signing_key = SigningKey::from_bytes(&[7_u8; 32]);
        let trust = trust_for(&signing_key);
        let pack_file = root.join("native-server-binaries.ccpack");
        build_signed_pack(
            &pack_file,
            &signing_key,
            "native-server-binaries",
            &[("bin/initdb.exe", b"pretend-initdb-bytes")],
        );
        let dest_dir = root.join("instdir").join("packs");

        ensure_pack_extracted(
            &pack_file,
            &dest_dir,
            "native-server-binaries",
            &trust,
            "1.0.0-rc15",
            "1.0.0-rc15",
            &AllowAllAuthority,
        )
        .expect("first extraction must succeed");

        // Re-run over the still-healthy, already-verified tree with an
        // authority that PANICS if ever consulted: a repair that finds
        // everything healthy must never even ask permission to stop the
        // service, let alone stop it.
        ensure_pack_extracted(
            &pack_file,
            &dest_dir,
            "native-server-binaries",
            &trust,
            "1.0.0-rc15",
            "1.0.0-rc15",
            &PanicIfConsultedAuthority,
        )
        .expect("re-running over an already-verified tree must succeed without consulting the authority");

        let _ = fs::remove_dir_all(&root);
    }

    // ---- native-cuda-runtime: optional-staging mechanism ----

    #[test]
    fn cuda_runtime_component_matches_the_python_builders_literal() {
        // Cross-language drift guard, same shape as FFMPEG_RUNTIME_COMPONENT's.
        assert_eq!(CUDA_RUNTIME_COMPONENT, "native-cuda-runtime");
    }

    #[test]
    fn default_optional_components_names_only_cuda_runtime() {
        assert_eq!(DEFAULT_OPTIONAL_COMPONENTS, &[CUDA_RUNTIME_COMPONENT]);
    }

    #[test]
    fn pack_extraction_destination_bridges_the_cuda_component_to_dependencies_cuda() {
        let dest_dir = Path::new(r"C:\Program Files\CivicCast Native\packs");
        assert_eq!(
            pack_extraction_destination(dest_dir, CUDA_RUNTIME_COMPONENT).expect("bridge"),
            Path::new(r"C:\Program Files\CivicCast Native\dependencies\cuda")
        );
    }

    #[test]
    fn cuda_runtime_stages_onto_the_dependencies_cuda_bin_path_the_presence_gate_checks() {
        // Mirrors media_tools_stages_onto_the_dependencies_ffmpeg_bin_path_the_
        // activation_layer_pins exactly, one directory over: the load-bearing
        // composition of the pack's bin/-rooted payload with the extraction
        // bridge, proven rather than merely described.
        let instdir = Path::new(r"C:\Program Files\CivicCast");
        let extraction = pack_extraction_destination(&instdir.join("packs"), CUDA_RUNTIME_COMPONENT)
            .expect("bridge resolves");
        assert_eq!(extraction, instdir.join("dependencies").join("cuda"));
        assert_eq!(
            extraction.join("bin").join("cublas64_12.dll"),
            instdir
                .join("dependencies")
                .join("cuda")
                .join("bin")
                .join("cublas64_12.dll")
        );
    }

    // ---- decide_optional_staging_action: the pure decision matrix ----

    #[test]
    fn optional_already_verified_destination_is_always_satisfied_regardless_of_source() {
        for source in [OfflineSourceState::Verified, OfflineSourceState::Absent] {
            assert_eq!(
                decide_optional_staging_action(&DestPackState::Verified, &source),
                OptionalStagingAction::AlreadySatisfied
            );
        }
    }

    #[test]
    fn optional_absent_destination_with_verified_source_copies() {
        assert_eq!(
            decide_optional_staging_action(&DestPackState::Absent, &OfflineSourceState::Verified),
            OptionalStagingAction::CopyFromOffline
        );
    }

    #[test]
    fn optional_corrupt_destination_with_verified_source_replaces() {
        assert_eq!(
            decide_optional_staging_action(
                &DestPackState::Corrupt("tampered".to_string()),
                &OfflineSourceState::Verified
            ),
            OptionalStagingAction::ReplaceCorruptFromOffline
        );
    }

    #[test]
    fn optional_absent_destination_with_no_source_is_skipped_not_aborted() {
        // The load-bearing divergence from the required decision matrix:
        // StagingAction::NeedsOnlineOrAbort becomes a quiet, recorded skip.
        assert_eq!(
            decide_optional_staging_action(&DestPackState::Absent, &OfflineSourceState::Absent),
            OptionalStagingAction::SkipAbsent
        );
    }

    #[test]
    fn optional_corrupt_destination_with_no_source_is_a_hard_failure_not_a_skip() {
        // The other load-bearing divergence: "optional means may be absent,
        // never may be untrusted" -- a present-but-corrupt pack with no
        // offline remedy must NOT collapse into the same SkipAbsent outcome
        // an absent one gets.
        assert_eq!(
            decide_optional_staging_action(
                &DestPackState::Corrupt("bad hash".to_string()),
                &OfflineSourceState::Absent
            ),
            OptionalStagingAction::CorruptWithNoRemedy
        );
    }

    // ---- stage_optional_packs: end to end ----

    #[test]
    fn stage_optional_packs_skips_and_records_a_wholly_absent_optional_component() {
        let root = scratch_dir("optional-absent");
        let signing_key = SigningKey::from_bytes(&[7_u8; 32]);
        let trust = trust_for(&signing_key);
        let installer_dir = root.join("installer"); // no packs/ subdirectory at all
        let instdir = root.join("instdir");

        let report = stage_optional_packs(
            &installer_dir,
            &instdir,
            &trust,
            &[CUDA_RUNTIME_COMPONENT.to_string()],
            "1.0.0-rc15",
            "1.0.0-rc15",
            &AllowAllAuthority,
        )
        .expect("an absent optional component must never fail staging");

        assert_eq!(report.skipped_absent, vec![CUDA_RUNTIME_COMPONENT.to_string()]);
        assert!(report.already_present.is_empty());
        assert!(report.copied_from_offline.is_empty());
        assert!(report.extracted.is_empty());
        assert!(
            !instdir
                .join("dependencies")
                .join("cuda")
                .exists(),
            "nothing should be extracted for a component that was never staged"
        );

        let _ = fs::remove_dir_all(&root);
    }

    #[test]
    fn stage_optional_packs_stages_and_extracts_a_present_offline_optional_component() {
        let root = scratch_dir("optional-present");
        let signing_key = SigningKey::from_bytes(&[7_u8; 32]);
        let trust = trust_for(&signing_key);
        let installer_dir = root.join("installer");
        let instdir = root.join("instdir");
        fs::create_dir_all(installer_dir.join("packs")).expect("mkdir installer packs");
        build_signed_pack(
            &installer_dir
                .join("packs")
                .join("native-cuda-runtime.ccpack"),
            &signing_key,
            CUDA_RUNTIME_COMPONENT,
            &[("bin/cublas64_12.dll", b"pretend-cublas64_12-bytes")],
        );

        let report = stage_optional_packs(
            &installer_dir,
            &instdir,
            &trust,
            &[CUDA_RUNTIME_COMPONENT.to_string()],
            "1.0.0-rc15",
            "1.0.0-rc15",
            &AllowAllAuthority,
        )
        .expect("a verified, side-loaded optional component must stage");

        assert_eq!(report.copied_from_offline, vec![CUDA_RUNTIME_COMPONENT.to_string()]);
        assert!(report.skipped_absent.is_empty());
        assert_eq!(report.extracted, vec![CUDA_RUNTIME_COMPONENT.to_string()]);
        assert_eq!(
            fs::read(
                instdir
                    .join("dependencies")
                    .join("cuda")
                    .join("bin")
                    .join("cublas64_12.dll")
            )
            .expect("read cublas64_12.dll"),
            b"pretend-cublas64_12-bytes",
            "a present optional pack must land at exactly the presence gate's path"
        );

        let _ = fs::remove_dir_all(&root);
    }

    #[test]
    fn stage_optional_packs_refuses_and_leaves_a_tampered_pack_with_no_remedy_as_a_hard_failure() {
        let root = scratch_dir("optional-corrupt-no-remedy");
        let signing_key = SigningKey::from_bytes(&[7_u8; 32]);
        let trust = trust_for(&signing_key);
        let installer_dir = root.join("installer"); // no offline remedy available
        let instdir = root.join("instdir");
        let dest_dir = instdir.join("packs");
        fs::create_dir_all(&dest_dir).expect("mkdir dest packs");
        fs::write(
            dest_dir.join("native-cuda-runtime.ccpack"),
            b"not a real pack at all",
        )
        .expect("write corrupt destination pack");

        let error = stage_optional_packs(
            &installer_dir,
            &instdir,
            &trust,
            &[CUDA_RUNTIME_COMPONENT.to_string()],
            "1.0.0-rc15",
            "1.0.0-rc15",
            &AllowAllAuthority,
        )
        .expect_err(
            "a present-but-untrusted optional pack with no remedy must fail staging, never be \
             silently skipped",
        );
        assert!(error.contains(CUDA_RUNTIME_COMPONENT));

        let _ = fs::remove_dir_all(&root);
    }

    #[test]
    fn stage_optional_packs_replaces_a_corrupt_destination_from_a_valid_offline_source() {
        let root = scratch_dir("optional-corrupt-replaced");
        let signing_key = SigningKey::from_bytes(&[7_u8; 32]);
        let trust = trust_for(&signing_key);
        let installer_dir = root.join("installer");
        let instdir = root.join("instdir");
        fs::create_dir_all(installer_dir.join("packs")).expect("mkdir installer packs");
        build_signed_pack(
            &installer_dir
                .join("packs")
                .join("native-cuda-runtime.ccpack"),
            &signing_key,
            CUDA_RUNTIME_COMPONENT,
            &[("bin/cublas64_12.dll", b"pretend-cublas64_12-bytes")],
        );
        let dest_dir = instdir.join("packs");
        fs::create_dir_all(&dest_dir).expect("mkdir dest packs");
        fs::write(
            dest_dir.join("native-cuda-runtime.ccpack"),
            b"not a real pack at all",
        )
        .expect("write corrupt destination pack");

        let report = stage_optional_packs(
            &installer_dir,
            &instdir,
            &trust,
            &[CUDA_RUNTIME_COMPONENT.to_string()],
            "1.0.0-rc15",
            "1.0.0-rc15",
            &AllowAllAuthority,
        )
        .expect("a corrupt destination must be replaced from a valid offline source");

        assert_eq!(report.replaced_from_offline, vec![CUDA_RUNTIME_COMPONENT.to_string()]);
        assert_eq!(report.extracted, vec![CUDA_RUNTIME_COMPONENT.to_string()]);

        let _ = fs::remove_dir_all(&root);
    }

    #[test]
    fn stage_optional_packs_is_idempotent_over_an_already_verified_tree() {
        let root = scratch_dir("optional-idempotent");
        let signing_key = SigningKey::from_bytes(&[7_u8; 32]);
        let trust = trust_for(&signing_key);
        let installer_dir = root.join("installer");
        let instdir = root.join("instdir");
        fs::create_dir_all(installer_dir.join("packs")).expect("mkdir installer packs");
        build_signed_pack(
            &installer_dir
                .join("packs")
                .join("native-cuda-runtime.ccpack"),
            &signing_key,
            CUDA_RUNTIME_COMPONENT,
            &[("bin/cublas64_12.dll", b"pretend-cublas64_12-bytes")],
        );

        stage_optional_packs(
            &installer_dir,
            &instdir,
            &trust,
            &[CUDA_RUNTIME_COMPONENT.to_string()],
            "1.0.0-rc15",
            "1.0.0-rc15",
            &AllowAllAuthority,
        )
        .expect("first optional staging must succeed");

        let second = stage_optional_packs(
            &installer_dir,
            &instdir,
            &trust,
            &[CUDA_RUNTIME_COMPONENT.to_string()],
            "1.0.0-rc15",
            "1.0.0-rc15",
            &PanicIfConsultedAuthority,
        )
        .expect("re-running over an already-verified optional tree must succeed");
        assert_eq!(second.already_present, vec![CUDA_RUNTIME_COMPONENT.to_string()]);
        assert!(second.copied_from_offline.is_empty());
        assert_eq!(second.extracted, vec![CUDA_RUNTIME_COMPONENT.to_string()]);

        let _ = fs::remove_dir_all(&root);
    }
}
