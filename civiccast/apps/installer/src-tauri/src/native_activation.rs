// SPDX-License-Identifier: Apache-2.0
// Copyright (c) The CivicCast Authors

use std::collections::{BTreeMap, BTreeSet};
use std::fs::{self, OpenOptions};
use std::io::{Read, Write};
use std::path::{Path, PathBuf};
#[cfg(target_os = "windows")]
use std::thread;
#[cfg(target_os = "windows")]
use std::time::Duration;

use serde::Serialize;
use serde_json::{json, Value};
use sha2::{Digest, Sha256};

use crate::native_distribution::{self, AcquiredDistribution, AcquiredPack};
use crate::native_packs::{self, PackTrust};

// Owner decision (Scott Converse, 2026-08-07, ratified): the caption FLOOR
// tier (`captions-floor`, `medium` / `faster-whisper-medium`) is the
// mandatory baseline for native station activation; `captions-large-v3` is
// an optional quality add-on, verified when present and simply absent when
// not. There is no model downgrade or caption-disabled success path --
// captions themselves stay a legal non-negotiable, only the required model
// TIER changed. See `native_distribution.rs::REQUIRED_COMPONENTS` (same
// swap, kept in lockstep) and `station_runtime.py::_resolve_caption_tier`
// (the runtime half of this contract).
const REQUIRED_COMPONENTS: [&str; 5] = [
    "core",
    "captions-floor",
    "summary-gemma4-12b",
    "summary-gemma4-e4b",
    "translation-translategemma-4b",
];
// Verified and staged when present in a distribution, never required.
const OPTIONAL_COMPONENTS: [&str; 1] = ["captions-large-v3"];
// Where `captions-large-v3`'s signed pack lands once staged -- unchanged
// from the original five-pack convention.
const LARGE_V3_STAGED_ROOT: &str = "components/captions-large-v3";
// Where `captions-floor`'s signed pack lands once staged -- `packs/`, not
// `components/`, matching the EXACT relative location
// `station_runtime.py`'s `_TIER_MODEL_ROOT_PREFIX[FLOOR_TIER_ID]` and the
// GUI acquisition flow's `caption_floor_tier_destination` already use for
// this tier, so the runtime's existing search-root resolution finds it
// without a second, parallel on-disk convention.
const FLOOR_STAGED_ROOT: &str = "packs/captions-floor";

/// Where a signed component pack lands once extracted into a station's
/// staging tree, relative to that staging root. `captions-floor` is the one
/// exception to the generic `components/<id>` convention (see
/// `FLOOR_STAGED_ROOT`'s doc comment); every other known component --
/// required or optional -- keeps the original layout.
fn staged_component_root(component: &str) -> String {
    match component {
        "captions-floor" => FLOOR_STAGED_ROOT.to_string(),
        "captions-large-v3" => LARGE_V3_STAGED_ROOT.to_string(),
        other => format!("components/{other}"),
    }
}

#[derive(Debug, Clone, Serialize)]
pub struct StagedDistribution {
    pub version_root: PathBuf,
    pub station_manifest: PathBuf,
    pub distribution_index_sha256: String,
}

pub fn stage_acquired_distribution<T>(
    distribution: &AcquiredDistribution,
    install_root: &Path,
    trust: &PackTrust,
    self_test: T,
) -> Result<StagedDistribution, String>
where
    T: FnOnce(&Path, &AcquiredDistribution) -> Result<(), String>,
{
    stage_distribution_with(
        distribution,
        install_root,
        |pack, destination| {
            let verified = native_packs::verify_and_extract_pack(
                &pack.cached_path,
                destination,
                trust,
                Some(&pack.component),
                Some(&distribution.index.product_version),
                Some(&distribution.index.compatible_core),
            )?;
            if verified.sha256 != pack.outer_sha256 {
                return Err(format!(
                    "Extracted native component pack does not match its signed index: {}",
                    pack.component
                ));
            }
            Ok(())
        },
        |staging, acquired| {
            compose_ollama_model_store(staging)?;
            validate_staged_runtime_layout(staging)?;
            self_test(staging, acquired)
        },
    )
}

pub(crate) fn compose_ollama_model_store(staging: &Path) -> Result<(), String> {
    let destination = staging.join("models").join("ollama");
    ensure_directory_or_create(&destination, "composed Ollama model store")?;
    for component in &REQUIRED_COMPONENTS[2..] {
        let component_root = staging.join("components").join(component);
        ensure_existing_directory(&component_root, "staged native model component")?;
        for top_level in ["blobs", "manifests"] {
            let source_root = component_root.join(top_level);
            ensure_existing_directory(&source_root, "staged Ollama model subtree")?;
            compose_tree(&source_root, &destination.join(top_level))?;
        }
    }
    Ok(())
}

fn compose_tree(source_root: &Path, destination_root: &Path) -> Result<(), String> {
    ensure_directory_or_create(destination_root, "composed Ollama subtree")?;
    let mut pending = vec![source_root.to_path_buf()];
    while let Some(directory) = pending.pop() {
        ensure_existing_directory(&directory, "staged Ollama source directory")?;
        let mut entries: Vec<_> = fs::read_dir(&directory)
            .map_err(|error| format!("Could not enumerate staged Ollama model tree: {error}"))?
            .collect::<Result<_, _>>()
            .map_err(|error| format!("Could not inspect staged Ollama model entry: {error}"))?;
        entries.sort_by_key(|entry| entry.file_name());
        for entry in entries {
            let source = entry.path();
            let metadata = fs::symlink_metadata(&source)
                .map_err(|error| format!("Could not inspect staged Ollama model file: {error}"))?;
            if metadata.file_type().is_symlink() {
                return Err(format!(
                    "Staged Ollama model tree contains a link: {}",
                    source.display()
                ));
            }
            let relative = source
                .strip_prefix(source_root)
                .map_err(|_| "Staged Ollama model path escaped its component.".to_string())?;
            let destination = destination_root.join(relative);
            if metadata.is_dir() {
                ensure_directory_or_create(&destination, "composed Ollama model directory")?;
                pending.push(source);
                continue;
            }
            if !metadata.is_file() {
                return Err(format!(
                    "Staged Ollama model tree contains a non-file: {}",
                    source.display()
                ));
            }
            if let Some(parent) = destination.parent() {
                ensure_directory_or_create(parent, "composed Ollama model directory")?;
            }
            if destination.exists() {
                let source_identity = file_identity(&source)?;
                let destination_identity = file_identity(&destination)?;
                if source_identity != destination_identity {
                    return Err(format!(
                        "Required Ollama packs disagree on shared model bytes: {}",
                        destination.display()
                    ));
                }
                continue;
            }
            if fs::hard_link(&source, &destination).is_err() {
                copy_new_verified(&source, &destination)?;
            }
        }
    }
    Ok(())
}

fn copy_new_verified(source: &Path, destination: &Path) -> Result<(), String> {
    let mut input = OpenOptions::new()
        .read(true)
        .open(source)
        .map_err(|error| format!("Could not open staged Ollama model file: {error}"))?;
    let mut output = OpenOptions::new()
        .create_new(true)
        .write(true)
        .open(destination)
        .map_err(|error| format!("Could not create composed Ollama model file: {error}"))?;
    std::io::copy(&mut input, &mut output)
        .map_err(|error| format!("Could not copy composed Ollama model file: {error}"))?;
    output
        .sync_all()
        .map_err(|error| format!("Could not flush composed Ollama model file: {error}"))?;
    drop(output);
    if file_identity(source)? != file_identity(destination)? {
        let _ = fs::remove_file(destination);
        return Err(format!(
            "Composed Ollama model copy failed byte verification: {}",
            destination.display()
        ));
    }
    Ok(())
}

fn file_identity(path: &Path) -> Result<(u64, String), String> {
    let metadata = fs::symlink_metadata(path)
        .map_err(|error| format!("Could not inspect staged model bytes: {error}"))?;
    if !metadata.is_file() || metadata.file_type().is_symlink() {
        return Err(format!(
            "Staged model path is not a regular file: {}",
            path.display()
        ));
    }
    let mut input = OpenOptions::new()
        .read(true)
        .open(path)
        .map_err(|error| format!("Could not open staged model bytes: {error}"))?;
    let mut digest = Sha256::new();
    let mut observed = 0_u64;
    let mut buffer = vec![0_u8; 1024 * 1024];
    loop {
        let count = input
            .read(&mut buffer)
            .map_err(|error| format!("Could not read staged model bytes: {error}"))?;
        if count == 0 {
            break;
        }
        observed += count as u64;
        digest.update(&buffer[..count]);
    }
    Ok((observed, format!("{:x}", digest.finalize())))
}

fn require_staged_files(staging: &Path, relative_files: &[&str]) -> Result<(), String> {
    for relative in relative_files {
        let path = staging.join(relative);
        let metadata = fs::symlink_metadata(&path).map_err(|_| {
            format!("Staged native station is missing a required runtime file: {relative}")
        })?;
        if !metadata.is_file() || metadata.file_type().is_symlink() {
            return Err(format!(
                "Staged native station runtime path is not a regular file: {relative}"
            ));
        }
    }
    Ok(())
}

/// The runtime files the promoted staged station MUST carry, expressed as the
/// SAME staging-relative paths the running service actually uses.
///
/// K1 activation defect (found by a clean-box install proof): postgres
/// and tsduck are NOT staged under `dependencies/`. They ship inside the signed
/// `native-server-binaries` pack, which
/// `install_layout.py::_SERVER_PACK_SUBDIR` resolves at runtime to
/// `<install_root>\packs\native-server-binaries\payload\bin` (pg_ctl.exe,
/// postgres.exe) and `...\payload\tsduck\bin` (tsp.exe) -- see
/// `scripts/build_native_server_pack.py` (`bin/<file>` + `tsduck/bin/<file>`
/// sources under the pack's `payload/` prefix). NATS JetStream was removed
/// from the product (owner decision 2026-08-20; see ADR 0023, which
/// supersedes ADR 0001), so nats-server.exe is no longer part of this pack
/// or this required-files list. node is BUILD-TIME ONLY
/// (`scripts/build_native_app_payload.py` uses `which(node)` to compile the
/// React portals; the runtime serves them as static dist via Python), so it is
/// never staged and requiring it can never pass -- it is absent here.
/// ffmpeg/ollama keep the real `dependencies/<tool>/` convention
/// `install_layout.py` (`ffmpeg_exe_path`/`ollama_exe_path`) pins.
///
/// K1-2: `postgres.exe` alone under-covers the runtime -- the supervisor
/// actually LAUNCHES PostgreSQL through `pg_ctl.exe`
/// (`native/supervisor/children.py::postgres_child_spec` builds
/// `argv=[pg_ctl_path, "start", ...]`; `pg_ctl` then spawns `postgres.exe` as
/// its child). Both binaries are pinned in `POSTGRES_BIN_PINS`
/// (`scripts/build_native_server_pack.py`) at the same staged prefix, so both
/// are required here -- the self-test now verifies the binary the runtime
/// actually invokes, not just the one it happens to spawn.
///
/// K1-1: `tsp.exe` (TSDuck) is deliberately NOT in this hard-required list.
/// The runtime treats TSDuck as optional -- `egress/ts_relay.py`'s
/// `CIVICCAST_TS_RELAY=auto` (the default) warns and passes udp-ts egress
/// straight through when `tsp` is unavailable, rather than failing the
/// channel. Activation must match that posture: see
/// `OPTIONAL_VERIFIED_IF_PRESENT_RUNTIME_FILES` below, which still verifies
/// tsp.exe as a real staged file WHEN it is present, but never hard-fails
/// activation on its absence.
///
/// This list is the SOURCE the self-test enforces; `main.rs`'s
/// `run_native_pre_activation_checks` version-probes the same server-pack
/// paths. A unit test (`validate_staged_runtime_layout_*`) pins it to the
/// runtime layout so the two cannot silently diverge again.
const REQUIRED_STAGED_RUNTIME_FILES: &[&str] = &[
    "runtime/python.exe",
    "packs/native-server-binaries/payload/bin/postgres.exe",
    "packs/native-server-binaries/payload/bin/pg_ctl.exe",
    "dependencies/ffmpeg/bin/ffmpeg.exe",
    "dependencies/ollama/ollama.exe",
    "runtime/Lib/site-packages/faster_whisper/__init__.py",
    "runtime/Lib/site-packages/ctranslate2/__init__.py",
    "runtime/Lib/site-packages/ctranslate2/_ext.cp312-win_amd64.pyd",
    // The mandatory caption FLOOR tier -- owner decision 2026-08-07.
    // Staged at `packs/captions-floor`, not `components/`; see
    // `FLOOR_STAGED_ROOT`'s doc comment for why.
    "packs/captions-floor/models/faster-whisper-medium/config.json",
    "packs/captions-floor/models/faster-whisper-medium/model.bin",
    "packs/captions-floor/models/faster-whisper-medium/tokenizer.json",
    "packs/captions-floor/models/faster-whisper-medium/vocabulary.txt",
    "packs/captions-floor/self-test/jfk.wav",
    "models/ollama/manifests/registry.ollama.ai/library/gemma4/12b",
    "models/ollama/manifests/registry.ollama.ai/library/gemma4/e4b",
    "models/ollama/manifests/registry.ollama.ai/library/translategemma/4b",
];

/// Runtime files the SERVICE treats as optional (see the K1-1 doc comment on
/// `REQUIRED_STAGED_RUNTIME_FILES`). Activation never hard-fails when one of
/// these is absent -- but if it IS staged, it must still be a real, regular
/// staged file; a broken or symlinked entry is not silently accepted just
/// because the requirement itself is soft.
const OPTIONAL_VERIFIED_IF_PRESENT_RUNTIME_FILES: &[&str] = &[
    "packs/native-server-binaries/payload/tsduck/bin/tsp.exe",
];

/// "Verified-if-present": absent is fine (optional dependency, matches the
/// runtime's own warn-and-pass-through posture); present-but-broken (missing,
/// a directory, or a symlink) still fails, same as a required file.
fn verify_optional_staged_files(staging: &Path, relative_files: &[&str]) -> Result<(), String> {
    for relative in relative_files {
        let path = staging.join(relative);
        if fs::symlink_metadata(&path).is_err() {
            continue;
        }
        require_staged_files(staging, &[*relative])?;
    }
    Ok(())
}

fn validate_staged_runtime_layout(staging: &Path) -> Result<(), String> {
    require_staged_files(staging, REQUIRED_STAGED_RUNTIME_FILES)?;
    verify_optional_staged_files(staging, OPTIONAL_VERIFIED_IF_PRESENT_RUNTIME_FILES)?;

    // captions-large-v3 is optional (owner decision 2026-08-07): verified
    // when present, simply absent when not. Presence is judged on the
    // component's staged directory entry, matching
    // `station_runtime.py::_staged_caption_tier_ids`'s lexists semantics --
    // a partially-staged large-v3 directory is "present" and must then pass
    // the full file check, never be silently treated as absent.
    let large_v3_root = staging.join(LARGE_V3_STAGED_ROOT);
    if fs::symlink_metadata(&large_v3_root).is_ok() {
        let large_v3_files = [
            "components/captions-large-v3/models/faster-whisper-large-v3/README.md",
            "components/captions-large-v3/models/faster-whisper-large-v3/config.json",
            "components/captions-large-v3/models/faster-whisper-large-v3/model.bin",
            "components/captions-large-v3/models/faster-whisper-large-v3/preprocessor_config.json",
            "components/captions-large-v3/models/faster-whisper-large-v3/tokenizer.json",
            "components/captions-large-v3/models/faster-whisper-large-v3/vocabulary.json",
            "components/captions-large-v3/self-test/jfk.wav",
        ];
        require_staged_files(staging, &large_v3_files)?;
    }
    Ok(())
}

pub fn stage_distribution_with<E, T>(
    distribution: &AcquiredDistribution,
    install_root: &Path,
    mut extract: E,
    self_test: T,
) -> Result<StagedDistribution, String>
where
    E: FnMut(&AcquiredPack, &Path) -> Result<(), String>,
    T: FnOnce(&Path, &AcquiredDistribution) -> Result<(), String>,
{
    validate_complete_distribution(distribution)?;
    let version = safe_version_segment(&distribution.index.product_version)?;
    ensure_directory_or_create(install_root, "native install root")?;
    let app_root = install_root.join("app");
    ensure_directory_or_create(&app_root, "native version root")?;
    let target = app_root.join(version);
    if target.exists() {
        return Err(format!(
            "Native station version tree already exists and will not be overwritten: {}",
            target.display()
        ));
    }
    let staging = app_root.join(format!(
        ".{version}.{}.staging",
        &distribution.index.sha256[..16]
    ));
    if staging.exists() {
        remove_stale_staging(&staging)?;
    }
    let mut guard = StagingGuard::new(staging.clone());

    let by_component: BTreeMap<_, _> = distribution
        .packs
        .iter()
        .map(|pack| (pack.component.as_str(), pack))
        .collect();
    let core = by_component
        .get("core")
        .copied()
        .ok_or_else(|| "Native station is missing the required core pack.".to_string())?;
    extract(core, &staging)?;
    ensure_existing_directory(&staging, "staged native core")?;

    for component in &REQUIRED_COMPONENTS[1..] {
        let pack = by_component
            .get(component)
            .copied()
            .ok_or_else(|| format!("Native station is missing required pack: {component}"))?;
        let destination = staging.join(staged_component_root(component));
        extract(pack, &destination)?;
        ensure_existing_directory(&destination, "staged native component")?;
    }

    // captions-large-v3 is optional (owner decision 2026-08-07): extracted
    // and verified when the distribution actually carries it, silently
    // skipped when it does not. There is no model-downgrade or
    // caption-disabled success path -- the floor tier above is already
    // mandatory and always extracted; this only adds the optional quality
    // tier on top when present.
    for component in OPTIONAL_COMPONENTS {
        if let Some(pack) = by_component.get(component).copied() {
            let destination = staging.join(staged_component_root(component));
            extract(pack, &destination)?;
            ensure_existing_directory(&destination, "staged native component")?;
        }
    }

    self_test(&staging, distribution)?;
    let manifest_path = staging.join("station-set.json");
    write_station_manifest(&manifest_path, distribution)?;
    promote_staging(&staging, &target)?;
    guard.disarm();
    Ok(StagedDistribution {
        version_root: target.clone(),
        station_manifest: target.join("station-set.json"),
        distribution_index_sha256: distribution.index.sha256.clone(),
    })
}

fn promote_staging(staging: &Path, target: &Path) -> Result<(), String> {
    #[cfg(target_os = "windows")]
    {
        const RETRY_WINDOW: Duration = Duration::from_secs(30);
        const RETRY_DELAY: Duration = Duration::from_millis(100);
        let deadline = std::time::Instant::now() + RETRY_WINDOW;
        loop {
            match fs::rename(staging, target) {
                Ok(()) => return Ok(()),
                Err(error)
                    if matches!(error.raw_os_error(), Some(5 | 32))
                        && std::time::Instant::now() < deadline =>
                {
                    thread::sleep(RETRY_DELAY);
                }
                Err(error) => {
                    return Err(format!(
                        "Could not atomically promote native station tree: {error}"
                    ));
                }
            }
        }
    }
    #[cfg(not(target_os = "windows"))]
    {
        fs::rename(staging, target)
            .map_err(|error| format!("Could not atomically promote native station tree: {error}"))
    }
}

fn validate_complete_distribution(distribution: &AcquiredDistribution) -> Result<(), String> {
    if distribution.index.kind != "channel-index" && distribution.index.kind != "station-index" {
        return Err("Native station distribution kind is invalid.".to_string());
    }
    if distribution.index.sha256.len() != 64
        || !distribution
            .index
            .sha256
            .bytes()
            .all(|character| character.is_ascii_digit() || (b'a'..=b'f').contains(&character))
    {
        return Err("Native station distribution index SHA-256 is invalid.".to_string());
    }
    let indexed: BTreeMap<_, _> = distribution
        .index
        .packs
        .iter()
        .map(|pack| (pack.component.as_str(), pack))
        .collect();
    let acquired: BTreeMap<_, _> = distribution
        .packs
        .iter()
        .map(|pack| (pack.component.as_str(), pack))
        .collect();
    let required: BTreeSet<_> = REQUIRED_COMPONENTS.into_iter().collect();
    if indexed.len() != distribution.index.packs.len()
        || acquired.len() != distribution.packs.len()
        || !required.is_subset(&indexed.keys().copied().collect())
        || !required.is_subset(&acquired.keys().copied().collect())
    {
        return Err("Native station does not contain one complete required pack set.".to_string());
    }
    for component in REQUIRED_COMPONENTS {
        let index_pack = indexed
            .get(component)
            .ok_or_else(|| format!("Native station index is missing {component}."))?;
        let acquired_pack = acquired
            .get(component)
            .ok_or_else(|| format!("Native station acquisition is missing {component}."))?;
        if !index_pack.required
            || acquired_pack.component != index_pack.component
            || acquired_pack.outer_sha256 != index_pack.sha256
            || acquired_pack.verified.sha256 != index_pack.sha256
            || acquired_pack.verified.component != index_pack.component
            || acquired_pack.verified.product_version != distribution.index.product_version
            || acquired_pack.verified.compatible_core != distribution.index.compatible_core
            || acquired_pack.verified.signing_key_id != distribution.index.signing_key_id
        {
            return Err(format!(
                "Native station acquired pack identity is inconsistent: {component}"
            ));
        }
    }
    // captions-large-v3 is optional: if the distribution carries it (in the
    // index, the acquisition, or both), its identity must still be fully
    // consistent -- an optional component is verified when present, never
    // half-trusted. A component present in only one of index/acquisition is
    // an acquisition-layer inconsistency, not a legitimate "not offered"
    // shape, so it fails the same as a required-component mismatch.
    for component in OPTIONAL_COMPONENTS {
        let index_pack = indexed.get(component);
        let acquired_pack = acquired.get(component);
        match (index_pack, acquired_pack) {
            (None, None) => {}
            (Some(index_pack), Some(acquired_pack)) => {
                if acquired_pack.component != index_pack.component
                    || acquired_pack.outer_sha256 != index_pack.sha256
                    || acquired_pack.verified.sha256 != index_pack.sha256
                    || acquired_pack.verified.component != index_pack.component
                    || acquired_pack.verified.product_version != distribution.index.product_version
                    || acquired_pack.verified.compatible_core != distribution.index.compatible_core
                    || acquired_pack.verified.signing_key_id != distribution.index.signing_key_id
                {
                    return Err(format!(
                        "Native station acquired pack identity is inconsistent: {component}"
                    ));
                }
            }
            _ => {
                return Err(format!(
                    "Native station optional pack is present in only one of the index or the acquisition: {component}"
                ));
            }
        }
    }
    Ok(())
}

/// Pure: the exact `station-set.json` document for `distribution` -- shared
/// by [`write_station_manifest`] (the versioned `app/<version>/` layout) and
/// [`activate_flat_station_with`] (the flat `$INSTDIR` layout, K1's fix).
/// Extracted so the two layouts can never independently drift on what "a
/// valid station-set" contains: there is exactly one place this document is
/// composed, and `station_runtime.py::_validate_station_set` /
/// `EXPECTED_RUNTIME_CONTRACT` is the single Python-side contract it must
/// keep satisfying.
fn station_manifest_value(distribution: &AcquiredDistribution) -> Value {
    let mut roots = BTreeMap::new();
    roots.insert("core".to_string(), ".".to_string());
    for component in REQUIRED_COMPONENTS[1..].iter().chain(OPTIONAL_COMPONENTS.iter()) {
        roots.insert(component.to_string(), staged_component_root(component));
    }
    let known: BTreeSet<&str> = REQUIRED_COMPONENTS
        .iter()
        .copied()
        .chain(OPTIONAL_COMPONENTS.iter().copied())
        .collect();
    let packs: Vec<Value> = distribution
        .packs
        .iter()
        .filter(|pack| known.contains(pack.component.as_str()))
        .map(|pack| {
            json!({
                "component": pack.component,
                "file_count": pack.verified.file_count,
                "outer_sha256": pack.outer_sha256,
                "payload_bytes": pack.verified.total_bytes,
                "root": roots[&pack.component],
            })
        })
        .collect();
    json!({
        "schema_version": 2,
        "product": "civiccast-native",
        "product_version": distribution.index.product_version,
        "compatible_core": distribution.index.compatible_core,
        "distribution_index_sha256": distribution.index.sha256,
        "signing_key_id": distribution.index.signing_key_id,
        "packs": packs,
        "runtime": {
            "caption_tap": "inline",
            "caption_tap_atomic": true,
            "caption_model_root":
                "components/captions-large-v3/models/faster-whisper-large-v3",
            "caption_runtime": "faster-whisper",
            "caption_device": "cpu",
            "caption_compute_type": "int8",
            "egress_engine": "gstreamer",
            "egress_embed_captions": true,
            "offline_only": true,
        },
    })
}

/// Write `value` as canonical JSON to `destination` via a same-directory
/// `<name>.json.partial` file (fsync'd before rename) -- generalizes
/// [`write_station_manifest`]'s original inline temp+rename dance so
/// [`activate_flat_station_with`] gets the IDENTICAL durability guarantee
/// for both files it writes, never a second, weaker implementation. A stale
/// `.partial` left by a prior crashed run is cleared first: unlike the
/// versioned layout (where a stale staging directory is simply discarded
/// wholesale by `StagingGuard`), a flat activation writes directly into the
/// live install root, so a leftover partial must never permanently block a
/// retry.
pub(crate) fn write_json_atomically(destination: &Path, value: &Value, label: &str) -> Result<(), String> {
    let bytes = native_distribution::canonical_json(value)?.into_bytes();
    let partial = destination.with_extension("json.partial");
    let _ = fs::remove_file(&partial);
    let mut output = OpenOptions::new()
        .create_new(true)
        .write(true)
        .open(&partial)
        .map_err(|error| format!("Could not create {label}: {error}"))?;
    output
        .write_all(&bytes)
        .map_err(|error| format!("Could not write {label}: {error}"))?;
    output
        .sync_all()
        .map_err(|error| format!("Could not flush {label}: {error}"))?;
    drop(output);
    fs::rename(&partial, destination).map_err(|error| {
        let _ = fs::remove_file(&partial);
        format!("Could not promote {label}: {error}")
    })
}

fn write_station_manifest(
    destination: &Path,
    distribution: &AcquiredDistribution,
) -> Result<(), String> {
    write_json_atomically(
        destination,
        &station_manifest_value(distribution),
        "staged station manifest",
    )
}

/// The two files [`activate_flat_station_with`] writes, and where they
/// landed.
#[derive(Debug, Clone, Serialize)]
pub struct FlatStationActivation {
    pub install_root: PathBuf,
    pub station_manifest: PathBuf,
    pub activation_receipt: PathBuf,
    /// `true` when an already-valid pair of files matching THIS
    /// `distribution` was found on disk and left untouched -- `self_test`
    /// was never invoked. `false` when this call actually (re)wrote both
    /// files, having run `self_test` first.
    pub already_activated: bool,
}

/// K1 fix: activate a FLAT-layout native station -- `station-set.json` and
/// `activation-self-test.json` written directly at `install_root`
/// (`$INSTDIR`), never under an `app/<version>/` subdirectory.
///
/// This closes the gap the K1 audit identified: [`stage_distribution_with`]
/// is the ONLY writer of these two files anywhere in this codebase, but its
/// only production caller (`main.rs::run_native_distribution_cli`, gated
/// behind `--civiccast-acquire-channel` / `--civiccast-import-station`) is
/// never invoked by `nsis-hooks-bootstrap.nsh` -- and even when it is
/// invoked directly, it only ever writes into the VERSIONED
/// `<install_root>/app/<version>/station-set.json` shape. The real installer
/// registers the LocalSystem service against `$INSTDIR\runtime\python.exe`
/// (flat, no junction), and `native/station_runtime.py::
/// load_native_station_environment` resolves that service's version root
/// straight from the running interpreter's own path -- landing on
/// `$INSTDIR` itself, not `$INSTDIR\app\<version>`. A flat root's
/// `station-set.json` must therefore live at `$INSTDIR\station-set.json`
/// directly; `_JUNCTION_VERSION_PARENT_NAME`'s own doc comment confirms the
/// junction/`app/<version>` sanity check is opt-in (`root.parent.name ==
/// "app"`) and simply does not apply to this shape.
///
/// Reuses [`station_manifest_value`] (the exact JSON [`write_station_manifest`]
/// emits, factored out so both layouts share one composition) and
/// [`write_json_atomically`] for BOTH files -- no second, parallel manifest
/// construction or write path. Unlike the versioned flow, there is no
/// staging-directory-plus-atomic-rename to fall back on if a step fails
/// partway (a flat root IS the live install, not a `.staging` scratch tree a
/// `StagingGuard` can discard), so the two files are sequenced
/// receipt-then-manifest with an explicit rollback: a manifest write failure
/// after a successful receipt write removes the just-written receipt again,
/// so a partial run can never leave `station-set.json` present without its
/// receipt -- the one combination `load_native_station_environment` would
/// read as a loud `NativeStationConfigurationError` instead of the graceful
/// not-yet-activated state. (The reverse -- a receipt present with no
/// manifest -- is inert to `load_native_station_environment`, which gates on
/// `station-set.json`'s presence first, but is still not left behind: see
/// the cleanup below.)
///
/// Idempotent: if `install_root` already carries a `station-set.json`
/// byte-identical (post-canonicalization) to what THIS `distribution` would
/// produce, AND a well-formed `activation-self-test.json` naming the same
/// `product_version`/`distribution_index_sha256`, the run is a clean no-op
/// -- neither `extract` nor `self_test` (expensive: live caption-model
/// inference plus live Ollama generate calls) is re-invoked against an
/// already-activated station. Anything else found on disk (absent, stale,
/// corrupt, or activated against a DIFFERENT distribution) is cleared and
/// rewritten from scratch -- never a partial merge with old content.
///
/// `extract` lands every REQUIRED_COMPONENT (except `core`, see below) and
/// any present OPTIONAL_COMPONENT's payload at its pinned destination under
/// `install_root` (the same `staged_component_root` convention
/// [`station_manifest_value`]'s `packs[].root` field records), then composes
/// the merged Ollama model store the same way the versioned flow's own
/// self-test wrapper does (see [`compose_ollama_model_store`]) -- this is
/// the piece a flat activation needs that the versioned flow gets for free
/// from `stage_distribution_with`'s own extraction loop: `self_test` reads
/// live bytes from disk (`run_native_caption_inference_self_test`,
/// `run_native_ai_inference_self_tests`), so those bytes must actually be
/// there first.
///
/// `core` is deliberately NEVER extracted here, unlike the versioned flow
/// (where it IS, straight into the version root). In the flat layout,
/// `install_root` is not a fresh scratch tree -- it is the SAME `$INSTDIR`
/// the elevated installer's OWN pack-staging step
/// (`--civiccast-stage-packs`, `native_pack_staging.rs`) already populated
/// and D2-verified (`runtime\`, `dependencies\*`) before this command ever
/// runs. Extracting a `core` pack's payload on top would either duplicate
/// those already-verified bytes or, worse, silently overwrite them with a
/// second, independently-built copy. A station bundle's `core` pack entry
/// therefore exists ONLY to satisfy [`validate_complete_distribution`]'s
/// structural contract (component identity, present in both the index and
/// the acquisition) -- its actual payload is never unpacked in this layout.
pub fn activate_flat_station_with<E, T>(
    install_root: &Path,
    distribution: &AcquiredDistribution,
    mut extract: E,
    self_test: T,
) -> Result<FlatStationActivation, String>
where
    E: FnMut(&AcquiredPack, &Path) -> Result<(), String>,
    T: FnOnce(&Path, &AcquiredDistribution) -> Result<Value, String>,
{
    validate_complete_distribution(distribution)?;
    ensure_existing_directory(install_root, "native flat install root")?;

    let manifest_path = install_root.join("station-set.json");
    let receipt_path = install_root.join("activation-self-test.json");
    let manifest_value = station_manifest_value(distribution);

    if flat_activation_already_matches(&manifest_path, &receipt_path, &manifest_value, distribution)
    {
        return Ok(FlatStationActivation {
            install_root: install_root.to_path_buf(),
            station_manifest: manifest_path,
            activation_receipt: receipt_path,
            already_activated: true,
        });
    }

    // A stale pair (present but not matching this distribution) is cleared
    // before rewriting -- never left for the writes below to merge with or
    // partially overwrite.
    if manifest_path.exists() {
        fs::remove_file(&manifest_path)
            .map_err(|error| format!("Could not clear a stale native station manifest: {error}"))?;
    }
    if receipt_path.exists() {
        fs::remove_file(&receipt_path).map_err(|error| {
            format!("Could not clear a stale native station activation receipt: {error}")
        })?;
    }

    extract_flat_distribution_components(install_root, distribution, &mut extract)?;

    let receipt_value = self_test(install_root, distribution)?;
    write_json_atomically(
        &receipt_path,
        &receipt_value,
        "native station activation receipt",
    )?;
    if let Err(error) = write_json_atomically(
        &manifest_path,
        &manifest_value,
        "native flat station manifest",
    ) {
        // Roll back the receipt: never leave it standing alone. Best-effort
        // -- the write error above is the one that actually gets reported.
        let _ = fs::remove_file(&receipt_path);
        return Err(error);
    }

    Ok(FlatStationActivation {
        install_root: install_root.to_path_buf(),
        station_manifest: manifest_path,
        activation_receipt: receipt_path,
        already_activated: false,
    })
}

/// Extract every non-`core` required component (and any present optional
/// component) of `distribution` to its pinned destination under
/// `install_root`, then compose the merged Ollama model store. See
/// [`activate_flat_station_with`]'s doc for why `core` is excluded.
///
/// Each destination is cleared first if it already exists: this function is
/// only ever reached (from [`activate_flat_station_with`]) after the
/// manifest/receipt-match idempotency check has already determined a real
/// (re)activation is needed, so any component directory already present is
/// necessarily stale (left by a prior activation against a different
/// distribution, or a partial prior run) -- never left for `extract` to
/// merge with or partially overwrite.
fn extract_flat_distribution_components<E>(
    install_root: &Path,
    distribution: &AcquiredDistribution,
    extract: &mut E,
) -> Result<(), String>
where
    E: FnMut(&AcquiredPack, &Path) -> Result<(), String>,
{
    let by_component: BTreeMap<_, _> = distribution
        .packs
        .iter()
        .map(|pack| (pack.component.as_str(), pack))
        .collect();
    for component in REQUIRED_COMPONENTS[1..]
        .iter()
        .chain(OPTIONAL_COMPONENTS.iter())
    {
        let Some(pack) = by_component.get(component).copied() else {
            // Absent is only valid for an OPTIONAL component -- validated
            // already by validate_complete_distribution for every REQUIRED
            // one, so reaching this branch for a required component would
            // itself be a validation bug, not a legitimate runtime state.
            continue;
        };
        let destination = install_root.join(staged_component_root(component));
        if destination.exists() {
            fs::remove_dir_all(&destination).map_err(|error| {
                format!("Could not clear a stale extracted native component tree for {component}: {error}")
            })?;
        }
        extract(pack, &destination)?;
        ensure_existing_directory(&destination, "extracted native component")?;
    }
    compose_ollama_model_store(install_root)
}

/// Production entry point for `--civiccast-activate-station`
/// (`main.rs::run_native_flat_activation_cli`): activates `distribution` at
/// `install_root`, extracting every component's payload via the SAME
/// verify-then-extract machinery [`stage_acquired_distribution`] uses for
/// the versioned layout (`native_packs::verify_and_extract_pack`, re-checked
/// against the pack's own signed outer SHA-256 -- never a second, weaker
/// extraction path), and running `self_test` against the now-populated
/// `install_root`. See [`activate_flat_station_with`] for the full
/// contract; this is a thin, real-I/O wrapper around it, mirroring
/// [`stage_acquired_distribution`]'s own relationship to
/// [`stage_distribution_with`].
pub fn activate_flat_station_from_acquired<T>(
    install_root: &Path,
    distribution: &AcquiredDistribution,
    trust: &PackTrust,
    self_test: T,
) -> Result<FlatStationActivation, String>
where
    T: FnOnce(&Path, &AcquiredDistribution) -> Result<Value, String>,
{
    activate_flat_station_with(
        install_root,
        distribution,
        |pack, destination| {
            let verified = native_packs::verify_and_extract_pack(
                &pack.cached_path,
                destination,
                trust,
                Some(&pack.component),
                Some(&distribution.index.product_version),
                Some(&distribution.index.compatible_core),
            )?;
            if verified.sha256 != pack.outer_sha256 {
                return Err(format!(
                    "Extracted native component pack does not match its signed index: {}",
                    pack.component
                ));
            }
            Ok(())
        },
        self_test,
    )
}

/// Whether `manifest_path`/`receipt_path` already hold a valid, matching
/// pair for `distribution` -- the [`activate_flat_station_with`] idempotency
/// fast-path. Returning `true` SKIPS re-extraction and the expensive
/// caption-inference self-test, so the bar for `true` must be the runtime's
/// bar: this probe must never claim a station is already activated on a
/// receipt the service would then reject.
///
/// The authoritative acceptance gate is the station runtime's
/// `_validate_activation_receipt` (in `civiccast/native/station_runtime.py`),
/// which requires `schema_version == 1`, `product == "civiccast-native"`,
/// `product_version == <version>`, `distribution_index_sha256 == <index sha>`,
/// AND a `caption_inference` object that exactly equals
/// `_expected_caption_receipt(tier_id)` for the tier the station resolved and
/// verified on disk. That final caption-inference IDENTITY is derived from the
/// Python `CAPTION_TIER_REGISTRY`; reimplementing that registry (and its tier
/// resolution) here would risk silent CLI/runtime drift, so this probe does
/// NOT attempt to reproduce it. Instead it confirms only what it can confirm
/// without divergence -- the structural completeness the runtime also
/// demands: `schema_version == 1`, the exact `product` string, the matching
/// version and index sha, and that `caption_inference` is PRESENT and is a
/// JSON object (not null/array/scalar). Anything short of that structural
/// completeness returns `false`, falling through to the full self-test
/// rewrite -- which is safe (just slower) because it re-derives a correct
/// receipt. This guarantees the CLI never reports "already activated" on a
/// receipt the runtime would reject, so a stale or damaged receipt is always
/// re-activated rather than skipped forever.
///
/// Any read/parse failure (absent, corrupt, foreign content) is treated as
/// "does not match" rather than propagated: a caller that cannot even read
/// the existing state must fall through to the clean-rewrite path, never
/// error out of an idempotency probe.
fn flat_activation_already_matches(
    manifest_path: &Path,
    receipt_path: &Path,
    expected_manifest: &Value,
    distribution: &AcquiredDistribution,
) -> bool {
    let Ok(existing_manifest_bytes) = fs::read(manifest_path) else {
        return false;
    };
    let Ok(existing_manifest) = serde_json::from_slice::<Value>(&existing_manifest_bytes) else {
        return false;
    };
    if &existing_manifest != expected_manifest {
        return false;
    }
    let Ok(existing_receipt_bytes) = fs::read(receipt_path) else {
        return false;
    };
    let Ok(existing_receipt) = serde_json::from_slice::<Value>(&existing_receipt_bytes) else {
        return false;
    };
    // Every field below is a field the runtime's `_validate_activation_receipt`
    // also requires. `caption_inference` can only be shape-checked here (see
    // the doc comment) -- its per-tier identity is confirmed by the fall-through
    // self-test, never by this probe.
    existing_receipt.get("schema_version") == Some(&Value::from(1))
        && existing_receipt.get("product") == Some(&Value::String("civiccast-native".to_string()))
        && existing_receipt.get("product_version")
            == Some(&Value::String(distribution.index.product_version.clone()))
        && existing_receipt.get("distribution_index_sha256")
            == Some(&Value::String(distribution.index.sha256.clone()))
        && existing_receipt
            .get("caption_inference")
            .is_some_and(Value::is_object)
}

fn safe_version_segment(value: &str) -> Result<&str, String> {
    if value.is_empty()
        || value.len() > 128
        || value.trim() != value
        || !value.is_ascii()
        || value == "."
        || value == ".."
        || value
            .bytes()
            .any(|character| !(character.is_ascii_alphanumeric() || b".-_+".contains(&character)))
    {
        return Err("Native station product version is not a safe path segment.".to_string());
    }
    Ok(value)
}

fn ensure_directory_or_create(path: &Path, label: &str) -> Result<(), String> {
    if path.exists() {
        return ensure_existing_directory(path, label);
    }
    fs::create_dir_all(path).map_err(|error| format!("Could not create {label}: {error}"))?;
    ensure_existing_directory(path, label)
}

fn ensure_existing_directory(path: &Path, label: &str) -> Result<(), String> {
    let metadata = fs::symlink_metadata(path)
        .map_err(|error| format!("Could not inspect {label}: {error}"))?;
    if !metadata.file_type().is_dir() || metadata.file_type().is_symlink() {
        return Err(format!("{label} must be a real directory, not a link."));
    }
    #[cfg(target_os = "windows")]
    {
        use std::os::windows::fs::MetadataExt;
        if metadata.file_attributes() & 0x400 != 0 {
            return Err(format!("{label} must not be a reparse point."));
        }
    }
    Ok(())
}

fn remove_stale_staging(staging: &Path) -> Result<(), String> {
    ensure_existing_directory(staging, "stale native staging tree")?;
    fs::remove_dir_all(staging)
        .map_err(|error| format!("Could not remove stale native staging tree: {error}"))
}

struct StagingGuard {
    path: PathBuf,
    armed: bool,
}

impl StagingGuard {
    fn new(path: PathBuf) -> Self {
        Self { path, armed: true }
    }

    fn disarm(&mut self) {
        self.armed = false;
    }
}

impl Drop for StagingGuard {
    fn drop(&mut self) {
        if self.armed && self.path.exists() {
            let _ = fs::remove_dir_all(&self.path);
        }
    }
}

#[cfg(test)]
mod tests {
    use super::{
        activate_flat_station_with, compose_ollama_model_store, flat_activation_already_matches,
        promote_staging, stage_distribution_with, station_manifest_value,
        validate_staged_runtime_layout, OPTIONAL_VERIFIED_IF_PRESENT_RUNTIME_FILES,
        REQUIRED_STAGED_RUNTIME_FILES,
    };
    use crate::native_distribution::{
        AcquiredDistribution, AcquiredPack, DistributionPack, VerifiedDistribution,
    };
    use crate::native_packs::{VerifiedPack, VerifiedPackFile};
    use serde_json::{json, Value};
    use std::collections::BTreeMap;
    #[cfg(target_os = "windows")]
    use std::fs::OpenOptions;
    #[cfg(target_os = "windows")]
    use std::os::windows::fs::OpenOptionsExt;
    use std::path::{Path, PathBuf};
    #[cfg(target_os = "windows")]
    use std::thread;
    #[cfg(target_os = "windows")]
    use std::time::Duration;

    const COMPONENTS: [&str; 5] = [
        "core",
        "captions-floor",
        "summary-gemma4-12b",
        "summary-gemma4-e4b",
        "translation-translategemma-4b",
    ];

    fn temporary_root(label: &str) -> PathBuf {
        let root = std::env::temp_dir().join(format!(
            "civiccast-native-activation-{label}-{}",
            std::process::id()
        ));
        let _ = std::fs::remove_dir_all(&root);
        std::fs::create_dir_all(&root).expect("create activation root");
        root
    }

    fn acquired() -> AcquiredDistribution {
        let mut index_packs = Vec::new();
        let mut acquired_packs = Vec::new();
        for (number, component) in COMPONENTS.iter().enumerate() {
            let sha = format!("{number:064x}");
            let filename = format!("{component}.ccpack");
            index_packs.push(DistributionPack {
                component: component.to_string(),
                filename,
                bytes: 1,
                sha256: sha.clone(),
                required: true,
                urls: Vec::new(),
            });
            acquired_packs.push(AcquiredPack {
                component: component.to_string(),
                cached_path: PathBuf::from(format!("{component}.ccpack")),
                outer_sha256: sha.clone(),
                verified: VerifiedPack {
                    path: PathBuf::from(format!("{component}.ccpack")),
                    sha256: sha,
                    component: component.to_string(),
                    product_version: "1.0.0-rc15".to_string(),
                    compatible_core: "1.0.0-rc15".to_string(),
                    signing_key_id: "test-key".to_string(),
                    file_count: 1,
                    total_bytes: 1,
                    metadata: BTreeMap::<String, Value>::new(),
                    files: vec![VerifiedPackFile {
                        path: "payload.bin".to_string(),
                        bytes: 1,
                        sha256: format!("{number:064x}"),
                    }],
                },
            });
        }
        AcquiredDistribution {
            index: VerifiedDistribution {
                sha256: "ab".repeat(32),
                kind: "station-index".to_string(),
                channel: "beta".to_string(),
                product_version: "1.0.0-rc15".to_string(),
                compatible_core: "1.0.0-rc15".to_string(),
                signing_key_id: "test-key".to_string(),
                created_epoch: 1_700_000_000,
                packs: index_packs,
            },
            packs: acquired_packs,
        }
    }

    /// `acquired()` plus an OPTIONAL `captions-large-v3` pack, for tests
    /// proving large-v3 is verified and staged when present (never a second
    /// invented fixture shape -- same numbering/hash convention, one more
    /// entry).
    fn acquired_with_large_v3() -> AcquiredDistribution {
        let mut distribution = acquired();
        let number = COMPONENTS.len();
        let component = "captions-large-v3";
        let sha = format!("{number:064x}");
        distribution.index.packs.push(DistributionPack {
            component: component.to_string(),
            filename: format!("{component}.ccpack"),
            bytes: 1,
            sha256: sha.clone(),
            required: false,
            urls: Vec::new(),
        });
        distribution.packs.push(AcquiredPack {
            component: component.to_string(),
            cached_path: PathBuf::from(format!("{component}.ccpack")),
            outer_sha256: sha.clone(),
            verified: VerifiedPack {
                path: PathBuf::from(format!("{component}.ccpack")),
                sha256: sha,
                component: component.to_string(),
                product_version: "1.0.0-rc15".to_string(),
                compatible_core: "1.0.0-rc15".to_string(),
                signing_key_id: "test-key".to_string(),
                file_count: 1,
                total_bytes: 1,
                metadata: BTreeMap::<String, Value>::new(),
                files: vec![VerifiedPackFile {
                    path: "payload.bin".to_string(),
                    bytes: 1,
                    sha256: format!("{number:064x}"),
                }],
            },
        });
        distribution
    }

    #[test]
    fn complete_pack_set_stages_core_and_models_in_one_version_tree() {
        let root = temporary_root("success");
        let distribution = acquired();
        let mut observed_destinations = Vec::new();
        let staged = stage_distribution_with(
            &distribution,
            &root,
            |pack, destination| {
                observed_destinations.push((pack.component.clone(), destination.to_path_buf()));
                std::fs::create_dir_all(destination).map_err(|error| error.to_string())?;
                std::fs::write(destination.join("payload.bin"), pack.component.as_bytes())
                    .map_err(|error| error.to_string())
            },
            |staging, _distribution| {
                assert!(staging.join("payload.bin").is_file());
                assert!(staging
                    .join("packs")
                    .join("captions-floor")
                    .join("payload.bin")
                    .is_file());
                for component in &COMPONENTS[2..] {
                    assert!(staging
                        .join("components")
                        .join(component)
                        .join("payload.bin")
                        .is_file());
                }
                Ok(())
            },
        )
        .expect("complete station stages");

        assert_eq!(staged.version_root, root.join("app").join("1.0.0-rc15"));
        assert!(staged.version_root.join("station-set.json").is_file());
        let station_set: Value = serde_json::from_slice(
            &std::fs::read(staged.version_root.join("station-set.json")).expect("read station set"),
        )
        .expect("parse station set");
        assert_eq!(station_set["schema_version"], 2);
        assert_eq!(station_set["runtime"]["caption_tap"], "inline");
        assert_eq!(station_set["runtime"]["caption_tap_atomic"], true);
        assert_eq!(
            station_set["runtime"]["caption_model_root"],
            "components/captions-large-v3/models/faster-whisper-large-v3"
        );
        assert_eq!(station_set["runtime"]["caption_runtime"], "faster-whisper");
        assert_eq!(station_set["runtime"]["caption_device"], "cpu");
        assert_eq!(station_set["runtime"]["caption_compute_type"], "int8");
        assert_eq!(station_set["runtime"]["egress_engine"], "gstreamer");
        assert_eq!(station_set["runtime"]["egress_embed_captions"], true);
        assert_eq!(station_set["runtime"]["offline_only"], true);
        assert_ne!(observed_destinations[0].1, staged.version_root);
        assert!(observed_destinations[0]
            .1
            .file_name()
            .and_then(|name| name.to_str())
            .is_some_and(|name| name.ends_with(".staging")));
        assert_eq!(
            observed_destinations[1].1,
            observed_destinations[0]
                .1
                .join("packs")
                .join("captions-floor")
        );
        assert!(staged.version_root.join("payload.bin").is_file());
        assert!(!root.join("current").exists());
        std::fs::remove_dir_all(root).expect("clean activation root");
    }

    #[test]
    fn floor_only_distribution_stages_and_activates_successfully() {
        // Owner decision (Scott Converse, 2026-08-07, ratified): large-v3 is
        // optional; the caption FLOOR tier is mandatory. THIS is the actual
        // proof the decision is implemented in the operator/import path --
        // a distribution carrying ONLY the five mandatory components (no
        // `captions-large-v3` pack anywhere in the index or the
        // acquisition) must stage AND activate successfully, exactly like
        // an air-gapped Station-Pack/USB import that never carried the
        // optional large-v3 pack at all.
        let root = temporary_root("floor-only");
        let distribution = acquired();
        assert!(
            distribution
                .packs
                .iter()
                .all(|pack| pack.component != "captions-large-v3"),
            "fixture must carry no large-v3 pack for this to be a real floor-only proof"
        );
        assert!(
            distribution
                .index
                .packs
                .iter()
                .all(|pack| pack.component != "captions-large-v3"),
            "fixture's index must carry no large-v3 pack for this to be a real floor-only proof"
        );

        let staged = stage_distribution_with(
            &distribution,
            &root,
            |pack, destination| {
                std::fs::create_dir_all(destination).map_err(|error| error.to_string())?;
                std::fs::write(destination.join("payload.bin"), pack.component.as_bytes())
                    .map_err(|error| error.to_string())
            },
            |_staging, _distribution| Ok(()),
        )
        .expect("a floor-only distribution must stage and activate successfully");

        assert!(staged
            .version_root
            .join("packs")
            .join("captions-floor")
            .join("payload.bin")
            .is_file());
        assert!(!staged.version_root.join("components").join("captions-large-v3").exists());

        let station_set: Value = serde_json::from_slice(
            &std::fs::read(staged.version_root.join("station-set.json")).expect("read station set"),
        )
        .expect("parse station set");
        let packs = station_set["packs"].as_array().expect("packs array");
        assert!(
            packs
                .iter()
                .any(|pack| pack["component"] == "captions-floor" && pack["root"] == "packs/captions-floor"),
            "station-set.json must record the staged floor caption pack"
        );
        assert!(
            !packs.iter().any(|pack| pack["component"] == "captions-large-v3"),
            "station-set.json must not claim an unstaged optional large-v3 pack"
        );
        std::fs::remove_dir_all(root).expect("clean activation root");
    }

    #[test]
    fn large_v3_is_staged_and_recorded_when_present_alongside_the_mandatory_floor_tier() {
        // The flip side of the floor-only proof above: large-v3 is
        // verified and staged when a distribution DOES carry it -- never a
        // silently-dropped optional component.
        let root = temporary_root("floor-plus-large-v3");
        let distribution = acquired_with_large_v3();

        let staged = stage_distribution_with(
            &distribution,
            &root,
            |pack, destination| {
                std::fs::create_dir_all(destination).map_err(|error| error.to_string())?;
                std::fs::write(destination.join("payload.bin"), pack.component.as_bytes())
                    .map_err(|error| error.to_string())
            },
            |_staging, _distribution| Ok(()),
        )
        .expect("a floor-plus-large-v3 distribution must stage and activate successfully");

        assert!(staged
            .version_root
            .join("components")
            .join("captions-large-v3")
            .join("payload.bin")
            .is_file());
        assert!(staged
            .version_root
            .join("packs")
            .join("captions-floor")
            .join("payload.bin")
            .is_file());

        let station_set: Value = serde_json::from_slice(
            &std::fs::read(staged.version_root.join("station-set.json")).expect("read station set"),
        )
        .expect("parse station set");
        let packs = station_set["packs"].as_array().expect("packs array");
        assert!(packs.iter().any(|pack| pack["component"] == "captions-large-v3"
            && pack["root"] == "components/captions-large-v3"));
        std::fs::remove_dir_all(root).expect("clean activation root");
    }

    // ---- K1 fix: flat-layout activation (`activate_flat_station_with`) ----
    //
    // These prove `activate_flat_station_with` writes `station-set.json` and
    // `activation-self-test.json` DIRECTLY at `install_root` -- no
    // `app/<version>` subdirectory -- and that it shares its manifest
    // composition with the versioned writer above (`station_manifest_value`),
    // never a second, drifting implementation.

    fn fake_receipt(distribution: &crate::native_distribution::AcquiredDistribution) -> Value {
        json!({
            "schema_version": 1,
            "product": "civiccast-native",
            "product_version": distribution.index.product_version,
            "distribution_index_sha256": distribution.index.sha256,
            "caption_inference": {
                "runtime": "faster-whisper 1.2.1",
                "ctranslate2": "4.8.1",
                "model": "Systran/faster-whisper-medium@test-revision",
                "model_path": "packs/captions-floor/models/faster-whisper-medium",
                "model_bin_bytes": 17_u64,
                "model_bin_sha256": "0".repeat(64),
                "device": "cpu",
                "compute_type": "int8",
                "local_files_only": true,
                "result": "passed",
            },
            "ai_inference": {
                "runtime": "Ollama 0.30.6",
                "models": ["gemma4:12b", "gemma4:e4b", "translategemma:4b"],
                "offline_only": true,
                "result": "passed",
            },
        })
    }

    /// Fake `extract` closure for the `activate_flat_station_with` tests
    /// below -- mirrors `stage_distribution_with`'s own tests' fake extract
    /// (a tiny `payload.bin`), EXCEPT for the three Ollama-model components,
    /// which get a real `blobs/` + `manifests/` shape (matching
    /// `required_model_packs_compose_one_ollama_store_without_duplicate_bytes`'s
    /// fixture below) so `compose_ollama_model_store` -- now called
    /// unconditionally at the end of extraction -- has something valid to
    /// compose rather than failing every one of these tests on a missing
    /// subtree.
    fn fake_component_extract(pack: &AcquiredPack, destination: &Path) -> Result<(), String> {
        const OLLAMA_MODEL_COMPONENTS: [&str; 3] = [
            "summary-gemma4-12b",
            "summary-gemma4-e4b",
            "translation-translategemma-4b",
        ];
        if OLLAMA_MODEL_COMPONENTS.contains(&pack.component.as_str()) {
            std::fs::create_dir_all(destination.join("blobs")).map_err(|error| error.to_string())?;
            std::fs::create_dir_all(destination.join("manifests"))
                .map_err(|error| error.to_string())?;
            std::fs::write(
                destination.join("blobs").join(format!("sha256-{}", pack.component)),
                pack.component.as_bytes(),
            )
            .map_err(|error| error.to_string())
        } else {
            std::fs::create_dir_all(destination).map_err(|error| error.to_string())?;
            std::fs::write(destination.join("payload.bin"), pack.component.as_bytes())
                .map_err(|error| error.to_string())
        }
    }

    #[test]
    fn flat_activation_writes_both_files_directly_at_install_root_and_they_parse() {
        let root = temporary_root("flat-activate");
        let distribution = acquired();

        let activation = activate_flat_station_with(
            &root,
            &distribution,
            fake_component_extract,
            |staging, distribution| {
                assert_eq!(staging, root, "self_test must run against install_root itself");
                Ok(fake_receipt(distribution))
            },
        )
        .expect("a complete distribution must activate a flat station");

        assert!(!activation.already_activated);
        assert_eq!(activation.station_manifest, root.join("station-set.json"));
        assert_eq!(activation.activation_receipt, root.join("activation-self-test.json"));
        // Flat: directly at install_root, never under app/<version>.
        assert!(!root.join("app").exists());
        // core is NEVER extracted in the flat layout (see the function doc)
        // -- only its manifest bookkeeping entry exists.
        assert!(!root.join("payload.bin").exists());
        // The other required components ARE extracted, at their pinned
        // destinations.
        assert!(root
            .join("packs")
            .join("captions-floor")
            .join("payload.bin")
            .is_file());
        assert!(root
            .join("components")
            .join("summary-gemma4-12b")
            .join("blobs")
            .exists());
        // The merged Ollama store was composed from the three extracted
        // model components.
        assert!(root
            .join("models")
            .join("ollama")
            .join("blobs")
            .join("sha256-summary-gemma4-12b")
            .is_file());

        let station_set: Value =
            serde_json::from_slice(&std::fs::read(&activation.station_manifest).expect("read manifest"))
                .expect("parse manifest");
        assert_eq!(station_set, station_manifest_value(&distribution));

        let receipt: Value =
            serde_json::from_slice(&std::fs::read(&activation.activation_receipt).expect("read receipt"))
                .expect("parse receipt");
        assert_eq!(receipt["schema_version"], 1);
        assert_eq!(receipt["product_version"], distribution.index.product_version);
        assert_eq!(receipt["distribution_index_sha256"], distribution.index.sha256);

        std::fs::remove_dir_all(root).expect("clean activation root");
    }

    #[test]
    fn flat_activation_is_idempotent_and_never_reruns_self_test_on_an_already_activated_root() {
        let root = temporary_root("flat-activate-idempotent");
        let distribution = acquired();

        let first = activate_flat_station_with(
            &root,
            &distribution,
            fake_component_extract,
            |_staging, distribution| Ok(fake_receipt(distribution)),
        )
        .expect("first activation succeeds");
        assert!(!first.already_activated);

        let second = activate_flat_station_with(
            &root,
            &distribution,
            |_pack, _destination| {
                panic!("extract must never be invoked on an already-matching flat activation");
            },
            |_staging, _distribution| {
                panic!("self_test must never be invoked on an already-matching flat activation");
            },
        )
        .expect("a re-run over an already-activated flat station must succeed");
        assert!(second.already_activated);
        assert_eq!(second.station_manifest, first.station_manifest);

        std::fs::remove_dir_all(root).expect("clean activation root");
    }

    #[test]
    fn flat_activation_failure_leaves_no_partial_manifest_or_receipt() {
        let root = temporary_root("flat-activate-self-test-fails");
        let distribution = acquired();

        let error = activate_flat_station_with(
            &root,
            &distribution,
            fake_component_extract,
            |_staging, _distribution| Err("caption decode-back failed".to_string()),
        )
        .expect_err("a failed self-test blocks flat activation");

        assert!(error.contains("caption decode-back failed"));
        assert!(!root.join("station-set.json").exists());
        assert!(!root.join("activation-self-test.json").exists());
        assert!(!root.join("station-set.json.partial").exists());
        assert!(!root.join("activation-self-test.json.partial").exists());

        std::fs::remove_dir_all(root).expect("clean activation root");
    }

    #[test]
    fn flat_activation_rolls_back_the_receipt_if_the_manifest_write_fails() {
        // Simulate a manifest-write failure by pre-occupying its `.partial`
        // staging path with a DIRECTORY (so `write_json_atomically`'s
        // `create_new` open fails) -- the receipt, written first and
        // successfully, must be rolled back rather than left standing alone.
        let root = temporary_root("flat-activate-manifest-write-fails");
        std::fs::create_dir_all(root.join("station-set.json.partial"))
            .expect("occupy manifest partial path");

        let distribution = acquired();
        let error = activate_flat_station_with(
            &root,
            &distribution,
            fake_component_extract,
            |_staging, distribution| Ok(fake_receipt(distribution)),
        )
        .expect_err("a manifest write failure must fail activation");

        assert!(error.contains("Could not"));
        assert!(!root.join("activation-self-test.json").exists());
        assert!(!root.join("activation-self-test.json.partial").exists());

        std::fs::remove_dir_all(root).expect("clean activation root");
    }

    #[test]
    fn flat_activation_cleanly_rewrites_stale_content_for_a_different_distribution() {
        let root = temporary_root("flat-activate-stale-rewrite");
        let first_distribution = acquired();
        let first = activate_flat_station_with(
            &root,
            &first_distribution,
            fake_component_extract,
            |_staging, distribution| Ok(fake_receipt(distribution)),
        )
        .expect("first activation succeeds");
        assert!(!first.already_activated);

        // A distribution with a DIFFERENT index sha -- the stale-content
        // case: an existing pair (and its extracted component trees) that
        // does not match the distribution now being activated must be
        // cleanly replaced, not merged with.
        let mut second_distribution = acquired();
        second_distribution.index.sha256 = "cd".repeat(32);

        let mut self_test_ran = false;
        let second = activate_flat_station_with(
            &root,
            &second_distribution,
            fake_component_extract,
            |_staging, distribution| {
                self_test_ran = true;
                Ok(fake_receipt(distribution))
            },
        )
        .expect("a stale pair for a different distribution must cleanly rewrite");
        assert!(!second.already_activated);
        assert!(self_test_ran, "a mismatched existing pair must re-run self_test");

        let station_set: Value =
            serde_json::from_slice(&std::fs::read(&second.station_manifest).expect("read manifest"))
                .expect("parse manifest");
        assert_eq!(
            station_set["distribution_index_sha256"],
            second_distribution.index.sha256
        );

        std::fs::remove_dir_all(root).expect("clean activation root");
    }

    #[test]
    fn flat_activation_never_extracts_core_onto_the_already_staged_runtime() {
        // The already-staged runtime (from --civiccast-stage-packs) is
        // simulated by files that already exist at install_root BEFORE
        // activation runs. If core's payload were ever extracted here, this
        // marker file would be at risk of collision/overwrite; asserting it
        // is untouched proves core extraction really is skipped, not just
        // that no *new* core files happen to appear.
        let root = temporary_root("flat-activate-core-untouched");
        std::fs::create_dir_all(root.join("runtime")).expect("simulate staged runtime dir");
        std::fs::write(root.join("runtime").join("python.exe"), b"already-staged-by-stage-packs")
            .expect("simulate staged runtime file");
        let distribution = acquired();

        activate_flat_station_with(
            &root,
            &distribution,
            fake_component_extract,
            |_staging, distribution| Ok(fake_receipt(distribution)),
        )
        .expect("activation succeeds without touching core");

        assert_eq!(
            std::fs::read(root.join("runtime").join("python.exe")).expect("still present"),
            b"already-staged-by-stage-packs",
            "core extraction must never overwrite the already-staged runtime"
        );

        std::fs::remove_dir_all(root).expect("clean activation root");
    }

    // ---- K1 P2 fix: the idempotency fast-path must not diverge from the
    // runtime's `_validate_activation_receipt` ----
    //
    // `flat_activation_already_matches` returning `true` skips extraction AND
    // the caption-inference self-test and reports "already activated". A
    // receipt that is valid JSON with a matching version+index but is
    // otherwise stale/damaged (missing `schema_version`/`product`, or a
    // `caption_inference` that is absent or not an object) must NOT take that
    // fast-path -- otherwise the CLI claims success while the service rejects
    // the same receipt, and re-running activation can never repair it. Each
    // test below writes a manifest that DOES match (so only the receipt is
    // under test) and asserts the probe refuses the fast-path -- except the
    // positive control, which proves a fully-formed receipt IS accepted.

    /// Write `station-set.json` (matching `distribution`) plus a receipt
    /// `Value`, then run the probe against them. Mirrors the K1 tests' own
    /// on-disk manifest+receipt setup, isolating the receipt as the variable
    /// under test.
    fn already_matches_for_receipt(
        label: &str,
        distribution: &crate::native_distribution::AcquiredDistribution,
        receipt: &Value,
    ) -> bool {
        let root = temporary_root(label);
        let manifest_path = root.join("station-set.json");
        let receipt_path = root.join("activation-self-test.json");
        let manifest_value = station_manifest_value(distribution);
        std::fs::write(
            &manifest_path,
            serde_json::to_vec(&manifest_value).expect("serialize manifest"),
        )
        .expect("write matching manifest");
        std::fs::write(
            &receipt_path,
            serde_json::to_vec(receipt).expect("serialize receipt"),
        )
        .expect("write receipt under test");
        let matched = flat_activation_already_matches(
            &manifest_path,
            &receipt_path,
            &manifest_value,
            distribution,
        );
        std::fs::remove_dir_all(root).expect("clean probe root");
        matched
    }

    #[test]
    fn idempotent_fast_path_accepts_a_fully_formed_receipt() {
        // POSITIVE control: schema_version 1, exact product, matching
        // version+index, caption_inference an object -> fast-path taken.
        let distribution = acquired();
        assert!(
            already_matches_for_receipt(
                "already-match-positive",
                &distribution,
                &fake_receipt(&distribution),
            ),
            "a complete, runtime-valid-shaped receipt must take the idempotent fast-path"
        );
    }

    #[test]
    fn idempotent_fast_path_refused_when_schema_version_is_missing() {
        let distribution = acquired();
        let mut receipt = fake_receipt(&distribution);
        receipt
            .as_object_mut()
            .expect("receipt is an object")
            .remove("schema_version");
        assert!(
            !already_matches_for_receipt("already-match-no-schema", &distribution, &receipt),
            "a receipt missing schema_version must fall through to re-activation"
        );
    }

    #[test]
    fn idempotent_fast_path_refused_when_schema_version_is_not_one() {
        let distribution = acquired();
        let mut receipt = fake_receipt(&distribution);
        receipt["schema_version"] = Value::from(2);
        assert!(
            !already_matches_for_receipt("already-match-schema-2", &distribution, &receipt),
            "a receipt with schema_version != 1 must fall through to re-activation"
        );
    }

    #[test]
    fn idempotent_fast_path_refused_when_product_is_wrong_or_missing() {
        let distribution = acquired();

        let mut wrong = fake_receipt(&distribution);
        wrong["product"] = Value::String("civiccast-wsl".to_string());
        assert!(
            !already_matches_for_receipt("already-match-wrong-product", &distribution, &wrong),
            "a receipt with the wrong product must fall through to re-activation"
        );

        let mut missing = fake_receipt(&distribution);
        missing
            .as_object_mut()
            .expect("receipt is an object")
            .remove("product");
        assert!(
            !already_matches_for_receipt("already-match-no-product", &distribution, &missing),
            "a receipt missing product must fall through to re-activation"
        );
    }

    #[test]
    fn idempotent_fast_path_refused_when_caption_inference_absent_or_not_an_object() {
        let distribution = acquired();

        let mut missing = fake_receipt(&distribution);
        missing
            .as_object_mut()
            .expect("receipt is an object")
            .remove("caption_inference");
        assert!(
            !already_matches_for_receipt("already-match-no-caption", &distribution, &missing),
            "a receipt missing caption_inference must fall through to re-activation"
        );

        let mut scalar = fake_receipt(&distribution);
        scalar["caption_inference"] = Value::String("passed".to_string());
        assert!(
            !already_matches_for_receipt("already-match-caption-string", &distribution, &scalar),
            "a receipt whose caption_inference is a string must fall through to re-activation"
        );
    }

    #[cfg(target_os = "windows")]
    #[test]
    fn promotion_waits_for_a_terminating_runtime_to_release_staged_files() {
        let root = temporary_root("promotion-sharing");
        let distribution = acquired();
        let mut lock_holder = None;

        let staged_result = stage_distribution_with(
            &distribution,
            &root,
            |pack, destination| {
                std::fs::create_dir_all(destination).map_err(|error| error.to_string())?;
                std::fs::write(destination.join("payload.bin"), pack.component.as_bytes())
                    .map_err(|error| error.to_string())
            },
            |staging, _distribution| {
                let model = staging.join("payload.bin");
                const FILE_SHARE_READ: u32 = 0x0000_0001;
                let mut options = OpenOptions::new();
                options.read(true).share_mode(FILE_SHARE_READ);
                let handle = options.open(&model).map_err(|error| error.to_string())?;
                lock_holder = Some(thread::spawn(move || {
                    thread::sleep(Duration::from_millis(750));
                    drop(handle);
                }));
                Ok(())
            },
        );

        let holder = match lock_holder {
            Some(holder) => holder,
            None => {
                let _ = std::fs::remove_dir_all(&root);
                panic!("lock holder must acquire the staged payload");
            }
        };
        if holder.join().is_err() {
            let _ = std::fs::remove_dir_all(&root);
            panic!("release staged-file handle");
        }
        let staged = match staged_result {
            Ok(staged) => staged,
            Err(error) => {
                let _ = std::fs::remove_dir_all(&root);
                panic!("promotion must retry transient Windows sharing: {error}");
            }
        };
        let promoted_payload_exists = staged.version_root.join("payload.bin").is_file();
        std::fs::remove_dir_all(root).expect("clean activation root");
        assert!(promoted_payload_exists);
    }

    #[cfg(target_os = "windows")]
    #[test]
    fn promotion_does_not_retry_a_non_sharing_filesystem_error() {
        let root = temporary_root("promotion-non-sharing");
        let staging = root.join("staging");
        let target = root.join("existing-target");
        std::fs::create_dir_all(&staging).expect("staging");
        std::fs::create_dir_all(&target).expect("target");
        std::fs::write(staging.join("new.txt"), b"new").expect("staged file");
        std::fs::write(target.join("existing.txt"), b"existing").expect("existing file");
        let started = std::time::Instant::now();

        let error = promote_staging(&staging, &target).expect_err("existing target must fail");

        assert!(
            started.elapsed() < Duration::from_secs(1),
            "non-sharing filesystem errors must fail without retrying"
        );
        assert!(error.contains("Could not atomically promote"));
        assert!(staging.join("new.txt").is_file());
        assert!(target.join("existing.txt").is_file());
        std::fs::remove_dir_all(root).expect("clean activation root");
    }

    // REWRITTEN 2026-08-07 (owner decision, ratified): this test used to
    // pin `captions-large-v3` as the mandatory caption pack. The owner has
    // since ruled large-v3 OPTIONAL and the caption FLOOR tier
    // (`captions-floor`) MANDATORY -- the whole point of this slice. The
    // pinning behavior this test protects (a missing mandatory caption pack
    // fails staging before any extraction runs) is preserved; only WHICH
    // component is mandatory changed. See
    // `floor_only_distribution_stages_and_activates_successfully` below for
    // the companion proof that a floor-only (no large-v3) distribution
    // stages successfully -- that test is the actual proof the owner's
    // decision is implemented, not just that this one didn't regress.
    #[test]
    fn missing_floor_caption_pack_fails_before_any_extraction() {
        let root = temporary_root("missing");
        let mut distribution = acquired();
        distribution
            .packs
            .retain(|pack| pack.component != "captions-floor");
        let mut called = false;

        let error = stage_distribution_with(
            &distribution,
            &root,
            |_pack, _destination| {
                called = true;
                Ok(())
            },
            |_staging, _distribution| Ok(()),
        )
        .expect_err("missing mandatory floor caption pack cannot stage");

        assert!(error.contains("complete required pack set"));
        assert!(!called);
        assert!(!root.join("app").exists());
        std::fs::remove_dir_all(root).expect("clean activation root");
    }

    #[test]
    fn failed_offline_self_test_never_promotes_or_leaves_staging() {
        let root = temporary_root("self-test");
        let distribution = acquired();

        let error = stage_distribution_with(
            &distribution,
            &root,
            |_pack, destination| {
                std::fs::create_dir_all(destination).map_err(|error| error.to_string())
            },
            |_staging, _distribution| Err("caption decode-back failed".to_string()),
        )
        .expect_err("failed self-test blocks activation");

        assert!(error.contains("caption decode-back failed"));
        assert!(!root.join("app").join("1.0.0-rc15").exists());
        let leftovers = std::fs::read_dir(root.join("app"))
            .expect("app root")
            .count();
        assert_eq!(leftovers, 0);
        std::fs::remove_dir_all(root).expect("clean activation root");
    }

    #[test]
    fn an_unrecognized_existing_version_tree_is_never_overwritten() {
        let root = temporary_root("existing");
        let target = root.join("app").join("1.0.0-rc15");
        std::fs::create_dir_all(&target).expect("existing target");
        std::fs::write(target.join("unknown.exe"), b"do not overwrite").expect("existing file");

        let error = stage_distribution_with(
            &acquired(),
            &root,
            |_pack, _destination| Ok(()),
            |_staging, _distribution| Ok(()),
        )
        .expect_err("foreign existing tree blocks");

        assert!(error.contains("already exists"));
        assert_eq!(
            std::fs::read(target.join("unknown.exe")).expect("preserved"),
            b"do not overwrite"
        );
        std::fs::remove_dir_all(root).expect("clean activation root");
    }

    #[test]
    fn required_model_packs_compose_one_ollama_store_without_duplicate_bytes() {
        let root = temporary_root("model-compose");
        let staging = root.join("staging");
        for (component, repository, tag, unique) in [
            ("summary-gemma4-12b", "gemma4", "12b", b"twelve".as_slice()),
            (
                "summary-gemma4-e4b",
                "gemma4",
                "e4b",
                b"efficient".as_slice(),
            ),
            (
                "translation-translategemma-4b",
                "translategemma",
                "4b",
                b"translate".as_slice(),
            ),
        ] {
            let component_root = staging.join("components").join(component);
            let blobs = component_root.join("blobs");
            let manifest = component_root
                .join("manifests")
                .join("registry.ollama.ai")
                .join("library")
                .join(repository);
            std::fs::create_dir_all(&blobs).expect("blob root");
            std::fs::create_dir_all(&manifest).expect("manifest root");
            std::fs::write(blobs.join("sha256-shared"), b"shared").expect("shared blob");
            std::fs::write(blobs.join(format!("sha256-{component}")), unique).expect("unique blob");
            std::fs::write(manifest.join(tag), component.as_bytes()).expect("manifest");
        }

        compose_ollama_model_store(&staging).expect("compose model store");

        let models = staging.join("models").join("ollama");
        assert_eq!(
            std::fs::read(models.join("blobs").join("sha256-shared")).expect("shared"),
            b"shared"
        );
        assert!(models
            .join("manifests")
            .join("registry.ollama.ai")
            .join("library")
            .join("gemma4")
            .join("12b")
            .is_file());
        assert!(models
            .join("manifests")
            .join("registry.ollama.ai")
            .join("library")
            .join("translategemma")
            .join("4b")
            .is_file());
        std::fs::remove_dir_all(root).expect("clean model compose root");
    }

    #[test]
    fn conflicting_shared_model_blob_fails_closed() {
        let root = temporary_root("model-conflict");
        let staging = root.join("staging");
        for (component, body) in [
            ("summary-gemma4-12b", b"first".as_slice()),
            ("summary-gemma4-e4b", b"second".as_slice()),
            ("translation-translategemma-4b", b"first".as_slice()),
        ] {
            let component_root = staging.join("components").join(component);
            std::fs::create_dir_all(component_root.join("blobs")).expect("blob root");
            std::fs::create_dir_all(component_root.join("manifests")).expect("manifest root");
            std::fs::write(component_root.join("blobs").join("sha256-shared"), body)
                .expect("shared blob");
        }

        let error = compose_ollama_model_store(&staging)
            .expect_err("conflicting signed packs cannot compose");

        assert!(error.contains("disagree on shared model bytes"));
        std::fs::remove_dir_all(root).expect("clean conflict root");
    }

    #[allow(dead_code)]
    fn _assert_path(_: &Path) {}

    /// Build a minimal staged tree with the CORRECT runtime layout: every path
    /// in `REQUIRED_STAGED_RUNTIME_FILES` created as a real regular file (server
    /// binaries under `packs/native-server-binaries/payload/bin`, tsp under
    /// `payload/tsduck/bin`, ffmpeg/ollama under `dependencies/`, python under
    /// `runtime/`, plus the caption-floor and ollama-manifest members). No
    /// `components/captions-large-v3` dir, so the optional large-v3 block is
    /// correctly skipped. Mirrors how the other tests here fabricate trees with
    /// `create_dir_all` + `write`.
    fn stage_correct_runtime_layout(label: &str) -> PathBuf {
        let staging = temporary_root(label);
        for relative in REQUIRED_STAGED_RUNTIME_FILES
            .iter()
            .chain(OPTIONAL_VERIFIED_IF_PRESENT_RUNTIME_FILES)
        {
            let path = staging.join(relative);
            if let Some(parent) = path.parent() {
                std::fs::create_dir_all(parent).expect("create staged parent dir");
            }
            std::fs::write(&path, b"x").expect("write staged runtime file");
        }
        staging
    }

    #[test]
    fn validate_staged_runtime_layout_passes_on_the_real_runtime_layout() {
        // K1 activation defect guard. The production path never exercised
        // `validate_staged_runtime_layout` (the existing staging tests pass a
        // MOCK self_test closure), so the required-path list silently pointed at
        // `dependencies/postgresql|nats|tsduck` and `dependencies/node` -- paths
        // the product never stages there -- and every real install failed the
        // self-test (exit 67 -> installer 123). This asserts the corrected list
        // PASSES against a tree built at the ACTUAL runtime layout
        // (`install_layout.py`).
        let staging = stage_correct_runtime_layout("selftest-correct-layout");
        validate_staged_runtime_layout(&staging)
            .expect("the corrected required-file list must pass against the real runtime layout");
        std::fs::remove_dir_all(&staging).expect("clean staging");
    }

    #[test]
    fn validate_staged_runtime_layout_fails_when_a_repathed_server_binary_is_missing() {
        // The other half of the guard: a tree that is correct EXCEPT for the
        // repathed postgres binary must FAIL, naming the real staged path -- so
        // a future regression that stops staging postgres.exe there (or reverts
        // the path) is caught, not silently passed.
        let staging = stage_correct_runtime_layout("selftest-missing-postgres");
        let postgres = staging.join("packs/native-server-binaries/payload/bin/postgres.exe");
        std::fs::remove_file(&postgres).expect("remove staged postgres binary");

        let error = validate_staged_runtime_layout(&staging)
            .expect_err("a missing repathed server binary must fail validation");
        assert!(
            error.contains("packs/native-server-binaries/payload/bin/postgres.exe"),
            "error must name the real staged postgres path, got: {error}"
        );
        std::fs::remove_dir_all(&staging).expect("clean staging");
    }

    #[test]
    fn required_staged_runtime_files_use_the_real_runtime_layout_not_the_wrong_convention() {
        // Cheap guard against re-introducing the wrong convention. The K1 defect
        // was postgres/nats/tsduck listed under `dependencies/` and node listed
        // at all; none of those substrings may reappear, and the real
        // server-pack paths must be present. NATS JetStream was removed from
        // the product (owner decision 2026-08-20; see ADR 0023, which
        // supersedes ADR 0001), so `dependencies/nats` stays in the
        // never-reappear list defensively even though nats-server.exe is no
        // longer staged at all.
        for wrong in [
            "dependencies/postgresql",
            "dependencies/nats",
            "dependencies/tsduck",
            "dependencies/node",
        ] {
            assert!(
                !REQUIRED_STAGED_RUNTIME_FILES
                    .iter()
                    .any(|path| path.contains(wrong)),
                "required-file list must not re-introduce the wrong convention: {wrong}"
            );
        }
        for expected in [
            "packs/native-server-binaries/payload/bin/postgres.exe",
            "packs/native-server-binaries/payload/bin/pg_ctl.exe",
        ] {
            assert!(
                REQUIRED_STAGED_RUNTIME_FILES.contains(&expected),
                "required-file list must pin the real staged server-pack path: {expected}"
            );
        }
    }

    #[test]
    fn tsp_exe_is_optional_not_hard_required() {
        // K1-1: tsp.exe must NOT be in the hard-required list -- the runtime
        // (egress/ts_relay.py, CIVICCAST_TS_RELAY=auto) warns and passes
        // through when TSDuck is unavailable rather than treating it as a
        // hard requirement, and activation must match that posture.
        assert!(
            !REQUIRED_STAGED_RUNTIME_FILES
                .iter()
                .any(|path| path.contains("tsp.exe")),
            "tsp.exe must not be a hard-required staged file (K1-1)"
        );
        assert!(
            OPTIONAL_VERIFIED_IF_PRESENT_RUNTIME_FILES
                .contains(&"packs/native-server-binaries/payload/tsduck/bin/tsp.exe"),
            "tsp.exe must still be verified-if-present at the real staged server-pack path"
        );
    }

    #[test]
    fn validate_staged_runtime_layout_passes_when_optional_tsp_is_absent() {
        // K1-1: an otherwise-correct layout with NO staged tsp.exe at all
        // must still pass activation -- TSDuck is optional.
        let staging = stage_correct_runtime_layout("selftest-tsp-absent");
        let tsp = staging.join("packs/native-server-binaries/payload/tsduck/bin/tsp.exe");
        std::fs::remove_file(&tsp).expect("remove staged tsp binary");

        validate_staged_runtime_layout(&staging)
            .expect("activation must not hard-fail when optional tsp.exe is absent");
        std::fs::remove_dir_all(&staging).expect("clean staging");
    }

    #[test]
    fn validate_staged_runtime_layout_fails_when_a_present_optional_file_is_broken() {
        // K1-1's other half: "verified-if-present" means present-but-broken
        // (here: a directory instead of a regular file) still fails --
        // making the requirement soft must never mean skipping verification
        // of whatever IS actually staged there.
        let staging = stage_correct_runtime_layout("selftest-tsp-broken");
        let tsp = staging.join("packs/native-server-binaries/payload/tsduck/bin/tsp.exe");
        std::fs::remove_file(&tsp).expect("remove staged tsp binary");
        std::fs::create_dir_all(&tsp).expect("stage a directory where tsp.exe should be");

        let error = validate_staged_runtime_layout(&staging)
            .expect_err("a present-but-broken optional file must still fail validation");
        assert!(
            error.contains("packs/native-server-binaries/payload/tsduck/bin/tsp.exe"),
            "error must name the broken optional staged path, got: {error}"
        );
        std::fs::remove_dir_all(&staging).expect("clean staging");
    }

    #[test]
    fn validate_staged_runtime_layout_fails_when_pg_ctl_is_missing() {
        // K1-2: the self-test must verify pg_ctl.exe -- the binary the
        // supervisor actually launches (children.py::postgres_child_spec
        // builds argv=[pg_ctl_path, "start", ...]) -- not just postgres.exe.
        let staging = stage_correct_runtime_layout("selftest-missing-pg-ctl");
        let pg_ctl = staging.join("packs/native-server-binaries/payload/bin/pg_ctl.exe");
        std::fs::remove_file(&pg_ctl).expect("remove staged pg_ctl binary");

        let error = validate_staged_runtime_layout(&staging)
            .expect_err("a missing pg_ctl.exe must fail validation");
        assert!(
            error.contains("packs/native-server-binaries/payload/bin/pg_ctl.exe"),
            "error must name the real staged pg_ctl path, got: {error}"
        );
        std::fs::remove_dir_all(&staging).expect("clean staging");
    }
}
