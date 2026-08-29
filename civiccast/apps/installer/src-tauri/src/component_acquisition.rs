// SPDX-License-Identifier: Apache-2.0
// Copyright (c) The CivicCast Authors

//! Streaming download engine for the large, out-of-band components the
//! sub-300 MB native bootstrap does not embed (owner-settled architecture,
//! `.agent-runs/native-windows/specs/plan-sub-300mb-bootstrap.md`): the
//! application-payload pack (~482 MB) and the server-binaries pack (~94 MB),
//! both signed `.ccpack` archives published as public GitHub Release assets
//! in a binaries-only public repository; the caption floor-tier
//! (`medium`) model weights (~1.5 GB), fetched directly from HuggingFace at
//! the pinned revision `native_packs::CAPTION_FLOOR_TIER_MODEL_REVISION`
//! already carries (owner BINDING ruling, 2026-07-30, naming `medium` --
//! see that constant's doc comment in `native_packs.rs`); and (task #56) the
//! `local_ai_model` component's gemma4:12b weights (~7.6 GB), fetched
//! directly from the Ollama registry's v2 protocol (a manifest fetch plus
//! several content-addressed layer blob fetches, never a single HTTPS GET --
//! see [`ComponentSource::OllamaManifest`]/[`ComponentSource::OllamaBlob`]).
//!
//! ## Three different components, three different trust models
//!
//! * **HuggingFace caption weight files** each have an individually pinned
//!   `(bytes, sha256)` -- see `native_packs::CAPTION_FLOOR_TIER_MODEL_FILES`
//!   (this module never re-transcribes that pin; `caption_floor_tier_file_sources`
//!   reads it directly). [`download_component`] verifies the downloaded
//!   bytes against that pin itself ([`ExpectedArtifact::Pinned`]).
//! * **Ollama registry manifest and blobs** are ALSO individually pinned
//!   `(bytes, sha256)` [`ExpectedArtifact::Pinned`] items, driven through the
//!   exact same generic [`download_component`]/[`ensure_component_available`]
//!   path as the HuggingFace files above (no new orchestration layer): the
//!   manifest's pin comes from the embedded reviewed lock
//!   (`native_packs::reviewed_ollama_model` -- the SAME lock
//!   `native_packs::validate_ollama_model_contract` already checks the
//!   signed-pack pull protocol against), and each blob's pin is its own
//!   content-addressed digest (the digest IS the expected hash). A model's
//!   several blobs are simply several [`crate::acquisition_catalog::CatalogItem`]s
//!   under one `local_ai_model` [`crate::acquisition_catalog::CatalogComponent`]
//!   -- progress aggregates across them exactly the way `captions_medium`'s
//!   four HuggingFace files already do (see `main.rs`'s
//!   `run_single_acquisition_component_with_persist`).
//! * **Signed component packs** (`GitHubReleaseAsset`) do NOT have an
//!   externally pinned outer-file hash available to this engine -- trust is
//!   established by the pack's own ed25519 manifest signature, verified by
//!   the EXISTING chain in `native_packs.rs` (`native_packs::verify_pack`),
//!   exactly the way `native_pack_staging::commit_pack_file` already trusts
//!   an offline-staged or channel-index-acquired pack. [`acquire_and_verify_pack`]
//!   downloads with [`ExpectedArtifact::Unverified`] (no self-check) and then
//!   calls `native_packs::verify_pack` -- never a second, parallel verifier.
//!
//! ## Resume / restart posture
//!
//! Mirrors the battle-tested HTTP mechanics already proven in
//! `native_distribution.rs::apply_transfer_response` (Content-Range
//! validated against the requested offset and, when known, the pinned total;
//! a server that answers `200` to a ranged request is treated as "ignored
//! Range" and the partial file is discarded, never appended to blindly).
//! This module does not fork that pack-specific function; it reuses its
//! Content-Range grammar (`native_distribution::parse_content_range`) and
//! reimplements only the generic (non-pack) streaming loop, since the
//! existing function is tightly coupled to `DistributionPack`.
//!
//! ## Progress
//!
//! [`ProgressObserver`] is deliberately dumb: it is handed `bytes_done`,
//! `bytes_total` (when known), and wall-clock `elapsed` and computes nothing
//! itself (no rate, no ETA) -- exactly the task's instruction that the
//! caller (the Tauri layer, once a progress UI is built on top of this) owns
//! that arithmetic. No `tauri::Window::emit`-based event mechanism exists
//! anywhere in this crate today (checked): the only existing progress/status
//! channel is the polled installer-state JSON file
//! (`write_installer_state`/`read_local_installer_state` in `main.rs`, read
//! by the frontend every 2s). [`ProgressObserver`] is intentionally
//! Tauri-agnostic (a plain trait, with a blanket impl for any suitable
//! closure) so either seam -- a future `window.emit`, or writing into that
//! same polled state file -- can be wired on top of it without this module
//! needing to change.

use std::fs::{self, File, OpenOptions};
use std::io::{Read, Write};
use std::path::{Path, PathBuf};
use std::sync::atomic::{AtomicBool, Ordering};
use std::time::{Duration, Instant};

use reqwest::blocking::{Client, Response};
use reqwest::header::{ACCEPT_ENCODING, CONTENT_RANGE, RANGE};
use reqwest::redirect::Policy;
use url::Url;

use crate::native_distribution::parse_content_range;
use crate::native_packs::{self, PackTrust, VerifiedPack};

// ---------------------------------------------------------------------------
// Component source resolution
// ---------------------------------------------------------------------------

/// Where one component's bytes come from. The base URL for GitHub release
/// assets is always supplied by the CALLER (configuration), never hardcoded
/// here -- the owner-settled architecture requires the binaries-only public
/// repository's base URL to be configuration, not a compiled-in final value.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum ComponentSource {
    /// A public GitHub Release asset: `{base_url}/{asset_name}`. `base_url`
    /// is everything up to and including the release tag segment (e.g.
    /// `https://github.com/OWNER/REPO/releases/download/v1.0.0-rc15`);
    /// `asset_name` is the literal asset filename GitHub serves it under.
    GitHubReleaseAsset {
        base_url: String,
        asset_name: String,
    },
    /// One file inside a HuggingFace model repository at a pinned revision:
    /// `https://huggingface.co/{repo}/resolve/{revision}/{path}`.
    HuggingFaceFile {
        repo: String,
        revision: String,
        path: String,
    },
    /// An Ollama registry v2 model manifest: `{registry_base}/v2/library/
    /// {repository}/manifests/{tag}` -- a small JSON document (a few hundred
    /// bytes to a few KB) listing the model's config and layer blob digests.
    /// `registry_base` is everything up to (not including) `/v2/...` (e.g.
    /// `https://registry.ollama.ai`), configuration the same way
    /// `GitHubReleaseAsset`'s `base_url` is -- see
    /// `acquisition_catalog::ollama_registry_base_url`. Verified by
    /// [`ExpectedArtifact::Pinned`] against the manifest identity the
    /// embedded reviewed lock already carries
    /// (`native_packs::reviewed_ollama_model`) -- the SAME
    /// `manifest_bytes`/`manifest_sha256` pin `native_packs::
    /// validate_ollama_model_contract` checks for the signed-pack pull
    /// protocol, reused here rather than re-pinned.
    OllamaManifest {
        registry_base: String,
        repository: String,
        tag: String,
    },
    /// One Ollama registry v2 content-addressed blob (the model's config
    /// object or one image layer): `{registry_base}/v2/library/{repository}
    /// /blobs/sha256:{digest}` (`digest` is the bare lowercase hex SHA-256,
    /// no `sha256:` prefix -- this variant adds that prefix itself, matching
    /// the OCI distribution spec's blob-pull URL grammar). Content-addressed:
    /// `digest` IS both the URL parameter and the expected hash
    /// ([`ExpectedArtifact::Pinned`]) -- no separate pin is needed beyond
    /// what the manifest (or, before that manifest is trusted, the embedded
    /// reviewed lock) already supplies.
    OllamaBlob {
        registry_base: String,
        repository: String,
        digest: String,
    },
}

impl ComponentSource {
    /// Resolve to a concrete URL. Does not validate scheme/shape -- see
    /// [`validate_https_url`], applied by the public entry points
    /// ([`download_component`], [`acquire_and_verify_pack`]) before any
    /// network access.
    pub fn resolve_url(&self) -> Result<String, AcquisitionError> {
        match self {
            ComponentSource::GitHubReleaseAsset {
                base_url,
                asset_name,
            } => {
                if base_url.trim().is_empty() || asset_name.trim().is_empty() {
                    return Err(AcquisitionError::NetworkFailed(
                        "GitHub release asset source is missing its base URL or asset name."
                            .to_string(),
                    ));
                }
                let trimmed_base = base_url.trim_end_matches('/');
                Ok(format!("{trimmed_base}/{asset_name}"))
            }
            ComponentSource::HuggingFaceFile {
                repo,
                revision,
                path,
            } => {
                if repo.trim().is_empty() || revision.trim().is_empty() || path.trim().is_empty()
                {
                    return Err(AcquisitionError::NetworkFailed(
                        "HuggingFace file source is missing its repo, revision, or path."
                            .to_string(),
                    ));
                }
                Ok(format!(
                    "https://huggingface.co/{repo}/resolve/{revision}/{path}"
                ))
            }
            ComponentSource::OllamaManifest {
                registry_base,
                repository,
                tag,
            } => {
                if registry_base.trim().is_empty()
                    || repository.trim().is_empty()
                    || tag.trim().is_empty()
                {
                    return Err(AcquisitionError::NetworkFailed(
                        "Ollama manifest source is missing its registry base URL, repository, or \
                         tag."
                            .to_string(),
                    ));
                }
                let trimmed_base = registry_base.trim_end_matches('/');
                Ok(format!(
                    "{trimmed_base}/v2/library/{repository}/manifests/{tag}"
                ))
            }
            ComponentSource::OllamaBlob {
                registry_base,
                repository,
                digest,
            } => {
                if registry_base.trim().is_empty()
                    || repository.trim().is_empty()
                    || digest.trim().is_empty()
                {
                    return Err(AcquisitionError::NetworkFailed(
                        "Ollama blob source is missing its registry base URL, repository, or \
                         digest."
                            .to_string(),
                    ));
                }
                let trimmed_base = registry_base.trim_end_matches('/');
                Ok(format!(
                    "{trimmed_base}/v2/library/{repository}/blobs/sha256:{digest}"
                ))
            }
        }
    }
}

fn validate_https_url(url: &str) -> Result<(), AcquisitionError> {
    if !url.is_ascii() {
        return Err(AcquisitionError::NetworkFailed(
            "Component source URL is not portable ASCII.".to_string(),
        ));
    }
    let parsed = Url::parse(url).map_err(|_| {
        AcquisitionError::NetworkFailed("Component source URL is not a valid URL.".to_string())
    })?;
    if parsed.scheme() != "https"
        || parsed.host_str().is_none()
        || !parsed.username().is_empty()
        || parsed.password().is_some()
        || parsed.fragment().is_some()
        || parsed.path().is_empty()
        || parsed.path() == "/"
    {
        return Err(AcquisitionError::NetworkFailed(
            "Component source URL must be unambiguous HTTPS.".to_string(),
        ));
    }
    Ok(())
}

// ---------------------------------------------------------------------------
// Typed, fail-loud errors
// ---------------------------------------------------------------------------

#[derive(Debug)]
pub enum AcquisitionError {
    /// A transport-level failure: DNS, TLS, connect, an unexpected non-2xx
    /// status other than 404, or the connection dropping mid-read.
    NetworkFailed(String),
    /// A `.partial` resume attempt could not be validated against the
    /// server's response (missing/invalid Content-Range, or a server
    /// answering with a different total than the resume expected) -- the
    /// `.partial` file has already been removed by the time this is
    /// returned.
    ResumeInvalid(String),
    /// The completed download's bytes did not match what was expected. For
    /// a [`ExpectedArtifact::Pinned`] artifact this compares byte count and
    /// SHA-256 directly; for a signed pack downloaded via
    /// [`acquire_and_verify_pack`] this instead reports the EXISTING signed
    /// manifest chain's rejection reason (`native_packs::verify_pack`). The
    /// artifact at `path` has already been deleted by the time this is
    /// returned.
    HashMismatch {
        path: PathBuf,
        expected: String,
        actual: String,
    },
    /// The destination volume is genuinely out of space. Reported ONLY for an
    /// OS error that actually means storage exhaustion
    /// ([`STORAGE_EXHAUSTION_OS_ERRORS`]) -- never as a catch-all.
    ///
    /// It used to be the catch-all, and that is the defect chain H2 closes:
    /// R7's durable `installer-state.json` recorded
    /// `{"kind":"disk_full","detail":"PermissionDenied"}` for both required
    /// components on a station with 175.3 GiB free, and the operator was shown
    /// a screen telling them to free disk space.
    DiskFull(std::io::ErrorKind),
    /// The process is not allowed to write where it is trying to write
    /// (`ErrorKind::PermissionDenied` -- Windows `ERROR_ACCESS_DENIED`).
    /// Distinct from every other local failure because the remedy is
    /// completely different and naming it wrong costs the operator the whole
    /// first run.
    PermissionDenied(std::io::ErrorKind),
    /// A local file operation failed for a reason this engine cannot
    /// distinguish further. The honest residual bucket: it claims nothing
    /// about the cause beyond "the local filesystem step failed", which is
    /// exactly what is known.
    WriteFailed(std::io::ErrorKind),
    /// The component source answered HTTP 404.
    SourceNotFound(String),
    /// The operator asked CivicCast to stop (G011.3). NOT a failure: no
    /// remedy is named, no error copy is shown, and the `.partial` is
    /// deliberately left in place so choosing Resume picks up where the
    /// transfer stopped rather than starting the file over.
    Canceled,
}

// ---------------------------------------------------------------------------
// Cancellation (G011.3)
// ---------------------------------------------------------------------------

/// Process-wide "the operator asked us to stop" flag, checked by the download
/// read loop between buffer reads.
///
/// Process-wide rather than per-transfer because that is exactly the scope of
/// the thing being canceled: there is one first-run acquisition driver per
/// process (`main.rs`'s `ACQUISITION_DRIVER_STARTED` is a one-way latch), and
/// the operator-facing control is "Stop downloading", not "stop this one
/// file". Keeping the flag here rather than threading a cancel token through
/// `download_component` / `ensure_component_available` /
/// `acquire_and_verify_pack` also means no signature in the engine changes,
/// so the cancel path cannot introduce a behavior difference in the paths it
/// is not about.
static CANCEL_REQUESTED: AtomicBool = AtomicBool::new(false);

/// Ask the in-flight download to stop at its next buffer boundary. Returns
/// immediately -- the transfer unwinds on its own thread.
pub fn request_cancel() {
    CANCEL_REQUESTED.store(true, Ordering::SeqCst);
}

/// Clear the cancel flag so a subsequent transfer can run. Called by the
/// retry/resume path: a canceled component that the operator chooses to
/// resume must not immediately cancel itself again.
pub fn clear_cancel() {
    CANCEL_REQUESTED.store(false, Ordering::SeqCst);
}

pub fn cancel_requested() -> bool {
    CANCEL_REQUESTED.load(Ordering::SeqCst)
}

/// The OS error codes that actually mean "the volume is out of space" -- the
/// ONLY inputs [`map_write_error`] is allowed to turn into
/// [`AcquisitionError::DiskFull`].
///
/// Raw OS codes rather than `io::ErrorKind::StorageFull`, which is still
/// unstable (`io_error_more`) on the toolchain this crate builds with, so a
/// real `ENOSPC`/`ERROR_DISK_FULL` arrives as `ErrorKind::Uncategorized` and
/// is indistinguishable by kind alone.
#[cfg(windows)]
pub const STORAGE_EXHAUSTION_OS_ERRORS: &[i32] = &[
    39,  // ERROR_HANDLE_DISK_FULL
    112, // ERROR_DISK_FULL
];
#[cfg(not(windows))]
pub const STORAGE_EXHAUSTION_OS_ERRORS: &[i32] = &[
    28, // ENOSPC
];

impl std::fmt::Display for AcquisitionError {
    fn fmt(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            AcquisitionError::NetworkFailed(reason) => {
                write!(formatter, "Could not download the component: {reason}")
            }
            AcquisitionError::ResumeInvalid(reason) => write!(
                formatter,
                "Resuming the partial component download failed validation: {reason}"
            ),
            AcquisitionError::HashMismatch {
                path,
                expected,
                actual,
            } => write!(
                formatter,
                "Downloaded component at {} failed verification (expected {expected}, got \
                 {actual}); the artifact was deleted.",
                path.display()
            ),
            AcquisitionError::DiskFull(kind) => write!(
                formatter,
                "The destination volume is out of space ({kind:?}); free space and retry."
            ),
            AcquisitionError::PermissionDenied(kind) => write!(
                formatter,
                "Windows refused permission to write the downloaded component ({kind:?}); the \
                 destination folder is not writable by this process."
            ),
            AcquisitionError::WriteFailed(kind) => write!(
                formatter,
                "A local file operation for the downloaded component failed ({kind:?})."
            ),
            AcquisitionError::SourceNotFound(location) => write!(
                formatter,
                "The component source was not found (HTTP 404): {location}"
            ),
            AcquisitionError::Canceled => write!(
                formatter,
                "The component download was stopped at the operator's request."
            ),
        }
    }
}

impl std::error::Error for AcquisitionError {}

/// Classify a local filesystem failure into a typed outcome that says what
/// actually happened.
///
/// The pre-fix body was `AcquisitionError::DiskFull(error.kind())` -- every
/// cause, one answer. Because the frontend keys its operator copy off the
/// `kind` alone (`acquisition-progress.ts`'s `ERROR_PRESENTATIONS`) and never
/// off `detail`, that single line is what put "This drive doesn't have enough
/// free space" in front of an R7 operator with 175.3 GiB free while the real
/// error, `PermissionDenied`, sat in the detail field nothing displays.
///
/// The rule this now holds to: NOTHING reports disk-full unless the OS error
/// actually means storage exhaustion. Everything the engine can distinguish
/// gets its own outcome; everything it cannot gets the honest residual
/// [`AcquisitionError::WriteFailed`].
fn map_write_error(error: std::io::Error) -> AcquisitionError {
    let kind = error.kind();
    if error
        .raw_os_error()
        .is_some_and(|raw| STORAGE_EXHAUSTION_OS_ERRORS.contains(&raw))
    {
        return AcquisitionError::DiskFull(kind);
    }
    match kind {
        std::io::ErrorKind::PermissionDenied => AcquisitionError::PermissionDenied(kind),
        other => AcquisitionError::WriteFailed(other),
    }
}

// ---------------------------------------------------------------------------
// Progress
// ---------------------------------------------------------------------------

/// A dumb progress sample: no rate, no ETA, no smoothing -- the caller
/// (eventually, the Tauri progress UI) computes all of that.
#[derive(Debug, Clone, Copy)]
pub struct DownloadProgress {
    pub bytes_done: u64,
    pub bytes_total: Option<u64>,
    pub elapsed: Duration,
}

/// The seam the Tauri layer subscribes to. Intentionally not
/// Tauri-specific -- see this module's doc comment for why (no existing
/// `window.emit` progress channel was found in this crate; the only
/// existing mechanism is the polled installer-state JSON file). A blanket
/// impl below lets any `Fn(DownloadProgress) + Send` closure serve as an
/// observer directly.
pub trait ProgressObserver: Send {
    fn on_progress(&self, progress: DownloadProgress);
}

impl<F> ProgressObserver for F
where
    F: Fn(DownloadProgress) + Send,
{
    fn on_progress(&self, progress: DownloadProgress) {
        self(progress)
    }
}

/// The default for callers with no progress seam wired up yet.
pub struct NoopProgress;

impl ProgressObserver for NoopProgress {
    fn on_progress(&self, _progress: DownloadProgress) {}
}

// ---------------------------------------------------------------------------
// Expected artifact / verification strategy
// ---------------------------------------------------------------------------

#[derive(Debug, Clone)]
pub enum ExpectedArtifact {
    /// A known, pinned byte count and SHA-256, checked directly against the
    /// downloaded bytes by [`download_component`] itself -- used for
    /// individually pinned files (the HuggingFace caption floor-tier
    /// weights; see [`caption_floor_tier_file_sources`]).
    Pinned { bytes: u64, sha256: String },
    /// No externally pinned hash for the raw downloaded bytes.
    /// [`download_component`] still streams-to-`.partial`-then-renames, but
    /// performs no hash check of its own -- the caller MUST verify before
    /// trusting the result (see [`acquire_and_verify_pack`], which reuses
    /// `native_packs::verify_pack` for this).
    Unverified,
}

// ---------------------------------------------------------------------------
// The download engine
// ---------------------------------------------------------------------------

fn partial_path_for(destination: &Path) -> PathBuf {
    let mut file_name = destination
        .file_name()
        .map(|value| value.to_os_string())
        .unwrap_or_default();
    file_name.push(".partial");
    destination.with_file_name(file_name)
}

fn partial_len(partial: &Path) -> Result<u64, AcquisitionError> {
    match fs::metadata(partial) {
        Ok(metadata) if metadata.is_file() => Ok(metadata.len()),
        Ok(_) => Ok(0),
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => Ok(0),
        Err(error) => Err(map_write_error(error)),
    }
}

fn hash_file(path: &Path) -> Result<String, AcquisitionError> {
    let mut file = File::open(path).map_err(map_write_error)?;
    // A re-READ failure of an already-downloaded artifact. This used to be a
    // second, hand-written `DiskFull` outside `map_write_error` entirely --
    // the same lie in a second place. It is a local file operation that
    // failed for a reason this engine cannot narrow further, which is exactly
    // what `WriteFailed` says.
    native_packs::sha256_reader(&mut file, "downloaded component")
        .map_err(|_reason| AcquisitionError::WriteFailed(std::io::ErrorKind::Other))
}

fn build_http_client() -> Result<Client, AcquisitionError> {
    Client::builder()
        // GitHub release asset downloads redirect (typically to a signed,
        // time-limited object-storage URL) -- unlike native_distribution.rs's
        // pack/index client, which pins exact HTTPS locations up front and
        // disables redirects entirely, this engine must follow them. Every
        // hop is still required to be HTTPS.
        .redirect(Policy::custom(|attempt| {
            if attempt.url().scheme() == "https" {
                attempt.follow()
            } else {
                attempt.error("component acquisition refuses a non-HTTPS redirect")
            }
        }))
        .connect_timeout(Duration::from_secs(30))
        .timeout(Duration::from_secs(6 * 60 * 60))
        .user_agent("CivicCast-Native-Bootstrap/1")
        .build()
        .map_err(|error| {
            AcquisitionError::NetworkFailed(format!(
                "Could not initialize the component download client: {error}"
            ))
        })
}

fn send_request(client: &Client, url: &str, offset: u64) -> Result<Response, AcquisitionError> {
    let mut request = client.get(url).header(ACCEPT_ENCODING, "identity");
    if offset > 0 {
        request = request.header(RANGE, format!("bytes={offset}-"));
    }
    request.send().map_err(|error| {
        AcquisitionError::NetworkFailed(format!("Could not reach {url}: {error}"))
    })
}

fn write_body_to_partial(
    partial: &Path,
    mut response: Response,
    offset: u64,
    bytes_total: Option<u64>,
    started: Instant,
    progress: &dyn ProgressObserver,
) -> Result<(), AcquisitionError> {
    let append = offset > 0;
    let mut options = OpenOptions::new();
    options.create(true).write(true);
    if append {
        options.append(true);
    } else {
        options.truncate(true);
    }
    let mut output = options.open(partial).map_err(map_write_error)?;

    progress.on_progress(DownloadProgress {
        bytes_done: offset,
        bytes_total,
        elapsed: started.elapsed(),
    });

    let mut bytes_done = offset;
    let mut buffer = vec![0_u8; 64 * 1024];
    loop {
        // G011.3. Checked at the buffer boundary, BEFORE the next read
        // blocks: the bytes already written stay in the `.partial`, which is
        // flushed below, so a later Resume picks up from here rather than
        // starting a multi-gigabyte file over. Cancelling is not an error and
        // does not delete anything.
        if cancel_requested() {
            output.sync_all().map_err(map_write_error)?;
            return Err(AcquisitionError::Canceled);
        }
        let count = response.read(&mut buffer).map_err(|error| {
            AcquisitionError::NetworkFailed(format!(
                "Component download connection failed: {error}"
            ))
        })?;
        if count == 0 {
            break;
        }
        output.write_all(&buffer[..count]).map_err(map_write_error)?;
        bytes_done = bytes_done.checked_add(count as u64).ok_or_else(|| {
            AcquisitionError::NetworkFailed(
                "Component download byte count overflowed.".to_string(),
            )
        })?;
        progress.on_progress(DownloadProgress {
            bytes_done,
            bytes_total,
            elapsed: started.elapsed(),
        });
    }
    output.sync_all().map_err(map_write_error)?;
    Ok(())
}

fn finalize_download(
    partial: &Path,
    destination: &Path,
    expected: &ExpectedArtifact,
) -> Result<PathBuf, AcquisitionError> {
    if let ExpectedArtifact::Pinned { bytes, sha256 } = expected {
        let observed_bytes = partial_len(partial)?;
        if observed_bytes != *bytes {
            let _ = fs::remove_file(partial);
            return Err(AcquisitionError::HashMismatch {
                path: partial.to_path_buf(),
                expected: format!("{bytes} bytes (sha256 {sha256})"),
                actual: format!("{observed_bytes} bytes"),
            });
        }
        let observed_hash = hash_file(partial)?;
        if &observed_hash != sha256 {
            let _ = fs::remove_file(partial);
            return Err(AcquisitionError::HashMismatch {
                path: partial.to_path_buf(),
                expected: sha256.clone(),
                actual: observed_hash,
            });
        }
    }
    fs::rename(partial, destination).map_err(map_write_error)?;
    Ok(destination.to_path_buf())
}

/// The core streaming primitive, generalized over any HTTPS URL: resumes
/// from an existing `.partial` file via HTTP Range when possible, restarts
/// cleanly if the server ignores Range or answers a mismatched
/// Content-Range, verifies the completed download against `expected`
/// ([`ExpectedArtifact::Pinned`] only -- see that variant's doc), and
/// renames `.partial` to `destination` atomically on success.
///
/// Split out from [`download_component`] so tests can drive it against a
/// plain-HTTP localhost fixture server without weakening the HTTPS-only
/// posture the public entry point enforces (see [`validate_https_url`],
/// applied only by [`download_component`]/[`acquire_and_verify_pack`]).
fn download_from_url(
    url: &str,
    destination: &Path,
    expected: &ExpectedArtifact,
    progress: &dyn ProgressObserver,
) -> Result<PathBuf, AcquisitionError> {
    let parent = destination.parent().ok_or_else(|| {
        AcquisitionError::NetworkFailed(format!(
            "Component download destination has no parent directory: {}",
            destination.display()
        ))
    })?;
    fs::create_dir_all(parent).map_err(map_write_error)?;
    let partial = partial_path_for(destination);
    let client = build_http_client()?;
    let known_total = match expected {
        ExpectedArtifact::Pinned { bytes, .. } => Some(*bytes),
        ExpectedArtifact::Unverified => None,
    };
    let started = Instant::now();
    let mut offset = partial_len(&partial)?;
    let mut restarted = false;

    loop {
        let response = send_request(&client, url, offset)?;
        let status = response.status().as_u16();
        match status {
            404 => return Err(AcquisitionError::SourceNotFound(url.to_string())),
            200 => {
                if offset > 0 {
                    let _ = fs::remove_file(&partial);
                    offset = 0;
                }
                write_body_to_partial(&partial, response, offset, known_total, started, progress)?;
                break;
            }
            206 => {
                let content_range = response
                    .headers()
                    .get(CONTENT_RANGE)
                    .and_then(|value| value.to_str().ok())
                    .map(str::to_string);
                let Some(content_range) = content_range else {
                    let _ = fs::remove_file(&partial);
                    return Err(AcquisitionError::ResumeInvalid(
                        "Resumed component response is missing Content-Range.".to_string(),
                    ));
                };
                let (start, end, total) = match parse_content_range(&content_range) {
                    Ok(parsed) => parsed,
                    Err(reason) => {
                        let _ = fs::remove_file(&partial);
                        return Err(AcquisitionError::ResumeInvalid(reason));
                    }
                };
                let total_mismatch =
                    known_total.is_some_and(|expected_total| expected_total != total);
                if start != offset || total_mismatch {
                    if restarted {
                        let _ = fs::remove_file(&partial);
                        return Err(AcquisitionError::ResumeInvalid(format!(
                            "Server's Content-Range (bytes {start}-{end}/{total}) does not match \
                             the requested resume point at offset {offset}."
                        )));
                    }
                    let _ = fs::remove_file(&partial);
                    offset = 0;
                    restarted = true;
                    continue;
                }
                write_body_to_partial(&partial, response, offset, known_total.or(Some(total)), started, progress)?;
                break;
            }
            other => {
                return Err(AcquisitionError::NetworkFailed(format!(
                    "Component source returned unexpected HTTP status {other}: {url}"
                )));
            }
        }
    }
    finalize_download(&partial, destination, expected)
}

/// Test-only seam exposing [`download_from_url`] outside this module,
/// `#[cfg(test)]`-gated so it does not exist at all in a release binary (no
/// production behavior change; nothing production code calls this). Exists
/// for exactly the reason [`download_from_url`]'s own doc comment already
/// gives: so a plain-HTTP localhost fixture server can drive the real
/// transfer/resume/verify mechanics without weakening
/// [`download_component`]'s HTTPS-only posture. `main.rs`'s acquisition
/// driver tests use this to prove its background-thread download path
/// against a real localhost transfer (never live internet), the same way
/// this module's own tests already do from inside this file.
#[cfg(test)]
pub(crate) fn download_from_url_for_tests(
    url: &str,
    destination: &Path,
    expected: &ExpectedArtifact,
    progress: &dyn ProgressObserver,
) -> Result<PathBuf, AcquisitionError> {
    download_from_url(url, destination, expected, progress)
}

/// Public entry point: resolves `source` to a concrete URL, enforces
/// unambiguous HTTPS, then streams the download. See [`download_from_url`]
/// for the actual transfer/resume/verify logic.
pub fn download_component(
    source: &ComponentSource,
    destination: &Path,
    expected: &ExpectedArtifact,
    progress: &dyn ProgressObserver,
) -> Result<PathBuf, AcquisitionError> {
    let url = source.resolve_url()?;
    validate_https_url(&url)?;
    download_from_url(&url, destination, expected, progress)
}

// ---------------------------------------------------------------------------
// Signed-pack acquisition: reuse, not a second verifier
// ---------------------------------------------------------------------------

/// Acquire a signed `.ccpack` component pack from `source` (today, always
/// [`ComponentSource::GitHubReleaseAsset`]) directly into `destination`,
/// then hand off to the EXISTING signed-manifest verification chain --
/// `native_packs::verify_pack` -- exactly as `native_pack_staging::
/// classify_dest_pack_state` / `commit_pack_file` already do for an
/// offline-staged or channel-index-acquired pack. No new hash-pinning
/// scheme is introduced for packs here: trust is established by the pack's
/// own ed25519 manifest signature (`native_packs::embedded_pack_trust`), not
/// by an externally pinned outer-file hash the way
/// [`ExpectedArtifact::Pinned`] works for the HuggingFace caption weight
/// files. A verification failure removes the downloaded file and reports it
/// as [`AcquisitionError::HashMismatch`] (the closest of the five typed
/// variants to "these bytes are not what was promised"), carrying the
/// existing verifier's own rejection reason as `actual`.
pub fn acquire_and_verify_pack(
    source: &ComponentSource,
    destination: &Path,
    trust: &PackTrust,
    expected_component: &str,
    expected_product_version: &str,
    expected_compatible_core: &str,
    progress: &dyn ProgressObserver,
) -> Result<VerifiedPack, AcquisitionError> {
    download_component(source, destination, &ExpectedArtifact::Unverified, progress)?;
    match native_packs::verify_pack(
        destination,
        trust,
        Some(expected_component),
        Some(expected_product_version),
        Some(expected_compatible_core),
    ) {
        Ok(verified) => Ok(verified),
        Err(reason) => {
            let _ = fs::remove_file(destination);
            Err(AcquisitionError::HashMismatch {
                path: destination.to_path_buf(),
                expected: "a validly signed component pack manifest".to_string(),
                actual: reason,
            })
        }
    }
}

// ---------------------------------------------------------------------------
// Caption floor-tier (HuggingFace) convenience: single source of truth
// ---------------------------------------------------------------------------

/// The `(source, expected, file_name)` triple for every pinned file in the
/// caption floor tier (`medium`), read directly from the SAME Rust mirror
/// `native_packs.rs` already carries
/// (`CAPTION_FLOOR_TIER_MODEL_REPOSITORY`/`_REVISION`/`_FILES`) -- never
/// re-transcribed here. That mirror is itself cross-checked against
/// `civiccast.native.caption_tiers.CAPTION_TIER_REGISTRY[FLOOR_TIER_ID]` by
/// `test_native_installer_identity.py::
/// test_caption_floor_tier_binding_matches_across_python_and_rust`.
pub fn caption_floor_tier_file_sources(
) -> Vec<(ComponentSource, ExpectedArtifact, &'static str)> {
    native_packs::CAPTION_FLOOR_TIER_MODEL_FILES
        .iter()
        .map(|(name, bytes, sha256)| {
            (
                ComponentSource::HuggingFaceFile {
                    repo: native_packs::CAPTION_FLOOR_TIER_MODEL_REPOSITORY.to_string(),
                    revision: native_packs::CAPTION_FLOOR_TIER_MODEL_REVISION.to_string(),
                    path: (*name).to_string(),
                },
                ExpectedArtifact::Pinned {
                    bytes: *bytes,
                    sha256: (*sha256).to_string(),
                },
                *name,
            )
        })
        .collect()
}

/// Where one caption floor-tier file belongs under a component's staged
/// tree, matching the `model_root`-relative payload convention
/// `native_packs.rs`'s `CaptionTierSpec`/`verify_caption_pack_tiers` already
/// use for the SIGNED caption pack's internal layout
/// (`models/faster-whisper-medium/<file>`). Kept as a plain path-join helper
/// here so the caller decides the staged tree's root; this module makes no
/// assumption about where that root lives on disk.
pub fn caption_floor_tier_destination(components_root: &Path, file_name: &str) -> PathBuf {
    components_root
        .join(native_packs::CAPTION_FLOOR_TIER_MODEL_ROOT)
        .join(file_name)
}

/// The `(source, expected, file_name)` triple for every pinned file in the
/// LARGE caption tier (`large-v3`), read directly from the SAME Rust mirror
/// `native_packs.rs` has always carried for the signed caption pack's
/// verification (`CAPTION_MODEL_FILES` + the repository/revision identity
/// constants) -- never re-transcribed here. Enrolled for direct HuggingFace
/// acquisition 2026-08-15 by owner ruling: a hardware-capable station gets
/// the better caption engine. Same trust model as the floor tier: per-file
/// pinned bytes + sha256 (`ExpectedArtifact::Pinned`).
pub fn caption_large_tier_file_sources(
) -> Vec<(ComponentSource, ExpectedArtifact, &'static str)> {
    native_packs::CAPTION_MODEL_FILES
        .iter()
        .map(|(name, bytes, sha256)| {
            (
                ComponentSource::HuggingFaceFile {
                    repo: native_packs::CAPTION_LARGE_TIER_MODEL_REPOSITORY.to_string(),
                    revision: native_packs::CAPTION_LARGE_TIER_MODEL_REVISION.to_string(),
                    path: (*name).to_string(),
                },
                ExpectedArtifact::Pinned {
                    bytes: *bytes,
                    sha256: (*sha256).to_string(),
                },
                *name,
            )
        })
        .collect()
}

/// Where one large-tier file belongs under a component's staged tree,
/// matching the `model_root`-relative layout the signed caption pack and
/// `station_runtime.py`'s large-v3 search root
/// (`components/captions-large-v3/models/faster-whisper-large-v3`) already
/// use. The caller supplies the `components/captions-large-v3` root; this
/// joins the tier's own `models/<dir>` suffix, mirroring
/// [`caption_floor_tier_destination`].
pub fn caption_large_tier_destination(components_root: &Path, file_name: &str) -> PathBuf {
    components_root
        .join(native_packs::CAPTION_MODEL_ROOT)
        .join(file_name)
}

// ---------------------------------------------------------------------------
// Integration seam
// ---------------------------------------------------------------------------

/// Offline-first acquisition for ONE already-pinned artifact at a
/// destination path the staging layer understands: if a byte-for-byte
/// verified copy already exists there, it is returned untouched (no
/// re-download -- the same idempotency posture
/// `native_pack_staging::decide_offline_staging_action`'s `AlreadySatisfied`
/// branch already has for packs); otherwise it is acquired via this engine
/// into that SAME path. This function never extracts or installs anything;
/// the caller hands the returned path to the EXISTING extraction/verify path
/// for that component kind.
///
/// This offline-first check only applies to [`ExpectedArtifact::Pinned`]
/// artifacts (the HuggingFace caption weight files), because that is the
/// only case where this module has a hash to check a pre-existing file
/// against on its own. A signed pack's offline-first check is ALREADY
/// handled by the existing `native_pack_staging::discover_offline_pack_sources`
/// / `classify_dest_pack_state` (which verify via the signed manifest, not a
/// pinned outer hash) -- callers acquiring a pack should run that existing
/// decision first and only reach for [`acquire_and_verify_pack`] on the
/// `NeedsOnlineOrAbort` branch, i.e. exactly the online-fallback gap this
/// engine's `GitHubReleaseAsset` source exists to fill.
/// Chain H1: `already_at` names locations OTHER than `destination` where an
/// acceptable copy may already live -- today, what the ELEVATED installer
/// staged under `<install_root>\packs\...`, which the non-elevated GUI can
/// read but must never try to write. Each is verified by the SAME pinned
/// byte-count + SHA-256 check as `destination` (never trusted for merely
/// existing) and the first that passes is returned as-is, so a component the
/// installer already delivered is never re-downloaded into the writable root.
pub fn ensure_component_available(
    destination: &Path,
    already_at: &[PathBuf],
    source: &ComponentSource,
    expected: &ExpectedArtifact,
    progress: &dyn ProgressObserver,
) -> Result<PathBuf, AcquisitionError> {
    if let Some(found) = locally_verified_pinned_path(destination, already_at, expected) {
        return Ok(found);
    }
    download_component(source, destination, expected, progress)
}

/// The offline-first candidate loop [`ensure_component_available`] runs
/// before ever touching the network, pulled out so a caller can run the SAME
/// no-network check on its own -- e.g. a pre-pass that wants to know which
/// components are already fully satisfied on disk before the sequential
/// download driver starts (`main.rs`'s `prescan_locally_satisfied_components`,
/// added after a field failure where an unrelated EARLIER catalog component
/// stuck on a bad connection left an already-satisfied LATER one, like
/// `local_ai_model`, showing "Waiting" the whole time it was stuck: the
/// component was never actually missing, the sequential driver simply had
/// not reached it yet). Never a second, weaker check -- this IS the check
/// [`ensure_component_available`] uses, just callable before the download
/// fallback it guards.
pub fn locally_verified_pinned_path(
    destination: &Path,
    already_at: &[PathBuf],
    expected: &ExpectedArtifact,
) -> Option<PathBuf> {
    if let ExpectedArtifact::Pinned { bytes, sha256 } = expected {
        for candidate in std::iter::once(destination).chain(already_at.iter().map(Path::new)) {
            if candidate.is_file()
                && partial_len(candidate).ok() == Some(*bytes)
                && hash_file(candidate).ok().as_deref() == Some(sha256.as_str())
            {
                return Some(candidate.to_path_buf());
            }
        }
    }
    None
}

#[cfg(test)]
mod tests {
    use super::*;
    use sha2::{Digest, Sha256};
    use std::collections::BTreeMap;
    use std::io::{BufRead, BufReader};
    use std::net::{SocketAddr, TcpListener, TcpStream};
    use std::sync::{Arc, Mutex};
    use std::thread::{self, JoinHandle};

    // -----------------------------------------------------------------
    // Tiny localhost HTTP/1.1 fixture server: no live internet, no new
    // dev-dependency (std::net::TcpListener only, per the task's own
    // instruction to match what the crate already has).
    // -----------------------------------------------------------------

    #[derive(Clone)]
    enum FixtureResponse {
        /// A complete, immediate response.
        Status(u16, Vec<(String, String)>, Vec<u8>),
        /// Announce `announced_len` via Content-Length but only ever write
        /// `body` bytes (`body.len() < announced_len`), then drop the
        /// connection -- simulates a genuinely interrupted transfer (the
        /// client must observe a read error, not a silently-short success).
        Truncated { announced_len: u64, body: Vec<u8> },
        /// A 200 response whose body is written in several separate
        /// `write`+`flush` calls with a short sleep between each, so a
        /// reader pumping a bounded buffer observes multiple distinct
        /// reads instead of the whole body arriving in one syscall.
        SlowChunks { chunks: Vec<Vec<u8>> },
    }

    fn read_request_head(stream: &mut TcpStream) -> (String, BTreeMap<String, String>) {
        let mut reader = BufReader::new(stream.try_clone().expect("clone fixture stream"));
        let mut request_line = String::new();
        reader
            .read_line(&mut request_line)
            .expect("read fixture request line");
        let mut headers = BTreeMap::new();
        loop {
            let mut line = String::new();
            reader
                .read_line(&mut line)
                .expect("read fixture header line");
            let trimmed = line.trim_end_matches(['\r', '\n']);
            if trimmed.is_empty() {
                break;
            }
            if let Some((name, value)) = trimmed.split_once(':') {
                headers.insert(
                    name.trim().to_ascii_lowercase(),
                    value.trim().to_string(),
                );
            }
        }
        (
            request_line.trim_end_matches(['\r', '\n']).to_string(),
            headers,
        )
    }

    fn write_status_and_headers(stream: &mut TcpStream, status: u16, headers: &[(String, String)]) {
        let reason = match status {
            200 => "OK",
            206 => "Partial Content",
            404 => "Not Found",
            _ => "Status",
        };
        let mut rendered = format!("HTTP/1.1 {status} {reason}\r\n");
        for (name, value) in headers {
            rendered.push_str(&format!("{name}: {value}\r\n"));
        }
        rendered.push_str("Connection: close\r\n\r\n");
        stream
            .write_all(rendered.as_bytes())
            .expect("write fixture response head");
    }

    /// Accepts exactly `responses.len()` sequential connections (each
    /// request gets exactly one reply, in order), on a background thread.
    fn serve_sequence(responses: Vec<FixtureResponse>) -> (SocketAddr, JoinHandle<()>) {
        let listener = TcpListener::bind("127.0.0.1:0").expect("bind fixture server");
        let addr = listener.local_addr().expect("read fixture server addr");
        let handle = thread::spawn(move || {
            for response in responses {
                let (mut stream, _) = listener.accept().expect("accept fixture connection");
                let (_request_line, _headers) = read_request_head(&mut stream);
                match response {
                    FixtureResponse::Status(status, extra_headers, body) => {
                        let mut headers = extra_headers;
                        headers.push(("Content-Length".to_string(), body.len().to_string()));
                        write_status_and_headers(&mut stream, status, &headers);
                        let _ = stream.write_all(&body);
                    }
                    FixtureResponse::Truncated {
                        announced_len,
                        body,
                    } => {
                        let headers = vec![("Content-Length".to_string(), announced_len.to_string())];
                        write_status_and_headers(&mut stream, 200, &headers);
                        let _ = stream.write_all(&body);
                        // Deliberately drop `stream` here without sending the
                        // remaining announced bytes.
                    }
                    FixtureResponse::SlowChunks { chunks } => {
                        let total: usize = chunks.iter().map(Vec::len).sum();
                        let headers = vec![("Content-Length".to_string(), total.to_string())];
                        write_status_and_headers(&mut stream, 200, &headers);
                        for chunk in &chunks {
                            if stream.write_all(chunk).is_err() {
                                break;
                            }
                            let _ = stream.flush();
                            thread::sleep(Duration::from_millis(5));
                        }
                    }
                }
            }
        });
        (addr, handle)
    }

    fn sha256_hex(bytes: &[u8]) -> String {
        let mut digest = Sha256::new();
        digest.update(bytes);
        format!("{:x}", digest.finalize())
    }

    fn scratch_dir(name: &str) -> PathBuf {
        let root = std::env::temp_dir().join(format!(
            "civiccast-component-acquisition-{name}-{}",
            std::process::id()
        ));
        let _ = fs::remove_dir_all(&root);
        fs::create_dir_all(&root).expect("create scratch dir");
        root
    }

    // -----------------------------------------------------------------
    // resolve_url / validate_https_url
    // -----------------------------------------------------------------

    #[test]
    fn github_release_asset_resolves_base_url_and_asset_name() {
        let source = ComponentSource::GitHubReleaseAsset {
            base_url: "https://github.com/civiccast-native/binaries/releases/download/v1"
                .to_string(),
            asset_name: "native-server-binaries.ccpack".to_string(),
        };
        assert_eq!(
            source.resolve_url().expect("resolve"),
            "https://github.com/civiccast-native/binaries/releases/download/v1/native-server-binaries.ccpack"
        );
    }

    #[test]
    fn huggingface_file_resolves_to_the_pinned_resolve_url_shape() {
        let source = ComponentSource::HuggingFaceFile {
            repo: "Systran/faster-whisper-medium".to_string(),
            revision: "08e178d48790749d25932bbc082711ddcfdfbc4f".to_string(),
            path: "model.bin".to_string(),
        };
        assert_eq!(
            source.resolve_url().expect("resolve"),
            "https://huggingface.co/Systran/faster-whisper-medium/resolve/08e178d48790749d25932bbc082711ddcfdfbc4f/model.bin"
        );
    }

    #[test]
    fn ollama_manifest_resolves_to_the_registry_v2_manifest_url_shape() {
        let source = ComponentSource::OllamaManifest {
            registry_base: "https://registry.ollama.ai".to_string(),
            repository: "gemma4".to_string(),
            tag: "12b".to_string(),
        };
        assert_eq!(
            source.resolve_url().expect("resolve"),
            "https://registry.ollama.ai/v2/library/gemma4/manifests/12b"
        );
    }

    #[test]
    fn ollama_blob_resolves_to_the_registry_v2_blob_url_shape_with_a_colon_before_the_digest() {
        let source = ComponentSource::OllamaBlob {
            registry_base: "https://registry.ollama.ai".to_string(),
            repository: "gemma4".to_string(),
            digest: "1278394b693672ac2799eadc9a83fd98259a6a88a40acfb1dcaa6c6fc895a606".to_string(),
        };
        assert_eq!(
            source.resolve_url().expect("resolve"),
            "https://registry.ollama.ai/v2/library/gemma4/blobs/sha256:1278394b693672ac2799eadc9a83fd98259a6a88a40acfb1dcaa6c6fc895a606"
        );
    }

    #[test]
    fn ollama_sources_reject_empty_fields_before_any_network_access() {
        let missing_repository = ComponentSource::OllamaManifest {
            registry_base: "https://registry.ollama.ai".to_string(),
            repository: String::new(),
            tag: "12b".to_string(),
        };
        assert!(missing_repository.resolve_url().is_err());
        let missing_digest = ComponentSource::OllamaBlob {
            registry_base: "https://registry.ollama.ai".to_string(),
            repository: "gemma4".to_string(),
            digest: String::new(),
        };
        assert!(missing_digest.resolve_url().is_err());
    }

    #[test]
    fn download_component_rejects_plain_http() {
        let root = scratch_dir("https-only");
        let source = ComponentSource::GitHubReleaseAsset {
            base_url: "http://example.invalid/download".to_string(),
            asset_name: "asset.ccpack".to_string(),
        };
        let expected = ExpectedArtifact::Pinned {
            bytes: 1,
            sha256: sha256_hex(b"a"),
        };
        let error = download_component(
            &source,
            &root.join("asset.ccpack"),
            &expected,
            &NoopProgress,
        )
        .expect_err("plain HTTP must be refused before any network access");
        match error {
            AcquisitionError::NetworkFailed(reason) => {
                assert!(reason.to_lowercase().contains("https"));
            }
            other => panic!("expected NetworkFailed, got {other:?}"),
        }
        let _ = fs::remove_dir_all(&root);
    }

    // -----------------------------------------------------------------
    // full download + hash pass
    // -----------------------------------------------------------------

    #[test]
    fn full_download_and_hash_pass_lands_the_verified_artifact() {
        let root = scratch_dir("full-ok");
        let body = b"hello component acquisition engine, this is the pretend artifact bytes"
            .to_vec();
        let expected = ExpectedArtifact::Pinned {
            bytes: body.len() as u64,
            sha256: sha256_hex(&body),
        };
        let (addr, handle) = serve_sequence(vec![FixtureResponse::Status(200, vec![], body.clone())]);
        let destination = root.join("artifact.bin");
        let url = format!("http://{addr}/artifact.bin");

        let result = download_from_url(&url, &destination, &expected, &NoopProgress);
        handle.join().expect("fixture server thread");

        assert_eq!(result.expect("download succeeds"), destination);
        assert_eq!(fs::read(&destination).expect("read artifact"), body);
        assert!(!partial_path_for(&destination).exists());
        let _ = fs::remove_dir_all(&root);
    }

    // -----------------------------------------------------------------
    // corrupted body -> HashMismatch + artifact deleted
    // -----------------------------------------------------------------

    #[test]
    fn corrupted_body_is_rejected_as_hash_mismatch_and_the_artifact_is_deleted() {
        let root = scratch_dir("bad-hash");
        let real_body = b"the real pinned bytes that the server should have sent".to_vec();
        let mut corrupted = real_body.clone();
        let last = corrupted.len() - 1;
        corrupted[last] ^= 0xFF;
        let expected = ExpectedArtifact::Pinned {
            bytes: real_body.len() as u64,
            sha256: sha256_hex(&real_body),
        };
        let (addr, handle) =
            serve_sequence(vec![FixtureResponse::Status(200, vec![], corrupted)]);
        let destination = root.join("artifact.bin");
        let url = format!("http://{addr}/artifact.bin");

        let error = download_from_url(&url, &destination, &expected, &NoopProgress)
            .expect_err("a corrupted body must fail hash verification");
        handle.join().expect("fixture server thread");

        match error {
            AcquisitionError::HashMismatch { .. } => {}
            other => panic!("expected HashMismatch, got {other:?}"),
        }
        assert!(!destination.exists(), "a hash-mismatched artifact must not be installed");
        assert!(
            !partial_path_for(&destination).exists(),
            "a hash-mismatched partial must be deleted, not left on disk"
        );
        let _ = fs::remove_dir_all(&root);
    }

    // -----------------------------------------------------------------
    // interrupted download -> resume from .partial completes, hash passes
    // -----------------------------------------------------------------

    #[test]
    fn interrupted_download_resumes_from_partial_and_completes_with_a_passing_hash() {
        let root = scratch_dir("resume");
        let body: Vec<u8> = (0..300_000u32).map(|value| (value % 251) as u8).collect();
        let expected = ExpectedArtifact::Pinned {
            bytes: body.len() as u64,
            sha256: sha256_hex(&body),
        };
        let split = body.len() / 3;
        let (first_part, second_part) = body.split_at(split);
        let destination = root.join("artifact.bin");

        let (addr, handle) = serve_sequence(vec![FixtureResponse::Truncated {
            announced_len: body.len() as u64,
            body: first_part.to_vec(),
        }]);
        let url = format!("http://{addr}/artifact.bin");
        let first_attempt = download_from_url(&url, &destination, &expected, &NoopProgress);
        handle.join().expect("first fixture server thread");

        assert!(
            first_attempt.is_err(),
            "a truncated transfer must not be accepted as a complete download"
        );
        assert!(!destination.exists());
        let partial = partial_path_for(&destination);
        assert!(
            partial.is_file(),
            "bytes received before the interruption must remain on disk for resume"
        );

        let (addr2, handle2) = serve_sequence(vec![FixtureResponse::Status(
            206,
            vec![(
                "Content-Range".to_string(),
                format!("bytes {split}-{}/{}", body.len() - 1, body.len()),
            )],
            second_part.to_vec(),
        )]);
        let url2 = format!("http://{addr2}/artifact.bin");
        let result = download_from_url(&url2, &destination, &expected, &NoopProgress);
        handle2.join().expect("second fixture server thread");

        assert_eq!(result.expect("resumed download completes"), destination);
        assert_eq!(fs::read(&destination).expect("read artifact"), body);
        assert!(!partial.exists());
        let _ = fs::remove_dir_all(&root);
    }

    // -----------------------------------------------------------------
    // server ignoring Range -> clean restart
    // -----------------------------------------------------------------

    #[test]
    fn server_ignoring_range_restarts_the_download_cleanly() {
        let root = scratch_dir("range-ignored");
        let body = b"the full body the server always sends regardless of any Range header"
            .to_vec();
        let expected = ExpectedArtifact::Pinned {
            bytes: body.len() as u64,
            sha256: sha256_hex(&body),
        };
        let destination = root.join("artifact.bin");
        fs::write(
            partial_path_for(&destination),
            b"stale partial bytes from a previous, unrelated attempt",
        )
        .expect("seed a pre-existing partial file");

        let (addr, handle) = serve_sequence(vec![FixtureResponse::Status(200, vec![], body.clone())]);
        let url = format!("http://{addr}/artifact.bin");
        let result = download_from_url(&url, &destination, &expected, &NoopProgress);
        handle.join().expect("fixture server thread");

        assert_eq!(result.expect("clean restart succeeds"), destination);
        assert_eq!(fs::read(&destination).expect("read artifact"), body);
        let _ = fs::remove_dir_all(&root);
    }

    // -----------------------------------------------------------------
    // 404 -> SourceNotFound
    // -----------------------------------------------------------------

    #[test]
    fn missing_source_returns_a_typed_source_not_found_error() {
        let root = scratch_dir("404");
        let expected = ExpectedArtifact::Pinned {
            bytes: 5,
            sha256: sha256_hex(b"abcde"),
        };
        let destination = root.join("artifact.bin");
        let (addr, handle) = serve_sequence(vec![FixtureResponse::Status(404, vec![], vec![])]);
        let url = format!("http://{addr}/missing.bin");

        let error = download_from_url(&url, &destination, &expected, &NoopProgress)
            .expect_err("a 404 must be a typed SourceNotFound error");
        handle.join().expect("fixture server thread");

        match error {
            AcquisitionError::SourceNotFound(location) => assert_eq!(location, url),
            other => panic!("expected SourceNotFound, got {other:?}"),
        }
        assert!(!destination.exists());
        let _ = fs::remove_dir_all(&root);
    }

    // -----------------------------------------------------------------
    // progress callback: monotonically nondecreasing, ends at total
    // -----------------------------------------------------------------

    #[test]
    fn progress_callback_is_monotonically_nondecreasing_and_ends_at_total() {
        let root = scratch_dir("progress");
        let chunks: Vec<Vec<u8>> = (0..8)
            .map(|chunk_index| vec![chunk_index as u8; 64 * 1024])
            .collect();
        let body: Vec<u8> = chunks.iter().flatten().copied().collect();
        let expected = ExpectedArtifact::Pinned {
            bytes: body.len() as u64,
            sha256: sha256_hex(&body),
        };
        let destination = root.join("artifact.bin");
        let (addr, handle) = serve_sequence(vec![FixtureResponse::SlowChunks { chunks }]);
        let url = format!("http://{addr}/artifact.bin");

        let observed: Arc<Mutex<Vec<u64>>> = Arc::new(Mutex::new(Vec::new()));
        let observed_for_closure = Arc::clone(&observed);
        let observer = move |progress: DownloadProgress| {
            observed_for_closure
                .lock()
                .expect("lock progress log")
                .push(progress.bytes_done);
        };

        let result = download_from_url(&url, &destination, &expected, &observer);
        handle.join().expect("fixture server thread");
        result.expect("download succeeds");

        let recorded = observed.lock().expect("read progress log").clone();
        assert!(
            recorded.len() >= 3,
            "expected several distinct progress callbacks, got {recorded:?}"
        );
        assert!(
            recorded.windows(2).all(|pair| pair[0] <= pair[1]),
            "bytes_done must never decrease across callbacks: {recorded:?}"
        );
        assert_eq!(
            *recorded.last().expect("at least one callback"),
            body.len() as u64,
            "the final callback must report the complete byte count"
        );
        let _ = fs::remove_dir_all(&root);
    }

    // -----------------------------------------------------------------
    // ensure_component_available: offline-first idempotency
    // -----------------------------------------------------------------

    #[test]
    fn ensure_component_available_accepts_an_already_verified_local_file_without_a_network_call() {
        let root = scratch_dir("ensure-available-offline");
        let body = b"already staged, already correct bytes".to_vec();
        let destination = root.join("artifact.bin");
        fs::write(&destination, &body).expect("pre-stage the artifact");
        let expected = ExpectedArtifact::Pinned {
            bytes: body.len() as u64,
            sha256: sha256_hex(&body),
        };
        // A source pointing at a server that was never started -- if this
        // were reached, the connection would fail.
        let source = ComponentSource::HuggingFaceFile {
            repo: "unused/unused".to_string(),
            revision: "0".repeat(40),
            path: "unused.bin".to_string(),
        };

        let result = ensure_component_available(&destination, &[], &source, &expected, &NoopProgress);
        assert_eq!(result.expect("already-staged file is accepted"), destination);
        assert_eq!(fs::read(&destination).expect("unchanged"), body);
        let _ = fs::remove_dir_all(&root);
    }

    #[test]
    fn ensure_component_available_falls_through_to_the_download_engine_when_nothing_verifies_locally(
    ) {
        // No destination file exists at all, so the offline-first
        // short-circuit must NOT fire -- proving this reaches
        // `download_component` (not merely returning early) without needing
        // live internet: an empty `base_url`/`asset_name` fails inside
        // `resolve_url` before any socket is opened, with a distinct,
        // recognizable error.
        let root = scratch_dir("ensure-available-falls-through");
        let destination = root.join("artifact.bin");
        let expected = ExpectedArtifact::Pinned {
            bytes: 5,
            sha256: sha256_hex(b"abcde"),
        };
        let source = ComponentSource::GitHubReleaseAsset {
            base_url: String::new(),
            asset_name: String::new(),
        };

        let error = ensure_component_available(&destination, &[], &source, &expected, &NoopProgress)
            .expect_err("no local copy verifies, so the download engine must be reached");
        match error {
            AcquisitionError::NetworkFailed(reason) => {
                assert!(reason.contains("base URL or asset name"));
            }
            other => panic!("expected NetworkFailed from resolve_url, got {other:?}"),
        }
        assert!(!destination.exists());
        let _ = fs::remove_dir_all(&root);
    }

    // -----------------------------------------------------------------
    // caption floor-tier convenience: sourced from the single Rust mirror
    // -----------------------------------------------------------------

    #[test]
    fn caption_floor_tier_file_sources_match_the_pinned_rust_mirror_exactly() {
        let sources = caption_floor_tier_file_sources();
        assert_eq!(sources.len(), native_packs::CAPTION_FLOOR_TIER_MODEL_FILES.len());
        for ((source, expected, file_name), (pinned_name, pinned_bytes, pinned_sha256)) in
            sources.iter().zip(native_packs::CAPTION_FLOOR_TIER_MODEL_FILES.iter())
        {
            assert_eq!(file_name, pinned_name);
            match source {
                ComponentSource::HuggingFaceFile {
                    repo,
                    revision,
                    path,
                } => {
                    assert_eq!(repo, native_packs::CAPTION_FLOOR_TIER_MODEL_REPOSITORY);
                    assert_eq!(revision, native_packs::CAPTION_FLOOR_TIER_MODEL_REVISION);
                    assert_eq!(path, pinned_name);
                }
                other => panic!("expected HuggingFaceFile, got {other:?}"),
            }
            match expected {
                ExpectedArtifact::Pinned { bytes, sha256 } => {
                    assert_eq!(bytes, pinned_bytes);
                    assert_eq!(sha256, pinned_sha256);
                }
                ExpectedArtifact::Unverified => panic!("caption floor-tier files must be pinned"),
            }
        }
    }

    #[test]
    fn caption_floor_tier_destination_joins_the_pinned_model_root() {
        let root = Path::new(r"C:\Program Files\CivicCast Native\packs\captions-floor");
        assert_eq!(
            caption_floor_tier_destination(root, "model.bin"),
            root.join("models").join("faster-whisper-medium").join("model.bin")
        );
    }

    // -----------------------------------------------------------------
    // task #56: Ollama registry v2 direct-pull, over the localhost fixture
    // server (never live internet) -- same `download_from_url_for_tests`
    // seam every other end-to-end test in this module already uses to prove
    // real transport/hash mechanics without weakening
    // `download_component`'s HTTPS-only posture. `ComponentSource::
    // OllamaManifest`/`OllamaBlob` are driven through the exact same
    // `download_from_url`/`ensure_component_available` engine as the
    // HuggingFace caption files -- no new orchestration code exists to test
    // separately.
    // -----------------------------------------------------------------

    #[test]
    fn ollama_manifest_and_blob_full_pull_verifies_hashes_and_aggregates_progress_across_both_fetches(
    ) {
        let root = scratch_dir("ollama-full-pull");
        let manifest_body =
            br#"{"config":{"digest":"sha256:aaaa"},"layers":[{"digest":"sha256:bbbb"}]}"#.to_vec();
        let blob_body: Vec<u8> = (0..50_000u32).map(|value| (value % 251) as u8).collect();

        let (addr, handle) = serve_sequence(vec![
            FixtureResponse::Status(200, vec![], manifest_body.clone()),
            FixtureResponse::Status(200, vec![], blob_body.clone()),
        ]);

        let manifest_source = ComponentSource::OllamaManifest {
            registry_base: format!("http://{addr}"),
            repository: "gemma4".to_string(),
            tag: "12b".to_string(),
        };
        let blob_source = ComponentSource::OllamaBlob {
            registry_base: format!("http://{addr}"),
            repository: "gemma4".to_string(),
            digest: sha256_hex(&blob_body),
        };
        assert_eq!(
            manifest_source.resolve_url().expect("resolve manifest url"),
            format!("http://{addr}/v2/library/gemma4/manifests/12b")
        );

        let manifest_expected = ExpectedArtifact::Pinned {
            bytes: manifest_body.len() as u64,
            sha256: sha256_hex(&manifest_body),
        };
        let blob_expected = ExpectedArtifact::Pinned {
            bytes: blob_body.len() as u64,
            sha256: sha256_hex(&blob_body),
        };

        // Two independent observer logs, one per fetch: each fetch's own
        // `bytes_done` sequence starts back at 0 and must be monotonic and
        // complete ON ITS OWN -- exactly what a caller aggregating several
        // items into one component-level progress row needs from each
        // underlying item (`main.rs`'s `AcquisitionStoreObserver` is that
        // caller, adding its own running `bytes_offset` on top; this module
        // never re-derives that aggregation, only proves each item's own
        // progress is clean input for it).
        let manifest_observed: Arc<Mutex<Vec<u64>>> = Arc::new(Mutex::new(Vec::new()));
        let manifest_destination = root.join("manifest.json");
        let observed_for_manifest = Arc::clone(&manifest_observed);
        let manifest_observer = move |progress: DownloadProgress| {
            observed_for_manifest.lock().expect("lock log").push(progress.bytes_done);
        };
        let manifest_url = manifest_source.resolve_url().expect("resolve manifest url");
        download_from_url_for_tests(
            &manifest_url,
            &manifest_destination,
            &manifest_expected,
            &manifest_observer,
        )
        .expect("manifest download and hash verification succeeds");

        let blob_observed: Arc<Mutex<Vec<u64>>> = Arc::new(Mutex::new(Vec::new()));
        let blob_destination = root.join("blob.bin");
        let observed_for_blob = Arc::clone(&blob_observed);
        let blob_observer = move |progress: DownloadProgress| {
            observed_for_blob.lock().expect("lock log").push(progress.bytes_done);
        };
        let blob_url = blob_source.resolve_url().expect("resolve blob url");
        download_from_url_for_tests(&blob_url, &blob_destination, &blob_expected, &blob_observer)
            .expect("blob download and digest verification succeeds");

        handle.join().expect("fixture server thread");

        assert_eq!(fs::read(&manifest_destination).expect("read manifest"), manifest_body);
        assert_eq!(fs::read(&blob_destination).expect("read blob"), blob_body);

        let manifest_recorded = manifest_observed.lock().expect("read manifest progress log").clone();
        assert!(
            manifest_recorded.windows(2).all(|pair| pair[0] <= pair[1]),
            "manifest fetch bytes_done must never decrease: {manifest_recorded:?}"
        );
        assert_eq!(
            *manifest_recorded.last().expect("at least one manifest callback"),
            manifest_body.len() as u64,
            "the manifest fetch's final callback must report its complete byte count"
        );

        let blob_recorded = blob_observed.lock().expect("read blob progress log").clone();
        assert!(
            blob_recorded.windows(2).all(|pair| pair[0] <= pair[1]),
            "blob fetch bytes_done must never decrease: {blob_recorded:?}"
        );
        assert_eq!(
            *blob_recorded.last().expect("at least one blob callback"),
            blob_body.len() as u64,
            "the blob fetch's final callback must report its complete byte count"
        );
        let _ = fs::remove_dir_all(&root);
    }

    #[test]
    fn ollama_blob_corrupted_body_is_rejected_as_hash_mismatch_and_the_blob_is_deleted() {
        let root = scratch_dir("ollama-corrupted-blob");
        let real_body: Vec<u8> = (0..10_000u32).map(|value| (value % 200) as u8).collect();
        let mut corrupted = real_body.clone();
        let last = corrupted.len() - 1;
        corrupted[last] ^= 0xFF;
        let digest = sha256_hex(&real_body);
        let expected = ExpectedArtifact::Pinned {
            bytes: real_body.len() as u64,
            sha256: digest.clone(),
        };
        let (addr, handle) = serve_sequence(vec![FixtureResponse::Status(200, vec![], corrupted)]);
        let source = ComponentSource::OllamaBlob {
            registry_base: format!("http://{addr}"),
            repository: "gemma4".to_string(),
            digest,
        };
        let destination = root.join("blobs").join("sha256-corrupted");
        let url = source.resolve_url().expect("resolve blob url");

        let error = download_from_url_for_tests(&url, &destination, &expected, &NoopProgress)
            .expect_err("a corrupted Ollama layer blob must fail digest verification");
        handle.join().expect("fixture server thread");

        match error {
            AcquisitionError::HashMismatch { .. } => {}
            other => panic!("expected HashMismatch, got {other:?}"),
        }
        assert!(!destination.exists(), "a hash-mismatched blob must not be installed");
        assert!(
            !partial_path_for(&destination).exists(),
            "a hash-mismatched partial blob must be deleted, not left on disk"
        );
        let _ = fs::remove_dir_all(&root);
    }

    #[test]
    fn ensure_component_available_skips_an_already_verified_ollama_blob_on_retry_without_a_network_call(
    ) {
        // Blobs are content-addressed: a digest-verified blob already on disk
        // (e.g. from a prior interrupted install run) must be accepted
        // untouched on retry, never re-fetched -- the SAME offline-first
        // posture `ensure_component_available` already gives the HuggingFace
        // caption files. The source below points at a server that was never
        // started; reaching it would fail the test.
        let root = scratch_dir("ollama-retry-skip");
        let body: Vec<u8> = (0..20_000u32).map(|value| (value % 233) as u8).collect();
        let destination = root.join("blobs").join("sha256-already-here");
        fs::create_dir_all(destination.parent().expect("parent")).expect("mkdir blobs dir");
        fs::write(&destination, &body).expect("pre-stage the completed blob");
        let expected = ExpectedArtifact::Pinned {
            bytes: body.len() as u64,
            sha256: sha256_hex(&body),
        };
        let source = ComponentSource::OllamaBlob {
            registry_base: "http://127.0.0.1:1".to_string(),
            repository: "gemma4".to_string(),
            digest: sha256_hex(&body),
        };

        let result = ensure_component_available(&destination, &[], &source, &expected, &NoopProgress);
        assert_eq!(
            result.expect("an already-digest-verified blob is accepted without a network call"),
            destination
        );
        assert_eq!(fs::read(&destination).expect("unchanged"), body);
        let _ = fs::remove_dir_all(&root);
    }
}

#[cfg(test)]
mod write_error_classification_tests {
    use super::*;
    use std::io::{Error, ErrorKind};

    /// Chain H2 RED. R7's `installer-state.json` recorded
    /// `{"kind":"disk_full","detail":"PermissionDenied"}` for BOTH required
    /// components on a station with 175.3 GiB free, because `map_write_error`
    /// wrapped every `io::Error` -- `PermissionDenied` included -- as
    /// `DiskFull`. The operator was told to free disk space for a problem that
    /// had nothing to do with disk space.
    #[test]
    fn permission_denied_is_its_own_outcome_and_never_disk_full() {
        let mapped = map_write_error(Error::from(ErrorKind::PermissionDenied));
        assert!(
            matches!(mapped, AcquisitionError::PermissionDenied(_)),
            "got {mapped:?}"
        );
    }

    /// The whole point of the fix: `disk_full` becomes a claim the engine can
    /// actually stand behind. Only a real storage-exhaustion OS error earns
    /// it.
    #[test]
    fn only_real_storage_exhaustion_is_reported_as_disk_full() {
        for raw in STORAGE_EXHAUSTION_OS_ERRORS {
            let mapped = map_write_error(Error::from_raw_os_error(*raw));
            assert!(
                matches!(mapped, AcquisitionError::DiskFull(_)),
                "raw os error {raw} must be disk_full, got {mapped:?}"
            );
        }
    }

    /// Falsification: sweep every write-failure shape this engine can
    /// plausibly see and assert NONE of them lands on `DiskFull`. A single
    /// catch-all reintroducing the defect fails here.
    #[test]
    fn no_other_write_failure_is_allowed_to_claim_the_drive_is_full() {
        for kind in [
            ErrorKind::PermissionDenied,
            ErrorKind::NotFound,
            ErrorKind::AlreadyExists,
            ErrorKind::InvalidInput,
            ErrorKind::BrokenPipe,
            ErrorKind::TimedOut,
            ErrorKind::Interrupted,
            ErrorKind::Unsupported,
            ErrorKind::Other,
        ] {
            let mapped = map_write_error(Error::from(kind));
            assert!(
                !matches!(mapped, AcquisitionError::DiskFull(_)),
                "{kind:?} must not be reported as disk_full, got {mapped:?}"
            );
        }
    }

    /// Anything the engine cannot distinguish is a plain local write failure,
    /// not a guess dressed up as a diagnosis.
    #[test]
    fn an_indistinguishable_local_failure_is_reported_as_a_write_failure() {
        let mapped = map_write_error(Error::from(ErrorKind::Other));
        assert!(
            matches!(mapped, AcquisitionError::WriteFailed(_)),
            "got {mapped:?}"
        );
    }

    /// The engine's own message for a permission failure must not send the
    /// operator hunting for disk space.
    #[test]
    fn the_permission_denied_message_never_mentions_disk_space() {
        let message = map_write_error(Error::from(ErrorKind::PermissionDenied)).to_string();
        let lowered = message.to_lowercase();
        assert!(!lowered.contains("disk space"), "{message}");
        assert!(!lowered.contains("free up"), "{message}");
        assert!(lowered.contains("permission"), "{message}");
    }

    /// `hash_file` re-reads an already-downloaded artifact. A failure there is
    /// a READ failure and was previously hard-coded to `DiskFull` outside
    /// `map_write_error` entirely -- a second copy of the same lie.
    #[test]
    fn a_failed_hash_reread_is_not_reported_as_disk_full() {
        let missing = std::env::temp_dir().join("civiccast-no-such-file-for-hash-reread");
        let _ = fs::remove_file(&missing);
        let error = hash_file(&missing).expect_err("a missing file cannot be hashed");
        assert!(
            !matches!(error, AcquisitionError::DiskFull(_)),
            "got {error:?}"
        );
    }
}
