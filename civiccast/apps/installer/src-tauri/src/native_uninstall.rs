// SPDX-License-Identifier: Apache-2.0
// Copyright (c) The CivicCast Authors

//! Native/WSL uninstall ownership policy and the Windows preflight adapter.
//!
//! Registry observations are direct Win32 registry calls: localized `reg.exe`
//! output is never parsed. The sole-active marker is not a selector mutation;
//! it is a product-owned proof consumed by NSIS only after the uninstaller has
//! completed its normal removal work.
//!
//! ## WSL ARP probe: elevated per-machine uninstall and other-user hives
//!
//! The WSL product's uninstall registration is a per-user (`HKEY_CURRENT_USER`)
//! ARP entry. When the Native uninstaller runs elevated for a per-machine
//! removal, `HKEY_CURRENT_USER` resolves to the *elevating admin's* hive, not
//! necessarily the hive of the user who installed WSL. To avoid misclassifying
//! a different user's still-installed WSL product as absent, the probe also
//! enumerates `HKEY_USERS` and checks every other loaded user hive.
//!
//! `HKEY_USERS` only exposes hives that are currently **loaded** — i.e. the
//! profiles of users who are logged on (or otherwise mounted) at probe time.
//! A per-user WSL install belonging to a user who is not logged in is
//! invisible to this probe and is indistinguishable from a true absence; see
//! [`WSL_ARP_PROBE_LOADED_HIVES_ONLY`]. Mounting `NTUSER.DAT` for unloaded
//! profiles, or reconciling against `C:\Users`, is a deliberate policy
//! decision reserved for the coordinator and is intentionally NOT implemented
//! here — this module only widens visibility to hives Windows has already
//! loaded, and fails closed (`Unknown`, which blocks uninstall) whenever the
//! `HKEY_USERS` enumeration itself fails or any probed view errors with
//! anything other than "not found".

#[cfg(target_os = "windows")]
use std::io;

#[cfg(target_os = "windows")]
use winreg::enums::{
    HKEY_CURRENT_USER, HKEY_LOCAL_MACHINE, HKEY_USERS, KEY_READ, KEY_SET_VALUE, KEY_WOW64_32KEY,
    KEY_WOW64_64KEY,
};
#[cfg(target_os = "windows")]
use winreg::RegKey;

/// `HKEY_USERS` enumeration (used to catch a per-user WSL install owned by a
/// different, currently logged-on user during an elevated uninstall) only
/// observes hives Windows has already loaded. Users who are not logged in
/// remain invisible to the probe and are NOT distinguished from a true
/// absence. This constant is the named seam a future coordinator-owned
/// change (mounting `NTUSER.DAT`, or reconciling against `C:\Users`) would
/// need to address; it is intentionally left unimplemented here.
///
/// Not read at runtime by this module (it is a documentation/grep seam and
/// a unit-test pin, not a branch condition), so it is exempted from the
/// unused-item lint rather than deleted.
#[allow(dead_code)]
pub const WSL_ARP_PROBE_LOADED_HIVES_ONLY: bool = true;

const SELECTOR_KEY: &str = r"SOFTWARE\CivicCast";
const SELECTOR_VALUE: &str = "ActiveRuntime";
const WSL_ARP_KEY: &str =
    r"Software\Microsoft\Windows\CurrentVersion\Uninstall\CivicCast Installer";
pub const SOLE_POSTCLEAR_EXIT_CODE: i32 = 73;
/// `native_uninstall_preflight` returns `TransferAcknowledgmentRequired`
/// (never touching the registry) when acknowledging a transfer, if given,
/// would flip an otherwise-`Block`ed uninstall to `AllowAfterTransfer`. The
/// CLI/NSIS layer maps that to this exit code so the interactive surfaces
/// know exactly when prompting for acknowledgment is the right response --
/// distinct from `SOLE_POSTCLEAR_EXIT_CODE` (73, a different armed-plan
/// signal) and from the generic blocked/error exit code (77) used for every
/// `Block` an acknowledgment cannot fix (unreadable selector, unknown WSL
/// presence).
pub const TRANSFER_ACK_REQUIRED_EXIT_CODE: i32 = 74;
const POSTCLEAR_MARKER: &str = "NativeUninstallPostclearPending";
const POSTCLEAR_MARKER_VALUE: &str = "civiccast-native-sole-active-v1";
/// Records that an acknowledged ActiveRuntime transfer to Wsl was performed
/// and verified, so the D1 "Cross-uninstall (active, survivor present)"
/// proof-matrix row has a durable, independently-inspectable fact to assert
/// against, distinct from (and in addition to) the ActiveRuntime value
/// itself flipping to `"wsl"`. Unlike `POSTCLEAR_MARKER`, this marker is a
/// permanent transfer-occurred record -- it is never consumed/cleared by
/// POSTUNINSTALL.
const TRANSFER_MARKER: &str = "NativeUninstallTransferCompleted";
const TRANSFER_MARKER_VALUE: &str = "civiccast-native-transfer-v1";

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Product {
    Native,
    Wsl,
}

impl Product {
    pub fn parse(value: &str) -> Option<Self> {
        match value {
            "native" => Some(Self::Native),
            "wsl" => Some(Self::Wsl),
            _ => None,
        }
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum SelectorState {
    Native,
    Wsl,
    Absent,
    Unreadable,
}

impl SelectorState {
    pub fn parse(value: &str) -> Option<Self> {
        match value {
            "native" => Some(Self::Native),
            "wsl" => Some(Self::Wsl),
            "absent" => Some(Self::Absent),
            "unreadable" => Some(Self::Unreadable),
            _ => None,
        }
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum OtherProductState {
    Present,
    Absent,
    Unknown,
}

impl OtherProductState {
    pub fn parse(value: &str) -> Option<Self> {
        match value {
            "present" => Some(Self::Present),
            "absent" => Some(Self::Absent),
            "unknown" => Some(Self::Unknown),
            _ => None,
        }
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum TransferState {
    NotRequested,
    AcceptedAndVerified,
    Refused,
    Failed,
}

impl TransferState {
    pub fn parse(value: &str) -> Option<Self> {
        match value {
            "not-requested" => Some(Self::NotRequested),
            "accepted-and-verified" => Some(Self::AcceptedAndVerified),
            "refused" => Some(Self::Refused),
            "failed" => Some(Self::Failed),
            _ => None,
        }
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Decision {
    AllowInactive,
    AllowNoOwner,
    AllowAfterTransfer,
    AllowSolePostclear,
    Block,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum SelectorMutation {
    None,
    ClearInPostUninstall,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct UninstallPlan {
    pub decision: Decision,
    pub selector_mutation: SelectorMutation,
}

fn blocked_plan() -> UninstallPlan {
    UninstallPlan {
        decision: Decision::Block,
        selector_mutation: SelectorMutation::None,
    }
}

/// The real-world result of [`native_uninstall_preflight`] once acknowledgment
/// is factored in: either the uninstall may proceed with `plan` (which may
/// still be a no-mutation `AllowInactive`/`AllowNoOwner`/`AllowAfterTransfer`,
/// or an `AllowSolePostclear` whose marker has already been armed), or an
/// un-acknowledged transfer-eligible call needs the caller to obtain operator
/// acknowledgment before retrying. This is a CLI/NSIS-facing wrapper around
/// [`UninstallPlan`], not a change to the pure policy core's [`Decision`]
/// enum -- `decide` itself is untouched.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum PreflightOutcome {
    Allowed(UninstallPlan),
    TransferAcknowledgmentRequired,
}

/// True exactly when acknowledging a transfer right now would flip `decide`'s
/// outcome from `Block` to `AllowAfterTransfer` -- i.e. this IS the D1
/// "uninstalling the ACTIVE product is blocked until ownership is
/// transferred" case. This is a CLI/NSIS-facing classification layered on
/// top of the pure policy core (it calls `decide`, never duplicates its
/// logic), not a new `Decision` variant: it lets the interactive surfaces
/// (the NSIS `MB_YESNO` prompt, the CLI's `--acknowledge-transfer` flag) know
/// WHEN prompting is the right response to a `Block`, versus a `Block` for an
/// unrelated reason (unreadable selector, unknown WSL-presence probe) that no
/// acknowledgment can fix.
pub fn transfer_would_unblock(
    product: Product,
    selector: SelectorState,
    other_product: OtherProductState,
) -> bool {
    let currently_active = matches!(
        (product, selector),
        (Product::Native, SelectorState::Native) | (Product::Wsl, SelectorState::Wsl)
    );
    currently_active
        && other_product == OtherProductState::Present
        && decide(
            product,
            selector,
            other_product,
            TransferState::NotRequested,
        )
        .decision
            == Decision::Block
}

pub fn decide(
    product: Product,
    selector: SelectorState,
    other_product: OtherProductState,
    transfer: TransferState,
) -> UninstallPlan {
    let no_mutation = |decision| UninstallPlan {
        decision,
        selector_mutation: SelectorMutation::None,
    };

    match selector {
        SelectorState::Unreadable => no_mutation(Decision::Block),
        SelectorState::Absent => no_mutation(Decision::AllowNoOwner),
        SelectorState::Native if product == Product::Wsl => no_mutation(Decision::AllowInactive),
        SelectorState::Wsl if product == Product::Native => no_mutation(Decision::AllowInactive),
        SelectorState::Native | SelectorState::Wsl => match other_product {
            OtherProductState::Present if transfer == TransferState::AcceptedAndVerified => {
                no_mutation(Decision::AllowAfterTransfer)
            }
            OtherProductState::Absent => UninstallPlan {
                decision: Decision::AllowSolePostclear,
                selector_mutation: SelectorMutation::ClearInPostUninstall,
            },
            OtherProductState::Present | OtherProductState::Unknown => no_mutation(Decision::Block),
        },
    }
}

/// Converts independently observed NSIS adapter strings into a safe plan.
///
/// Parsing is deliberately exact: missing, misspelled, or unexpected values
/// produce a blocking plan rather than defaulting to an uninstall action.
pub fn decide_from_adapter_inputs(
    product: &str,
    selector: &str,
    other_product: &str,
    transfer: &str,
) -> UninstallPlan {
    match (
        Product::parse(product),
        SelectorState::parse(selector),
        OtherProductState::parse(other_product),
        TransferState::parse(transfer),
    ) {
        (Some(product), Some(selector), Some(other_product), Some(transfer)) => {
            decide(product, selector, other_product, transfer)
        }
        _ => blocked_plan(),
    }
}

/// Parse the complete process argument vector for the uninstall-policy mode.
///
/// The policy sentinel owns the invocation whenever it is present. Every
/// missing, duplicate, or foreign argument then returns a blocking plan; a
/// generic `--help` or another CivicCast mode can never hijack the request.
pub fn decide_from_cli_args(args: &[String]) -> Option<UninstallPlan> {
    const SENTINEL: &str = "--civiccast-native-uninstall-policy";
    if !args.iter().any(|arg| arg == SENTINEL) {
        return None;
    }

    let mut sentinel_seen = false;
    let mut product: Option<&str> = None;
    let mut selector: Option<&str> = None;
    let mut other_product: Option<&str> = None;
    let mut transfer: Option<&str> = None;
    let mut index = 0;
    while index < args.len() {
        let argument = args[index].as_str();
        if argument == SENTINEL {
            if sentinel_seen {
                return Some(blocked_plan());
            }
            sentinel_seen = true;
            index += 1;
            continue;
        }

        let destination = match argument {
            "--product" => &mut product,
            "--selector" => &mut selector,
            "--other-product" => &mut other_product,
            "--transfer-state" => &mut transfer,
            _ => return Some(blocked_plan()),
        };
        if destination.is_some() || index + 1 >= args.len() {
            return Some(blocked_plan());
        }
        *destination = Some(args[index + 1].as_str());
        index += 2;
    }

    Some(match (product, selector, other_product, transfer) {
        (Some(product), Some(selector), Some(other_product), Some(transfer)) => {
            decide_from_adapter_inputs(product, selector, other_product, transfer)
        }
        _ => blocked_plan(),
    })
}

pub fn decision_token(plan: UninstallPlan) -> &'static str {
    match plan.decision {
        Decision::AllowInactive => "allow-inactive",
        Decision::AllowNoOwner => "allow-no-owner",
        Decision::AllowAfterTransfer => "allow-after-transfer",
        Decision::AllowSolePostclear => "allow-sole-postclear",
        Decision::Block => "block",
    }
}

pub fn selector_mutation_token(plan: UninstallPlan) -> &'static str {
    match plan.selector_mutation {
        SelectorMutation::None => "none",
        SelectorMutation::ClearInPostUninstall => "clear-postuninstall",
    }
}

#[cfg(target_os = "windows")]
fn classify_registry_error(error: &io::Error) -> OtherProductState {
    if error.kind() == io::ErrorKind::NotFound {
        OtherProductState::Absent
    } else {
        OtherProductState::Unknown
    }
}

#[cfg(target_os = "windows")]
pub(crate) fn probe_active_runtime_selector() -> SelectorState {
    let hklm = RegKey::predef(HKEY_LOCAL_MACHINE);
    let key = match hklm.open_subkey_with_flags(SELECTOR_KEY, KEY_READ | KEY_WOW64_64KEY) {
        Ok(key) => key,
        Err(error) if error.kind() == io::ErrorKind::NotFound => return SelectorState::Absent,
        Err(_) => return SelectorState::Unreadable,
    };
    match key.get_value::<String, _>(SELECTOR_VALUE) {
        Ok(value) => SelectorState::parse(&value).unwrap_or(SelectorState::Unreadable),
        Err(error) if error.kind() == io::ErrorKind::NotFound => SelectorState::Absent,
        Err(_) => SelectorState::Unreadable,
    }
}

/// Well-known service SIDs that are never a real user profile and never own
/// a per-user WSL install. Compared case-insensitively.
const WELL_KNOWN_SERVICE_SIDS: [&str; 3] = ["S-1-5-18", "S-1-5-19", "S-1-5-20"];

/// Decide whether an `HKEY_USERS` top-level subkey name should be skipped
/// when hunting for another user's WSL ARP registration: `.DEFAULT` is not a
/// real profile, `*_Classes` subkeys are the per-user COM/shell shadow of an
/// already-enumerated SID and never carry ARP entries, and the well-known
/// service SIDs (SYSTEM/LOCAL SERVICE/NETWORK SERVICE) are never a WSL owner.
///
/// Pure and unit-tested independent of any live registry.
fn should_skip_users_subkey(name: &str) -> bool {
    let upper = name.to_ascii_uppercase();
    if upper == ".DEFAULT" {
        return true;
    }
    if upper.ends_with("_CLASSES") {
        return true;
    }
    WELL_KNOWN_SERVICE_SIDS.iter().any(|sid| upper == *sid)
}

/// Fail-closed combination of independently observed registry-view
/// classifications: any `Present` wins outright; otherwise any `Unknown`
/// (a probe that failed for a reason other than "not found", or an
/// enumeration step that could not run at all) wins over `Absent`; only when
/// every observed state is `Absent` does the combination report `Absent`.
///
/// Pure and unit-tested independent of any live registry, mirroring the
/// existing `classify_registry_error` testing style.
fn combine_probe_results<I>(results: I) -> OtherProductState
where
    I: IntoIterator<Item = OtherProductState>,
{
    let mut saw_unknown = false;
    for state in results {
        match state {
            OtherProductState::Present => return OtherProductState::Present,
            OtherProductState::Unknown => saw_unknown = true,
            OtherProductState::Absent => {}
        }
    }
    if saw_unknown {
        OtherProductState::Unknown
    } else {
        OtherProductState::Absent
    }
}

#[cfg(target_os = "windows")]
fn probe_wsl_arp_view(access: u32) -> OtherProductState {
    let hkcu = RegKey::predef(HKEY_CURRENT_USER);
    match hkcu.open_subkey_with_flags(WSL_ARP_KEY, KEY_READ | access) {
        Ok(_) => OtherProductState::Present,
        Err(error) => classify_registry_error(&error),
    }
}

/// Probe one WOW64 view of the WSL ARP key under an arbitrary root (used for
/// `HKEY_USERS\<SID>` roots; `subkey_prefix` is the SID subkey name).
#[cfg(target_os = "windows")]
fn probe_wsl_arp_view_under(root: &RegKey, subkey_prefix: &str, access: u32) -> OtherProductState {
    let path = format!("{subkey_prefix}\\{WSL_ARP_KEY}");
    match root.open_subkey_with_flags(&path, KEY_READ | access) {
        Ok(_) => OtherProductState::Present,
        Err(error) => classify_registry_error(&error),
    }
}

/// Enumerate every other *loaded* user hive under `HKEY_USERS` and probe
/// each (both WOW64 views) for the WSL ARP entry. See the module doc-comment
/// and [`WSL_ARP_PROBE_LOADED_HIVES_ONLY`] for the loaded-hives-only
/// limitation this intentionally does not solve.
#[cfg(target_os = "windows")]
fn probe_wsl_arp_hkey_users() -> OtherProductState {
    let hkey_users = RegKey::predef(HKEY_USERS);
    let names: Vec<String> = match hkey_users
        .enum_keys()
        .collect::<Result<Vec<String>, io::Error>>()
    {
        Ok(names) => names,
        // Enumeration itself failing (e.g. access denied) must fail closed:
        // it means we cannot rule out another loaded user owning WSL.
        Err(_) => return OtherProductState::Unknown,
    };

    combine_probe_results(
        names
            .into_iter()
            .filter(|name| !should_skip_users_subkey(name))
            .flat_map(|name| {
                [
                    probe_wsl_arp_view_under(&hkey_users, &name, KEY_WOW64_64KEY),
                    probe_wsl_arp_view_under(&hkey_users, &name, KEY_WOW64_32KEY),
                ]
            }),
    )
}

#[cfg(target_os = "windows")]
pub(crate) fn probe_wsl_arp() -> OtherProductState {
    // Same-user, un-elevated case: both HKCU ARP views must agree Absent
    // before we trust it; any denied/broken view is Unknown and blocks.
    let hkcu_state = combine_probe_results([
        probe_wsl_arp_view(KEY_WOW64_64KEY),
        probe_wsl_arp_view(KEY_WOW64_32KEY),
    ]);
    if hkcu_state == OtherProductState::Present {
        return OtherProductState::Present;
    }

    // Elevated per-machine case: HKCU is the elevating admin's hive, so also
    // check every other loaded user hive via HKEY_USERS (see module
    // doc-comment for the loaded-hives-only limitation this does not solve).
    let hkey_users_state = probe_wsl_arp_hkey_users();
    combine_probe_results([hkcu_state, hkey_users_state])
}

#[cfg(target_os = "windows")]
fn clear_postclear_marker() -> Result<(), String> {
    let hklm = RegKey::predef(HKEY_LOCAL_MACHINE);
    match hklm.open_subkey_with_flags(SELECTOR_KEY, KEY_SET_VALUE | KEY_WOW64_64KEY) {
        Ok(key) => key
            .delete_value(POSTCLEAR_MARKER)
            .or_else(|error| {
                if error.kind() == io::ErrorKind::NotFound {
                    Ok(())
                } else {
                    Err(error)
                }
            })
            .map_err(|error| format!("Could not clear stale native uninstall marker: {error}")),
        Err(error) if error.kind() == io::ErrorKind::NotFound => Ok(()),
        Err(error) => Err(format!(
            "Could not open the native lifecycle key to clear a stale marker: {error}"
        )),
    }
}

#[cfg(target_os = "windows")]
fn write_postclear_marker() -> Result<(), String> {
    let hklm = RegKey::predef(HKEY_LOCAL_MACHINE);
    let (key, _) = hklm
        .create_subkey_with_flags(SELECTOR_KEY, KEY_READ | KEY_SET_VALUE | KEY_WOW64_64KEY)
        .map_err(|error| format!("Could not create the native lifecycle marker: {error}"))?;
    key.set_value(POSTCLEAR_MARKER, &POSTCLEAR_MARKER_VALUE)
        .map_err(|error| {
            format!("Could not persist the native sole-active uninstall marker: {error}")
        })?;
    let persisted: String = key.get_value(POSTCLEAR_MARKER).map_err(|error| {
        format!("Could not verify the native sole-active uninstall marker: {error}")
    })?;
    if persisted != POSTCLEAR_MARKER_VALUE {
        return Err(
            "Native sole-active uninstall marker verification returned an unexpected value."
                .to_string(),
        );
    }
    Ok(())
}

/// Write `ActiveRuntime = "native"` and read it back to verify the write
/// landed -- the SAME write + read-back-verify convention as
/// [`write_postclear_marker`] immediately above, reusing
/// `SELECTOR_KEY`/`SELECTOR_VALUE` rather than re-declaring the registry path
/// a second time.
///
/// TWO callers, both of which decide WHEN this is safe and neither of which
/// this function second-guesses -- it only writes and verifies:
///
/// * D5 Repair's selector-repair remedy
///   (`native_repair::decide_selector_repair_action`).
/// * The install-time native ownership claim
///   ([`decide_install_selector_claim`], chain G).
///
/// Matches this module's existing untested-directly convention for real
/// registry mutation (the HARD RULE forbids unit-testing real registry
/// writes; both gating decisions are unit-tested instead).
#[cfg(target_os = "windows")]
pub(crate) fn write_selector_native() -> Result<(), String> {
    let hklm = RegKey::predef(HKEY_LOCAL_MACHINE);
    let (key, _) = hklm
        .create_subkey_with_flags(SELECTOR_KEY, KEY_READ | KEY_SET_VALUE | KEY_WOW64_64KEY)
        .map_err(|error| {
            format!(
                "Could not create/open the native lifecycle key to repair ActiveRuntime: {error}"
            )
        })?;
    key.set_value(SELECTOR_VALUE, &"native")
        .map_err(|error| format!("Could not write ActiveRuntime: {error}"))?;
    let persisted: String = key
        .get_value(SELECTOR_VALUE)
        .map_err(|error| format!("Could not verify ActiveRuntime after the write: {error}"))?;
    if persisted != NATIVE_SELECTOR_VALUE {
        return Err(
            "ActiveRuntime write verification mismatch: wrote \"native\" but the read-back did \
             not match."
                .to_string(),
        );
    }
    Ok(())
}

#[cfg(not(target_os = "windows"))]
pub(crate) fn write_selector_native() -> Result<(), String> {
    Err(
        "Writing the ActiveRuntime selector requires Windows registry access and fails closed \
         on this platform."
            .to_string(),
    )
}

// ---------------------------------------------------------------------------
// Install-time native ownership claim (chain G)
// ---------------------------------------------------------------------------

/// The EXACT `ActiveRuntime` text the native runtime's own guard accepts.
///
/// `civiccast.native.win_probes.read_selector` returns
/// `SelectorRead(ok=True, value="native")` only for a `REG_SZ` value named
/// `ActiveRuntime` under `SOFTWARE\CivicCast`, read through the 64-bit view
/// (`KEY_WOW64_64KEY`), whose text is exactly `native`. Anything else -- a
/// different type, a different spelling, the WOW6432Node shadow -- comes back
/// `ok=False` and `civiccast.native.runtime_guard.decide`'s step 2 blocks the
/// start. Stated here as a named constant so the write side and the tests
/// that pin the contract cannot drift apart.
pub const NATIVE_SELECTOR_VALUE: &str = "native";

/// What an install may do about `ActiveRuntime`.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum SelectorClaimAction {
    /// No selector exists and the WSL product is provably absent: this
    /// install is the machine's only CivicCast runtime, so it claims
    /// ownership by writing `"native"`.
    ClaimNative,
    /// The selector already says `"native"`; nothing to write.
    AlreadyNative,
    /// The WSL product owns the machine. An install NEVER steals that.
    LeaveWslOwnership,
    /// Ownership cannot be established from here -- the selector could not be
    /// read, or it is absent while a WSL product is (or may be) installed.
    /// The selector is left exactly as found.
    LeaveUnprovable,
}

/// Chain G's whole decision, pure and total over `SelectorState` x
/// `OtherProductState`.
///
/// ## The defect this closes
///
/// `ActiveRuntime` is the authority basis the LocalSystem supervisor's
/// dual-runtime guard starts the control plane on
/// (`civiccast/native/runtime_guard.py::decide`). Before this, the ONLY
/// writers were the WSL lane (`cutover-to-wsl`), the operator-run
/// `civiccast-runtime cutover-to-native` verb, D5 repair, and uninstall
/// bookkeeping -- a plain native install wrote it NEVER. So a freshly
/// installed native station had `selector=absent`, and `decide`'s step 4 then
/// depends entirely on `detect_wsl_install()`, which is a deliberate
/// TRI-STATE: on a machine where `wsl.exe` is the OS inbox stub and the
/// SCM WSL-service query is ambiguous it answers `None` (unknown), and the
/// guard correctly refuses to invent an authority basis --
/// `blocked_probe_unavailable`, control plane never starts. That fail-closed
/// behavior is CORRECT and is unchanged here. What was missing is the other
/// half: a native install must produce the selector it is asking the guard to
/// honor.
///
/// ## Why the table looks like `decide_selector_repair_action` but is not it
///
/// Repair (`native_repair::decide_selector_repair_action`) treats `Absent` as
/// a legitimate settled state and never touches it, because repair has no new
/// information -- it is only cleaning up corruption. An INSTALL does have new
/// information: the native product is being installed, elevated, right now.
/// That is a genuine ownership event, so `Absent` is the one cell an install
/// may legitimately write -- and only when `probe_wsl_arp` independently
/// proves the CivicCast WSL product is not registered, so the write cannot
/// silently take a machine away from a WSL install that was there first.
/// Every other cell is left exactly as found:
///
/// | selector     | WSL product         | action             |
/// |--------------|---------------------|--------------------|
/// | `Native`     | any                 | `AlreadyNative`    |
/// | `Wsl`        | any                 | `LeaveWslOwnership`|
/// | `Absent`     | `Absent`            | `ClaimNative`      |
/// | `Absent`     | `Present`/`Unknown` | `LeaveUnprovable`  |
/// | `Unreadable` | any                 | `LeaveUnprovable`  |
pub fn decide_install_selector_claim(
    selector: SelectorState,
    other_product: OtherProductState,
) -> SelectorClaimAction {
    match selector {
        SelectorState::Native => SelectorClaimAction::AlreadyNative,
        SelectorState::Wsl => SelectorClaimAction::LeaveWslOwnership,
        SelectorState::Unreadable => SelectorClaimAction::LeaveUnprovable,
        SelectorState::Absent => match other_product {
            OtherProductState::Absent => SelectorClaimAction::ClaimNative,
            OtherProductState::Present | OtherProductState::Unknown => {
                SelectorClaimAction::LeaveUnprovable
            }
        },
    }
}

/// The result of one install-time claim attempt.
///
/// `write_error` is `Some` ONLY when [`SelectorClaimAction::ClaimNative`] was
/// decided and the registry write (or its read-back verification) failed --
/// never for a deliberate non-write, which is a legitimate outcome rather
/// than a fault.
#[derive(Debug, Clone)]
pub struct SelectorClaimOutcome {
    pub action: SelectorClaimAction,
    /// One operator-readable sentence naming what was observed and what was
    /// done about it. Printed into the install log on EVERY path, including
    /// the ones that write nothing: a station whose selector was left alone
    /// will not start, and this line is the only place that says why.
    pub detail: String,
    pub write_error: Option<String>,
}

/// [`decide_install_selector_claim`] plus the probe/write I/O, with all three
/// sides injected so the orchestration itself is unit-testable without
/// touching a real registry (this module's HARD RULE).
pub fn claim_install_selector_with(
    probe_selector: impl Fn() -> SelectorState,
    probe_other_product: impl Fn() -> OtherProductState,
    write_native: impl Fn() -> Result<(), String>,
) -> SelectorClaimOutcome {
    let selector = probe_selector();
    // Only consulted in the ONE cell where it can change the answer, so a
    // slow/ambiguous ARP enumeration cannot affect an install whose selector
    // already settles the question.
    let other_product = if selector == SelectorState::Absent {
        probe_other_product()
    } else {
        OtherProductState::Unknown
    };
    let action = decide_install_selector_claim(selector, other_product);
    let (detail, write_error) = match action {
        SelectorClaimAction::ClaimNative => match write_native() {
            Ok(()) => (
                "ActiveRuntime was absent and no CivicCast WSL product is registered; this \
                 install claimed native ownership (ActiveRuntime = \"native\", read-back \
                 verified)."
                    .to_string(),
                None,
            ),
            Err(error) => (
                format!(
                    "ActiveRuntime was absent and no CivicCast WSL product is registered, but \
                     claiming native ownership failed: {error}"
                ),
                Some(error),
            ),
        },
        SelectorClaimAction::AlreadyNative => (
            "ActiveRuntime already reads \"native\"; this install left it unchanged.".to_string(),
            None,
        ),
        SelectorClaimAction::LeaveWslOwnership => (
            "ActiveRuntime reads \"wsl\", so the WSL product owns this machine; this install \
             left it unchanged. The native runtime will not start until an operator runs \
             `civiccast-runtime cutover-to-native`."
                .to_string(),
            None,
        ),
        SelectorClaimAction::LeaveUnprovable => (
            format!(
                "ActiveRuntime was left unchanged: observed selector {selector:?} with WSL \
                 product state {other_product:?}, which does not establish that this machine's \
                 runtime ownership is the native product's to claim. The native runtime will \
                 not start until an operator sets it; inspect \
                 HKLM\\SOFTWARE\\CivicCast\\ActiveRuntime."
            ),
            None,
        ),
    };
    SelectorClaimOutcome {
        action,
        detail,
        write_error,
    }
}

/// Production wiring of [`claim_install_selector_with`]: the real registry
/// selector probe, the real WSL-product ARP probe, and the real
/// write + read-back-verify.
#[cfg(target_os = "windows")]
pub fn claim_install_selector() -> SelectorClaimOutcome {
    claim_install_selector_with(
        probe_active_runtime_selector,
        probe_wsl_arp,
        write_selector_native,
    )
}

/// The acknowledged-transfer write: flips `ActiveRuntime` from `"native"` to
/// `"wsl"` using the SAME write + read-back-verify convention as
/// [`write_postclear_marker`] / [`repair_write_selector_native`] above, with
/// one addition the transfer's transactional contract requires: on a FAILED
/// write attempt (the `set_value` call itself erroring), this also re-reads
/// the key and confirms the pre-transfer value is still there, rather than
/// merely assuming a single `RegSetValueEx` call for one string value is
/// atomic. Callers (`native_uninstall_preflight`) treat any `Err` from this
/// function as "abort the uninstall before any removal step runs"; the
/// caller-facing contract is: `Ok(())` means `ActiveRuntime` is verified
/// `"wsl"`, `Err(_)` means `ActiveRuntime` is verified (or, in the rare case
/// the confirmation re-read itself fails, explicitly flagged as
/// indeterminate and named for manual inspection) still `"native"`.
#[cfg(target_os = "windows")]
pub(crate) fn transfer_active_runtime_to_wsl() -> Result<(), String> {
    let hklm = RegKey::predef(HKEY_LOCAL_MACHINE);
    let key = hklm
        .create_subkey_with_flags(SELECTOR_KEY, KEY_READ | KEY_SET_VALUE | KEY_WOW64_64KEY)
        .map_err(|error| {
            format!(
                "Could not open the native lifecycle key to transfer ActiveRuntime; the \
                 original value was not touched: {error}"
            )
        })?
        .0;

    let original: Option<String> = key.get_value(SELECTOR_VALUE).ok();

    if let Err(error) = key.set_value(SELECTOR_VALUE, &"wsl") {
        return Err(match &original {
            Some(value) => match key.get_value::<String, _>(SELECTOR_VALUE) {
                Ok(reread) if &reread == value => format!(
                    "Could not write ActiveRuntime during transfer (write call failed): \
                     {error}. Verified ActiveRuntime is still {value:?} (original state intact)."
                ),
                Ok(reread) => format!(
                    "Could not write ActiveRuntime during transfer (write call failed): \
                     {error}. ActiveRuntime is now {reread:?}, which does NOT match the \
                     pre-transfer value {value:?} -- state is INDETERMINATE and needs manual \
                     inspection of HKLM\\Software\\CivicCast\\ActiveRuntime."
                ),
                Err(reread_error) => format!(
                    "Could not write ActiveRuntime during transfer (write call failed): \
                     {error}. Could not re-read ActiveRuntime afterward to confirm the \
                     original value {value:?} is intact ({reread_error}); state is \
                     INDETERMINATE and needs manual inspection of \
                     HKLM\\Software\\CivicCast\\ActiveRuntime."
                ),
            },
            None => format!(
                "Could not write ActiveRuntime during transfer (write call failed): {error}. \
                 The pre-transfer value could not be read either, so original-state \
                 intactness cannot be confirmed; inspect \
                 HKLM\\Software\\CivicCast\\ActiveRuntime manually."
            ),
        });
    }

    let persisted: String = key
        .get_value(SELECTOR_VALUE)
        .map_err(|error| format!("Could not verify ActiveRuntime after transfer write: {error}"))?;
    if persisted != "wsl" {
        return Err(format!(
            "ActiveRuntime transfer verification mismatch: wrote \"wsl\" but the read-back \
             returned {persisted:?}."
        ));
    }
    Ok(())
}

#[cfg(not(target_os = "windows"))]
pub(crate) fn transfer_active_runtime_to_wsl() -> Result<(), String> {
    Err(
        "ActiveRuntime transfer requires Windows registry access and fails closed on this \
         platform."
            .to_string(),
    )
}

/// Write + read-back-verify [`TRANSFER_MARKER`] (see its doc comment); called
/// only immediately after [`transfer_active_runtime_to_wsl`] has itself
/// verified the selector write. A failure here does NOT undo the transfer
/// (the selector legitimately stays `"wsl"` -- see the module-level "on any
/// post-transfer uninstall failure" note in [`native_uninstall_preflight`]);
/// it is surfaced as an error so that specific preflight call aborts before
/// any removal step runs, and a retry is safe (the next call observes
/// `ActiveRuntime = Wsl`, which `decide` resolves to `AllowInactive` with no
/// further mutation, needing no re-acknowledgment).
#[cfg(target_os = "windows")]
fn write_transfer_marker() -> Result<(), String> {
    let hklm = RegKey::predef(HKEY_LOCAL_MACHINE);
    let (key, _) = hklm
        .create_subkey_with_flags(SELECTOR_KEY, KEY_READ | KEY_SET_VALUE | KEY_WOW64_64KEY)
        .map_err(|error| {
            format!(
                "Could not create the native lifecycle key to record the transfer marker: {error}"
            )
        })?;
    key.set_value(TRANSFER_MARKER, &TRANSFER_MARKER_VALUE)
        .map_err(|error| format!("Could not persist the native transfer marker: {error}"))?;
    let persisted: String = key
        .get_value(TRANSFER_MARKER)
        .map_err(|error| format!("Could not verify the native transfer marker: {error}"))?;
    if persisted != TRANSFER_MARKER_VALUE {
        return Err(
            "Native transfer marker verification returned an unexpected value.".to_string(),
        );
    }
    Ok(())
}

/// Probe the authoritative Windows state and arm POSTUNINSTALL only for the
/// active-Native, no-WSL-survivor case (`AllowSolePostclear`).
///
/// When Native is active AND the WSL product remains installed (D1's
/// transfer-required case, [`transfer_would_unblock`]):
/// * `acknowledge_transfer == false` returns `TransferAcknowledgmentRequired`
///   without reading or writing anything beyond the two read-only probes
///   below -- an unacknowledged/declined/cancelled call is a true no-op (D1's
///   "transfer refused/cancelled: NOTHING removed, both products intact").
/// * `acknowledge_transfer == true` performs the write+read-back-verified
///   `ActiveRuntime` transfer to `"wsl"` ([`transfer_active_runtime_to_wsl`])
///   BEFORE removal proceeds, matching D1's "authorized transaction... before
///   removal proceeds." A transfer-write failure aborts with `Err` and the
///   original state verified intact (see that function's doc comment); a
///   verified transfer records [`TRANSFER_MARKER`]
///   ([`write_transfer_marker`]) for the proof matrix. If marker-recording
///   itself fails, this call returns `Err` (so NSIS aborts before any
///   removal step runs) -- but the selector STAYS `"wsl"`: WSL genuinely now
///   owns activation, which is correct, not a rollback case, and a retry
///   needs no re-acknowledgment (the next call observes
///   `ActiveRuntime = Wsl` for `product = Native`, which `decide` already
///   resolves to `AllowInactive` with zero further mutation).
#[cfg(target_os = "windows")]
pub fn native_uninstall_preflight(acknowledge_transfer: bool) -> Result<PreflightOutcome, String> {
    clear_postclear_marker()?;
    let selector = probe_active_runtime_selector();
    let wsl_arp = probe_wsl_arp();
    let needs_transfer = transfer_would_unblock(Product::Native, selector, wsl_arp);

    if needs_transfer && !acknowledge_transfer {
        return Ok(PreflightOutcome::TransferAcknowledgmentRequired);
    }

    let plan = if needs_transfer {
        // acknowledge_transfer == true here (the branch above returned
        // otherwise).
        match transfer_active_runtime_to_wsl() {
            Ok(()) => {
                write_transfer_marker()?;
                decide(
                    Product::Native,
                    selector,
                    wsl_arp,
                    TransferState::AcceptedAndVerified,
                )
            }
            Err(error) => {
                return Err(format!(
                    "CivicCast (Native) uninstall ownership transfer FAILED: {error} The \
                     uninstall was aborted before any removal step ran; nothing was removed."
                ));
            }
        }
    } else {
        decide(
            Product::Native,
            selector,
            wsl_arp,
            TransferState::NotRequested,
        )
    };

    if plan.decision == Decision::Block {
        return Err(format!(
            "CivicCast (Native) uninstall is blocked: ActiveRuntime={selector:?}, WSL ARP={wsl_arp:?}."
        ));
    }
    if plan.decision == Decision::AllowSolePostclear {
        write_postclear_marker()?;
    }
    Ok(PreflightOutcome::Allowed(plan))
}

#[cfg(not(target_os = "windows"))]
pub fn native_uninstall_preflight(_acknowledge_transfer: bool) -> Result<PreflightOutcome, String> {
    Err("Native uninstall preflight requires Windows registry access and fails closed on this platform.".to_string())
}

// ---------------------------------------------------------------------------
// D4 bidirectional state inventory
// ---------------------------------------------------------------------------
//
// `spec-installer-lifecycle.md` D4: "Exact state inventory (files, registry
// keys, service, firewall rules) is enumerated in the spec's implementation
// and asserted by the proofs -- 'everything gone' means that inventory,
// bidirectionally." This table is the ONE source of truth for every
// machine-scoped state item `native_service_registration.rs`'s
// `NSIS_HOOK_POSTINSTALL` wiring establishes, paired with the POSTUNINSTALL
// step that must remove it. `nsis-hooks-native.nsh`'s `NSIS_HOOK_POSTUNINSTALL`
// macro is still empty (a later work package, not this one); when that work
// lands it MUST consume this table rather than re-deriving its own list, so
// install-creates and uninstall-removes can never drift apart -- extending
// the same file/constants this module already tracks for the ownership
// decision (`SELECTOR_KEY`, `WSL_ARP_KEY`, `POSTCLEAR_MARKER`) rather than
// forking a second inventory concept elsewhere.

// Not consumed by any live code path yet -- the POSTUNINSTALL teardown that
// will read this table is a later work package (see the doc comment above).
// Exempted from the unused-item lint rather than deleted, the same
// documentation/grep-seam convention `WSL_ARP_PROBE_LOADED_HIVES_ONLY` above
// already uses; fully exercised by `state_inventory_tests` below in the
// meantime.
#[allow(dead_code)]
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum StateItemKind {
    Service,
    RegistryValue,
    FirewallRule,
}

#[allow(dead_code)]
#[derive(Debug, Clone, Copy)]
pub struct StateInventoryItem {
    pub kind: StateItemKind,
    pub identifier: &'static str,
    pub established_by: &'static str,
    pub removed_by: &'static str,
}

#[allow(dead_code)]
pub const NATIVE_D4_STATE_INVENTORY: &[StateInventoryItem] = &[
    StateInventoryItem {
        kind: StateItemKind::Service,
        identifier: crate::native_service_registration::SERVICE_NAME,
        established_by: "python.exe -m civiccast.native.supervisor.service_host install \
            --startup auto (NSIS_HOOK_POSTINSTALL)",
        removed_by: "native_service_registration::stop_native_service (sc.exe stop, polled to \
            STOPPED) then native_service_registration::teardown_native_state's \
            \"remove service\" step (python.exe -m civiccast.native.supervisor.service_host \
            remove), driven by --civiccast-teardown-native-state \
            (NSIS_HOOK_POSTUNINSTALL, start of the macro)",
    },
    StateInventoryItem {
        kind: StateItemKind::RegistryValue,
        identifier: r"HKLM\SOFTWARE\CivicCast\Native\DatabaseUrl",
        established_by: "winreg set_value, read-back verified (native_service_registration::\
            write_database_url -- built and tested, NOT yet wired into NSIS_HOOK_POSTINSTALL; \
            see wp2-d4-service-registration evidence STOP section)",
        removed_by: "native_service_registration::teardown_native_state's \
            \"clear credentials\" step (delete_native_credential_values), \
            driven by --civiccast-teardown-native-state \
            (NSIS_HOOK_PREUNINSTALL, which is where the teardown CLI actually \
            runs; its result is carried into NSIS_HOOK_POSTUNINSTALL). \
            SECURITY FIX F-02 (2026-08-01 sandbox newcomer re-walk), \
            REVERSING the 2026-07-30 coordinator decision that preserved this \
            value: the re-walk read this live PostgreSQL password verbatim out \
            of the registry of a machine the product had already been \
            uninstalled from. Preserving product DATA under \
            %PROGRAMDATA%\\CivicCast was never a decision to leave a live \
            SECRET behind -- data is preserved; credentials are not. \
            DISCLOSED CONSEQUENCE, deliberately not hidden: the preserved \
            PostgreSQL cluster can no longer be reused by a reinstall, because \
            the password cannot be reconstructed from anything on disk. \
            civiccast.native.provision's decision matrix classifies that as \
            FAIL_LOUD_MISSING_REGISTRY and refuses rather than regenerating a \
            password the cluster would reject -- correct fail-closed behavior, \
            but it means uninstall-then-reinstall over preserved data needs \
            operator recovery. Re-establishing a credential for a surviving, \
            product-owned cluster is a separate, still-open unit of work",
    },
    StateInventoryItem {
        kind: StateItemKind::FirewallRule,
        identifier: crate::native_service_registration::FIREWALL_RULE_NAME,
        established_by: "netsh advfirewall firewall add rule (NSIS_HOOK_POSTINSTALL)",
        removed_by: "native_service_registration::delete_native_firewall_rule (probe then \
            netsh advfirewall firewall delete rule, idempotent), driven by \
            --civiccast-teardown-native-state (NSIS_HOOK_POSTUNINSTALL, start of the macro)",
    },
    StateInventoryItem {
        kind: StateItemKind::RegistryValue,
        identifier: r"HKLM\SOFTWARE\CivicCast\Native\InstalledVersion",
        established_by: "WriteRegStr at the fully-successful end of \
            NSIS_HOOK_POSTINSTALL (the D3 fresh-install gate's prior-version \
            signal -- ARP DisplayVersion is unusable because Tauri writes it \
            before the hook runs; Sandbox matrix row 1, 2026-07-30)",
        removed_by: "native_service_registration::teardown_native_state's \
            \"clear install markers\" step \
            (delete_native_install_marker_values), driven by \
            --civiccast-teardown-native-state (NSIS_HOOK_PREUNINSTALL; result \
            carried into NSIS_HOOK_POSTUNINSTALL). F-01 uninstaller half \
            (2026-08-01 sandbox newcomer re-walk), REVERSING the 2026-07-30 \
            coordinator decision that preserved this value so a reinstall \
            would be treated as an upgrade over surviving data. The re-walk is \
            the counter-evidence: the uninstaller reported \"Uninstall was \
            completed successfully\", left InstalledVersion=1.0.0-rc15, and \
            the next install read it, did not fire the D3 fresh-install gate, \
            logged \"step d3-engine: begin (old=1.0.0-rc15)\" against a \
            product that was not installed, and rolled back. On a machine with \
            no product installed that treatment is not an upgrade, it is a \
            false one. The ROUTING side (how much the D3 gate may trust this \
            marker, and what it does when its two signals disagree) is a \
            separate unit of work; this entry is only the uninstaller's \
            obligation",
    },
];

#[cfg(test)]
mod state_inventory_tests {
    use super::*;

    #[test]
    fn inventory_has_exactly_the_four_d4_items_service_two_registry_firewall() {
        assert_eq!(NATIVE_D4_STATE_INVENTORY.len(), 4);
        assert_eq!(
            NATIVE_D4_STATE_INVENTORY
                .iter()
                .filter(|item| item.kind == StateItemKind::RegistryValue)
                .count(),
            2,
            "DatabaseUrl and InstalledVersion are the tracked registry values -- the \
             installer-handoff SetupNonce this inventory used to also track was retired \
             along with the rest of the nonce/handoff mechanism"
        );
        assert!(NATIVE_D4_STATE_INVENTORY
            .iter()
            .any(|item| item.kind == StateItemKind::Service));
        assert!(NATIVE_D4_STATE_INVENTORY
            .iter()
            .any(|item| item.kind == StateItemKind::RegistryValue));
        assert!(NATIVE_D4_STATE_INVENTORY
            .iter()
            .any(|item| item.kind == StateItemKind::FirewallRule));
    }

    #[test]
    fn every_item_has_a_non_empty_identifier_and_no_duplicates() {
        let identifiers: Vec<&str> = NATIVE_D4_STATE_INVENTORY
            .iter()
            .map(|item| item.identifier)
            .collect();
        for identifier in &identifiers {
            assert!(!identifier.trim().is_empty());
        }
        let mut sorted = identifiers.clone();
        sorted.sort_unstable();
        sorted.dedup();
        assert_eq!(
            sorted.len(),
            identifiers.len(),
            "duplicate identifier in the D4 state inventory: {identifiers:?}"
        );
    }

    /// Bidirectionality: every item this table says is established somewhere
    /// also names where it is removed -- a blank `removed_by` would mean the
    /// table itself has drifted into a one-way (install-only) list, which is
    /// exactly the drift this table exists to prevent.
    #[test]
    fn every_item_names_both_an_establishing_and_a_removing_step() {
        for item in NATIVE_D4_STATE_INVENTORY {
            assert!(
                item.established_by.contains("POSTINSTALL"),
                "{:?} must name its POSTINSTALL establishing step",
                item.identifier
            );
            // Every item must name a REAL fate, and there are exactly two
            // truthful ones: it is torn down by POSTUNINSTALL, or it is
            // deliberately preserved and names what WILL remove it (the
            // typed PURGE action). "Names a keyword" is not a fate -- the
            // previous version of this assertion passed happily on the
            // literal text "POSTUNINSTALL -- not yet implemented" while
            // uninstall removed nothing at all, which is precisely how the
            // teardown BLOCKER survived undetected.
            let torn_down = item.removed_by.contains("POSTUNINSTALL");
            let deliberately_preserved = item.removed_by.contains("NOT removed by uninstall")
                && item.removed_by.contains("PURGE");
            assert!(
                torn_down || deliberately_preserved,
                "{:?} must either name its POSTUNINSTALL teardown or state it is \
                 deliberately preserved AND name the PURGE action that removes it; \
                 got: {:?}",
                item.identifier,
                item.removed_by
            );
            // The BLOCKER fix this table now documents: every removal is a REAL
            // wired mechanism (native_service_registration::teardown_native_state
            // and its steps, driven by --civiccast-teardown-native-state), never
            // the "not yet implemented" placeholder this table carried before.
            assert!(
                !item.removed_by.contains("not yet implemented"),
                "{:?}'s removal is no longer unimplemented -- update this string if it \
                 regresses",
                item.identifier
            );
        }
    }

    /// F-02 (sandbox newcomer re-walk `dd7f835f`, 2026-08-01): the live
    /// PostgreSQL password was read verbatim out of
    /// `HKLM\SOFTWARE\CivicCast\Native\DatabaseUrl` on a machine where the
    /// product had already been uninstalled through its own uninstaller.
    /// "Uninstall deliberately preserves product data" is a decision about
    /// DATA -- it was never a decision to leave live secrets on a machine the
    /// product no longer occupies.
    ///
    /// This is the bidirectional inventory's own statement of that rule: every
    /// credential-bearing value under `CivicCast\Native` names an ordinary
    /// POSTUNINSTALL teardown step as its remover, and none of them may claim
    /// the "deliberately preserved until a future PURGE" fate that
    /// `every_item_names_both_an_establishing_and_a_removing_step` above
    /// otherwise permits.
    ///
    /// RETIRED: the installer-handoff `SetupNonce` used to be tracked here
    /// too, as a second credential beside `DatabaseUrl`. The nonce/handoff
    /// mechanism was retired in favor of the control plane admitting first
    /// setup purely by checking the request's peer IP is loopback, so there
    /// is no longer a second credential-shaped value under this key.
    #[test]
    fn every_credential_bearing_value_is_removed_by_an_ordinary_uninstall() {
        for identifier in [r"HKLM\SOFTWARE\CivicCast\Native\DatabaseUrl"] {
            let item = NATIVE_D4_STATE_INVENTORY
                .iter()
                .find(|item| item.identifier == identifier)
                .unwrap_or_else(|| {
                    panic!(
                        "{identifier} is a credential this installer writes, so the D4 state \
                         inventory must track it and name the uninstall step that removes it"
                    )
                });
            assert!(
                !item.removed_by.contains("NOT removed by uninstall"),
                "{identifier} is a LIVE CREDENTIAL; an ordinary uninstall must delete it, not \
                 defer it to a future PURGE action. Got: {:?}",
                item.removed_by
            );
            assert!(
                item.removed_by.contains("clear credentials"),
                "{identifier} must name the teardown_native_state \"clear credentials\" step \
                 that actually removes it. Got: {:?}",
                item.removed_by
            );
        }
    }

    /// F-01, uninstaller half (sandbox newcomer re-walk `dd7f835f`,
    /// 2026-08-01): the uninstaller completed and reported success, leaving
    /// `InstalledVersion=1.0.0-rc15` behind. The very next install read it,
    /// classified a clean install as an upgrade, ran the D3 engine against a
    /// product that was not there, and rolled back. Uninstall -> reinstall was
    /// broken by state the uninstaller itself left.
    ///
    /// The ROUTING side of that (what the D3 gate does with a version marker
    /// it should not trust) is chain K's. This is the uninstaller side, stated
    /// as a rule: nothing that CLAIMS a product is installed may survive a
    /// completed uninstall.
    #[test]
    fn a_completed_uninstall_leaves_nothing_claiming_a_product_is_installed() {
        let item = NATIVE_D4_STATE_INVENTORY
            .iter()
            .find(|item| item.identifier == r"HKLM\SOFTWARE\CivicCast\Native\InstalledVersion")
            .expect("InstalledVersion must be tracked in the D4 state inventory");
        assert!(
            !item.removed_by.contains("NOT removed by uninstall"),
            "InstalledVersion is the D3 gate's 'a product is installed, and it is THIS \
             version' signal. A completed uninstall that leaves it behind makes the next \
             install misroute -- exactly what the re-walk reproduced. Got: {:?}",
            item.removed_by
        );
        assert!(
            item.removed_by.contains("clear install markers"),
            "InstalledVersion must name the teardown_native_state \"clear install markers\" \
             step that actually removes it. Got: {:?}",
            item.removed_by
        );
    }

    #[test]
    fn service_inventory_identifier_matches_the_registration_module_constant() {
        let service_item = NATIVE_D4_STATE_INVENTORY
            .iter()
            .find(|item| item.kind == StateItemKind::Service)
            .expect("a Service item must exist");
        assert_eq!(
            service_item.identifier,
            crate::native_service_registration::SERVICE_NAME
        );
    }

    #[test]
    fn firewall_inventory_identifier_matches_the_registration_module_constant() {
        let firewall_item = NATIVE_D4_STATE_INVENTORY
            .iter()
            .find(|item| item.kind == StateItemKind::FirewallRule)
            .expect("a FirewallRule item must exist");
        assert_eq!(
            firewall_item.identifier,
            crate::native_service_registration::FIREWALL_RULE_NAME
        );
    }

    #[test]
    fn registry_value_inventory_identifier_names_the_exact_hklm_path() {
        let registry_item = NATIVE_D4_STATE_INVENTORY
            .iter()
            .find(|item| item.kind == StateItemKind::RegistryValue)
            .expect("a RegistryValue item must exist");
        assert_eq!(
            registry_item.identifier,
            r"HKLM\SOFTWARE\CivicCast\Native\DatabaseUrl"
        );
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn inactive_product_is_allowed_without_selector_mutation() {
        let plan = decide(
            Product::Native,
            SelectorState::Wsl,
            OtherProductState::Present,
            TransferState::NotRequested,
        );

        assert_eq!(plan.decision, Decision::AllowInactive);
        assert_eq!(plan.selector_mutation, SelectorMutation::None);
    }

    #[test]
    fn policy_table_covers_every_valid_input_combination_for_both_products() {
        let products = [Product::Native, Product::Wsl];
        let selectors = [
            SelectorState::Native,
            SelectorState::Wsl,
            SelectorState::Absent,
            SelectorState::Unreadable,
        ];
        let other_product_states = [
            OtherProductState::Present,
            OtherProductState::Absent,
            OtherProductState::Unknown,
        ];
        let transfers = [
            TransferState::NotRequested,
            TransferState::AcceptedAndVerified,
            TransferState::Refused,
            TransferState::Failed,
        ];

        for product in products {
            for selector in selectors {
                for other_product in other_product_states {
                    for transfer in transfers {
                        let plan = decide(product, selector, other_product, transfer);
                        let active = matches!(
                            (product, selector),
                            (Product::Native, SelectorState::Native)
                                | (Product::Wsl, SelectorState::Wsl)
                        );
                        let expected = match selector {
                            SelectorState::Unreadable => (Decision::Block, SelectorMutation::None),
                            SelectorState::Absent => {
                                (Decision::AllowNoOwner, SelectorMutation::None)
                            }
                            _ if !active => (Decision::AllowInactive, SelectorMutation::None),
                            _ if other_product == OtherProductState::Present
                                && transfer == TransferState::AcceptedAndVerified =>
                            {
                                (Decision::AllowAfterTransfer, SelectorMutation::None)
                            }
                            _ if other_product == OtherProductState::Absent => (
                                Decision::AllowSolePostclear,
                                SelectorMutation::ClearInPostUninstall,
                            ),
                            _ => (Decision::Block, SelectorMutation::None),
                        };

                        assert_eq!(
                            (plan.decision, plan.selector_mutation),
                            expected,
                            "product={product:?}, selector={selector:?}, other={other_product:?}, transfer={transfer:?}"
                        );
                    }
                }
            }
        }
    }

    // ---- transfer_would_unblock: pure, CLI/NSIS prompt-gating classifier ----

    #[test]
    fn transfer_would_unblock_true_only_for_active_product_with_wsl_survivor() {
        assert!(transfer_would_unblock(
            Product::Native,
            SelectorState::Native,
            OtherProductState::Present,
        ));
        assert!(transfer_would_unblock(
            Product::Wsl,
            SelectorState::Wsl,
            OtherProductState::Present,
        ));
    }

    #[test]
    fn transfer_would_unblock_false_when_no_other_product_present() {
        assert!(!transfer_would_unblock(
            Product::Native,
            SelectorState::Native,
            OtherProductState::Absent,
        ));
        assert!(!transfer_would_unblock(
            Product::Native,
            SelectorState::Native,
            OtherProductState::Unknown,
        ));
    }

    #[test]
    fn transfer_would_unblock_false_when_the_product_is_not_the_active_one() {
        // Uninstalling the INACTIVE product never needs a transfer -- D1's
        // "uninstalling the inactive product never touches the selector".
        assert!(!transfer_would_unblock(
            Product::Native,
            SelectorState::Wsl,
            OtherProductState::Present,
        ));
        assert!(!transfer_would_unblock(
            Product::Wsl,
            SelectorState::Native,
            OtherProductState::Present,
        ));
    }

    #[test]
    fn transfer_would_unblock_false_for_absent_or_unreadable_selector() {
        for selector in [SelectorState::Absent, SelectorState::Unreadable] {
            for other in [
                OtherProductState::Present,
                OtherProductState::Absent,
                OtherProductState::Unknown,
            ] {
                assert!(
                    !transfer_would_unblock(Product::Native, selector, other),
                    "selector={selector:?}, other={other:?}"
                );
            }
        }
    }

    #[test]
    fn transfer_would_unblock_agrees_with_decide_across_the_full_input_space() {
        // Cross-check against the exhaustive `decide` table above: every case
        // this function reports `true` for must be a case where
        // `TransferState::AcceptedAndVerified` (instead of `NotRequested`)
        // would flip `decide`'s outcome from `Block` to `AllowAfterTransfer`,
        // and every case it reports `false` for must NOT flip that way.
        let products = [Product::Native, Product::Wsl];
        let selectors = [
            SelectorState::Native,
            SelectorState::Wsl,
            SelectorState::Absent,
            SelectorState::Unreadable,
        ];
        let others = [
            OtherProductState::Present,
            OtherProductState::Absent,
            OtherProductState::Unknown,
        ];
        for product in products {
            for selector in selectors {
                for other in others {
                    let not_requested =
                        decide(product, selector, other, TransferState::NotRequested);
                    let accepted =
                        decide(product, selector, other, TransferState::AcceptedAndVerified);
                    let acknowledgment_would_flip_block_to_allow = not_requested.decision
                        == Decision::Block
                        && accepted.decision == Decision::AllowAfterTransfer;
                    assert_eq!(
                        transfer_would_unblock(product, selector, other),
                        acknowledgment_would_flip_block_to_allow,
                        "product={product:?}, selector={selector:?}, other={other:?}"
                    );
                }
            }
        }
    }

    // ---- exit code constants stay distinct ----

    #[test]
    fn transfer_ack_required_exit_code_is_distinct_from_sole_postclear_and_common_cli_codes() {
        let reserved = [SOLE_POSTCLEAR_EXIT_CODE, 0, 64, 72, 75, 76, 77, 79];
        assert!(!reserved.contains(&TRANSFER_ACK_REQUIRED_EXIT_CODE));
    }

    #[test]
    fn malformed_adapter_inputs_fail_closed() {
        for (product, selector, other_product, transfer) in [
            ("", "native", "present", "accepted-and-verified"),
            ("Native", "native", "present", "accepted-and-verified"),
            ("native", "missing", "present", "accepted-and-verified"),
            ("native", "native", "maybe", "accepted-and-verified"),
            ("native", "native", "present", "accepted"),
            ("wsl ", "wsl", "absent", "not-requested"),
        ] {
            let plan = decide_from_adapter_inputs(product, selector, other_product, transfer);
            assert_eq!(plan.decision, Decision::Block);
            assert_eq!(plan.selector_mutation, SelectorMutation::None);
        }
    }

    #[test]
    fn cli_policy_mode_rejects_help_foreign_duplicate_and_missing_arguments() {
        let malformed = [
            vec![
                "--civiccast-native-uninstall-policy",
                "--product",
                "native",
                "--selector",
                "malformed",
                "--other-product",
                "unknown",
                "--transfer-state",
                "failed",
                "--help",
            ],
            vec![
                "--civiccast-acquire-channel",
                "https://example.invalid/channel.json",
                "--civiccast-native-uninstall-policy",
                "--product",
                "native",
                "--selector",
                "wsl",
                "--other-product",
                "present",
                "--transfer-state",
                "not-requested",
            ],
            vec![
                "--civiccast-native-uninstall-policy",
                "--civiccast-native-uninstall-policy",
                "--product",
                "native",
                "--selector",
                "wsl",
                "--other-product",
                "present",
                "--transfer-state",
                "not-requested",
            ],
            vec![
                "--civiccast-native-uninstall-policy",
                "--product",
                "native",
                "--product",
                "wsl",
                "--selector",
                "wsl",
                "--other-product",
                "present",
                "--transfer-state",
                "not-requested",
            ],
            vec![
                "--civiccast-native-uninstall-policy",
                "--product",
                "native",
                "--selector",
                "wsl",
                "--other-product",
                "present",
            ],
        ];

        for args in malformed {
            let owned: Vec<String> = args.into_iter().map(str::to_string).collect();
            let plan = decide_from_cli_args(&owned).expect("sentinel must own invocation");
            assert_eq!(plan, blocked_plan(), "args={owned:?}");
        }
    }

    #[test]
    fn cli_parser_distinguishes_absent_mode_from_valid_policy_invocation() {
        assert_eq!(decide_from_cli_args(&["--help".to_string()]), None);

        let args = [
            "--civiccast-native-uninstall-policy",
            "--product",
            "native",
            "--selector",
            "wsl",
            "--other-product",
            "present",
            "--transfer-state",
            "not-requested",
        ]
        .map(str::to_string);
        let plan = decide_from_cli_args(&args).expect("policy mode");
        assert_eq!(plan.decision, Decision::AllowInactive);
        assert_eq!(plan.selector_mutation, SelectorMutation::None);
    }

    #[test]
    fn adapter_tokens_expose_only_permitted_actions() {
        assert_eq!(
            decision_token(decide_from_adapter_inputs(
                "native",
                "wsl",
                "present",
                "not-requested"
            )),
            "allow-inactive"
        );
        assert_eq!(
            selector_mutation_token(decide_from_adapter_inputs("wsl", "wsl", "absent", "failed")),
            "clear-postuninstall"
        );
    }

    #[cfg(target_os = "windows")]
    #[test]
    fn registry_probe_classifier_only_treats_not_found_as_absent() {
        assert_eq!(
            classify_registry_error(&std::io::Error::from(std::io::ErrorKind::NotFound)),
            OtherProductState::Absent
        );
        assert_eq!(
            classify_registry_error(&std::io::Error::from(std::io::ErrorKind::PermissionDenied)),
            OtherProductState::Unknown
        );
        assert_eq!(
            classify_registry_error(&std::io::Error::from(std::io::ErrorKind::InvalidData)),
            OtherProductState::Unknown
        );
    }

    #[test]
    fn hkey_users_skip_predicate_excludes_default_classes_and_service_sids() {
        for skipped in [
            ".DEFAULT",
            ".default",
            "S-1-5-18",
            "s-1-5-18",
            "S-1-5-19",
            "S-1-5-20",
            "S-1-5-21-1111111111-2222222222-3333333333-1001_Classes",
            "s-1-5-21-1111111111-2222222222-3333333333-1001_classes",
        ] {
            assert!(
                should_skip_users_subkey(skipped),
                "expected {skipped:?} to be skipped"
            );
        }
    }

    #[test]
    fn hkey_users_skip_predicate_keeps_real_user_and_unrelated_service_sids() {
        for kept in [
            "S-1-5-21-1111111111-2222222222-3333333333-1001",
            "S-1-5-21-1111111111-2222222222-3333333333-1002",
            "S-1-5-21-4444444444-5555555555-6666666666-1001",
            // Not a well-known skip SID (e.g. NT AUTHORITY\IUSR, S-1-5-17),
            // must still be probed rather than silently excluded.
            "S-1-5-17",
        ] {
            assert!(
                !should_skip_users_subkey(kept),
                "expected {kept:?} to be probed, not skipped"
            );
        }
    }

    #[test]
    fn combine_probe_results_present_wins_over_unknown_and_absent() {
        assert_eq!(
            combine_probe_results([
                OtherProductState::Absent,
                OtherProductState::Unknown,
                OtherProductState::Present,
            ]),
            OtherProductState::Present
        );
        assert_eq!(
            combine_probe_results([OtherProductState::Present, OtherProductState::Absent]),
            OtherProductState::Present
        );
    }

    #[test]
    fn combine_probe_results_fails_closed_to_unknown_without_any_present() {
        assert_eq!(
            combine_probe_results([OtherProductState::Absent, OtherProductState::Unknown]),
            OtherProductState::Unknown
        );
        assert_eq!(
            combine_probe_results([OtherProductState::Unknown]),
            OtherProductState::Unknown
        );
    }

    #[test]
    fn combine_probe_results_is_absent_only_when_every_observed_state_is_absent() {
        assert_eq!(
            combine_probe_results([OtherProductState::Absent, OtherProductState::Absent]),
            OtherProductState::Absent
        );
        assert_eq!(
            combine_probe_results(std::iter::empty()),
            OtherProductState::Absent
        );
    }

    /// Simulates the classification truth table `probe_wsl_arp` enforces
    /// without touching a live registry: HKCU's combined view plus the
    /// HKEY_USERS enumeration's combined view, run through the same
    /// fail-closed combinator the real probe uses.
    #[test]
    fn probe_wsl_arp_truth_table_present_beats_unknown_beats_absent() {
        let cases = [
            // (hkcu_combined, hkey_users_combined, expected)
            (
                OtherProductState::Absent,
                OtherProductState::Absent,
                OtherProductState::Absent,
            ),
            (
                OtherProductState::Present,
                OtherProductState::Unknown,
                OtherProductState::Present,
            ),
            (
                OtherProductState::Unknown,
                OtherProductState::Present,
                OtherProductState::Present,
            ),
            (
                OtherProductState::Absent,
                OtherProductState::Present,
                OtherProductState::Present,
            ),
            (
                OtherProductState::Absent,
                OtherProductState::Unknown,
                OtherProductState::Unknown,
            ),
            (
                OtherProductState::Unknown,
                OtherProductState::Absent,
                OtherProductState::Unknown,
            ),
        ];
        for (hkcu, hkey_users, expected) in cases {
            assert_eq!(
                combine_probe_results([hkcu, hkey_users]),
                expected,
                "hkcu={hkcu:?}, hkey_users={hkey_users:?}"
            );
        }
    }
}

#[cfg(test)]
mod install_selector_claim_tests {
    use super::*;

    /// Chain G RED: on a fresh native install with no selector written by
    /// anyone and no CivicCast WSL product registered, the install must claim
    /// `ActiveRuntime = "native"`. Without this the LocalSystem supervisor's
    /// dual-runtime guard reads `selector=absent`, and on any machine where
    /// the WSL install-detection probe cannot answer (R7: `wsl.exe` is the
    /// inbox stub and the SCM WSL-service query is ambiguous) it returns
    /// `blocked_probe_unavailable` and never starts the control plane.
    #[test]
    fn a_fresh_native_install_with_no_selector_and_no_wsl_product_claims_native() {
        assert_eq!(
            decide_install_selector_claim(SelectorState::Absent, OtherProductState::Absent),
            SelectorClaimAction::ClaimNative
        );
    }

    /// An install NEVER steals the other product's existing ownership claim --
    /// the same rule `decide_selector_repair_action` states for repair. The
    /// guard's `never_start` on `selector=wsl` is the correct product
    /// behavior; the operator runs `cutover-to-native` to change it.
    #[test]
    fn an_install_never_steals_an_existing_wsl_ownership_claim() {
        for other in [
            OtherProductState::Absent,
            OtherProductState::Present,
            OtherProductState::Unknown,
        ] {
            assert_eq!(
                decide_install_selector_claim(SelectorState::Wsl, other),
                SelectorClaimAction::LeaveWslOwnership,
                "other={other:?}"
            );
        }
    }

    /// A repair/upgrade install over a station that already claimed native is
    /// a no-op, not a redundant write: the value is already exactly what the
    /// guard needs, and a write that cannot change anything should not be
    /// able to fail the install either.
    #[test]
    fn an_install_over_an_existing_native_claim_is_a_no_op() {
        for other in [
            OtherProductState::Absent,
            OtherProductState::Present,
            OtherProductState::Unknown,
        ] {
            assert_eq!(
                decide_install_selector_claim(SelectorState::Native, other),
                SelectorClaimAction::AlreadyNative,
                "other={other:?}"
            );
        }
    }

    /// Fail-closed: a selector this process could not READ may already say
    /// `"wsl"`. Writing over it would silently steal ownership on exactly the
    /// evidence we do not have.
    #[test]
    fn an_unreadable_selector_is_never_overwritten_by_an_install() {
        for other in [
            OtherProductState::Absent,
            OtherProductState::Present,
            OtherProductState::Unknown,
        ] {
            assert_eq!(
                decide_install_selector_claim(SelectorState::Unreadable, other),
                SelectorClaimAction::LeaveUnprovable,
                "other={other:?}"
            );
        }
    }

    /// The coexistence row: no selector, but the WSL product IS installed (or
    /// its presence cannot be proved either way). The native installer has no
    /// authority to decide which of two installed products transmits, so it
    /// leaves the selector absent and the guard's `refuse_instruct` tells the
    /// operator to run the cutover.
    #[test]
    fn an_absent_selector_with_a_wsl_product_present_or_unknown_is_left_to_the_operator() {
        for other in [OtherProductState::Present, OtherProductState::Unknown] {
            assert_eq!(
                decide_install_selector_claim(SelectorState::Absent, other),
                SelectorClaimAction::LeaveUnprovable,
                "other={other:?}"
            );
        }
    }

    /// Totality over the whole 4x3 input product -- the same property
    /// `decide_selector_repair_action`'s own table carries. Exactly ONE cell
    /// writes.
    #[test]
    fn the_claim_decision_is_total_and_exactly_one_cell_writes() {
        let selectors = [
            SelectorState::Native,
            SelectorState::Wsl,
            SelectorState::Absent,
            SelectorState::Unreadable,
        ];
        let others = [
            OtherProductState::Absent,
            OtherProductState::Present,
            OtherProductState::Unknown,
        ];
        let mut writes = 0;
        for selector in selectors {
            for other in others {
                if decide_install_selector_claim(selector, other)
                    == SelectorClaimAction::ClaimNative
                {
                    writes += 1;
                }
            }
        }
        assert_eq!(
            writes, 1,
            "only (Absent, Absent) may write; every other cell leaves the selector alone"
        );
    }

    /// The written value is the EXACT byte string the Python guard's read
    /// path accepts. `civiccast.native.win_probes.read_selector` returns
    /// `SelectorRead(ok=True, value="native")` only for a `REG_SZ` value named
    /// `ActiveRuntime` under `SOFTWARE\CivicCast` in the 64-bit view whose
    /// text is exactly `native`; anything else is `ok=False` (unreadable) and
    /// the guard blocks. This pins all three halves of that contract on the
    /// writing side.
    #[test]
    fn the_claimed_selector_matches_the_python_guards_read_contract() {
        assert_eq!(NATIVE_SELECTOR_VALUE, "native");
        assert_eq!(SELECTOR_KEY, r"SOFTWARE\CivicCast");
        assert_eq!(SELECTOR_VALUE, "ActiveRuntime");
    }
}

#[cfg(test)]
mod install_selector_claim_orchestration_tests {
    use super::*;
    use std::cell::RefCell;

    /// Behavioral RED: the claim ORCHESTRATION (probe selector, probe the WSL
    /// product, then write or deliberately not write) is exercised end to end
    /// against injected probes, so the "did an install actually write the
    /// selector" question is answered by a test rather than by reading
    /// `run_native_provision`. The real registry mutation stays out of the
    /// test per this module's HARD RULE -- only the writer is faked.
    fn run(
        selector: SelectorState,
        other: OtherProductState,
        write_result: Result<(), String>,
    ) -> (SelectorClaimOutcome, usize) {
        let writes = RefCell::new(0usize);
        let outcome = claim_install_selector_with(
            || selector,
            || other,
            || {
                *writes.borrow_mut() += 1;
                write_result.clone()
            },
        );
        let count = *writes.borrow();
        (outcome, count)
    }

    #[test]
    fn a_fresh_install_writes_the_selector_exactly_once_and_reports_it_claimed() {
        let (outcome, writes) = run(SelectorState::Absent, OtherProductState::Absent, Ok(()));
        assert_eq!(outcome.action, SelectorClaimAction::ClaimNative);
        assert_eq!(outcome.write_error, None);
        assert_eq!(writes, 1);
    }

    #[test]
    fn every_non_claiming_cell_never_touches_the_writer() {
        for (selector, other) in [
            (SelectorState::Native, OtherProductState::Absent),
            (SelectorState::Wsl, OtherProductState::Absent),
            (SelectorState::Unreadable, OtherProductState::Absent),
            (SelectorState::Absent, OtherProductState::Present),
            (SelectorState::Absent, OtherProductState::Unknown),
        ] {
            let (outcome, writes) = run(selector, other, Ok(()));
            assert_eq!(writes, 0, "selector={selector:?}, other={other:?}");
            assert_ne!(outcome.action, SelectorClaimAction::ClaimNative);
        }
    }

    #[test]
    fn a_failed_selector_write_is_surfaced_and_never_swallowed() {
        let (outcome, writes) = run(
            SelectorState::Absent,
            OtherProductState::Absent,
            Err("access denied".to_string()),
        );
        assert_eq!(writes, 1);
        assert_eq!(outcome.action, SelectorClaimAction::ClaimNative);
        assert_eq!(outcome.write_error.as_deref(), Some("access denied"));
    }

    /// The operator-facing sentence for each outcome must name the real state,
    /// never a generic success. A station whose selector was left alone will
    /// not start, and the install log is the only place that says why.
    #[test]
    fn every_outcome_explains_itself_distinctly() {
        let mut seen: Vec<String> = Vec::new();
        for (selector, other) in [
            (SelectorState::Absent, OtherProductState::Absent),
            (SelectorState::Native, OtherProductState::Absent),
            (SelectorState::Wsl, OtherProductState::Absent),
            (SelectorState::Unreadable, OtherProductState::Absent),
            (SelectorState::Absent, OtherProductState::Present),
        ] {
            let (outcome, _) = run(selector, other, Ok(()));
            let detail = outcome.detail;
            assert!(!detail.trim().is_empty());
            assert!(
                detail.contains("ActiveRuntime"),
                "detail must name the selector: {detail}"
            );
            seen.push(detail);
        }
        seen.sort();
        seen.dedup();
        assert_eq!(
            seen.len(),
            5,
            "each observed (selector, other-product) pair explains itself distinctly"
        );
    }
}
