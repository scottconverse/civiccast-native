// SPDX-License-Identifier: Apache-2.0
// Copyright (c) The CivicCast Authors

//! The PRODUCTION component catalog for the interactive download experience
//! (audit-lite FINDING-001, `.agent-runs/native-windows/ws5-installer/
//! evidence/audit-lite-overnight-slices-2026-07-31.md`: `main.rs`'s
//! `run_acquisition_components` was never invoked because no real catalog
//! existed to hand it -- every fresh-install GUI download screen sat on
//! "Waiting" forever). This module supplies exactly that catalog for the
//! FIVE components that have a real, resolvable source today:
//!
//! * `app_runtime` -- the signed `native-app-payload` pack
//!   (`native_pack_staging::APP_PAYLOAD_COMPONENT`).
//! * `server_binaries` -- the signed `native-server-binaries` pack
//!   ([`SERVER_BINARIES_COMPONENT`]).
//! * `media_tools` -- the signed `native-ffmpeg-runtime` pack
//!   (`native_pack_staging::FFMPEG_RUNTIME_COMPONENT`), built by
//!   `scripts/build_native_ffmpeg_pack.py`. Shaped EXACTLY like the two
//!   packs above (same [`pack_item`] helper, same `GitHubReleaseAsset`
//!   source against the same [`components_base_url`], same
//!   [`ExpectedArtifact::Unverified`] + [`AcquisitionTrust::Pack`] signed-
//!   manifest trust model) -- no new dispatch code was needed. It closes a
//!   gap the same shape as `app_runtime`'s was: the bootstrap install shipped
//!   no `ffmpeg.exe`/`ffprobe.exe` at all, while `native_activation.rs`'s
//!   `validate_staged_runtime_layout` and `main.rs`'s staged-runtime
//!   self-test both pin `dependencies/ffmpeg/bin/ffmpeg.exe` literally.
//!   **DEFINED BUT NOT ENROLLED for this beta -- see the dated section
//!   below and [`media_tools_component`]'s own doc comment.**
//! * `captions_medium` -- the caption floor-tier (`medium`) weight files,
//!   sourced from `component_acquisition::caption_floor_tier_file_sources`
//!   (the EXISTING single mirror of `native_packs::CAPTION_FLOOR_TIER_MODEL_*`
//!   -- never re-transcribed here).
//! * `local_ai_model` -- (task #56) the gemma4:12b summary/translation model,
//!   pulled directly from the Ollama registry's v2 protocol: one manifest
//!   fetch plus one item per content-addressed blob (config + every layer),
//!   sourced from [`local_ai_model_items`] via `native_packs::
//!   reviewed_ollama_model("gemma4-12b")` -- the SAME embedded reviewed lock
//!   `native_packs::validate_ollama_model_contract` already pins for the
//!   signed-pack pull protocol, never a second, hand-transcribed copy of
//!   those digests. `component_acquisition::ComponentSource::OllamaManifest`/
//!   `OllamaBlob` resolve each item's URL; every item is
//!   [`ExpectedArtifact::Pinned`] and [`AcquisitionTrust::PinnedFile`], driven
//!   through the EXISTING generic multi-item engine (`main.rs`'s
//!   `run_single_acquisition_component_with_persist`) -- no new dispatch code
//!   was needed for this component; it is shaped exactly like
//!   `captions_medium`'s multi-file item list.
//!
//! Both packs are published as public GitHub Release assets in a
//! binaries-only public repository; [`components_base_url`] resolves the
//! base URL, defaulting to the shakedown release that already carries both
//! assets today but overridable via [`COMPONENTS_BASE_URL_ENV_VAR`] for the
//! freeze re-point (a later release will publish under a different tag).
//! [`ollama_registry_base_url`] resolves `local_ai_model`'s registry base the
//! same way, overridable via [`OLLAMA_REGISTRY_BASE_URL_ENV_VAR`].
//!
//! `captions_large` IS in this catalog (enrolled 2026-08-15, owner ruling:
//! a hardware-capable station gets the better caption engine). It acquired a
//! pinned direct-download source the same way the floor tier has one: the
//! six large-v3 files' bytes + sha256 were already mirrored verbatim in
//! `native_packs::CAPTION_MODEL_FILES` for signed-pack verification, and
//! `component_acquisition::caption_large_tier_file_sources` now reads that
//! same single source of truth. It stays OPTIONAL: `required: false` in
//! `components-catalog.ts`, pre-selected only when the hardware poll says the
//! machine is large-v3 capable (the existing `hardware_inventory.rs` ladder,
//! >= 8 GB NVIDIA VRAM), and always uncheckable by the operator.
//!
//! `cuda_runtime` IS in this catalog too (enrolled 2026-08-16, same owner
//! ruling): the signed `native-cuda-runtime` pack
//! (`native_pack_staging::CUDA_RUNTIME_COMPONENT`), built by `scripts/
//! build_native_cuda_pack.py` from the pinned `nvidia-cublas-cu12`/`nvidia-
//! cudnn-cu12` PyPI wheels. Shaped EXACTLY like `app_runtime`/
//! `server_binaries` -- the same [`pack_item`] helper, the same
//! `GitHubReleaseAsset` source against [`components_base_url`], the same
//! [`ExpectedArtifact::Unverified`] + [`AcquisitionTrust::Pack`] signed-
//! manifest trust model, destined for the same `packs\` root (NOT the
//! `components\captions-large-v3` convention `captions_large` uses -- that
//! convention is specific to caption-tier model roots
//! `station_runtime.py` searches; `cuda_runtime` is a signed pack extracted
//! by `native_pack_staging::pack_extraction_destination`'s own
//! `dependencies\cuda` bridge, the same class of bridge `media_tools`'s
//! `dependencies\ffmpeg` already uses). It stays OPTIONAL on the frontend
//! (`required: false`, `deliverable: true`), pre-selected only when the
//! hardware poll says the machine is large-v3 capable -- the SAME condition
//! that pre-selects `captions_large`, since a GPU capable of the large
//! caption model is the GPU this component lets that model actually use.
//!
//! ## `media_tools` is defined but NOT enrolled in this beta's fresh-install
//! ## catalog (2026-08-01)
//!
//! The `native-ffmpeg-runtime` pack described above builds and verifies
//! cleanly, but it is not published to the releases repository at the resolved
//! release tag ([`components_base_url`]'s default) -- a fresh install that
//! tried to download it would get an HTTP 404. This unpublished-pack condition
//! is the only remaining blocker to enrolling the component in fresh-install
//! staging and acquisition.
//!
//! [`media_tools_component`] therefore stays a normal, fully-shaped,
//! unit-tested component builder -- same [`pack_item`] helper, same
//! `GitHubReleaseAsset` source, same [`AcquisitionTrust::Pack`] trust model,
//! same `dependencies\ffmpeg` staging bridge (`native_pack_staging::
//! pack_extraction_destination`) as every enrolled component -- but is
//! deliberately NOT called from [`production_catalog`]'s returned list, and
//! `"media_tools"` is deliberately absent from [`PRODUCTION_CATALOG_IDS`].
//! The interactive GUI download screen (`main.rs`'s
//! `run_production_acquisition` iterates exactly what [`production_catalog`]
//! returns) does not fetch this pack from the public release tag. The private
//! native-beta candidate instead carries it as a signed sidecar and
//! `native_pack_staging::DEFAULT_REQUIRED_COMPONENTS` requires it before the
//! supervisor starts. Public release enrollment remains a separate one-line
//! catalog change once the pack is published.
//!
//! ## `local_ai_model`'s consumption side is still a residual (like #54's
//! ## caption pack was)
//!
//! This module downloads gemma4:12b's manifest and blobs into
//! `<download_root>\packs\local-ai-model\models\...` (chain H1: the
//! per-machine writable root, see the destinations section below), in
//! Ollama's OWN on-disk layout
//! (`models\manifests\<registry>\library\<repo>\<tag>` +
//! `models\blobs\sha256-<digest>`, mirroring exactly what
//! `native_packs::validate_ollama_model_contract`'s signed-pack path already
//! encodes as internal zip paths) so that directory can be pointed to
//! directly by `OLLAMA_MODELS`.
//!
//! Chain H1 narrowed this residual but did NOT close it. The SEARCH side is
//! now coherent: `install_layout.ollama_model_store_candidates` gained
//! `acquired_local_ai_models_dir` (this exact directory) as its third,
//! lowest-preference candidate, so the supervisor's ollama child and
//! `model_download._installed_ollama_models_root` both find a store the
//! first-run GUI downloaded. What is STILL not wired is
//! `civiccast.installer.model_download.download_release_models`, which
//! shells out to `ollama pull` unconditionally rather than skipping a
//! verified manifest+blob set already present. That remains a residual,
//! reported here rather than silently assumed to already exist.
//!
//! ## Destinations: TWO roots, one relative layout (chain H1, 2026-08-01)
//!
//! Every item carries a `destination` (where a DOWNLOAD lands) and a
//! `staged_at` (where an already-delivered copy may ALREADY live). They are
//! the same relative path under two different roots, so a component the
//! installer staged and one the GUI downloaded are interchangeable to every
//! consumer, Rust or Python.
//!
//! **Why they are no longer the same folder.** This module used to anchor
//! everything at `<installer_dir>\packs\`, where `installer_dir` is
//! `main.rs`'s `acquisition_installer_directory()` -- `current_exe()`'s
//! parent. On the INSTALLED GUI that is
//! `C:\Program Files\CivicCast (Native)`, and the GUI runs NON-ELEVATED, so
//! the very first `fs::create_dir_all` of a download destination returned
//! PermissionDenied. R7's real-hardware run failed `captions_medium` and
//! `local_ai_model` at 0 bytes each, on a station with 175.3 GiB free.
//!
//! * `destination` -> `main.rs`'s `acquisition_download_root()`
//!   (`<PROGRAMDATA>\CivicCast`), which a non-elevated interactive user can
//!   write (measured: `C:\ProgramData` carries
//!   `BUILTIN\Users:(CI)(WD,AD,WEA,WA)` and it inherits down) and which the
//!   installer already creates. It is the SAME root
//!   `civiccast.native.supervisor.install_layout`'s `civiccast_data_root`
//!   and `civiccast.native.provision.__main__`'s `resolve_provision_paths`
//!   derive, so the writer and the consumers cannot diverge.
//! * `staged_at` -> `<install_root>\packs\`, unchanged. Packs the ELEVATED
//!   installer put there stay there and are still accepted without any
//!   network access (`main.rs`'s `run_pack_item` and
//!   `component_acquisition::ensure_component_available` both verify every
//!   candidate with the SAME check they apply to `destination`) -- that is
//!   the "Found locally -- verified" the R7 log already showed for
//!   `app_runtime` and `server_binaries`. Staged copies are checked LAST, so
//!   a user-writable directory can never shadow them... and are checked at
//!   all, so nothing already delivered is re-downloaded.
//!
//! Integrity does not rest on either directory's ACL: every acquired
//! artifact is verified against a pinned SHA-256 (caption weights, Ollama
//! blobs) or an ed25519 signed manifest (`.ccpack`) at acquisition time AND
//! again at consumption time (`station_runtime._validate_tier_model_root`
//! re-hashes every mandatory model file on every station start).
//!
//! **The offline side-load remedy is untouched.** `native_pack_staging.rs`
//! still tells operators to "place them in a 'packs' folder next to the
//! installer, and run setup again", and NSIS still runs
//! `--civiccast-stage-packs "$EXEDIR" --install-root "$INSTDIR"` against
//! that folder (`nsis-hooks-bootstrap.nsh`). That runs at INSTALL time,
//! before this GUI flow exists at all, so moving the download root cannot
//! affect it. Filenames still match the existing `<component>.ccpack`
//! convention `native_pack_staging::commit_pack_file` uses (component
//! identity is verified from the signed manifest, never from the filename,
//! so this is for operator legibility only).
//!
//! The caption floor-tier files land in a `captions-floor` subdirectory
//! under whichever `packs\` root applies, via the EXISTING
//! `component_acquisition::caption_floor_tier_destination` path-join helper
//! (never a second, parallel one) -- exactly the shape that function's own
//! test already exercises.

use std::path::{Path, PathBuf};

use crate::component_acquisition::{self, ComponentSource, ExpectedArtifact};
use crate::native_pack_staging;
use crate::native_packs::{self, PackTrust};

/// Overridable at deploy time for a mirror or a subsequent frozen release.
pub const COMPONENTS_BASE_URL_ENV_VAR: &str = "CIVICCAST_COMPONENTS_BASE_URL";

/// The frozen native-beta release (`scottconverse/civiccast-releases`) that
/// carries the two side-load component packs compiled against this trust root.
pub const DEFAULT_COMPONENTS_BASE_URL: &str =
    "https://github.com/scottconverse/civiccast-releases/releases/download/native-beta-1.0.0-beta.1-rc1";

/// Resolves the configured base URL for the two GitHub-release-asset packs:
/// [`COMPONENTS_BASE_URL_ENV_VAR`] when set to a non-blank value, else
/// [`DEFAULT_COMPONENTS_BASE_URL`]. Pure aside from the one env read -- no
/// filesystem or network access.
pub fn components_base_url() -> String {
    std::env::var(COMPONENTS_BASE_URL_ENV_VAR)
        .ok()
        .map(|value| value.trim().to_string())
        .filter(|value| !value.is_empty())
        .unwrap_or_else(|| DEFAULT_COMPONENTS_BASE_URL.to_string())
}

/// Matches `native_pack_staging::DEFAULT_REQUIRED_COMPONENTS[0]` exactly (a
/// drift-guard test below pins this against that slice, the same way
/// `native_pack_staging.rs` already pins `APP_PAYLOAD_COMPONENT` against the
/// Python side).
pub const SERVER_BINARIES_COMPONENT: &str = "native-server-binaries";

/// The `local_ai_model` component's reviewed-lock key (task #56): the
/// gemma4:12b summary/translation model, matching the ~7.6 GB
/// `components-catalog.ts` placeholder size for `local_ai_model` exactly.
/// `native_packs.rs`'s embedded reviewed lock also carries `gemma4-e4b` and
/// `translategemma-4b`, but only THIS entry is wired to a catalog component
/// today -- the other two remain sourced only through the signed-pack pull
/// protocol, out of this task's scope.
pub const LOCAL_AI_MODEL_LOCK_KEY: &str = "gemma4-12b";

/// Overridable at deploy time (a registry mirror, or an air-gapped proxy)
/// the same way [`COMPONENTS_BASE_URL_ENV_VAR`] overrides the GitHub release
/// packs' base URL.
pub const OLLAMA_REGISTRY_BASE_URL_ENV_VAR: &str = "CIVICCAST_OLLAMA_REGISTRY_BASE_URL";

/// The public Ollama registry -- matches the embedded reviewed lock's own
/// `registry` field (`native_packs::reviewed_ollama_model`'s `registry`;
/// pinned against this exact string by a test below so the two can never
/// silently drift apart).
pub const DEFAULT_OLLAMA_REGISTRY_BASE_URL: &str = "https://registry.ollama.ai";

/// Resolves the configured base URL for direct Ollama registry pulls:
/// [`OLLAMA_REGISTRY_BASE_URL_ENV_VAR`] when set to a non-blank value, else
/// [`DEFAULT_OLLAMA_REGISTRY_BASE_URL`]. Pure aside from the one env read --
/// no filesystem or network access. Mirrors [`components_base_url`]'s
/// override pattern exactly (task #56's own instruction: reuse the same
/// env-override shape, not a second one).
pub fn ollama_registry_base_url() -> String {
    std::env::var(OLLAMA_REGISTRY_BASE_URL_ENV_VAR)
        .ok()
        .map(|value| value.trim().to_string())
        .filter(|value| !value.is_empty())
        .unwrap_or_else(|| DEFAULT_OLLAMA_REGISTRY_BASE_URL.to_string())
}

/// One item's post-download trust model.
#[derive(Debug, Clone)]
pub enum AcquisitionTrust {
    /// A signed component pack: trust is the pack's own ed25519 manifest
    /// signature (`native_packs::verify_pack`, reached through
    /// `component_acquisition::acquire_and_verify_pack` -- never a second,
    /// parallel verifier), not an externally pinned outer-file hash.
    Pack {
        trust: PackTrust,
        expected_component: String,
        expected_product_version: String,
        expected_compatible_core: String,
    },
    /// An individually pinned file (bytes + sha256), checked directly by
    /// the download engine itself (`ExpectedArtifact::Pinned`).
    PinnedFile,
}

/// One underlying download within a catalog component. A component with
/// more than one item (`captions_medium`'s four HuggingFace files, or
/// `local_ai_model`'s manifest + config blob + layer blobs) is driven and
/// reported to the frontend as a SINGLE aggregate progress entry -- see
/// `main.rs`'s `run_single_acquisition_component`.
#[derive(Debug, Clone)]
pub struct CatalogItem {
    pub source: ComponentSource,
    pub expected: ExpectedArtifact,
    /// Where a DOWNLOAD lands. Always under the per-machine writable
    /// acquisition root (chain H1) -- never under the install directory,
    /// which the non-elevated first-run GUI cannot write.
    pub destination: PathBuf,
    /// Where an already-satisfied copy may ALREADY live, checked (with the
    /// same verification as `destination`) before any network access. Today:
    /// the copy the elevated installer staged under `<install_root>\packs\`,
    /// which the GUI may read but must never write. This is what keeps
    /// "Found locally -- verified" working for `app_runtime` and
    /// `server_binaries` after the download root moved.
    pub staged_at: Vec<PathBuf>,
    pub trust: AcquisitionTrust,
}

/// One frontend-facing component: `id` matches `components-catalog.ts`'s
/// `ComponentId` verbatim -- the id the polled
/// `acquisition.components[].id` entry must carry for
/// `useAcquisitionComponents` (`AcquisitionFlow.tsx`) to find it.
#[derive(Debug, Clone)]
pub struct CatalogComponent {
    pub id: String,
    pub items: Vec<CatalogItem>,
}

/// The `packs\` subtree, relative to whichever ROOT is being addressed. Both
/// the writable download root and the install directory lay out their
/// components identically underneath it, so a component found staged and one
/// downloaded are interchangeable to every consumer (Rust or Python).
fn packs_dir(root: &Path) -> PathBuf {
    root.join("packs")
}

/// The two roots every catalog item is derived from.
///
/// `download` is the per-machine writable acquisition root
/// (`%PROGRAMDATA%\CivicCast`); `staged` is the install directory the ELEVATED
/// installer already wrote into. Before chain H1 there was one root for both
/// jobs -- `current_exe()`'s parent -- which on the installed GUI is
/// `C:\Program Files\CivicCast (Native)`, so first-run downloads went straight
/// into a folder a non-elevated process cannot write.
#[derive(Debug, Clone, Copy)]
struct CatalogRoots<'a> {
    download: &'a Path,
    staged: &'a Path,
}

fn pack_item(
    roots: CatalogRoots<'_>,
    base_url: &str,
    trust: &PackTrust,
    component: &str,
    product_version: &str,
) -> CatalogItem {
    let asset_name = format!("{component}.ccpack");
    CatalogItem {
        source: ComponentSource::GitHubReleaseAsset {
            base_url: base_url.to_string(),
            asset_name: asset_name.clone(),
        },
        expected: ExpectedArtifact::Unverified,
        destination: packs_dir(roots.download).join(&asset_name),
        staged_at: vec![packs_dir(roots.staged).join(&asset_name)],
        trust: AcquisitionTrust::Pack {
            trust: trust.clone(),
            expected_component: component.to_string(),
            expected_product_version: product_version.to_string(),
            expected_compatible_core: product_version.to_string(),
        },
    }
}

/// The root `local_ai_model` stages under -- Ollama's OWN `OLLAMA_MODELS`
/// layout (`models/manifests/...` + `models/blobs/...`), so this directory
/// can later be pointed to directly by that env var, or imported into
/// wherever `ollama pull` would otherwise place its store (see the module
/// doc's "consumption side is still a residual" section).
fn local_ai_model_root(root: &Path) -> PathBuf {
    packs_dir(root).join("local-ai-model").join("models")
}


/// One item for a reviewed Ollama blob (config or a layer): a
/// [`ComponentSource::OllamaBlob`] item, verified against its own
/// content-addressed digest, landing at the SAME `blobs/sha256-<digest>`
/// path Ollama's own store uses (dash, not colon -- Windows-legal, and
/// exactly what `native_packs.rs`'s signed-pack path already encodes as its
/// internal zip paths for this same model).
fn ollama_blob_item(
    registry_base: &str,
    repository: &str,
    roots: CatalogRoots<'_>,
    blob: &native_packs::ReviewedOllamaBlob,
) -> CatalogItem {
    let relative = PathBuf::from("blobs").join(format!("sha256-{}", blob.sha256));
    CatalogItem {
        source: ComponentSource::OllamaBlob {
            registry_base: registry_base.to_string(),
            repository: repository.to_string(),
            digest: blob.sha256.clone(),
        },
        expected: ExpectedArtifact::Pinned {
            bytes: blob.bytes,
            sha256: blob.sha256.clone(),
        },
        destination: local_ai_model_root(roots.download).join(&relative),
        staged_at: vec![local_ai_model_root(roots.staged).join(&relative)],
        trust: AcquisitionTrust::PinnedFile,
    }
}

/// The `media_tools` component's definition (task: unblock the beta install
/// tag, 2026-08-01): kept as a standalone builder, deliberately NOT called
/// from [`production_catalog`] and deliberately NOT `#[cfg(test)]`-gated --
/// see the module doc's dated "defined but NOT enrolled" section for why
/// (unpublished asset). `#[allow(
/// dead_code)]` because a normal (non-test) build never calls this today;
/// the tests below do, so the shape stays provably correct. Re-enabling
/// `media_tools` is a one-line change: call this from [`production_catalog`]
/// the same way [`local_ai_model_items`] is called, and add `"media_tools"`
/// back to [`PRODUCTION_CATALOG_IDS`]. The private candidate's offline/NSIS
/// path already requires the signed sidecar.
#[allow(dead_code)]
fn media_tools_component(
    roots: CatalogRoots<'_>,
    base_url: &str,
    trust: &PackTrust,
    product_version: &str,
) -> CatalogComponent {
    CatalogComponent {
        id: "media_tools".to_string(),
        items: vec![pack_item(
            roots,
            base_url,
            trust,
            native_pack_staging::FFMPEG_RUNTIME_COMPONENT,
            product_version,
        )],
    }
}

/// Builds the full `local_ai_model` item list for one reviewed Ollama model
/// entry: one manifest item, then one item per blob (config first, then
/// every layer in the reviewed lock's own order). `Err` only when
/// `lock_key` is absent from the embedded reviewed lock -- see
/// `native_packs::reviewed_ollama_model`'s doc for why that is an
/// impossible-in-production, checked invariant for a key this crate
/// hardcodes itself.
pub(crate) fn local_ai_model_items(
    roots: CatalogRoots<'_>,
    lock_key: &str,
) -> Result<Vec<CatalogItem>, String> {
    let model = native_packs::reviewed_ollama_model(lock_key)?;
    let registry_base = ollama_registry_base_url();
    let manifest_relative = PathBuf::from("manifests")
        .join(&model.registry)
        .join("library")
        .join(&model.repository)
        .join(&model.tag);

    let manifest_item = CatalogItem {
        source: ComponentSource::OllamaManifest {
            registry_base: registry_base.clone(),
            repository: model.repository.clone(),
            tag: model.tag.clone(),
        },
        expected: ExpectedArtifact::Pinned {
            bytes: model.manifest_bytes,
            sha256: model.manifest_sha256.clone(),
        },
        destination: local_ai_model_root(roots.download).join(&manifest_relative),
        staged_at: vec![local_ai_model_root(roots.staged).join(&manifest_relative)],
        trust: AcquisitionTrust::PinnedFile,
    };

    let mut items = vec![manifest_item];
    items.push(ollama_blob_item(
        &registry_base,
        &model.repository,
        roots,
        &model.config,
    ));
    for layer in &model.layers {
        items.push(ollama_blob_item(&registry_base, &model.repository, roots, layer));
    }
    Ok(items)
}

/// The production catalog: every entry has a real, resolvable source and a
/// destination inside the offline side-load convention documented above.
/// Pure aside from reading [`COMPONENTS_BASE_URL_ENV_VAR`]/
/// [`OLLAMA_REGISTRY_BASE_URL_ENV_VAR`] -- no filesystem or network access
/// (the caller drives the actual transfer). Panics only on the
/// impossible-in-production condition [`local_ai_model_items`]'s doc
/// describes (an embedded reviewed lock missing the hardcoded
/// [`LOCAL_AI_MODEL_LOCK_KEY`]) -- this function's signature returns a plain
/// `Vec`, matching every other infallible entry already built above, rather
/// than pushing a `Result` onto every caller for a condition CI itself
/// checks (see the test pinning this lookup below).
pub fn production_catalog(
    installer_dir: &Path,
    download_root: &Path,
    trust: &PackTrust,
    product_version: &str,
) -> Vec<CatalogComponent> {
    let base_url = components_base_url();
    let roots = CatalogRoots {
        download: download_root,
        staged: installer_dir,
    };
    let captions_download_root = packs_dir(roots.download).join("captions-floor");
    let captions_staged_root = packs_dir(roots.staged).join("captions-floor");
    // The LARGE tier deliberately lives under `components\captions-large-v3`
    // (NOT `packs\`): that is the root `station_runtime.py`'s
    // `_TIER_MODEL_ROOT_PREFIX[LARGE_V3_TIER_ID]` has always searched, and
    // the same layout the signed station-pack import stages -- so a tier
    // delivered by either path is interchangeable to the runtime.
    let captions_large_download_root = roots.download.join("components").join("captions-large-v3");
    let captions_large_staged_root = roots.staged.join("components").join("captions-large-v3");

    vec![
        CatalogComponent {
            id: "app_runtime".to_string(),
            items: vec![pack_item(
                roots,
                &base_url,
                trust,
                native_pack_staging::APP_PAYLOAD_COMPONENT,
                product_version,
            )],
        },
        CatalogComponent {
            id: "server_binaries".to_string(),
            items: vec![pack_item(
                roots,
                &base_url,
                trust,
                SERVER_BINARIES_COMPONENT,
                product_version,
            )],
        },
        // `media_tools` is deliberately NOT included here -- see the module
        // doc's dated "defined but NOT enrolled" section and
        // `media_tools_component`'s own doc comment (unpublished asset).
        // Do not "fix" this by adding it back before the pack is published
        // at the resolved release tag.
        CatalogComponent {
            id: "captions_medium".to_string(),
            items: component_acquisition::caption_floor_tier_file_sources()
                .into_iter()
                .map(|(source, expected, file_name)| CatalogItem {
                    source,
                    destination: component_acquisition::caption_floor_tier_destination(
                        &captions_download_root,
                        file_name,
                    ),
                    staged_at: vec![component_acquisition::caption_floor_tier_destination(
                        &captions_staged_root,
                        file_name,
                    )],
                    expected,
                    trust: AcquisitionTrust::PinnedFile,
                })
                .collect(),
        },
        // Enrolled 2026-08-15 by owner ruling ("the user should get the
        // better caption model if the hardware supports it"): the large-v3
        // tier as direct pinned HuggingFace files, the exact trust model
        // `captions_medium` uses. The tier is OPTIONAL (`required: false` on
        // the frontend); whether a fresh install pre-selects it is the
        // frontend's hardware-driven decision, not this catalog's.
        CatalogComponent {
            id: "captions_large".to_string(),
            items: component_acquisition::caption_large_tier_file_sources()
                .into_iter()
                .map(|(source, expected, file_name)| CatalogItem {
                    source,
                    destination: component_acquisition::caption_large_tier_destination(
                        &captions_large_download_root,
                        file_name,
                    ),
                    staged_at: vec![component_acquisition::caption_large_tier_destination(
                        &captions_large_staged_root,
                        file_name,
                    )],
                    expected,
                    trust: AcquisitionTrust::PinnedFile,
                })
                .collect(),
        },
        // Enrolled 2026-08-16 by the same owner ruling as `captions_large`
        // above: the signed `native-cuda-runtime` pack, shaped exactly like
        // `app_runtime`/`server_binaries` (same `pack_item` helper, same
        // GitHub-release-asset source, same signed-manifest trust model),
        // destined for the SAME `packs\` root those two use -- unlike
        // `captions_large`, this is a signed pack extracted via
        // `native_pack_staging::pack_extraction_destination`'s own
        // `dependencies\cuda` bridge, not a caption-tier model root.
        CatalogComponent {
            id: "cuda_runtime".to_string(),
            items: vec![pack_item(
                roots,
                &base_url,
                trust,
                native_pack_staging::CUDA_RUNTIME_COMPONENT,
                product_version,
            )],
        },
        CatalogComponent {
            id: "local_ai_model".to_string(),
            items: local_ai_model_items(roots, LOCAL_AI_MODEL_LOCK_KEY).unwrap_or_else(
                |reason| {
                    panic!(
                        "embedded reviewed Ollama model lock is missing \
                         {LOCAL_AI_MODEL_LOCK_KEY:?}, which this crate hardcodes itself: {reason}"
                    )
                },
            ),
        },
    ]
}

/// The catalog ids `production_catalog` always produces. Used by `main.rs`
/// to report a loud, typed error for every catalog id when the embedded pack
/// trust cannot be established at all (an impossible state in a real release
/// build, but a normal one in a local `cargo run`/`cargo test` build with no
/// embedded signing key) -- rather than leaving those rows silently stuck at
/// "pending" forever, reproducing the exact defect this module exists to
/// close.
///
/// SIX entries: `"media_tools"` is still deliberately absent (2026-08-01,
/// unpublished PACK asset; see the module doc's dated "defined but NOT
/// enrolled" section -- do not re-add it before the pack is published).
/// `"captions_large"` was enrolled 2026-08-15 by owner ruling: unlike
/// `media_tools`, its artifacts are individually pinned HuggingFace files
/// (bytes + sha256, same trust model as `captions_medium`), so there is no
/// unpublished asset to wait for. It stays `required: false` on the frontend
/// -- deliverable and hardware-recommended, selected by default only on a
/// large-v3-capable machine. `"cuda_runtime"` was enrolled 2026-08-16 by the
/// SAME owner ruling ("the user should get the better caption model if the
/// hardware supports it", extended: getting there needs the GPU library the
/// caption runtime actually loads) -- unlike `media_tools`, its pack IS built
/// and published by this branch's own workflow step, so there is no
/// unpublished-asset blocker either. It also stays `required: false` --
/// deliverable, and pre-selected under the same large-v3-capable condition
/// as `captions_large`.
pub const PRODUCTION_CATALOG_IDS: [&str; 6] = [
    "app_runtime",
    "server_binaries",
    "captions_medium",
    "captions_large",
    "cuda_runtime",
    "local_ai_model",
];

#[cfg(test)]
mod tests {
    use super::*;

    fn test_trust() -> PackTrust {
        use ed25519_dalek::SigningKey;
        let signing_key = SigningKey::from_bytes(&[9_u8; 32]);
        PackTrust {
            key_id: "test-key".to_string(),
            public_key: signing_key.verifying_key(),
        }
    }

    #[test]
    fn production_catalog_ids_match_the_frontend_component_ids_and_the_pinned_constant() {
        let trust = test_trust();
        let catalog = production_catalog(
            Path::new(r"C:\installer"),
            Path::new(r"C:\installer"),
            &trust,
            "1.0.0-rc15",
        );
        let ids: Vec<&str> = catalog.iter().map(|component| component.id.as_str()).collect();
        assert_eq!(ids, PRODUCTION_CATALOG_IDS);
    }

    #[test]
    fn every_catalog_item_has_a_resolvable_source_and_a_destination_under_a_component_root() {
        // `captions_large` deliberately lives under `components\` (NOT
        // `packs\`): `components/captions-large-v3` is the one canonical
        // large-tier location `station_runtime.py` searches and the signed
        // station-pack import stages, so acquisition must land there too --
        // one location per tier, both delivery paths interchangeable.
        let trust = test_trust();
        let installer_dir = Path::new(r"C:\installer");
        let catalog = production_catalog(installer_dir, installer_dir, &trust, "1.0.0-rc15");
        for component in &catalog {
            assert!(!component.items.is_empty(), "{} has no items", component.id);
            let expected_root = if component.id == "captions_large" {
                installer_dir.join("components").join("captions-large-v3")
            } else {
                installer_dir.join("packs")
            };
            for item in &component.items {
                item.source.resolve_url().unwrap_or_else(|error| {
                    panic!("{} item source does not resolve: {error}", component.id)
                });
                assert!(
                    item.destination.starts_with(&expected_root),
                    "{} destination {} is not under its component root {}",
                    component.id,
                    item.destination.display(),
                    expected_root.display()
                );
            }
        }
    }

    #[test]
    fn the_three_enrolled_pack_components_are_unverified_at_the_download_engine_layer() {
        // Packs are ExpectedArtifact::Unverified -- trust is the signed
        // manifest (acquire_and_verify_pack), never an externally pinned
        // outer-file hash the download engine checks itself. `media_tools`
        // is covered separately below (`media_tools_component_...`) since it
        // is no longer in the production catalog -- see the module doc.
        let trust = test_trust();
        let catalog = production_catalog(
            Path::new(r"C:\installer"),
            Path::new(r"C:\installer"),
            &trust,
            "1.0.0-rc15",
        );
        for id in ["app_runtime", "server_binaries", "cuda_runtime"] {
            let component = catalog.iter().find(|c| c.id == id).expect("component present");
            assert_eq!(component.items.len(), 1);
            let item = &component.items[0];
            assert!(matches!(item.expected, ExpectedArtifact::Unverified));
            assert!(matches!(item.trust, AcquisitionTrust::Pack { .. }));
        }
    }

    #[test]
    fn pack_items_resolve_to_the_configured_base_url_and_the_pinned_component_asset_names() {
        let trust = test_trust();
        let catalog = production_catalog(
            Path::new(r"C:\installer"),
            Path::new(r"C:\installer"),
            &trust,
            "1.0.0-rc15",
        );
        let app_runtime = catalog.iter().find(|c| c.id == "app_runtime").expect("present");
        assert_eq!(
            app_runtime.items[0].source.resolve_url().expect("resolve"),
            format!(
                "{}/{}.ccpack",
                DEFAULT_COMPONENTS_BASE_URL,
                native_pack_staging::APP_PAYLOAD_COMPONENT
            )
        );
        let server_binaries = catalog
            .iter()
            .find(|c| c.id == "server_binaries")
            .expect("present");
        assert_eq!(
            server_binaries.items[0].source.resolve_url().expect("resolve"),
            format!("{DEFAULT_COMPONENTS_BASE_URL}/{SERVER_BINARIES_COMPONENT}.ccpack")
        );
        let cuda_runtime = catalog
            .iter()
            .find(|c| c.id == "cuda_runtime")
            .expect("present");
        assert_eq!(
            cuda_runtime.items[0].source.resolve_url().expect("resolve"),
            format!(
                "{}/{}.ccpack",
                DEFAULT_COMPONENTS_BASE_URL,
                native_pack_staging::CUDA_RUNTIME_COMPONENT
            )
        );
        // media_tools is no longer in the production catalog -- see
        // `media_tools_component_is_still_correctly_shaped_and_ready_to_re_enable`
        // below, which resolves its URL directly through the standalone builder.
    }

    #[test]
    fn server_binaries_component_id_matches_the_offline_staging_default_required_set() {
        assert_eq!(
            SERVER_BINARIES_COMPONENT,
            native_pack_staging::DEFAULT_REQUIRED_COMPONENTS[0]
        );
        assert!(native_pack_staging::DEFAULT_REQUIRED_COMPONENTS
            .contains(&native_pack_staging::APP_PAYLOAD_COMPONENT));
    }

    #[test]
    fn cuda_runtime_component_id_matches_the_offline_staging_default_optional_set() {
        // The catalog id and the staging-bridge component identity must be
        // the SAME string this crate downloads and the SAME string
        // native_pack_staging::stage_optional_packs stages by default --
        // never two independently-typed literals that could drift apart.
        assert_eq!(
            native_pack_staging::CUDA_RUNTIME_COMPONENT,
            native_pack_staging::DEFAULT_OPTIONAL_COMPONENTS[0]
        );
    }

    #[test]
    fn cuda_runtime_stages_onto_the_dependencies_cuda_bin_path_the_presence_gate_checks() {
        // The load-bearing reconciliation, mirrored from media_tools's own
        // ffmpeg test one directory over: the pack's payload is rooted at
        // `bin/`, and `pack_extraction_destination` maps this component to
        // `<INSTDIR>\dependencies\cuda`, so the two compose to exactly the
        // `dependencies/cuda/bin/cublas64_12.dll` path
        // `station_runtime.cuda_bin_dir`/`resolve_cuda_bin_dir` pin literally.
        let instdir = Path::new(r"C:\Program Files\CivicCast");
        let extraction = native_pack_staging::pack_extraction_destination(
            &instdir.join("packs"),
            native_pack_staging::CUDA_RUNTIME_COMPONENT,
        )
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

    #[test]
    fn media_tools_is_excluded_while_its_pack_is_unpublished() {
        // 2026-08-01: the native-ffmpeg-runtime pack is not published to the
        // releases repo for this beta. A fresh install
        // must not attempt to download this pack, nor abort demanding it.
        let trust = test_trust();
        let catalog = production_catalog(
            Path::new(r"C:\installer"),
            Path::new(r"C:\installer"),
            &trust,
            "1.0.0-rc15",
        );
        assert!(
            catalog.iter().all(|component| component.id != "media_tools"),
            "media_tools must not be in the production catalog the GUI download \
             screen drives (main.rs's run_production_acquisition iterates exactly \
             what production_catalog returns)"
        );
        assert!(!PRODUCTION_CATALOG_IDS.contains(&"media_tools"));
        assert!(native_pack_staging::DEFAULT_REQUIRED_COMPONENTS
            .contains(&native_pack_staging::FFMPEG_RUNTIME_COMPONENT));
    }

    #[test]
    fn media_tools_component_is_still_correctly_shaped_and_ready_to_re_enable() {
        // The component definition itself must stay correct even though it
        // is not enrolled -- proving `media_tools_component` (the one-line
        // re-enable point named in the module doc) is not orphaned/rotted
        // code, and giving this shape live test coverage instead of only a
        // comment (a comment cannot fail).
        let trust = test_trust();
        let component = media_tools_component(
            CatalogRoots {
                download: Path::new(r"C:\installer"),
                staged: Path::new(r"C:\installer"),
            },
            &components_base_url(),
            &trust,
            "1.0.0-rc15",
        );
        assert_eq!(component.id, "media_tools");
        assert_eq!(component.items.len(), 1);
        let item = &component.items[0];
        assert!(matches!(item.expected, ExpectedArtifact::Unverified));
        match &item.trust {
            AcquisitionTrust::Pack {
                expected_component, ..
            } => assert_eq!(
                expected_component,
                native_pack_staging::FFMPEG_RUNTIME_COMPONENT
            ),
            other => panic!("media_tools must use signed-pack trust, got {other:?}"),
        }
        assert_eq!(
            item.source.resolve_url().expect("resolve"),
            format!(
                "{}/{}.ccpack",
                DEFAULT_COMPONENTS_BASE_URL,
                native_pack_staging::FFMPEG_RUNTIME_COMPONENT
            )
        );
    }

    #[test]
    fn media_tools_stages_onto_the_dependencies_ffmpeg_bin_path_the_activation_layer_pins() {
        // The load-bearing reconciliation: the pack's payload is rooted at
        // `bin/`, and `pack_extraction_destination` maps this component to
        // `<INSTDIR>\dependencies\ffmpeg`, so the two compose to exactly the
        // `dependencies/ffmpeg/bin/ffmpeg.exe` path
        // `native_activation::validate_staged_runtime_layout` and `main.rs`'s
        // staged-runtime self-test both pin literally. Asserted here rather
        // than described in a comment, because a comment cannot fail.
        let instdir = Path::new(r"C:\Program Files\CivicCast");
        let extraction = native_pack_staging::pack_extraction_destination(
            &instdir.join("packs"),
            native_pack_staging::FFMPEG_RUNTIME_COMPONENT,
        )
        .expect("bridge resolves");
        assert_eq!(extraction, instdir.join("dependencies").join("ffmpeg"));
        assert_eq!(
            extraction.join("bin").join("ffmpeg.exe"),
            instdir
                .join("dependencies")
                .join("ffmpeg")
                .join("bin")
                .join("ffmpeg.exe")
        );
    }

    #[test]
    fn captions_medium_has_one_item_per_pinned_floor_tier_file_and_every_item_is_hash_pinned() {
        let trust = test_trust();
        let catalog = production_catalog(
            Path::new(r"C:\installer"),
            Path::new(r"C:\installer"),
            &trust,
            "1.0.0-rc15",
        );
        let captions = catalog
            .iter()
            .find(|c| c.id == "captions_medium")
            .expect("present");
        let pinned_files = component_acquisition::caption_floor_tier_file_sources();
        assert_eq!(captions.items.len(), pinned_files.len());
        for (item, (pinned_source, pinned_expected, _file_name)) in
            captions.items.iter().zip(pinned_files.iter())
        {
            assert!(matches!(item.trust, AcquisitionTrust::PinnedFile));
            assert_eq!(&item.source, pinned_source);
            match (&item.expected, pinned_expected) {
                (
                    ExpectedArtifact::Pinned { bytes, sha256 },
                    ExpectedArtifact::Pinned {
                        bytes: pinned_bytes,
                        sha256: pinned_sha256,
                    },
                ) => {
                    assert_eq!(bytes, pinned_bytes);
                    assert_eq!(sha256, pinned_sha256);
                }
                other => panic!("expected both Pinned, got {other:?}"),
            }
        }
    }

    #[test]
    fn captions_medium_destinations_match_the_existing_caption_floor_tier_destination_helper() {
        let trust = test_trust();
        let installer_dir = Path::new(r"C:\installer");
        let catalog = production_catalog(installer_dir, installer_dir, &trust, "1.0.0-rc15");
        let captions = catalog
            .iter()
            .find(|c| c.id == "captions_medium")
            .expect("present");
        let captions_root = installer_dir.join("packs").join("captions-floor");
        for (item, (_source, _expected, file_name)) in captions
            .items
            .iter()
            .zip(component_acquisition::caption_floor_tier_file_sources().iter())
        {
            assert_eq!(
                item.destination,
                component_acquisition::caption_floor_tier_destination(&captions_root, file_name)
            );
        }
    }

    #[test]
    fn components_base_url_defaults_when_the_env_override_is_unset() {
        // Deliberately does not touch the real env var (parallel test
        // threads share the process environment) -- proves the default path
        // by construction instead: DEFAULT_COMPONENTS_BASE_URL is exactly
        // what a production_catalog built with no override in effect
        // resolves to, asserted above in
        // `pack_items_resolve_to_the_configured_base_url_and_the_pinned_component_asset_names`.
        // This test only pins the constant's own shape so a future edit
        // cannot silently drop the release tag.
        assert!(DEFAULT_COMPONENTS_BASE_URL.starts_with("https://github.com/"));
        assert!(DEFAULT_COMPONENTS_BASE_URL.contains("/releases/download/"));
    }

    // -----------------------------------------------------------------
    // task #56: local_ai_model (direct Ollama registry pull)
    // -----------------------------------------------------------------

    #[test]
    fn local_ai_model_has_one_manifest_item_then_one_item_per_reviewed_blob_in_lock_order() {
        let trust = test_trust();
        let catalog = production_catalog(
            Path::new(r"C:\installer"),
            Path::new(r"C:\installer"),
            &trust,
            "1.0.0-rc15",
        );
        let component = catalog
            .iter()
            .find(|c| c.id == "local_ai_model")
            .expect("local_ai_model is in the production catalog");
        let model = native_packs::reviewed_ollama_model(LOCAL_AI_MODEL_LOCK_KEY)
            .expect("gemma4-12b is in the embedded lock");
        // manifest + config + every layer, one item apiece.
        assert_eq!(component.items.len(), 2 + model.layers.len());
        assert_eq!(component.items.len(), 6, "gemma4-12b pins exactly 4 layers");

        let manifest_item = &component.items[0];
        assert!(matches!(manifest_item.source, ComponentSource::OllamaManifest { .. }));
        match &manifest_item.expected {
            ExpectedArtifact::Pinned { bytes, sha256 } => {
                assert_eq!(*bytes, model.manifest_bytes);
                assert_eq!(sha256, &model.manifest_sha256);
            }
            ExpectedArtifact::Unverified => panic!("the manifest item must be pinned"),
        }
        assert!(matches!(manifest_item.trust, AcquisitionTrust::PinnedFile));

        let config_item = &component.items[1];
        match &config_item.expected {
            ExpectedArtifact::Pinned { bytes, sha256 } => {
                assert_eq!(*bytes, model.config.bytes);
                assert_eq!(sha256, &model.config.sha256);
            }
            ExpectedArtifact::Unverified => panic!("the config item must be pinned"),
        }

        for (item, layer) in component.items[2..].iter().zip(model.layers.iter()) {
            assert!(matches!(item.source, ComponentSource::OllamaBlob { .. }));
            match &item.expected {
                ExpectedArtifact::Pinned { bytes, sha256 } => {
                    assert_eq!(bytes, &layer.bytes);
                    assert_eq!(sha256, &layer.sha256);
                }
                ExpectedArtifact::Unverified => panic!("every layer item must be pinned"),
            }
            assert!(matches!(item.trust, AcquisitionTrust::PinnedFile));
        }
    }

    #[test]
    fn local_ai_model_items_resolve_to_the_configured_registry_and_ollamas_own_local_layout() {
        let trust = test_trust();
        let installer_dir = Path::new(r"C:\installer");
        let catalog = production_catalog(installer_dir, installer_dir, &trust, "1.0.0-rc15");
        let component = catalog.iter().find(|c| c.id == "local_ai_model").expect("present");
        let model = native_packs::reviewed_ollama_model(LOCAL_AI_MODEL_LOCK_KEY).expect("gemma4-12b");
        let root = installer_dir
            .join("packs")
            .join("local-ai-model")
            .join("models");

        let manifest_item = &component.items[0];
        assert_eq!(
            manifest_item.source.resolve_url().expect("resolve manifest url"),
            format!(
                "{DEFAULT_OLLAMA_REGISTRY_BASE_URL}/v2/library/{}/manifests/{}",
                model.repository, model.tag
            )
        );
        assert_eq!(
            manifest_item.destination,
            root.join("manifests")
                .join(&model.registry)
                .join("library")
                .join(&model.repository)
                .join(&model.tag)
        );

        let config_item = &component.items[1];
        assert_eq!(
            config_item.source.resolve_url().expect("resolve config blob url"),
            format!(
                "{DEFAULT_OLLAMA_REGISTRY_BASE_URL}/v2/library/{}/blobs/sha256:{}",
                model.repository, model.config.sha256
            )
        );
        assert_eq!(
            config_item.destination,
            root.join("blobs").join(format!("sha256-{}", model.config.sha256))
        );

        for (item, layer) in component.items[2..].iter().zip(model.layers.iter()) {
            assert_eq!(
                item.source.resolve_url().expect("resolve layer blob url"),
                format!(
                    "{DEFAULT_OLLAMA_REGISTRY_BASE_URL}/v2/library/{}/blobs/sha256:{}",
                    model.repository, layer.sha256
                )
            );
            assert_eq!(
                item.destination,
                root.join("blobs").join(format!("sha256-{}", layer.sha256))
            );
        }
    }

    #[test]
    fn ollama_registry_base_url_defaults_to_the_embedded_locks_own_registry() {
        // Deliberately does not touch the real env var (parallel test
        // threads share the process environment) -- proves the default by
        // construction against the SAME identity the embedded reviewed lock
        // carries, so the acquisition-time base URL can never silently drift
        // from what the lock was built against.
        let model = native_packs::reviewed_ollama_model(LOCAL_AI_MODEL_LOCK_KEY).expect("gemma4-12b");
        assert_eq!(
            DEFAULT_OLLAMA_REGISTRY_BASE_URL,
            format!("https://{}", model.registry)
        );
    }

    // No test mutates `OLLAMA_REGISTRY_BASE_URL_ENV_VAR` directly (parallel
    // test threads share the process environment -- see
    // `components_base_url_defaults_when_the_env_override_is_unset`'s doc
    // comment above, which this mirrors): `ollama_registry_base_url`'s
    // override branch is the identical `env::var().ok().filter(!empty)`
    // shape `components_base_url` already has, exercised by construction via
    // the default-value tests above and below, not a live env mutation.

    #[test]
    fn local_ai_model_items_reports_an_unknown_lock_key_instead_of_silently_defaulting() {
        let error = local_ai_model_items(
            CatalogRoots {
                download: Path::new(r"C:\installer"),
                staged: Path::new(r"C:\installer"),
            },
            "not-a-real-model",
        )
            .expect_err("an unknown lock key must fail loud");
        assert!(error.contains("not present in the reviewed model lock"));
    }
}

#[cfg(test)]
mod writable_destination_tests {
    use super::*;

    const INSTALLED_GUI_DIR: &str = r"C:\Program Files\CivicCast (Native)";
    const PER_MACHINE_ROOT: &str = r"C:\ProgramData\CivicCast";

    fn catalog() -> Vec<CatalogComponent> {
        use ed25519_dalek::SigningKey;
        let signing_key = SigningKey::from_bytes(&[9_u8; 32]);
        production_catalog(
            Path::new(INSTALLED_GUI_DIR),
            Path::new(PER_MACHINE_ROOT),
            &PackTrust {
                key_id: "test-key".to_string(),
                public_key: signing_key.verifying_key(),
            },
            "1.0.0-rc15",
        )
    }

    /// Chain H1 RED. The installed GUI runs non-elevated from
    /// `C:\Program Files\CivicCast (Native)\CivicCast Native.exe`, and every
    /// download destination was derived from `current_exe()`'s parent -- so
    /// first run tried to create `C:\Program Files\CivicCast (Native)\packs\...`
    /// and got PermissionDenied at 0 bytes on both required components.
    #[test]
    fn no_download_destination_is_ever_derived_under_program_files() {
        for component in catalog() {
            for item in component.items {
                assert!(
                    !item.destination.starts_with(INSTALLED_GUI_DIR),
                    "{}: destination {} is under the read-only install directory",
                    component.id,
                    item.destination.display()
                );
            }
        }
    }

    /// Every download lands under the per-machine writable root the installer
    /// already creates -- one root for the whole catalog, never a per-component
    /// invention.
    #[test]
    fn every_download_destination_lands_under_the_per_machine_writable_root() {
        for component in catalog() {
            assert!(!component.items.is_empty(), "{}", component.id);
            for item in component.items {
                assert!(
                    item.destination.starts_with(PER_MACHINE_ROOT),
                    "{}: destination {} is outside the writable acquisition root",
                    component.id,
                    item.destination.display()
                );
            }
        }
    }

    /// Reconciling the two sources: what the ELEVATED installer already staged
    /// into Program Files stays there and is still recognized without any
    /// network access ("Found locally -- verified", which the R7 log shows
    /// already worked for `app_runtime` and `server_binaries`). Moving the
    /// download destination must not lose that.
    #[test]
    fn installer_staged_copies_under_the_install_directory_are_still_recognized() {
        for component in catalog() {
            for item in &component.items {
                assert!(
                    !item.staged_at.is_empty(),
                    "{}: no installer-staged location is checked before downloading",
                    component.id
                );
                for staged in &item.staged_at {
                    assert!(
                        staged.starts_with(INSTALLED_GUI_DIR),
                        "{}: staged location {} is not under the install directory",
                        component.id,
                        staged.display()
                    );
                }
            }
        }
    }

    /// The two roots must describe the SAME relative layout, so a component
    /// found staged and a component downloaded are interchangeable to every
    /// consumer.
    #[test]
    fn the_staged_and_download_locations_share_one_relative_layout() {
        for component in catalog() {
            for item in &component.items {
                let downloaded = item
                    .destination
                    .strip_prefix(PER_MACHINE_ROOT)
                    .expect("destination is under the writable root");
                let staged = item.staged_at[0]
                    .strip_prefix(INSTALLED_GUI_DIR)
                    .expect("staged copy is under the install directory");
                assert_eq!(
                    downloaded,
                    staged,
                    "{}: staged and downloaded layouts diverge",
                    component.id
                );
            }
        }
    }
}
