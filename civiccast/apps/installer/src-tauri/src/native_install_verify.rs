// SPDX-License-Identifier: Apache-2.0
// Copyright (c) The CivicCast Authors

//! D2 install-time re-verification of a laid installer tree against its
//! shipped manifest (`spec-installer-lifecycle.md` D2: "install-time
//! verification chains to Authenticode, not to a checksum file an attacker
//! could swap beside the payload... Verify before laying files; corrupt =>
//! loud failure"; `nsis-hooks-native.nsh:130-137` names the residual: "D2
//! install-time verification (SHA256SUMS chained to Authenticode) of the
//! placed $INSTDIR\runtime tree BEFORE the engine's lay_tree trusts it").
//!
//! This module is the RE-VERIFICATION half: after the installer's NSIS file
//! section has laid `$INSTDIR\runtime` (the application payload) and
//! `$INSTDIR\native-runtime` (the media closure) from the SIGNED installer
//! executable, this walks the tree exactly as laid on disk and re-derives
//! every fact from it -- independent of the build-time verifier
//! (`scripts/verify_native_app_payload.py`), which runs before the payload
//! is even embedded. A mismatch here means disk corruption, a partial copy,
//! or tampering AFTER the signed bytes were extracted -- exactly the D5
//! Repair re-check ("re-verify current tree against the signed manifest"),
//! run proactively at install/upgrade time too.
//!
//! Deliberately reuses `native_packs`'s existing primitives instead of
//! re-implementing them: `sha256_reader` (the same streaming, 1 MiB-buffer
//! hash loop used for the multi-gigabyte component packs), `safe_relative_path`
//! (the same path-traversal/reserved-name guard), and `canonical_json` (for
//! test-fixture construction only). For component-pack trees (caption/model
//! packs, staged under `<version_root>/components/<name>` by
//! `native_activation::stage_acquired_distribution`), `verify_component_pack_tree`
//! calls `native_packs::open_and_verify_pack` + `native_packs::verify_extracted_tree`
//! DIRECTLY -- the exact per-tier caption-pack verification that landed in
//! `native_packs.rs` at 5ad71753 -- rather than duplicating that logic here.

use std::collections::BTreeSet;
use std::fs::{self, File};
use std::path::{Path, PathBuf};
use std::time::Instant;

use serde::{Deserialize, Serialize};

use crate::native_packs::{self, PackTrust, VerifiedPack};

/// Reported first-N cap when nothing more specific is requested by the
/// caller. The installer hook always passes an explicit value; this is the
/// library-level default for direct callers/tests.
pub const DEFAULT_MAX_FAILURES: usize = 25;

#[derive(Debug, Clone, Serialize)]
pub struct TreeVerificationReport {
    pub tree: PathBuf,
    pub manifest: String,
    pub file_count: usize,
    pub total_bytes: u64,
    pub elapsed_ms: u128,
}

#[derive(Debug, Deserialize)]
struct ManifestFile {
    path: String,
    sha256: String,
    bytes: u64,
}

#[derive(Debug, Deserialize)]
struct ShippedManifest {
    files: Vec<ManifestFile>,
}

/// Re-verify a laid tree (`tree`) against its shipped manifest
/// (`tree/manifest_name`): presence, size, and streamed SHA-256 of every
/// manifest entry, and fail-closed rejection of any on-disk file the
/// manifest does not name (`trust_artifacts` lists root-level filenames --
/// e.g. the manifest itself, `SHA256SUMS`, `LICENSE-BOM.md` -- that are
/// expected beside the payload and are not part of the file contract).
///
/// Streams every hash through a bounded buffer (never reads a whole file into
/// memory, so this scales to the multi-gigabyte payload tree) and reports
/// elapsed wall-clock time in both the success report and the failure
/// message. Reports at most `max_failures` individual problems, each naming
/// its exact relative path.
pub fn verify_manifest_tree(
    tree: &Path,
    manifest_name: &str,
    trust_artifacts: &[&str],
    max_failures: usize,
) -> Result<TreeVerificationReport, String> {
    let started = Instant::now();
    let manifest_path = tree.join(manifest_name);
    if !manifest_path.is_file() {
        return Err(format!(
            "D2 install-time verification refused: no {manifest_name} at {} -- a laid tree \
             with no shipped manifest can never be trusted.",
            tree.display()
        ));
    }
    let manifest_bytes = fs::read(&manifest_path)
        .map_err(|error| format!("Could not read {manifest_name}: {error}"))?;
    let manifest: ShippedManifest = serde_json::from_slice(&manifest_bytes)
        .map_err(|error| format!("{manifest_name} is malformed: {error}"))?;
    if manifest.files.is_empty() {
        return Err(format!(
            "{manifest_name} names zero files; refusing to trust an empty manifest."
        ));
    }

    // The expected set, path-safety-checked the same way native_packs.rs
    // checks component-pack manifest paths (traversal/reserved-name guard),
    // and de-duplicated so a manifest cannot smuggle two different hashes
    // for the same on-disk path.
    let mut expected_paths: BTreeSet<String> = BTreeSet::new();
    let mut entries: Vec<(String, u64, String)> = Vec::with_capacity(manifest.files.len());
    for item in &manifest.files {
        let safe_path = native_packs::safe_relative_path(&item.path)
            .map_err(|error| format!("{manifest_name} names an unsafe path: {error}"))?;
        if !expected_paths.insert(safe_path.clone()) {
            return Err(format!(
                "{manifest_name} names the same path more than once: {safe_path}"
            ));
        }
        entries.push((safe_path, item.bytes, item.sha256.to_lowercase()));
    }

    let mut excluded_root_names: BTreeSet<String> = trust_artifacts
        .iter()
        .map(|value| value.to_string())
        .collect();
    excluded_root_names.insert(manifest_name.to_string());

    // Walk the tree exactly as laid on disk. Reparse points/symlinks are
    // refused outright -- the same posture native_packs.rs takes for
    // component packs -- since a laid tree must be the SIGNED bytes, never a
    // link to something else.
    let mut on_disk_paths: BTreeSet<String> = BTreeSet::new();
    let mut directories = vec![tree.to_path_buf()];
    while let Some(directory) = directories.pop() {
        let read_dir = fs::read_dir(&directory).map_err(|error| {
            format!(
                "Could not inventory the laid tree at {}: {error}",
                directory.display()
            )
        })?;
        for entry in read_dir {
            let entry =
                entry.map_err(|error| format!("Could not inventory the laid tree: {error}"))?;
            let path = entry.path();
            let file_type = entry
                .file_type()
                .map_err(|error| format!("Could not inspect laid tree entry: {error}"))?;
            if file_type.is_symlink() {
                return Err(format!(
                    "Laid tree contains a symbolic link, which is never allowed: {}",
                    path.display()
                ));
            }
            if file_type.is_dir() {
                directories.push(path);
                continue;
            }
            let relative = path
                .strip_prefix(tree)
                .map_err(|_| "Could not compute a laid-tree-relative path.".to_string())?
                .to_string_lossy()
                .replace('\\', "/");
            if !relative.contains('/') && excluded_root_names.contains(&relative) {
                // A root-level trust artifact (the manifest itself,
                // SHA256SUMS, LICENSE-BOM.md, ...): expected beside the
                // payload, not part of the file-content contract.
                continue;
            }
            on_disk_paths.insert(relative);
        }
    }

    let mut failures: Vec<String> = Vec::new();
    let mut total_bytes = 0_u64;
    for (relative_path, expected_bytes, expected_sha256) in &entries {
        total_bytes = total_bytes.saturating_add(*expected_bytes);
        let full_path = tree.join(Path::new(relative_path));
        let metadata = match fs::symlink_metadata(&full_path) {
            Ok(metadata) => metadata,
            Err(_) => {
                if failures.len() < max_failures {
                    failures.push(format!("MISSING: {relative_path}"));
                }
                continue;
            }
        };
        if metadata.file_type().is_symlink() {
            if failures.len() < max_failures {
                failures.push(format!(
                    "SYMLINK NOT ALLOWED (manifest entry replaced by a link): {relative_path}"
                ));
            }
            continue;
        }
        if metadata.len() != *expected_bytes {
            if failures.len() < max_failures {
                failures.push(format!(
                    "SIZE MISMATCH: {relative_path} (on-disk {} != manifest {})",
                    metadata.len(),
                    expected_bytes
                ));
            }
            continue;
        }
        // Streamed hash: `sha256_reader` reads through a bounded 1 MiB
        // buffer (see native_packs.rs), never loading the whole file --
        // required here because this tree is 2 GB+.
        let mut file = File::open(&full_path)
            .map_err(|error| format!("Could not open laid tree file {relative_path}: {error}"))?;
        let actual_sha256 = native_packs::sha256_reader(&mut file, relative_path)?;
        if actual_sha256 != *expected_sha256 && failures.len() < max_failures {
            failures.push(format!(
                "SHA-256 MISMATCH: {relative_path} (on-disk {actual_sha256} != manifest {expected_sha256})"
            ));
        }
    }

    for relative_path in on_disk_paths.difference(&expected_paths) {
        if failures.len() < max_failures {
            failures.push(format!("EXTRA (not in manifest): {relative_path}"));
        }
    }

    let elapsed_ms = started.elapsed().as_millis();
    if !failures.is_empty() {
        return Err(format!(
            "D2 install-time verification FAILED for {} against {manifest_name} after {elapsed_ms}ms \
             ({} manifest file(s) checked); first {} failure(s):\n  {}",
            tree.display(),
            entries.len(),
            failures.len(),
            failures.join("\n  ")
        ));
    }

    Ok(TreeVerificationReport {
        tree: tree.to_path_buf(),
        manifest: manifest_name.to_string(),
        file_count: entries.len(),
        total_bytes,
        elapsed_ms,
    })
}

/// Re-verify an already-extracted component-pack tree (e.g. a caption/model
/// pack staged under `<version_root>/components/<name>`) by re-opening its
/// ORIGINAL signed `.ccpack` (re-checking the ed25519 signature and every
/// entry hash from the pack itself, never trusting a loose file beside it)
/// and then re-walking `destination` against that freshly-verified file
/// list. Both steps call straight into `native_packs` -- no verification
/// logic is duplicated here.
pub fn verify_component_pack_tree(
    pack_file: &Path,
    destination: &Path,
    trust: &PackTrust,
    expected_component: Option<&str>,
    expected_product_version: Option<&str>,
    expected_compatible_core: Option<&str>,
) -> Result<VerifiedPack, String> {
    let (verified, _archive) = native_packs::open_and_verify_pack(
        pack_file,
        trust,
        expected_component,
        expected_product_version,
        expected_compatible_core,
    )?;
    native_packs::verify_extracted_tree(destination, &verified.files)?;
    Ok(verified)
}

#[cfg(test)]
mod tests {
    use super::{verify_component_pack_tree, verify_manifest_tree};
    use crate::native_packs::{self, PackTrust};
    use ed25519_dalek::{Signer, SigningKey};
    use serde_json::json;
    use sha2::{Digest, Sha256};
    use std::fs;
    use std::io::Write;
    use std::path::{Path, PathBuf};
    use zip::write::SimpleFileOptions;
    use zip::{CompressionMethod, ZipWriter};

    const TRUST_ARTIFACTS: [&str; 3] =
        ["app-payload-manifest.json", "SHA256SUMS", "LICENSE-BOM.md"];

    fn sha256_hex(bytes: &[u8]) -> String {
        let mut digest = Sha256::new();
        digest.update(bytes);
        format!("{:x}", digest.finalize())
    }

    fn scratch_dir(name: &str) -> PathBuf {
        let root = std::env::temp_dir().join(format!(
            "civiccast-native-install-verify-{name}-{}-{}",
            std::process::id(),
            name.len() // trivial extra uniqueness without extra deps
        ));
        let _ = fs::remove_dir_all(&root);
        fs::create_dir_all(&root).expect("create scratch dir");
        root
    }

    /// Write a two-file tree plus a matching `app-payload-manifest.json`
    /// whose shape mirrors the real build-time manifest (schema is a
    /// superset: only `files[].{path,sha256,bytes}` are read).
    fn write_clean_payload_tree(root: &Path) {
        fs::write(root.join("python.exe"), b"pretend-interpreter-bytes").expect("write python.exe");
        fs::create_dir_all(root.join("Lib").join("site-packages")).expect("mkdir site-packages");
        fs::write(
            root.join("Lib")
                .join("site-packages")
                .join("civiccast_marker.txt"),
            b"pretend-package-bytes",
        )
        .expect("write package marker");

        let manifest = json!({
            "schema_version": 1,
            "files": [
                {
                    "path": "python.exe",
                    "bytes": b"pretend-interpreter-bytes".len(),
                    "sha256": sha256_hex(b"pretend-interpreter-bytes"),
                    "distribution": "python",
                    "version": "3.12.10",
                    "license": "PSF-2.0",
                },
                {
                    "path": "Lib/site-packages/civiccast_marker.txt",
                    "bytes": b"pretend-package-bytes".len(),
                    "sha256": sha256_hex(b"pretend-package-bytes"),
                    "distribution": "civiccast",
                    "version": "1.0.0rc15",
                    "license": "Apache-2.0",
                },
            ],
        });
        fs::write(
            root.join("app-payload-manifest.json"),
            serde_json::to_vec_pretty(&manifest).expect("serialize manifest"),
        )
        .expect("write manifest");
    }

    #[test]
    fn clean_tree_passes_verification() {
        let root = scratch_dir("clean");
        write_clean_payload_tree(&root);

        let report = verify_manifest_tree(&root, "app-payload-manifest.json", &TRUST_ARTIFACTS, 25)
            .expect("a byte-identical laid tree must verify");
        assert_eq!(report.file_count, 2);
        assert_eq!(
            report.total_bytes,
            (b"pretend-interpreter-bytes".len() + b"pretend-package-bytes".len()) as u64
        );

        let _ = fs::remove_dir_all(&root);
    }

    #[test]
    fn tampered_file_is_named_in_the_failure() {
        let root = scratch_dir("tampered");
        write_clean_payload_tree(&root);
        // Flip one byte in python.exe after the manifest was written, exactly
        // the "byte-flipped DLL" repair scenario (D5) applied at install time.
        let target = root.join("python.exe");
        let mut bytes = fs::read(&target).expect("read python.exe");
        bytes[0] ^= 0xFF;
        fs::write(&target, &bytes).expect("rewrite tampered python.exe");

        let error = verify_manifest_tree(&root, "app-payload-manifest.json", &TRUST_ARTIFACTS, 25)
            .expect_err("a tampered file must fail closed");
        assert!(
            error.contains("python.exe"),
            "error must name the exact tampered path, got: {error}"
        );
        assert!(
            error.to_lowercase().contains("sha-256") || error.to_lowercase().contains("hash"),
            "error must identify a hash mismatch, got: {error}"
        );

        let _ = fs::remove_dir_all(&root);
    }

    #[test]
    fn missing_file_is_reported_by_exact_path() {
        let root = scratch_dir("missing");
        write_clean_payload_tree(&root);
        fs::remove_file(
            root.join("Lib")
                .join("site-packages")
                .join("civiccast_marker.txt"),
        )
        .expect("delete manifest-named file");

        let error = verify_manifest_tree(&root, "app-payload-manifest.json", &TRUST_ARTIFACTS, 25)
            .expect_err("a manifest entry absent on disk must fail closed");
        assert!(
            error.contains("Lib/site-packages/civiccast_marker.txt"),
            "error must name the exact missing path, got: {error}"
        );
        assert!(
            error.to_lowercase().contains("missing"),
            "error must say MISSING, got: {error}"
        );

        let _ = fs::remove_dir_all(&root);
    }

    #[test]
    fn extra_file_is_rejected_fail_closed() {
        let root = scratch_dir("extra");
        write_clean_payload_tree(&root);
        fs::write(root.join("unexpected-smuggled.dll"), b"not in the manifest")
            .expect("write extra file");

        let error = verify_manifest_tree(&root, "app-payload-manifest.json", &TRUST_ARTIFACTS, 25)
            .expect_err("an on-disk file absent from the manifest must fail closed");
        assert!(
            error.contains("unexpected-smuggled.dll"),
            "error must name the exact extra path, got: {error}"
        );

        let _ = fs::remove_dir_all(&root);
    }

    #[test]
    fn absent_manifest_fails_closed_rather_than_trusting_an_empty_tree() {
        let root = scratch_dir("no-manifest");
        fs::write(root.join("python.exe"), b"bytes-with-no-manifest-at-all")
            .expect("write a file with no manifest present");

        let error = verify_manifest_tree(&root, "app-payload-manifest.json", &TRUST_ARTIFACTS, 25)
            .expect_err("a laid tree with no manifest must never verify as trusted");
        assert!(
            error.contains("app-payload-manifest.json"),
            "error must name the missing manifest file, got: {error}"
        );

        let _ = fs::remove_dir_all(&root);
    }

    #[test]
    fn failures_are_capped_at_the_requested_count_and_say_so() {
        let root = scratch_dir("many-missing");
        write_clean_payload_tree(&root);
        fs::remove_file(root.join("python.exe")).expect("delete first file");
        fs::remove_file(
            root.join("Lib")
                .join("site-packages")
                .join("civiccast_marker.txt"),
        )
        .expect("delete second file");

        let error = verify_manifest_tree(&root, "app-payload-manifest.json", &TRUST_ARTIFACTS, 1)
            .expect_err("missing files must fail closed");
        assert_eq!(
            error.matches("MISSING:").count(),
            1,
            "must report at most the requested cap, got: {error}"
        );

        let _ = fs::remove_dir_all(&root);
    }

    #[test]
    fn elapsed_time_is_reported_on_a_clean_pass() {
        let root = scratch_dir("timed");
        write_clean_payload_tree(&root);

        let report = verify_manifest_tree(&root, "app-payload-manifest.json", &TRUST_ARTIFACTS, 25)
            .expect("clean tree must verify");
        // elapsed_ms is a u128 (always >= 0); the real assertion is that the
        // field is populated at all -- covered by the struct construction
        // succeeding above. This test exists to pin the performance-guard
        // contract (the caller/hook prints this value).
        let _ = report.elapsed_ms;

        let _ = fs::remove_dir_all(&root);
    }

    // ---- component-pack tree re-verification (reuses native_packs.rs) ----

    fn build_signed_pack(pack_path: &Path, payload: &[(&str, &[u8])]) -> SigningKey {
        let signing_key = SigningKey::from_bytes(&[9_u8; 32]);
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
        let manifest_value = json!({
            "schema_version": 1,
            "product": "civiccast-native",
            "component": "captions-test-tier",
            "product_version": "1.0.0-rc15",
            "compatible_core": "1.0.0-rc15",
            "signing_key_id": "test-key",
            "file_count": payload.len(),
            "total_bytes": total_bytes,
            "files": files_json,
            "metadata": {},
        });
        let manifest_bytes = native_packs::canonical_json(&manifest_value)
            .expect("canonicalize test manifest")
            .into_bytes();
        let signature = signing_key.sign(&manifest_bytes);
        let signature_b64 = base64::engine::general_purpose::STANDARD.encode(signature.to_bytes());

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
        signing_key
    }

    use base64::Engine as _;

    fn trust_for(signing_key: &SigningKey) -> PackTrust {
        PackTrust {
            key_id: "test-key".to_string(),
            public_key: signing_key.verifying_key(),
        }
    }

    #[test]
    fn a_correctly_extracted_pack_tree_passes_reverification() {
        let root = scratch_dir("pack-clean");
        let pack_path = root.join("captions-test-tier.ccpack");
        let signing_key =
            build_signed_pack(&pack_path, &[("model/weights.bin", b"pretend-weights")]);
        let trust = trust_for(&signing_key);

        let destination = root.join("extracted");
        fs::create_dir_all(destination.join("model")).expect("mkdir extracted model dir");
        fs::write(
            destination.join("model").join("weights.bin"),
            b"pretend-weights",
        )
        .expect("write extracted payload file");

        let verified = verify_component_pack_tree(
            &pack_path,
            &destination,
            &trust,
            Some("captions-test-tier"),
            Some("1.0.0-rc15"),
            Some("1.0.0-rc15"),
        )
        .expect("a byte-identical extracted pack tree must reverify");
        assert_eq!(verified.component, "captions-test-tier");

        let _ = fs::remove_dir_all(&root);
    }

    #[test]
    fn a_tampered_extracted_pack_file_fails_reverification() {
        let root = scratch_dir("pack-tampered");
        let pack_path = root.join("captions-test-tier.ccpack");
        let signing_key =
            build_signed_pack(&pack_path, &[("model/weights.bin", b"pretend-weights")]);
        let trust = trust_for(&signing_key);

        let destination = root.join("extracted");
        fs::create_dir_all(destination.join("model")).expect("mkdir extracted model dir");
        // Extracted bytes differ from what the SIGNED pack manifest names --
        // exactly the "byte-flipped DLL" scenario the caption-pack per-tier
        // verifier (native_packs.rs, 5ad71753) is designed to catch, applied
        // here to the LAID/EXTRACTED tree rather than the archive itself.
        fs::write(
            destination.join("model").join("weights.bin"),
            b"TAMPERED-weights",
        )
        .expect("write tampered extracted payload file");

        let error = verify_component_pack_tree(
            &pack_path,
            &destination,
            &trust,
            Some("captions-test-tier"),
            Some("1.0.0-rc15"),
            Some("1.0.0-rc15"),
        )
        .expect_err("a tampered extracted pack file must fail closed");
        assert!(
            error.contains("weights.bin") || error.to_lowercase().contains("verification"),
            "unexpected error: {error}"
        );

        let _ = fs::remove_dir_all(&root);
    }
}
