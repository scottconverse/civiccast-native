// SPDX-License-Identifier: Apache-2.0
// Copyright (c) The CivicCast Authors

//! D5 repair (`spec-installer-lifecycle.md` D5: "re-verify current tree
//! against the signed manifest, re-lay corrupted files, re-register
//! service, never touch data"; `spec-native-beta-recovery.md` WP2: "repair
//! that detects and restores corruption in the installed application,
//! version, selector, runtime, dependency, and caption trees").
//!
//! ## Reuse, not a fork
//!
//! Every byte of verification/extraction/side-load logic here is a call
//! into ALREADY-LANDED, already-unit-tested primitives -- nothing is
//! reimplemented:
//!
//! * pack presence/corruption classification: `native_pack_staging::
//!   classify_dest_pack_state`;
//! * offline/side-load discovery: `native_pack_staging::
//!   discover_offline_pack_sources`;
//! * the pure offline decision matrix: `native_pack_staging::
//!   decide_offline_staging_action` (this module's own
//!   [`decide_component_repair_action`] is a thin repair-flavored RENAME of
//!   the same three outcomes onto repair vocabulary, not a new decision);
//! * landing a side-loaded pack: `native_pack_staging::commit_pack_file`;
//! * verify-or-rebuild an extracted tree from an already-verified pack:
//!   `native_pack_staging::ensure_pack_extracted` (its own doc: "if a tree
//!   already exists at the destination and re-verifies... it is accepted
//!   with zero re-extraction. A missing OR corrupt... destination is
//!   cleared and rebuilt from scratch" -- this literally already IS D5's
//!   "re-verify current tree against the signed manifest, re-lay corrupted
//!   files" for a pack-delivered component);
//! * re-verifying a laid tree against its ORIGINAL signed pack:
//!   `native_install_verify::verify_component_pack_tree` (this is also
//!   where per-tier CAPTION pack verification already lives --
//!   `native_packs::verify_extracted_tree` calls into
//!   `verify_caption_pack_tiers` for any pack whose manifest declares
//!   `caption_tiers` -- so a captions-* component needs NO caption-specific
//!   code in this module at all: it is repaired by the exact same
//!   [`repair_pack_component`] path as every other component pack);
//! * re-registering the service: `native_service_registration::
//!   register_native_service` (already idempotent install-or-update via the
//!   pywin32 seam -- its own doc: "install-or-update is ALREADY idempotent
//!   (D5 Repair's 're-register service'... satisfied by the seam itself");
//! * re-registering the firewall rule: `native_service_registration::
//!   register_native_firewall_rule` (already idempotent: probe, no-op if
//!   present).
//!
//! ## Component universe: required + whatever is actually present
//!
//! [`discover_repair_component_universe`] always checks
//! `native_pack_staging::DEFAULT_REQUIRED_COMPONENTS` (server binaries, app
//! payload, FFmpeg, and Ollama -- the installed application and dependency/
//! runtime trees), and ADDITIONALLY checks
//! any other `.ccpack` file OR extracted-tree directory already present
//! under `$INSTDIR\packs` -- this is how an optional captions-* pack (per
//! `spec-native-beta-recovery.md` WP2: "caption trees... if present") is
//! covered without hard-coding its component name here: the caption pack is
//! not in `DEFAULT_REQUIRED_COMPONENTS` (WP1's adaptive-tier caption
//! contract is a separate, optional delivery), but if it (or even just its
//! orphaned extracted tree, with the raw `.ccpack` itself missing) is
//! present on disk, it joins the universe and is repaired -- or reported
//! NOT-REPAIRABLE-LOCALLY -- exactly like every required component.
//!
//! ## "Version": read, not invented
//!
//! No code in this crate writes a separate ARP `DisplayVersion` (grepped:
//! zero hits) -- Tauri/NSIS's own installer template owns that key, and
//! rewriting it without rebuilding/re-signing the installer is out of this
//! module's reach. What IS real, already-verified data is each component
//! pack's own signed `product_version` field (`native_packs::VerifiedPack::
//! product_version`) -- already enforced during every repair call above
//! (every `classify_dest_pack_state`/`verify_pack`/
//! `verify_component_pack_tree` call in this module passes
//! `expected_product_version`, so a version-mismatched pack already fails
//! closed and is repaired -- or reported unrepairable -- through the exact
//! same path as any other corruption). [`read_component_versions`] makes
//! that fact a NAMED, separately reported "version" row (D5's own vocabulary),
//! grounded in the pack's real signed manifest field, not a second
//! enforcement path.
//!
//! ## Selector: only touched when unambiguously safe
//!
//! `ActiveRuntime` being `Native`, `Wsl`, or `Absent` are all LEGITIMATE
//! product states (D1: "Uninstalling the inactive product never touches the
//! selector"; a fresh install before first activation may never have set
//! it) -- repair must never treat "WSL currently owns activation" as
//! corruption to silently overwrite. The ONE genuinely corrupt state is
//! `Unreadable` (a present value that fails to parse), and even then this
//! module only self-heals it to `"native"` when WSL's ARP registration is
//! independently confirmed `Absent` (native is the sole installed product,
//! so there is no other legitimate owner it could be silently overwriting).
//! Any other combination is reported, never guessed -- see
//! [`decide_selector_repair_action`].

use std::collections::BTreeSet;
use std::fs;
use std::path::{Path, PathBuf};

use serde::Serialize;

use crate::native_install_verify;
use crate::native_pack_staging::{
    self, DestPackState, OfflineSourceState, StagingAction, TreeRebuildAuthority,
};
use crate::native_packs::{self, PackTrust};
#[cfg(target_os = "windows")]
use crate::native_service_registration;
#[cfg(target_os = "windows")]
use crate::native_uninstall;
use crate::native_uninstall::{OtherProductState, SelectorState};

// ---------------------------------------------------------------------------
// Per-component pack repair
// ---------------------------------------------------------------------------

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize)]
#[serde(rename_all = "kebab-case")]
pub enum RepairAction {
    NoActionNeeded,
    RepairedFromLocalPack,
    RepairedFromSideLoad,
    NotRepairableLocally,
}

impl RepairAction {
    pub fn is_unrepairable(self) -> bool {
        matches!(self, RepairAction::NotRepairableLocally)
    }

    pub fn is_repair(self) -> bool {
        matches!(
            self,
            RepairAction::RepairedFromLocalPack | RepairAction::RepairedFromSideLoad
        )
    }
}

#[derive(Debug, Clone, Serialize)]
pub struct ComponentRepairResult {
    pub component: String,
    pub action: RepairAction,
    pub detail: String,
}

/// Pure: maps `native_pack_staging::StagingAction` (the ALREADY-EXISTING,
/// already-unit-tested offline/side-load decision) onto repair vocabulary.
/// `tree_was_already_verified` is only consulted for `AlreadySatisfied` --
/// it distinguishes "raw pack fine, tree fine too" (no action) from "raw
/// pack fine, tree was corrupt/missing" (D5's "re-lay corrupted files" via a
/// re-extract from the ALREADY-verified local pack, the task's own "restores
/// from the local .ccpack (re-extract)" case). Never touches a filesystem;
/// callers combine this with the real side effects.
pub fn decide_component_repair_action(
    staging_action: StagingAction,
    tree_was_already_verified: bool,
) -> RepairAction {
    match staging_action {
        StagingAction::NeedsOnlineOrAbort => RepairAction::NotRepairableLocally,
        StagingAction::CopyFromOffline | StagingAction::ReplaceCorruptFromOffline => {
            RepairAction::RepairedFromSideLoad
        }
        StagingAction::AlreadySatisfied => {
            if tree_was_already_verified {
                RepairAction::NoActionNeeded
            } else {
                RepairAction::RepairedFromLocalPack
            }
        }
    }
}

fn not_repairable_detail(
    component: &str,
    local_pack: &Path,
    source_dir: &Path,
    dest_state: &DestPackState,
) -> String {
    let dest_summary = match dest_state {
        DestPackState::Absent => "no local pack is present".to_string(),
        DestPackState::Corrupt(reason) => {
            format!("the local pack failed re-verification ({reason})")
        }
        DestPackState::Verified => {
            "the local pack unexpectedly verified".to_string() // unreachable when this is called
        }
    };
    format!(
        "{component}: {dest_summary} at {}, and no verified side-load pack for this component \
         was found under {} (--installer-dir). NOT-REPAIRABLE-LOCALLY. Remedies: (1) place a \
         valid, signed {component}.ccpack in a 'packs' folder under --installer-dir and re-run \
         repair, or (2) restore {} from a known-good backup, then re-run repair.",
        local_pack.display(),
        source_dir.display(),
        local_pack.display(),
    )
}

/// Repair ONE component pack: its raw `.ccpack` at
/// `$INSTDIR\packs\<component>.ccpack` and its extracted tree (per
/// `native_pack_staging::pack_extraction_destination`'s per-component
/// mapping -- `native-app-payload` bridges to `$INSTDIR\runtime`, every
/// other component uses `$INSTDIR\packs\<component>\payload`). Three
/// possible remedies, matching the task's own framing exactly: repair from
/// the local (already on `$INSTDIR\packs`) `.ccpack` (re-extract only, raw
/// pack itself was fine), repair from an installer-dir side-load
/// (`--installer-dir\packs\*.ccpack`, discovered by signed identity, not
/// filename), or NOT-REPAIRABLE-LOCALLY naming both remedies.
#[allow(clippy::too_many_arguments)]
pub fn repair_pack_component(
    installer_dir: &Path,
    instdir: &Path,
    trust: &PackTrust,
    component: &str,
    expected_product_version: &str,
    expected_compatible_core: &str,
    authority: &dyn TreeRebuildAuthority,
) -> ComponentRepairResult {
    let dest_dir = instdir.join("packs");
    let local_pack = dest_dir.join(format!("{component}.ccpack"));
    let source_dir = installer_dir.join("packs");

    let dest_state = native_pack_staging::classify_dest_pack_state(
        &local_pack,
        trust,
        component,
        expected_product_version,
        expected_compatible_core,
    );
    let offline_sources = native_pack_staging::discover_offline_pack_sources(
        &source_dir,
        trust,
        expected_product_version,
        expected_compatible_core,
    );
    let source_state = if offline_sources.contains_key(component) {
        OfflineSourceState::Verified
    } else {
        OfflineSourceState::Absent
    };
    let staging_action =
        native_pack_staging::decide_offline_staging_action(&dest_state, &source_state);

    if staging_action == StagingAction::NeedsOnlineOrAbort {
        return ComponentRepairResult {
            component: component.to_string(),
            action: RepairAction::NotRepairableLocally,
            detail: not_repairable_detail(component, &local_pack, &source_dir, &dest_state),
        };
    }

    if matches!(
        staging_action,
        StagingAction::CopyFromOffline | StagingAction::ReplaceCorruptFromOffline
    ) {
        let source_path = offline_sources
            .get(component)
            .expect("CopyFromOffline/ReplaceCorruptFromOffline implies a verified offline source");
        if let Err(error) = native_pack_staging::commit_pack_file(
            source_path,
            &local_pack,
            trust,
            component,
            expected_product_version,
            expected_compatible_core,
        ) {
            return ComponentRepairResult {
                component: component.to_string(),
                action: RepairAction::NotRepairableLocally,
                detail: format!(
                    "{component}: found an installer-dir side-load pack at {} but it failed \
                     re-verification after copy: {error}",
                    source_path.display()
                ),
            };
        }
        let action = decide_component_repair_action(staging_action, false);
        return match native_pack_staging::ensure_pack_extracted(
            &local_pack,
            &dest_dir,
            component,
            trust,
            expected_product_version,
            expected_compatible_core,
            authority,
        ) {
            Ok(_) => ComponentRepairResult {
                component: component.to_string(),
                action,
                detail: format!(
                    "{component}: local pack was {dest_state:?}; restored from installer-dir \
                     side-load {}",
                    source_path.display()
                ),
            },
            Err(error) => ComponentRepairResult {
                component: component.to_string(),
                action: RepairAction::NotRepairableLocally,
                detail: format!(
                    "{component}: side-loaded pack verified but its extracted tree could not be \
                     rebuilt: {error}"
                ),
            },
        };
    }

    // AlreadySatisfied: the local raw pack itself is present and verified.
    // Check the EXTRACTED tree once (no redundant hashing on the healthy
    // path); only call into `ensure_pack_extracted` -- which re-verifies
    // internally before rebuilding -- when that check already failed.
    let extraction_dir =
        match native_pack_staging::pack_extraction_destination(&dest_dir, component) {
            Ok(dir) => dir,
            Err(error) => {
                return ComponentRepairResult {
                    component: component.to_string(),
                    action: RepairAction::NotRepairableLocally,
                    detail: format!(
                        "{component}: could not determine its extraction destination: {error}"
                    ),
                }
            }
        };
    let tree_check = native_install_verify::verify_component_pack_tree(
        &local_pack,
        &extraction_dir,
        trust,
        Some(component),
        Some(expected_product_version),
        Some(expected_compatible_core),
    );
    let tree_was_already_verified = tree_check.is_ok();
    let action = decide_component_repair_action(staging_action, tree_was_already_verified);
    if tree_was_already_verified {
        return ComponentRepairResult {
            component: component.to_string(),
            action,
            detail: format!(
                "{component}: local pack and its extracted tree both verified against the \
                 signed manifest; no action needed"
            ),
        };
    }
    let tree_error = tree_check.expect_err("just checked is_ok() == false above");
    match native_pack_staging::ensure_pack_extracted(
        &local_pack,
        &dest_dir,
        component,
        trust,
        expected_product_version,
        expected_compatible_core,
        authority,
    ) {
        Ok(_) => ComponentRepairResult {
            component: component.to_string(),
            action,
            detail: format!(
                "{component}: local pack verified; its extracted tree was corrupt/missing \
                 ({tree_error}) and was re-extracted from the verified local pack {}",
                local_pack.display()
            ),
        },
        Err(error) => ComponentRepairResult {
            component: component.to_string(),
            action: RepairAction::NotRepairableLocally,
            detail: format!(
                "{component}: local pack verified but its extracted tree could not be rebuilt: {error}"
            ),
        },
    }
}

/// The component universe: every REQUIRED component (always checked, even
/// with zero on-disk trace) UNION every other `.ccpack` file or extracted-
/// tree directory already present under `$INSTDIR\packs` (an optional
/// component, e.g. a captions-* pack, or an orphaned extracted tree whose
/// raw pack was itself deleted -- both are real corruption states this must
/// detect, not silently skip because they are not in the required set).
pub fn discover_repair_component_universe(
    instdir: &Path,
    required_components: &[String],
) -> Vec<String> {
    let mut set: BTreeSet<String> = required_components.iter().cloned().collect();
    let packs_dir = instdir.join("packs");
    if let Ok(entries) = fs::read_dir(&packs_dir) {
        for entry in entries.filter_map(Result::ok) {
            let path = entry.path();
            let Ok(file_type) = entry.file_type() else {
                continue;
            };
            if file_type.is_file() {
                let is_ccpack = path
                    .extension()
                    .and_then(|value| value.to_str())
                    .is_some_and(|value| value.eq_ignore_ascii_case("ccpack"));
                if is_ccpack {
                    if let Some(stem) = path.file_stem().and_then(|value| value.to_str()) {
                        set.insert(stem.to_string());
                    }
                }
            } else if file_type.is_dir() {
                if let Some(name) = path.file_name().and_then(|value| value.to_str()) {
                    // <installer-path-audit MA-30> D5 repair reported
                    // `Unrepairable` -- exit 79 -- on EVERY healthy activated
                    // station.
                    //
                    // This enrolled every directory under `$INSTDIR\packs`,
                    // excluding only the literal `.acquire-cache`. But the
                    // activation step passes
                    // `--cache-root "$INSTDIR\packs\.station-cache"` and
                    // `retain_verified_index` does
                    // `create_dir_all(cache_root.join("indexes"))`, so
                    // `$INSTDIR\packs\.station-cache\` EXISTS after every
                    // successful install -- USB side-load and download-only
                    // alike. `repair_pack_component` then looked for
                    // `$INSTDIR\packs\.station-cache.ccpack`, found nothing,
                    // returned NotRepairableLocally, and `overall_outcome`'s
                    // `any()` turned that into Unrepairable, with a message
                    // telling the operator to obtain a signed
                    // `.station-cache.ccpack` that does not and cannot exist.
                    //
                    // Every DOT-prefixed directory here is installer
                    // bookkeeping, never a component: skipping the whole
                    // class closes this rather than adding a second literal
                    // beside `.acquire-cache` for the next one to miss.
                    if !name.starts_with('.') {
                        set.insert(name.to_string());
                    }
                }
            }
        }
    }
    set.into_iter().collect()
}

// ---------------------------------------------------------------------------
// "Version" -- read each pack's own signed product_version, report mismatches
// ---------------------------------------------------------------------------

/// Read each component's LOCAL raw pack's signed `product_version` (no
/// `expected_product_version` constraint -- this reads the fact, it does
/// not enforce it a second time; enforcement already happened inside
/// [`repair_pack_component`] via `expected_product_version`). A component
/// with no readable local pack (e.g. it ended NOT-REPAIRABLE-LOCALLY above)
/// reports its error instead of a version string.
pub fn read_component_versions(
    instdir: &Path,
    trust: &PackTrust,
    components: &[String],
) -> Vec<(String, Result<String, String>)> {
    let dest_dir = instdir.join("packs");
    components
        .iter()
        .map(|component| {
            let local_pack = dest_dir.join(format!("{component}.ccpack"));
            let result = native_packs::verify_pack(&local_pack, trust, Some(component), None, None)
                .map(|verified| verified.product_version);
            (component.clone(), result)
        })
        .collect()
}

/// Pure: which of the given `(component, observed_version)` pairs disagree
/// with `expected_version`. Named separately from the per-component pack
/// repair above because D5/WP2 name "version" as its own tree in the
/// decision matrix, even though structurally every mismatch here was already
/// caught (and repaired, or reported unrepairable) by the SAME
/// `expected_product_version` parameter passed through every verification
/// call above -- this is the visibility row, not a second enforcement path.
pub fn version_mismatches<'a>(
    observed: impl IntoIterator<Item = (&'a str, &'a str)>,
    expected_version: &str,
) -> Vec<String> {
    observed
        .into_iter()
        .filter(|(_, version)| *version != expected_version)
        .map(|(component, _)| component.to_string())
        .collect()
}

// ---------------------------------------------------------------------------
// Selector
// ---------------------------------------------------------------------------

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize)]
#[serde(rename_all = "kebab-case")]
pub enum SelectorRepairAction {
    NoActionNeeded,
    RepairedToNative,
    NotRepairableLocally,
}

/// Pure: see the module doc's "Selector" section. `Native`, `Wsl`, and
/// `Absent` are all legitimate product states and are NEVER touched --
/// only a genuinely unparseable (`Unreadable`) value is ever a repair
/// candidate, and even then only when WSL's ARP registration independently
/// proves `Absent` (native is the sole installed product, so writing
/// `"native"` cannot silently overwrite a real WSL ownership claim).
pub fn decide_selector_repair_action(
    selector: SelectorState,
    other_product: OtherProductState,
) -> SelectorRepairAction {
    match selector {
        SelectorState::Native | SelectorState::Wsl | SelectorState::Absent => {
            SelectorRepairAction::NoActionNeeded
        }
        SelectorState::Unreadable => match other_product {
            OtherProductState::Absent => SelectorRepairAction::RepairedToNative,
            OtherProductState::Present | OtherProductState::Unknown => {
                SelectorRepairAction::NotRepairableLocally
            }
        },
    }
}

#[derive(Debug, Clone, Serialize)]
pub struct SelectorRepairResult {
    pub observed_selector: String,
    pub observed_other_product: String,
    pub action: SelectorRepairAction,
    pub detail: String,
}

/// Real-registry selector repair (untested directly -- the HARD RULE forbids
/// unit-testing real registry writes; [`decide_selector_repair_action`]
/// carries the full unit-tested decision logic that gates the write below).
#[cfg(target_os = "windows")]
pub fn repair_selector() -> SelectorRepairResult {
    let selector = native_uninstall::probe_active_runtime_selector();
    let other = native_uninstall::probe_wsl_arp();
    let action = decide_selector_repair_action(selector, other);
    let detail = match action {
        SelectorRepairAction::NoActionNeeded => {
            format!("ActiveRuntime is {selector:?}, a legitimate state; no action needed.")
        }
        SelectorRepairAction::RepairedToNative => {
            match native_uninstall::write_selector_native() {
                Ok(()) => {
                    "ActiveRuntime was Unreadable and WSL is not installed (native is the sole \
                        product); repaired to \"native\"."
                        .to_string()
                }
                Err(error) => {
                    return SelectorRepairResult {
                        observed_selector: format!("{selector:?}"),
                        observed_other_product: format!("{other:?}"),
                        action: SelectorRepairAction::NotRepairableLocally,
                        detail: format!(
                            "ActiveRuntime needed repair but the write failed: {error}"
                        ),
                    }
                }
            }
        }
        SelectorRepairAction::NotRepairableLocally => format!(
            "ActiveRuntime is {selector:?} with WSL-other-product state {other:?}; never \
             guessed between native/WSL ownership. Inspect HKLM\\Software\\CivicCast\\\
             ActiveRuntime manually."
        ),
    };
    SelectorRepairResult {
        observed_selector: format!("{selector:?}"),
        observed_other_product: format!("{other:?}"),
        action,
        detail,
    }
}

#[cfg(not(target_os = "windows"))]
pub fn repair_selector() -> SelectorRepairResult {
    SelectorRepairResult {
        observed_selector: "unreadable".to_string(),
        observed_other_product: "unknown".to_string(),
        action: SelectorRepairAction::NotRepairableLocally,
        detail: "Selector repair requires Windows registry access and fails closed on this \
                 platform."
            .to_string(),
    }
}

// ---------------------------------------------------------------------------
// Service + firewall re-registration
// ---------------------------------------------------------------------------

/// Real service/SCM/firewall re-registration (untested directly, same HARD
/// RULE as `native_service_registration::register_native_service`). Both
/// underlying calls are already idempotent, so this is safe to run
/// unconditionally on every repair -- D5's own wording, "re-register
/// service", is unconditional, not corruption-gated.
#[cfg(target_os = "windows")]
fn reregister_service_and_firewall(instdir: &Path) -> (bool, String, bool, String) {
    let (service_ok, service_detail) =
        match native_service_registration::register_native_service(instdir) {
            Ok(()) => (
                true,
                "CivicCast (Native) service re-registered (idempotent install-or-update)."
                    .to_string(),
            ),
            Err(error) => (false, format!("service re-registration failed: {error}")),
        };
    let (firewall_ok, firewall_detail) =
        match native_service_registration::register_native_firewall_rule(instdir) {
            Ok(()) => (
                true,
                "CivicCast (Native) firewall rule re-registered (idempotent).".to_string(),
            ),
            Err(error) => (
                false,
                format!("firewall rule re-registration failed: {error}"),
            ),
        };
    (service_ok, service_detail, firewall_ok, firewall_detail)
}

#[cfg(not(target_os = "windows"))]
fn reregister_service_and_firewall(_instdir: &Path) -> (bool, String, bool, String) {
    (
        false,
        "service re-registration requires Windows.".to_string(),
        false,
        "firewall rule re-registration requires Windows.".to_string(),
    )
}

// ---------------------------------------------------------------------------
// Orchestration
// ---------------------------------------------------------------------------

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize)]
#[serde(rename_all = "kebab-case")]
pub enum OverallOutcome {
    AllVerified,
    Repaired,
    Unrepairable,
}

#[derive(Debug, Clone, Serialize)]
pub struct RepairReport {
    pub instdir: PathBuf,
    pub installer_dir: PathBuf,
    pub expected_product_version: String,
    pub components: Vec<ComponentRepairResult>,
    pub version_mismatches: Vec<String>,
    pub selector: SelectorRepairResult,
    pub service_reregistered: bool,
    pub service_detail: String,
    pub firewall_reregistered: bool,
    pub firewall_detail: String,
    /// <installer-path-audit MA-31, honesty half> What this repair did NOT
    /// look at.
    ///
    /// A grep for `station-set`, `activation-self-test`, `schema` and
    /// `DATABASE_URL` across this module's non-test body found none:
    /// `run_repair` covers component packs (raw + extracted tree), each
    /// pack's signed `product_version`, the ActiveRuntime selector, and
    /// service/firewall re-registration. It does not look at
    /// `station-set.json`, `activation-self-test.json`, the database schema,
    /// or `DatabaseUrl`. So on EXACTLY the machine the installer-path audit
    /// is about -- new code over an old schema, or a rolled-back flat layout
    /// -- repair returns `AllVerified` / exit 0: a "healthy" verdict derived
    /// from pack hashes alone.
    ///
    /// Closing that for real needs a schema-currency row, and repair
    /// deliberately never starts the service (`main.rs`), so reading the
    /// schema would mean starting PostgreSQL from a GUI diagnostic -- a
    /// behaviour change that should be decided, not slipped in. Until it is,
    /// the report says what it did not check, so `AllVerified` cannot be read
    /// as "this station can serve".
    pub not_checked: Vec<String>,
    pub outcome: OverallOutcome,
}

/// The checks a D5 repair run does NOT perform, in operator-readable form.
///
/// <installer-path-audit MA-31> Stated as data on the report rather than as a
/// comment in this file, because the report is what an operator and a support
/// case actually read.
pub fn repair_checks_not_performed() -> Vec<String> {
    vec![
        "database schema currency: NOT CHECKED (needs the database, and repair deliberately \
         does not start the station's service)"
            .to_string(),
        "station activation artifacts (station-set.json, activation-self-test.json): NOT \
         CHECKED"
            .to_string(),
        "whether the station can actually serve: NOT CHECKED -- this report covers component \
         pack integrity, pack versions, the ActiveRuntime selector, and service/firewall \
         registration only"
            .to_string(),
    ]
}

/// Pure combination of every sub-result into the ONE exit-code-mapped
/// outcome the task requires ("Exit code distinguishes: all-verified /
/// repaired / unrepairable"). Any unrepairable element anywhere (a
/// component, the selector, or a failed service/firewall re-registration --
/// D5's "re-register service" is part of the repair contract, so its
/// failure IS a repair failure) wins over "repaired"; "repaired" wins over
/// "all-verified".
pub fn overall_outcome(
    components: &[ComponentRepairResult],
    selector_action: SelectorRepairAction,
    service_ok: bool,
    firewall_ok: bool,
) -> OverallOutcome {
    let any_unrepairable = components
        .iter()
        .any(|component| component.action.is_unrepairable())
        || selector_action == SelectorRepairAction::NotRepairableLocally
        || !service_ok
        || !firewall_ok;
    if any_unrepairable {
        return OverallOutcome::Unrepairable;
    }
    let any_repaired = components
        .iter()
        .any(|component| component.action.is_repair())
        || selector_action == SelectorRepairAction::RepairedToNative;
    if any_repaired {
        OverallOutcome::Repaired
    } else {
        OverallOutcome::AllVerified
    }
}

/// The full D5 repair run, with the selector-repair and service/firewall-
/// re-registration steps INJECTED (mirrors `native_activation::
/// stage_acquired_distribution` wrapping `stage_distribution_with` with an
/// injected `self_test` closure -- the same established seam, not a new
/// idiom) so the orchestration logic (component loop, the "skip service
/// re-registration when a required tree is unrepairable" guard, and outcome
/// combination) is unit-testable without ever touching a real registry or
/// SCM from `cargo test`. [`run_repair`] below wires the real
/// Windows-gated closures; tests wire fakes.
#[allow(clippy::too_many_arguments)]
pub fn run_repair_with<S, R>(
    instdir: &Path,
    installer_dir: &Path,
    trust: &PackTrust,
    required_components: &[String],
    expected_product_version: &str,
    expected_compatible_core: &str,
    selector_repair: S,
    service_and_firewall_repair: R,
    authority: &dyn TreeRebuildAuthority,
) -> RepairReport
where
    S: FnOnce() -> SelectorRepairResult,
    R: FnOnce(&Path) -> (bool, String, bool, String),
{
    let universe = discover_repair_component_universe(instdir, required_components);
    let components: Vec<ComponentRepairResult> = universe
        .iter()
        .map(|component| {
            repair_pack_component(
                installer_dir,
                instdir,
                trust,
                component,
                expected_product_version,
                expected_compatible_core,
                authority,
            )
        })
        .collect();

    let version_observed = read_component_versions(instdir, trust, &universe);
    let version_mismatched = version_mismatches(
        version_observed.iter().filter_map(|(component, result)| {
            result
                .as_ref()
                .ok()
                .map(|version| (component.as_str(), version.as_str()))
        }),
        expected_product_version,
    );

    let required_ok = required_components.iter().all(|required| {
        components
            .iter()
            .find(|result| &result.component == required)
            .map(|result| !result.action.is_unrepairable())
            .unwrap_or(false)
    });

    let selector = selector_repair();

    let (service_ok, service_detail, firewall_ok, firewall_detail) = if required_ok {
        service_and_firewall_repair(instdir)
    } else {
        (
            false,
            "skipped: a required application/runtime component is not repairable locally"
                .to_string(),
            false,
            "skipped: a required application/runtime component is not repairable locally"
                .to_string(),
        )
    };

    let outcome = overall_outcome(&components, selector.action, service_ok, firewall_ok);

    RepairReport {
        instdir: instdir.to_path_buf(),
        installer_dir: installer_dir.to_path_buf(),
        expected_product_version: expected_product_version.to_string(),
        components,
        version_mismatches: version_mismatched,
        selector,
        service_reregistered: service_ok,
        service_detail,
        firewall_reregistered: firewall_ok,
        firewall_detail,
        not_checked: repair_checks_not_performed(),
        outcome,
    }
}

/// The CLI-facing entry point: wires the REAL Windows-gated selector and
/// service/firewall repair closures into [`run_repair_with`]. `authority` is
/// the caller-supplied [`TreeRebuildAuthority`] -- `main.rs`'s
/// `--civiccast-repair` CLI passes the production
/// `native_service_registration::ServiceQuiescenceAuthority`, closing the
/// exact gap this module's doc explains: the standalone repair path
/// previously reached `ensure_pack_extracted`'s destructive rebuild with no
/// stop-the-service call anywhere in its chain.
#[allow(clippy::too_many_arguments)]
pub fn run_repair(
    instdir: &Path,
    installer_dir: &Path,
    trust: &PackTrust,
    required_components: &[String],
    expected_product_version: &str,
    expected_compatible_core: &str,
    authority: &dyn TreeRebuildAuthority,
) -> RepairReport {
    run_repair_with(
        instdir,
        installer_dir,
        trust,
        required_components,
        expected_product_version,
        expected_compatible_core,
        repair_selector,
        reregister_service_and_firewall,
        authority,
    )
}

#[cfg(test)]
mod tests {
    use super::*;
    use base64::engine::general_purpose::STANDARD as BASE64;
    use base64::Engine as _;
    use ed25519_dalek::{Signer, SigningKey};
    use serde_json::json;
    use sha2::{Digest, Sha256};
    use std::cell::Cell;
    use std::io::Write as _;
    use zip::write::SimpleFileOptions;
    use zip::{CompressionMethod, ZipWriter};

    /// This module's own tests never exercise the [`TreeRebuildAuthority`]
    /// gate itself -- that behavior is fully covered by
    /// `native_pack_staging`'s own tests (recording/refusing fakes, byte-
    /// for-byte tree preservation). Every call here just needs a permissive
    /// authority so repair's existing corruption/side-load/idempotency
    /// coverage keeps its original meaning.
    struct AllowAllAuthority;

    impl TreeRebuildAuthority for AllowAllAuthority {
        fn authorize_rebuild(&self, _component: &str) -> Result<(), String> {
            Ok(())
        }
    }

    // ---- decide_component_repair_action: pure decision matrix ----

    #[test]
    fn already_satisfied_with_verified_tree_needs_no_action() {
        assert_eq!(
            decide_component_repair_action(StagingAction::AlreadySatisfied, true),
            RepairAction::NoActionNeeded
        );
    }

    #[test]
    fn already_satisfied_with_corrupt_tree_repairs_from_local_pack() {
        assert_eq!(
            decide_component_repair_action(StagingAction::AlreadySatisfied, false),
            RepairAction::RepairedFromLocalPack
        );
    }

    #[test]
    fn copy_from_offline_repairs_from_side_load() {
        assert_eq!(
            decide_component_repair_action(StagingAction::CopyFromOffline, false),
            RepairAction::RepairedFromSideLoad
        );
    }

    #[test]
    fn replace_corrupt_from_offline_repairs_from_side_load() {
        assert_eq!(
            decide_component_repair_action(StagingAction::ReplaceCorruptFromOffline, false),
            RepairAction::RepairedFromSideLoad
        );
    }

    #[test]
    fn needs_online_or_abort_is_not_repairable_locally() {
        assert_eq!(
            decide_component_repair_action(StagingAction::NeedsOnlineOrAbort, false),
            RepairAction::NotRepairableLocally
        );
    }

    // ---- decide_selector_repair_action: pure decision matrix ----

    #[test]
    fn selector_native_is_never_touched() {
        for other in [
            OtherProductState::Present,
            OtherProductState::Absent,
            OtherProductState::Unknown,
        ] {
            assert_eq!(
                decide_selector_repair_action(SelectorState::Native, other),
                SelectorRepairAction::NoActionNeeded
            );
        }
    }

    #[test]
    fn selector_wsl_is_a_legitimate_state_never_touched() {
        for other in [
            OtherProductState::Present,
            OtherProductState::Absent,
            OtherProductState::Unknown,
        ] {
            assert_eq!(
                decide_selector_repair_action(SelectorState::Wsl, other),
                SelectorRepairAction::NoActionNeeded
            );
        }
    }

    #[test]
    fn selector_absent_is_a_legitimate_state_never_touched() {
        for other in [
            OtherProductState::Present,
            OtherProductState::Absent,
            OtherProductState::Unknown,
        ] {
            assert_eq!(
                decide_selector_repair_action(SelectorState::Absent, other),
                SelectorRepairAction::NoActionNeeded
            );
        }
    }

    #[test]
    fn selector_unreadable_with_no_wsl_survivor_self_heals_to_native() {
        assert_eq!(
            decide_selector_repair_action(SelectorState::Unreadable, OtherProductState::Absent),
            SelectorRepairAction::RepairedToNative
        );
    }

    #[test]
    fn selector_unreadable_with_a_possible_wsl_survivor_is_never_guessed() {
        assert_eq!(
            decide_selector_repair_action(SelectorState::Unreadable, OtherProductState::Present),
            SelectorRepairAction::NotRepairableLocally
        );
        assert_eq!(
            decide_selector_repair_action(SelectorState::Unreadable, OtherProductState::Unknown),
            SelectorRepairAction::NotRepairableLocally
        );
    }

    // ---- version_mismatches: pure ----

    #[test]
    fn version_mismatches_names_only_the_disagreeing_components() {
        let observed = [
            ("app", "1.0.0-rc15"),
            ("server", "0.9.0"),
            ("caption", "1.0.0-rc15"),
        ];
        let mismatched = version_mismatches(observed, "1.0.0-rc15");
        assert_eq!(mismatched, vec!["server".to_string()]);
    }

    #[test]
    fn version_mismatches_is_empty_when_everything_agrees() {
        let observed = [("app", "1.0.0-rc15"), ("server", "1.0.0-rc15")];
        assert!(version_mismatches(observed, "1.0.0-rc15").is_empty());
    }

    // ---- overall_outcome: pure ----

    fn result_of(action: RepairAction) -> ComponentRepairResult {
        ComponentRepairResult {
            component: "x".to_string(),
            action,
            detail: "d".to_string(),
        }
    }

    #[test]
    fn overall_outcome_all_verified_when_nothing_needed_repair() {
        let components = vec![result_of(RepairAction::NoActionNeeded)];
        assert_eq!(
            overall_outcome(
                &components,
                SelectorRepairAction::NoActionNeeded,
                true,
                true
            ),
            OverallOutcome::AllVerified
        );
    }

    #[test]
    fn overall_outcome_repaired_when_a_component_was_repaired_and_nothing_is_unrepairable() {
        let components = vec![
            result_of(RepairAction::NoActionNeeded),
            result_of(RepairAction::RepairedFromLocalPack),
        ];
        assert_eq!(
            overall_outcome(
                &components,
                SelectorRepairAction::NoActionNeeded,
                true,
                true
            ),
            OverallOutcome::Repaired
        );
    }

    #[test]
    fn overall_outcome_repaired_when_only_the_selector_was_repaired() {
        let components = vec![result_of(RepairAction::NoActionNeeded)];
        assert_eq!(
            overall_outcome(
                &components,
                SelectorRepairAction::RepairedToNative,
                true,
                true
            ),
            OverallOutcome::Repaired
        );
    }

    #[test]
    fn overall_outcome_unrepairable_when_any_component_is_unrepairable() {
        let components = vec![
            result_of(RepairAction::NoActionNeeded),
            result_of(RepairAction::NotRepairableLocally),
        ];
        assert_eq!(
            overall_outcome(
                &components,
                SelectorRepairAction::NoActionNeeded,
                true,
                true
            ),
            OverallOutcome::Unrepairable
        );
    }

    #[test]
    fn overall_outcome_unrepairable_when_selector_is_unrepairable() {
        let components = vec![result_of(RepairAction::NoActionNeeded)];
        assert_eq!(
            overall_outcome(
                &components,
                SelectorRepairAction::NotRepairableLocally,
                true,
                true
            ),
            OverallOutcome::Unrepairable
        );
    }

    #[test]
    fn overall_outcome_unrepairable_when_service_or_firewall_reregistration_failed() {
        let components = vec![result_of(RepairAction::NoActionNeeded)];
        assert_eq!(
            overall_outcome(
                &components,
                SelectorRepairAction::NoActionNeeded,
                false,
                true
            ),
            OverallOutcome::Unrepairable
        );
        assert_eq!(
            overall_outcome(
                &components,
                SelectorRepairAction::NoActionNeeded,
                true,
                false
            ),
            OverallOutcome::Unrepairable
        );
    }

    // ---- integration-shaped: real signed pack fixtures (fs-only, no
    //      registry/service -- safe to run in cargo test) ----

    fn sha256_hex(bytes: &[u8]) -> String {
        let mut digest = Sha256::new();
        digest.update(bytes);
        format!("{:x}", digest.finalize())
    }

    fn scratch_dir(name: &str) -> PathBuf {
        let root = std::env::temp_dir().join(format!(
            "civiccast-native-repair-{name}-{}",
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
        product_version: &str,
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
        // enforces in production (SOURCE_BOUND_COMPONENTS in native_packs.rs).
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
            "product_version": product_version,
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

    const VERSION: &str = "1.0.0-rc15";

    #[test]
    fn healthy_component_needs_no_repair() {
        let root = scratch_dir("healthy");
        let signing_key = SigningKey::from_bytes(&[3_u8; 32]);
        let trust = trust_for(&signing_key);
        let installer_dir = root.join("installer");
        let instdir = root.join("instdir");
        fs::create_dir_all(installer_dir.join("packs")).expect("mkdir installer packs");
        fs::create_dir_all(instdir.join("packs")).expect("mkdir instdir packs");
        let pack_file = instdir.join("packs").join("native-server-binaries.ccpack");
        build_signed_pack(
            &pack_file,
            &signing_key,
            "native-server-binaries",
            VERSION,
            &[("bin/initdb.exe", b"pretend-initdb-bytes")],
        );
        // Extract it first (healthy install state) via the same primitive
        // repair reuses.
        native_pack_staging::ensure_pack_extracted(
            &pack_file,
            &instdir.join("packs"),
            "native-server-binaries",
            &trust,
            VERSION,
            VERSION,
            &AllowAllAuthority,
        )
        .expect("pre-extract a healthy tree");

        let result = repair_pack_component(
            &installer_dir,
            &instdir,
            &trust,
            "native-server-binaries",
            VERSION,
            VERSION,
            &AllowAllAuthority,
        );
        assert_eq!(result.action, RepairAction::NoActionNeeded);

        let _ = fs::remove_dir_all(&root);
    }

    #[test]
    fn corrupt_extracted_tree_with_a_healthy_local_pack_is_repaired_by_reextraction() {
        let root = scratch_dir("reextract");
        let signing_key = SigningKey::from_bytes(&[3_u8; 32]);
        let trust = trust_for(&signing_key);
        let installer_dir = root.join("installer");
        let instdir = root.join("instdir");
        fs::create_dir_all(installer_dir.join("packs")).expect("mkdir installer packs");
        fs::create_dir_all(instdir.join("packs")).expect("mkdir instdir packs");
        let pack_file = instdir.join("packs").join("native-server-binaries.ccpack");
        build_signed_pack(
            &pack_file,
            &signing_key,
            "native-server-binaries",
            VERSION,
            &[("bin/initdb.exe", b"pretend-initdb-bytes")],
        );
        let extraction_dir = native_pack_staging::ensure_pack_extracted(
            &pack_file,
            &instdir.join("packs"),
            "native-server-binaries",
            &trust,
            VERSION,
            VERSION,
            &AllowAllAuthority,
        )
        .expect("pre-extract");
        // Byte-flip the extracted file -- the exact "byte-flipped DLL" D5
        // repair scenario, but on the LAID tree, with a perfectly healthy
        // local .ccpack still sitting right beside it.
        fs::write(
            extraction_dir.join("bin").join("initdb.exe"),
            b"TAMPERED-bytes",
        )
        .expect("tamper extracted file");

        let result = repair_pack_component(
            &installer_dir,
            &instdir,
            &trust,
            "native-server-binaries",
            VERSION,
            VERSION,
            &AllowAllAuthority,
        );
        assert_eq!(result.action, RepairAction::RepairedFromLocalPack);
        assert_eq!(
            fs::read(extraction_dir.join("bin").join("initdb.exe")).expect("read repaired file"),
            b"pretend-initdb-bytes"
        );

        let _ = fs::remove_dir_all(&root);
    }

    #[test]
    fn missing_local_pack_is_repaired_from_installer_dir_side_load() {
        let root = scratch_dir("sideload");
        let signing_key = SigningKey::from_bytes(&[3_u8; 32]);
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
            VERSION,
            &[("bin/initdb.exe", b"pretend-initdb-bytes")],
        );
        // No pack at all under instdir\packs -- deleted/never staged.

        let result = repair_pack_component(
            &installer_dir,
            &instdir,
            &trust,
            "native-server-binaries",
            VERSION,
            VERSION,
            &AllowAllAuthority,
        );
        assert_eq!(result.action, RepairAction::RepairedFromSideLoad);
        assert!(
            instdir
                .join("packs")
                .join("native-server-binaries.ccpack")
                .is_file(),
            "the side-loaded pack must be landed as the new local pack"
        );
        assert!(
            instdir
                .join("packs")
                .join("native-server-binaries")
                .join("payload")
                .join("bin")
                .join("initdb.exe")
                .is_file(),
            "the extracted tree must be rebuilt from the side-loaded pack"
        );

        let _ = fs::remove_dir_all(&root);
    }

    #[test]
    fn corrupt_local_pack_with_no_side_load_is_not_repairable_locally() {
        let root = scratch_dir("unrepairable");
        let signing_key = SigningKey::from_bytes(&[3_u8; 32]);
        let trust = trust_for(&signing_key);
        let installer_dir = root.join("installer");
        let instdir = root.join("instdir");
        fs::create_dir_all(installer_dir.join("packs")).expect("mkdir installer packs");
        fs::create_dir_all(instdir.join("packs")).expect("mkdir instdir packs");
        let pack_file = instdir.join("packs").join("native-server-binaries.ccpack");
        fs::create_dir_all(pack_file.parent().expect("parent")).expect("mkdir packs dir");
        fs::write(&pack_file, b"not-even-a-zip-file").expect("write garbage pack");

        let result = repair_pack_component(
            &installer_dir,
            &instdir,
            &trust,
            "native-server-binaries",
            VERSION,
            VERSION,
            &AllowAllAuthority,
        );
        assert_eq!(result.action, RepairAction::NotRepairableLocally);
        assert!(result.detail.contains("native-server-binaries"));
        assert!(result.detail.to_lowercase().contains("packs"));
        assert!(
            result.detail.contains("NOT-REPAIRABLE-LOCALLY"),
            "detail must name the exact outcome: {}",
            result.detail
        );

        let _ = fs::remove_dir_all(&root);
    }

    #[test]
    fn a_stale_version_pack_is_treated_as_corrupt_and_repaired_from_a_correct_side_load() {
        // Exactly the "version" tree scenario: an operator accidentally
        // side-loads (or a prior bad copy leaves behind) a wrong-version
        // pack. `expected_product_version` is threaded through every check
        // this module makes, so this is caught and repaired via the SAME
        // path as any other corruption -- no separate "version" mutation
        // path exists or is needed.
        let root = scratch_dir("stale-version");
        let signing_key = SigningKey::from_bytes(&[3_u8; 32]);
        let trust = trust_for(&signing_key);
        let installer_dir = root.join("installer");
        let instdir = root.join("instdir");
        fs::create_dir_all(installer_dir.join("packs")).expect("mkdir installer packs");
        fs::create_dir_all(instdir.join("packs")).expect("mkdir instdir packs");
        // Stale local pack: right component, wrong product_version.
        build_signed_pack(
            &instdir.join("packs").join("native-server-binaries.ccpack"),
            &signing_key,
            "native-server-binaries",
            "0.9.0-stale",
            &[("bin/initdb.exe", b"stale-bytes")],
        );
        // Correct-version side-load.
        build_signed_pack(
            &installer_dir
                .join("packs")
                .join("native-server-binaries.ccpack"),
            &signing_key,
            "native-server-binaries",
            VERSION,
            &[("bin/initdb.exe", b"pretend-initdb-bytes")],
        );

        let result = repair_pack_component(
            &installer_dir,
            &instdir,
            &trust,
            "native-server-binaries",
            VERSION,
            VERSION,
            &AllowAllAuthority,
        );
        assert_eq!(result.action, RepairAction::RepairedFromSideLoad);
        assert_eq!(
            fs::read(
                instdir
                    .join("packs")
                    .join("native-server-binaries")
                    .join("payload")
                    .join("bin")
                    .join("initdb.exe")
            )
            .expect("read repaired file"),
            b"pretend-initdb-bytes"
        );

        let _ = fs::remove_dir_all(&root);
    }

    // ---- discover_repair_component_universe ----

    #[test]
    fn universe_always_includes_required_components_even_with_no_trace_on_disk() {
        let root = scratch_dir("universe-required-only");
        let instdir = root.join("instdir");
        fs::create_dir_all(&instdir).expect("mkdir instdir");
        let required = vec![
            "native-server-binaries".to_string(),
            "native-app-payload".to_string(),
        ];
        let universe = discover_repair_component_universe(&instdir, &required);
        assert!(universe.contains(&"native-server-binaries".to_string()));
        assert!(universe.contains(&"native-app-payload".to_string()));
        let _ = fs::remove_dir_all(&root);
    }

    #[test]
    fn universe_discovers_an_optional_present_caption_pack() {
        let root = scratch_dir("universe-caption");
        let instdir = root.join("instdir");
        fs::create_dir_all(instdir.join("packs")).expect("mkdir packs");
        fs::write(
            instdir.join("packs").join("captions-large-v3.ccpack"),
            b"pretend pack bytes",
        )
        .expect("write caption pack placeholder");
        let required = vec![
            "native-server-binaries".to_string(),
            "native-app-payload".to_string(),
        ];
        let universe = discover_repair_component_universe(&instdir, &required);
        assert!(
            universe.contains(&"captions-large-v3".to_string()),
            "an optional present caption pack must join the repair universe: {universe:?}"
        );
        let _ = fs::remove_dir_all(&root);
    }

    #[test]
    fn universe_discovers_an_orphaned_extracted_tree_with_no_matching_raw_pack() {
        let root = scratch_dir("universe-orphan");
        let instdir = root.join("instdir");
        fs::create_dir_all(
            instdir
                .join("packs")
                .join("captions-large-v3")
                .join("payload"),
        )
        .expect("mkdir orphaned extracted tree");
        // No captions-large-v3.ccpack anywhere -- deleted, but the tree
        // remains: this is a real corruption state repair must detect.
        let required = vec![
            "native-server-binaries".to_string(),
            "native-app-payload".to_string(),
        ];
        let universe = discover_repair_component_universe(&instdir, &required);
        assert!(
            universe.contains(&"captions-large-v3".to_string()),
            "an orphaned extracted tree with no matching pack must still join the universe: {universe:?}"
        );
        let _ = fs::remove_dir_all(&root);
    }

    #[test]
    fn universe_never_treats_the_acquire_cache_directory_as_a_component() {
        let root = scratch_dir("universe-acquire-cache");
        let instdir = root.join("instdir");
        fs::create_dir_all(instdir.join("packs").join(".acquire-cache")).expect("mkdir cache dir");
        let required: Vec<String> = Vec::new();
        let universe = discover_repair_component_universe(&instdir, &required);
        assert!(!universe.contains(&".acquire-cache".to_string()));
        let _ = fs::remove_dir_all(&root);
    }

    #[test]
    fn ma30_the_station_cache_directory_is_never_treated_as_a_component() {
        // <installer-path-audit MA-30> D5 repair returned `Unrepairable` --
        // exit 79 -- on EVERY healthy activated station.
        //
        // The activation step passes
        // `--cache-root "$INSTDIR\packs\.station-cache"` and
        // `retain_verified_index` does `create_dir_all(cache_root.join(
        // "indexes"))`, so `$INSTDIR\packs\.station-cache\` exists after every
        // successful install -- USB side-load and download-only alike. The
        // universe excluded only the literal `.acquire-cache`, so
        // `.station-cache` was enrolled as a component,
        // `repair_pack_component` found no `.station-cache.ccpack`, returned
        // NotRepairableLocally, and `overall_outcome`'s `any()` made the whole
        // repair Unrepairable -- with a remedy the operator cannot follow,
        // because that pack does not and cannot exist.
        let root = scratch_dir("universe-station-cache");
        let instdir = root.join("instdir");
        fs::create_dir_all(instdir.join("packs").join(".station-cache").join("indexes"))
            .expect("mkdir the station cache exactly as activation leaves it");
        fs::create_dir_all(instdir.join("packs").join("captions-floor"))
            .expect("mkdir a real staged component beside it");
        let required: Vec<String> = Vec::new();

        let universe = discover_repair_component_universe(&instdir, &required);

        assert!(
            !universe.contains(&".station-cache".to_string()),
            "the per-SHA pack cache is installer bookkeeping, not a component: {universe:?}"
        );
        assert!(
            universe.contains(&"captions-floor".to_string()),
            "a real staged component beside it must still be discovered: {universe:?}"
        );
    }

    #[test]
    fn ma31_the_report_says_what_this_repair_did_not_check() {
        // <installer-path-audit MA-31, honesty half> A grep for
        // `station-set`, `activation-self-test`, `schema` and `DATABASE_URL`
        // across this module's non-test body found none, so `AllVerified` /
        // exit 0 is a verdict derived from pack hashes alone -- on a
        // new-code-over-old-schema station, or a rolled-back flat layout, it
        // reports "healthy" over a station that cannot serve.
        let not_checked = repair_checks_not_performed();
        assert!(!not_checked.is_empty());
        let combined = not_checked.join(" ").to_lowercase();
        assert!(combined.contains("schema"), "{combined}");
        assert!(combined.contains("not checked"), "{combined}");
        assert!(
            combined.contains("station-set.json"),
            "the activation artifacts must be named too: {combined}"
        );
        assert!(
            combined.contains("needs the database"),
            "the report must say WHY the schema is unchecked, or it reads as an oversight \
             rather than a boundary: {combined}"
        );
    }

    #[test]
    fn ma31_every_repair_report_carries_the_not_checked_rows() {
        // Not just the constructor -- the report a real run produces, on the
        // AllVerified path specifically, which is the one that misleads.
        let root = scratch_dir("repair-not-checked");
        let signing_key = SigningKey::from_bytes(&[5_u8; 32]);
        let trust = trust_for(&signing_key);
        let installer_dir = root.join("installer");
        let instdir = root.join("instdir");
        fs::create_dir_all(installer_dir.join("packs")).expect("mkdir installer packs");
        fs::create_dir_all(instdir.join("packs")).expect("mkdir instdir packs");
        let report = run_repair_with(
            &instdir,
            &installer_dir,
            &trust,
            &[],
            VERSION,
            VERSION,
            || fake_selector(SelectorRepairAction::NoActionNeeded),
            |_instdir| (true, "ok".to_string(), true, "ok".to_string()),
            &AllowAllAuthority,
        );
        assert_eq!(report.outcome, OverallOutcome::AllVerified);
        assert!(
            !report.not_checked.is_empty(),
            "an AllVerified verdict is exactly where the boundary has to be stated"
        );
    }

    #[test]
    fn ma30_every_dot_prefixed_directory_is_bookkeeping_not_a_component() {
        // Skipping the whole DOT-prefixed class rather than adding a second
        // literal is the fix: the next bookkeeping directory someone adds
        // must not resurrect this defect.
        let root = scratch_dir("universe-dot-dirs");
        let instdir = root.join("instdir");
        for name in [".acquire-cache", ".station-cache", ".partials", ".tmp"] {
            fs::create_dir_all(instdir.join("packs").join(name)).expect("mkdir bookkeeping dir");
        }
        let required: Vec<String> = Vec::new();
        let universe = discover_repair_component_universe(&instdir, &required);
        assert!(
            universe.is_empty(),
            "no dot-prefixed directory may be enrolled as a component: {universe:?}"
        );
    }

    // ---- run_repair_with: full orchestration with injected fakes (no
    //      real registry/SCM access) ----

    fn fake_selector(action: SelectorRepairAction) -> SelectorRepairResult {
        SelectorRepairResult {
            observed_selector: "test".to_string(),
            observed_other_product: "test".to_string(),
            action,
            detail: "fake".to_string(),
        }
    }

    #[test]
    fn run_repair_with_reports_all_verified_over_a_fully_healthy_install_and_still_reregisters() {
        let root = scratch_dir("orchestration-healthy");
        let signing_key = SigningKey::from_bytes(&[5_u8; 32]);
        let trust = trust_for(&signing_key);
        let installer_dir = root.join("installer");
        let instdir = root.join("instdir");
        fs::create_dir_all(installer_dir.join("packs")).expect("mkdir installer packs");
        for component in ["native-server-binaries", "native-app-payload"] {
            let pack_file = instdir.join("packs").join(format!("{component}.ccpack"));
            fs::create_dir_all(pack_file.parent().expect("parent")).expect("mkdir packs dir");
            build_signed_pack(
                &pack_file,
                &signing_key,
                component,
                VERSION,
                &[("bin/tool.exe", b"pretend-bytes")],
            );
            native_pack_staging::ensure_pack_extracted(
                &pack_file,
                &instdir.join("packs"),
                component,
                &trust,
                VERSION,
                VERSION,
                &AllowAllAuthority,
            )
            .expect("pre-extract healthy component");
        }
        let required = vec![
            "native-server-binaries".to_string(),
            "native-app-payload".to_string(),
        ];

        let service_and_firewall_calls = Cell::new(0);
        let report = run_repair_with(
            &instdir,
            &installer_dir,
            &trust,
            &required,
            VERSION,
            VERSION,
            || fake_selector(SelectorRepairAction::NoActionNeeded),
            |_instdir| {
                service_and_firewall_calls.set(service_and_firewall_calls.get() + 1);
                (
                    true,
                    "fake service ok".to_string(),
                    true,
                    "fake firewall ok".to_string(),
                )
            },
            &AllowAllAuthority,
        );

        assert_eq!(report.outcome, OverallOutcome::AllVerified);
        assert!(report
            .components
            .iter()
            .all(|c| c.action == RepairAction::NoActionNeeded));
        assert!(report.version_mismatches.is_empty());
        assert_eq!(
            service_and_firewall_calls.get(),
            1,
            "D5's 're-register service' runs unconditionally, even over a healthy install"
        );
        assert!(report.service_reregistered);
        assert!(report.firewall_reregistered);

        let _ = fs::remove_dir_all(&root);
    }

    #[test]
    fn run_repair_with_skips_service_reregistration_when_a_required_component_is_unrepairable() {
        let root = scratch_dir("orchestration-broken");
        let signing_key = SigningKey::from_bytes(&[5_u8; 32]);
        let trust = trust_for(&signing_key);
        let installer_dir = root.join("installer");
        let instdir = root.join("instdir");
        fs::create_dir_all(installer_dir.join("packs")).expect("mkdir installer packs");
        // native-app-payload: totally absent, no side-load either.
        let required = vec!["native-app-payload".to_string()];

        let service_and_firewall_calls = Cell::new(0);
        let report = run_repair_with(
            &instdir,
            &installer_dir,
            &trust,
            &required,
            VERSION,
            VERSION,
            || fake_selector(SelectorRepairAction::NoActionNeeded),
            |_instdir| {
                service_and_firewall_calls.set(service_and_firewall_calls.get() + 1);
                (
                    true,
                    "should not run".to_string(),
                    true,
                    "should not run".to_string(),
                )
            },
            &AllowAllAuthority,
        );

        assert_eq!(report.outcome, OverallOutcome::Unrepairable);
        assert_eq!(
            service_and_firewall_calls.get(),
            0,
            "service/firewall re-registration must never run against a broken application tree"
        );
        assert!(!report.service_reregistered);
        assert!(!report.firewall_reregistered);
        assert!(report.service_detail.contains("skipped"));

        let _ = fs::remove_dir_all(&root);
    }

    #[test]
    fn run_repair_with_reports_repaired_when_a_side_load_fixed_a_missing_component() {
        let root = scratch_dir("orchestration-repaired");
        let signing_key = SigningKey::from_bytes(&[5_u8; 32]);
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
            VERSION,
            &[("bin/initdb.exe", b"pretend-initdb-bytes")],
        );
        let required = vec!["native-server-binaries".to_string()];

        let report = run_repair_with(
            &instdir,
            &installer_dir,
            &trust,
            &required,
            VERSION,
            VERSION,
            || fake_selector(SelectorRepairAction::NoActionNeeded),
            |_instdir| (true, "ok".to_string(), true, "ok".to_string()),
            &AllowAllAuthority,
        );

        assert_eq!(report.outcome, OverallOutcome::Repaired);
        assert_eq!(
            report.components[0].action,
            RepairAction::RepairedFromSideLoad
        );

        let _ = fs::remove_dir_all(&root);
    }
}
