// SPDX-License-Identifier: Apache-2.0
// Copyright (c) The CivicCast Authors

//! Pre-elevation first-install coordination over the existing signed channel,
//! verified pack cache, and NSIS EXEDIR side-load contract.

use std::collections::{BTreeMap, BTreeSet};
use std::path::{Path, PathBuf};
use std::sync::{Mutex, OnceLock};
use std::sync::atomic::{AtomicBool, Ordering};
use crate::native_packs::{PackTrust, VerifiedPack};

use crate::native_distribution::VerifiedDistribution;

const REQUIRED: [&str; 10] = [
    "core", "captions-floor", "summary-gemma4-12b", "summary-gemma4-e4b",
    "translation-translategemma-4b", "native-server-binaries", "native-app-payload",
    "native-ffmpeg-runtime", "native-ollama-runtime", "installer-bootstrap",
];

pub static MODE: OnceLock<Result<FirstInstallMode, String>> = OnceLock::new();
static INDEX: Mutex<Option<VerifiedDistribution>> = Mutex::new(None);
static READY: Mutex<Option<PreparedHandoff>> = Mutex::new(None);
static ACTIVE: AtomicBool = AtomicBool::new(false);
#[derive(PartialEq,Eq)]
enum SetupTerminal { Idle, Failed, Completed }
static HANDOFF: Mutex<SetupTerminal> = Mutex::new(SetupTerminal::Idle);
static SETUP_RUNNING: AtomicBool = AtomicBool::new(false);
static SETUP_WAIT_UNCONFIRMED: AtomicBool = AtomicBool::new(false);

pub fn is_entry() -> bool { MODE.get().is_some() }
pub fn can_close() -> bool {
    !SETUP_RUNNING.load(Ordering::SeqCst) && HANDOFF.try_lock().is_ok()
}

fn mode() -> Result<&'static FirstInstallMode, String> {
    MODE.get().ok_or("This is not a first-install entry.")?.as_ref().map_err(Clone::clone)
}

fn progress_envelope(snapshot: Option<String>) -> Result<String,String> {
    let Some(snapshot)=snapshot else { return Ok("null".into()); };
    let acquisition:serde_json::Value=serde_json::from_str(&snapshot)
        .map_err(|_| "The owned download progress could not be read.")?;
    let updated=std::time::SystemTime::now().duration_since(std::time::UNIX_EPOCH)
        .map_err(|_| "The download progress time is unavailable.")?.as_secs();
    Ok(serde_json::json!({"schema_version":1,"current_lane_id":"acquisition","status":"running",
        "message":"Preparing the verified selected installation.","reboot_required":false,
        "updated_at_unix":updated,"acquisition":acquisition}).to_string())
}

pub fn progress_state() -> Result<String,String> {
    // In this exclusive entry, memory is the owned acquisition truth. Never
    // reconcile an installed service or let stale disk completion mask failure.
    progress_envelope(crate::acquisition_state::snapshot_json())
}

pub fn persist_progress() -> Result<(),String> {
    let root=&mode()?.cache_root;
    std::fs::create_dir_all(root).map_err(|_| "Cannot create the first-install progress directory.")?;
    reject_ancestor_reparse(root)?;
    let path=root.join("first-install-progress.json");
    if path.exists() { reject_ancestor_reparse(&path)?; }
    std::fs::write(path,progress_state()?).map_err(|_| "Cannot save first-install download progress.".to_string())
}

pub fn load_plan() -> Result<BTreeMap<String, u64>, String> {
    let mode = mode()?;
    let mut index = INDEX.lock().map_err(|_| "The release plan is unavailable.")?;
    if index.is_none() {
        let trust = crate::native_packs::embedded_pack_trust()?;
        *index = Some(crate::native_distribution::read_online_distribution_index(
            &mode.authority_url, &mode.cache_root, &trust, &mode.channel,
            crate::CIVICCAST_VERSION, crate::CIVICCAST_VERSION)
            .map_err(|_| "The signed release plan could not be verified. Check the matching first-install files and connection.".to_string())?);
    }
    let index = index.as_ref().ok_or("The release plan is unavailable.")?;
    select_install_components(index, &REQUIRED_UI.iter().map(|id| (*id).into()).collect::<Vec<_>>())?;
    component_sizes(index)
}

const REQUIRED_UI: [&str; 4] = ["app_runtime", "server_binaries", "captions_medium", "local_ai_model"];

pub fn validate_plan(ids: &[String]) -> Result<(), String> {
    let index = INDEX.lock().map_err(|_| "The release plan is unavailable.")?;
    select_install_components(index.as_ref().ok_or("Verify the release plan before starting downloads.")?, ids)?;
    Ok(())
}

pub fn begin(ids: Vec<String>) -> Result<(), String> {
    let handoff = HANDOFF.try_lock().map_err(|_| "Windows Setup is using the verified installation. Wait for it to finish.".to_string())?;
    if SETUP_RUNNING.load(Ordering::SeqCst) { return Err("Windows Setup is still running. Finish it before changing files.".into()); }
    if *handoff != SetupTerminal::Idle { return Err("Windows Setup already started for this installation. Check or retry its result.".into()); }
    if ACTIVE.compare_exchange(false, true, Ordering::SeqCst, Ordering::SeqCst).is_err() {
        return Err("The selected first-install plan is still running. Wait before resuming.".into());
    }
    let mut ready = match READY.lock() {
        Ok(ready) => ready,
        Err(_) => { ACTIVE.store(false,Ordering::SeqCst); return Err("The prepared installation is unavailable.".into()); }
    };
    *ready=None;
    for id in &ids { crate::acquisition_state::mark_pending(id); }
    if let Err(error) = crate::persist_acquisition_progress() {
        ACTIVE.store(false, Ordering::SeqCst);
        return Err(error);
    }
    crate::component_acquisition::clear_cancel();
    std::thread::spawn(move || {
        let result = acquire_selected(&ids);
        // Publish terminal state under the same lock used by begin/launch.
        // Complete rows can be observed before this block ends, but handoff
        // cannot pass admission until ACTIVE and READY agree with those rows.
        let _handoff = match HANDOFF.lock() { Ok(guard)=>guard, Err(_)=>return };
        let mut ready = match READY.lock() { Ok(guard)=>guard, Err(_)=>{ ACTIVE.store(false,Ordering::SeqCst); return; } };
        let result = if crate::component_acquisition::cancel_requested() {
            Err(Failure::Transfer(crate::component_acquisition::AcquisitionError::Canceled))
        } else { result };
        match result {
            Ok(prepared) => {
                let totals=component_sizes(&prepared.channel).unwrap_or_default();
                *ready=Some(prepared);
                for id in &ids {
                    crate::acquisition_state::upsert(crate::acquisition_state::AcquisitionComponentProgress {
                        id:id.clone(), state:crate::acquisition_state::AcquisitionComponentState::Complete,
                        bytes_done:totals.get(id).copied().unwrap_or(0), bytes_total:totals.get(id).copied(), elapsed_seconds:0, error:None });
                }
                if crate::persist_acquisition_progress().is_err() {
                    *ready=None;
                    for id in &ids {
                        crate::acquisition_state::upsert(crate::acquisition_state::AcquisitionComponentProgress {
                            id:id.clone(),state:crate::acquisition_state::AcquisitionComponentState::Error,
                            bytes_done:totals.get(id).copied().unwrap_or(0),bytes_total:totals.get(id).copied(),elapsed_seconds:0,
                            error:Some(crate::acquisition_state::AcquisitionComponentError {
                                kind:crate::acquisition_state::AcquisitionErrorKind::WriteFailed,
                                detail:"The verified installation progress could not be saved. Resume the same plan to retry preparation.".into() }),
                        });
                    }
                    crate::persist_acquisition_progress_best_effort();
                }
            }
            Err(failure) => {
            *ready=None;
            let classified = match failure {
                Failure::Transfer(error) => crate::classify_acquisition_error(&error),
                Failure::Integrity => Some((crate::acquisition_state::AcquisitionErrorKind::HashMismatch,
                    "The signed installation could not be verified or staged. Resume to retry the same selected plan.".into())),
                Failure::Preparation => Some((crate::acquisition_state::AcquisitionErrorKind::WriteFailed,
                    "The local installation could not be prepared. Resume to retry the same selected plan.".into())),
            };
            for id in &ids {
                crate::acquisition_state::upsert(crate::acquisition_state::AcquisitionComponentProgress {
                    id:id.clone(), state:if classified.is_some() {crate::acquisition_state::AcquisitionComponentState::Error}
                        else {crate::acquisition_state::AcquisitionComponentState::Canceled},
                    bytes_done:0, bytes_total:None, elapsed_seconds:0,
                    error:classified.as_ref().map(|(kind, _)| crate::acquisition_state::AcquisitionComponentError {
                        kind:*kind, detail:"The selected installation could not be acquired. Resume to retry the same selected plan.".into() }),
                });
            }
            crate::persist_acquisition_progress_best_effort();
            }
        }
        ACTIVE.store(false, Ordering::SeqCst);
    });
    Ok(())
}

pub fn cancel() -> Result<String,String> {
    let ready = READY.lock().map_err(|_| "The prepared installation is unavailable.")?;
    if ready.is_some() { return Ok("The selected downloads already finished; Windows Setup has not been canceled.".into()); }
    crate::component_acquisition::request_cancel();
    crate::acquisition_state::mark_unfinished_canceled();
    crate::persist_acquisition_progress()?;
    Ok("The selected downloads stopped. Resume keeps the same plan and verified cache.".into())
}

enum Failure { Preparation, Integrity, Transfer(crate::component_acquisition::AcquisitionError) }
impl From<String> for Failure { fn from(_:String)->Self { Self::Preparation } }
impl From<&str> for Failure { fn from(_:&str)->Self { Self::Preparation } }

fn acquire_selected(ids: &[String]) -> Result<PreparedHandoff, Failure> {
    let mode = mode()?;
    let trust = crate::native_packs::embedded_pack_trust()?;
    let index = INDEX.lock().map_err(|_| "The release plan is unavailable.")?
        .clone().ok_or("The release plan is unavailable.")?;
    let selected = select_install_components(&index, ids)?;
    std::fs::create_dir_all(&mode.cache_root).map_err(|_| "Cannot prepare the verified cache.")?;
    reject_ancestor_reparse(&mode.cache_root)?;
    let totals = component_sizes(&index)?;
    let mut offsets = BTreeMap::<String,u64>::new();
    let mut order: Vec<_> = index.packs.iter().filter(|pack| selected.contains(&pack.component)).collect();
    order.sort_by_key(|pack| pack.component != "installer-bootstrap");
    let mut prepared = None;
    for pack in order {
        if crate::component_acquisition::cancel_requested() {
            return Err(Failure::Transfer(crate::component_acquisition::AcquisitionError::Canceled));
        }
        let id = ui_component(&pack.component)?;
        let offset = *offsets.get(id).unwrap_or(&0);
        let observer = crate::AcquisitionStoreObserver { component_id:id.into(),
            bytes_total_hint:totals.get(id).copied(), bytes_offset:offset,
            invoked:std::sync::Arc::new(AtomicBool::new(false)), persist:crate::persist_acquisition_progress_best_effort };
        let url = pack.urls.first().ok_or("The signed channel pack has no download source.")?;
        let (base, name) = url.rsplit_once('/').ok_or("The signed channel pack URL is invalid.")?;
        let path = crate::component_acquisition::ensure_component_available(
            &mode.cache_root.join(format!("{}.ccpack", pack.sha256)), &[],
            &crate::component_acquisition::ComponentSource::GitHubReleaseAsset {base_url:base.into(),asset_name:name.into()},
            &crate::component_acquisition::ExpectedArtifact::Pinned {bytes:pack.bytes,sha256:pack.sha256.clone()},
            &observer).map_err(Failure::Transfer)?;
        if pack.component == "installer-bootstrap" {
            let nonce = std::time::SystemTime::now().duration_since(std::time::UNIX_EPOCH)
                .map_err(|_| "Cannot identify the prepared installation.")?.as_nanos();
            prepared = Some(prepare_bootstrap(&path, &mode.cache_root.join(format!("prepared-{nonce}")), &index, ids, &trust)?);
        } else {
            let handoff = prepared.as_ref().ok_or("The verified bootstrap is unavailable.")?;
            let authority = if REQUIRED[..5].contains(&pack.component.as_str()) || pack.component == "captions-large-v3" {
                &handoff.station
            } else { &index };
            let (version, compatible) = crate::native_distribution::pack_identity_expectations(authority, &pack.component);
            crate::native_packs::verify_pack(&path, &trust, Some(&pack.component), version, compatible)
                .map_err(|_| Failure::Integrity)?;
            let directory = if authority.kind == "station-index" { "station" } else { "packs" };
            let destination = handoff.root.join(directory).join(&pack.filename);
            std::fs::hard_link(&path, &destination).or_else(|_| std::fs::copy(&path, &destination).map(|_| ()))
                .map_err(|_| "Cannot stage the verified installation pack.")?;
        }
        offsets.insert(id.into(), offset.checked_add(pack.bytes).ok_or("The installation size is invalid.")?);
    }
    if crate::component_acquisition::cancel_requested() {
        return Err(Failure::Transfer(crate::component_acquisition::AcquisitionError::Canceled));
    }
    prepared.ok_or(Failure::Preparation)
}

fn verify_file(path: &Path, bytes: u64, sha: &str) -> Result<std::fs::File, String> {
    use std::io::Read;
    use sha2::{Digest, Sha256};
    reject_ancestor_reparse(path)?;
    let metadata = std::fs::symlink_metadata(path).map_err(|_| "A prepared file is missing.")?;
    if !metadata.is_file() || metadata.file_type().is_symlink() {
        return Err("A prepared file is not an owned regular file.".into());
    }
    let mut options = std::fs::OpenOptions::new();
    options.read(true);
    #[cfg(windows)] {
        use std::os::windows::fs::OpenOptionsExt;
        use std::os::windows::fs::MetadataExt;
        if metadata.file_attributes() & 0x400 != 0 { return Err("A prepared file is a reparse point.".into()); }
        options.share_mode(1); // Read-only sharing; deny mutation/deletion through handoff.
    }
    let mut file = options.open(path).map_err(|_| "Cannot lock the prepared file for verification.")?;
    if file.metadata().map_err(|_| "Cannot read the prepared file.")?.len() != bytes {
        return Err("A prepared file has changed size.".into());
    }
    let mut hash = Sha256::new();
    let mut buffer = [0u8; 65536];
    loop {
        let count = file.read(&mut buffer).map_err(|_| "Cannot verify the prepared file.")?;
        if count == 0 { break; }
        hash.update(&buffer[..count]);
    }
    if format!("{:x}", hash.finalize()) != sha { return Err("A prepared file has changed bytes.".into()); }
    Ok(file)
}

fn reject_ancestor_reparse(path: &Path) -> Result<(), String> {
    for ancestor in path.ancestors().filter(|path| !path.as_os_str().is_empty()) {
        crate::native_packs::reject_reparse_path(ancestor)
            .map_err(|_| "The installation cache contains a redirected path.".to_string())?;
    }
    Ok(())
}

#[derive(Debug,PartialEq,Eq,serde::Serialize)]
#[serde(rename_all="snake_case")]
pub enum SetupOutcome { Running, Unconfirmed, Failed, Completed }

#[derive(serde::Deserialize,PartialEq,Eq)]
#[serde(rename_all="snake_case")]
pub enum SetupAction { Start, Check, Retry }

pub fn launch_setup(action: SetupAction) -> Result<SetupOutcome, String> {
    let mut handed_off = HANDOFF.lock().map_err(|_| "The Windows Setup handoff is unavailable.")?;
    if SETUP_RUNNING.load(Ordering::SeqCst) {
        return Ok(if SETUP_WAIT_UNCONFIRMED.load(Ordering::SeqCst) {SetupOutcome::Unconfirmed} else {SetupOutcome::Running});
    }
    if ACTIVE.load(Ordering::SeqCst) { return Err("Wait for the selected installation to finish downloading.".into()); }
    if *handed_off == SetupTerminal::Completed { return Ok(SetupOutcome::Completed); }
    if *handed_off == SetupTerminal::Failed && action != SetupAction::Retry { return Ok(SetupOutcome::Failed); }
    if *handed_off == SetupTerminal::Idle && action == SetupAction::Check {
        return Err("No Windows Setup process was started for this installation.".into());
    }
    let ready = READY.lock().map_err(|_| "The prepared installation is unavailable.")?;
    let ready = ready.as_ref().ok_or("Finish acquiring the verified installation before opening Windows Setup.")?;
    let trust = crate::native_packs::embedded_pack_trust()?;
    let admitted = crate::ACQUISITION_DRIVER_PLAN.lock().map_err(|_| "The selected plan is unavailable.")?
        .clone().ok_or("No selected first-install plan was admitted.")?;
    if select_install_components(&ready.channel, &admitted)? != ready.selected {
        return Err("The prepared installation does not match the admitted selection.".into());
    }
    // Re-verify every authority and pack immediately before crossing elevation.
    let bootstrap_pin = ready.channel.packs.iter().find(|pack| pack.component == "installer-bootstrap")
        .ok_or("The bootstrap authority is unavailable.")?;
    let mut guards = vec![verify_file(&ready.bootstrap_pack, bootstrap_pin.bytes, &bootstrap_pin.sha256)?];
    crate::native_packs::verify_pack(&ready.bootstrap_pack, &trust, Some("installer-bootstrap"),
        Some(&ready.channel.product_version), Some(&ready.channel.compatible_core))?;
    for file in &ready.bootstrap.files {
        guards.push(verify_file(&ready.root.join(&file.path), file.bytes, &file.sha256)?);
    }
    let raw = std::fs::read(ready.root.join("station/station-index.json"))
        .map_err(|_| "The station authority is unavailable.")?;
    let station = crate::native_distribution::verify_distribution_bytes(&raw, &trust,
        Some("station-index"), Some(&ready.channel.channel), Some(&ready.channel.product_version), Some(&ready.channel.compatible_core))?;
    if station.sha256 != ready.station.sha256 { return Err("The prepared station authority changed.".into()); }
    guards.push(verify_file(&ready.root.join("station/station-index.json"), raw.len() as u64, &station.sha256)?);
    for pack in ready.channel.packs.iter().filter(|pack| ready.selected.contains(&pack.component) && pack.component != "installer-bootstrap") {
        let model = REQUIRED[..5].contains(&pack.component.as_str()) || pack.component == "captions-large-v3";
        let path = ready.root.join(if model {"station"} else {"packs"}).join(&pack.filename);
        guards.push(verify_file(&path, pack.bytes, &pack.sha256)?);
        let authority = if model { &ready.station } else { &ready.channel };
        let (version, compatible) = crate::native_distribution::pack_identity_expectations(authority, &pack.component);
        crate::native_packs::verify_pack(&path, &trust, Some(&pack.component), version, compatible)?;
    }
    #[cfg(windows)] {
        use std::os::windows::ffi::OsStrExt;
        use windows_sys::Win32::UI::Shell::{ShellExecuteExW, SHELLEXECUTEINFOW, SEE_MASK_NOCLOSEPROCESS};
        use windows_sys::Win32::Foundation::{CloseHandle, WAIT_OBJECT_0};
        use windows_sys::Win32::System::Threading::{WaitForSingleObject, GetExitCodeProcess};
        let exe:Vec<u16> = ready.root.join("setup.exe").as_os_str().encode_wide().chain(Some(0)).collect();
        let directory:Vec<u16> = ready.root.as_os_str().encode_wide().chain(Some(0)).collect();
        let verb:Vec<u16> = "runas".encode_utf16().chain(Some(0)).collect();
        let mut info:SHELLEXECUTEINFOW = unsafe { std::mem::zeroed() };
        info.cbSize=std::mem::size_of::<SHELLEXECUTEINFOW>() as u32;
        info.fMask=SEE_MASK_NOCLOSEPROCESS;
        info.lpVerb=verb.as_ptr(); info.lpFile=exe.as_ptr(); info.lpDirectory=directory.as_ptr(); info.nShow=1;
        *handed_off=SetupTerminal::Failed;
        if unsafe { ShellExecuteExW(&mut info) } == 0 || info.hProcess.is_null() {
            return Err("Windows Setup was not opened. Approve the Windows permission prompt to continue.".into());
        }
        // Bound the command wait, but retain verified files through the owned
        // Setup lifetime. A slow Setup is not success and is never terminated.
        SETUP_RUNNING.store(true, Ordering::SeqCst);
        SETUP_WAIT_UNCONFIRMED.store(false, Ordering::SeqCst);
        let waited = unsafe { WaitForSingleObject(info.hProcess, 30_000) };
        if waited != WAIT_OBJECT_0 {
            SETUP_WAIT_UNCONFIRMED.store(waited == windows_sys::Win32::Foundation::WAIT_FAILED,Ordering::SeqCst);
            let handle = info.hProcess as usize;
            std::thread::spawn(move || {
                let _guards = guards;
                let handle = handle as windows_sys::Win32::Foundation::HANDLE;
                loop {
                    let wait = unsafe { WaitForSingleObject(handle, 1_000) };
                    if wait == WAIT_OBJECT_0 { break; }
                    if wait == windows_sys::Win32::Foundation::WAIT_FAILED {
                        SETUP_WAIT_UNCONFIRMED.store(true,Ordering::SeqCst);
                        // A failed wait is not proof of exit. Query the owned
                        // handle; keep files locked while exit remains unknown.
                        let mut code=259;
                        if unsafe { GetExitCodeProcess(handle,&mut code) } != 0 && code != 259 { break; }
                        std::thread::sleep(std::time::Duration::from_secs(1));
                    } else {
                        SETUP_WAIT_UNCONFIRMED.store(false,Ordering::SeqCst);
                    }
                }
                let mut exit=1;
                let obtained = unsafe { GetExitCodeProcess(handle,&mut exit) };
                unsafe { CloseHandle(handle); }
                if let Ok(mut terminal) = HANDOFF.lock() {
                    *terminal=if obtained != 0 && exit == 0 {SetupTerminal::Completed} else {SetupTerminal::Failed};
                }
                SETUP_RUNNING.store(false, Ordering::SeqCst);
            });
            return Ok(if waited == windows_sys::Win32::Foundation::WAIT_FAILED {SetupOutcome::Unconfirmed} else {SetupOutcome::Running});
        }
        let mut exit=1;
        let obtained = unsafe { GetExitCodeProcess(info.hProcess,&mut exit) };
        unsafe { CloseHandle(info.hProcess); }
        SETUP_RUNNING.store(false, Ordering::SeqCst);
        if waited != WAIT_OBJECT_0 || obtained == 0 || exit != 0 {
            return Ok(SetupOutcome::Failed);
        }
        *handed_off=SetupTerminal::Completed;
        Ok(SetupOutcome::Completed)
    }
    #[cfg(not(windows))] { let _ = (&mut handed_off, guards); Err("Windows Setup requires Windows.".into()) }
}

#[derive(Debug, Clone)]
pub struct FirstInstallMode {
    pub authority_url: String,
    pub channel: String,
    pub cache_root: PathBuf,
}

#[derive(serde::Deserialize)]
#[serde(deny_unknown_fields)]
struct EntryHint {
    schema_version: u32,
    product_version: String,
    compatible_core: String,
    channel: String,
    channel_url: String,
}

pub fn read_entry_hint(raw: &[u8], version: &str, user_state: &Path) -> Result<FirstInstallMode, String> {
    if raw.len() > 16 * 1024 { return Err("The first-install release hint is too large.".into()); }
    let hint: EntryHint = serde_json::from_slice(raw)
        .map_err(|_| "The first-install release hint is invalid. Obtain the matching installer files.".to_string())?;
    if hint.schema_version != 1 || hint.product_version != version || hint.compatible_core != version {
        return Err("The first-install release hint belongs to a different CivicCast version.".into());
    }
    parse_mode(&["--civiccast-first-install".into(), "--channel-url".into(), hint.channel_url,
        "--channel".into(), hint.channel], user_state)?.ok_or("First-install entry was not selected.".into())
}

pub fn parse_mode(args: &[String], user_state: &Path) -> Result<Option<FirstInstallMode>, String> {
    if !args.iter().any(|arg| arg == "--civiccast-first-install") {
        return Ok(None);
    }
    let mut authority_url = None;
    let mut channel = None;
    let mut cache_root = None;
    let mut mode_seen = false;
    let mut position = 0;
    while position < args.len() {
        let flag = args[position].as_str();
        if flag == "--civiccast-first-install" && !mode_seen {
            mode_seen = true;
            position += 1;
            continue;
        }
        let value = args.get(position + 1).filter(|value| !value.starts_with("--"))
            .ok_or_else(|| "First-install arguments are incomplete. Supply the matching signed channel URL.".to_string())?;
        match flag {
            "--channel-url" if authority_url.is_none() => authority_url = Some(value.clone()),
            "--channel" if channel.is_none() => channel = Some(value.clone()),
            "--cache-root" if cache_root.is_none() => cache_root = Some(PathBuf::from(value)),
            _ => return Err("First install does not accept other installer actions or duplicate options.".into()),
        }
        position += 2;
    }
    let authority_url = authority_url.ok_or_else(||
        "First install needs an explicit signed channel URL for this CivicCast version. No legacy download location is used.".to_string())?;
    let url = url::Url::parse(&authority_url)
        .map_err(|_| "First install needs an unambiguous HTTPS channel URL.".to_string())?;
    if url.scheme() != "https" || url.host_str().is_none() || !url.username().is_empty()
        || url.password().is_some() || url.fragment().is_some() || url.path() == "/" {
        return Err("First install needs an unambiguous HTTPS channel URL.".into());
    }
    let channel = channel.unwrap_or_else(|| "beta".into());
    if channel.is_empty() || !channel.bytes().all(|byte| byte.is_ascii_lowercase()
        || byte.is_ascii_digit() || byte == b'-') {
        return Err("The requested first-install channel is invalid.".into());
    }
    let cache_root = cache_root.unwrap_or_else(|| user_state.join("first-install-cache"));
    Ok(Some(FirstInstallMode {authority_url, channel, cache_root}))
}

pub fn select_install_components(
    index: &VerifiedDistribution,
    selected_ids: &[String],
) -> Result<BTreeSet<String>, String> {
    let selected = crate::canonical_acquisition_plan(selected_ids)?;
    if index.kind != "channel-index" {
        return Err("First install requires a verified online channel authority.".into());
    }
    let mut desired: BTreeSet<String> = REQUIRED.into_iter().map(str::to_string).collect();
    for (ui_id, component) in [("captions_large", "captions-large-v3"),
        ("cuda_runtime", "native-cuda-runtime")] {
        if selected.iter().any(|id| id == ui_id) {
            desired.insert(component.into());
        }
        if index.packs.iter().any(|pack| pack.component == component && pack.required) {
            return Err("The signed installation plan incorrectly requires an optional component.".into());
        }
    }
    for component in &desired {
        let pack = index.packs.iter().find(|pack| &pack.component == component)
            .ok_or_else(|| format!("The signed installation plan is missing {component}. Obtain the matching release plan."))?;
        if REQUIRED.contains(&component.as_str()) && !pack.required {
            return Err(format!("The signed installation plan must require {component}."));
        }
    }
    if index.packs.iter().any(|pack| pack.required && !desired.contains(&pack.component)) {
        return Err("The signed installation plan declares an unsupported mandatory component.".into());
    }
    Ok(desired)
}

pub fn ui_component(component: &str) -> Result<&'static str, String> {
    match component {
        "native-server-binaries" => Ok("server_binaries"),
        "captions-floor" => Ok("captions_medium"),
        "captions-large-v3" => Ok("captions_large"),
        "native-cuda-runtime" => Ok("cuda_runtime"),
        "summary-gemma4-12b" | "summary-gemma4-e4b" | "translation-translategemma-4b" => Ok("local_ai_model"),
        "core" | "native-app-payload" | "native-ffmpeg-runtime" | "native-ollama-runtime"
        | "installer-bootstrap" => Ok("app_runtime"),
        _ => Err("The signed plan contains an unsupported first-install component.".into()),
    }
}

pub fn component_sizes(index: &VerifiedDistribution) -> Result<BTreeMap<String, u64>, String> {
    let mut sizes = BTreeMap::<String, u64>::new();
    for pack in &index.packs {
        if let Ok(id) = ui_component(&pack.component) {
            let total = sizes.entry(id.into()).or_default();
            *total = total.checked_add(pack.bytes)
                .ok_or_else(|| "The signed installation size exceeds its supported range.".to_string())?;
        }
    }
    Ok(sizes)
}

pub fn validate_station_selection(
    channel: &VerifiedDistribution, station: &VerifiedDistribution, selected_ids: &[String],
) -> Result<(), String> {
    let selected = select_install_components(channel, selected_ids)?;
    if station.kind != "station-index" || station.channel != channel.channel
        || station.product_version != channel.product_version
        || station.compatible_core != channel.compatible_core
        || station.signing_key_id != channel.signing_key_id {
        return Err("The station authority does not match this installation release.".into());
    }
    let expected: BTreeSet<&str> = REQUIRED[..5].iter().copied()
        .chain(selected.contains("captions-large-v3").then_some("captions-large-v3"))
        .collect();
    let actual: BTreeSet<&str> = station.packs.iter().map(|pack| pack.component.as_str()).collect();
    if actual != expected || actual.len() != station.packs.len() {
        return Err("The signed station plan does not match the selected models.".into());
    }
    for pack in &station.packs {
        let pin = channel.packs.iter().find(|pin| pin.component == pack.component)
            .ok_or("A station pack is absent from the signed channel.")?;
        if !pack.urls.is_empty() || pack.bytes != pin.bytes || pack.sha256 != pin.sha256
            || pack.filename != pin.filename || pack.required != REQUIRED[..5].contains(&pack.component.as_str()) {
            return Err("The signed station pack differs from the selected channel pack.".into());
        }
    }
    Ok(())
}

#[derive(Debug)]
pub struct PreparedHandoff {
    pub root: PathBuf,
    pub bootstrap_pack: PathBuf,
    pub bootstrap: VerifiedPack,
    pub channel: VerifiedDistribution,
    pub station: VerifiedDistribution,
    pub selected: BTreeSet<String>,
}

pub fn prepare_bootstrap(
    bootstrap_pack: &Path, root: &Path, channel: &VerifiedDistribution,
    selected_ids: &[String], trust: &PackTrust,
) -> Result<PreparedHandoff, String> {
    let selected = select_install_components(channel, selected_ids)?;
    let pin = channel.packs.iter().find(|pack| pack.component == "installer-bootstrap")
        .ok_or("The signed channel has no installer bootstrap.")?;
    let verified = crate::native_packs::verify_pack(bootstrap_pack, trust,
        Some("installer-bootstrap"), Some(&channel.product_version), Some(&channel.compatible_core))?;
    if verified.sha256 != pin.sha256 || std::fs::metadata(bootstrap_pack)
        .map_err(|_| "The verified bootstrap is unavailable.")?.len() != pin.bytes {
        return Err("The bootstrap differs from the signed channel pin.".into());
    }
    let station_name = if selected.contains("captions-large-v3") {
        "station-indexes/large.json"
    } else { "station-indexes/baseline.json" };
    let files: BTreeSet<&str> = verified.files.iter().map(|file| file.path.as_str()).collect();
    if !files.contains("setup.exe") || !files.contains(station_name)
        || files.iter().any(|file| !["setup.exe", "station-indexes/baseline.json", "station-indexes/large.json"].contains(file)) {
        return Err("The bootstrap does not contain the closed installation payload.".into());
    }
    crate::native_packs::verify_and_extract_pack(bootstrap_pack, root, trust,
        Some("installer-bootstrap"), Some(&channel.product_version), Some(&channel.compatible_core))?;
    let raw = std::fs::read(root.join(station_name))
        .map_err(|_| "The signed station authority is unavailable.")?;
    let station = crate::native_distribution::verify_distribution_bytes(&raw, trust,
        Some("station-index"), Some(&channel.channel), Some(&channel.product_version), Some(&channel.compatible_core))?;
    validate_station_selection(channel, &station, selected_ids)?;
    std::fs::create_dir(root.join("station")).map_err(|_| "Cannot prepare the station directory.")?;
    std::fs::write(root.join("station/station-index.json"), raw)
        .map_err(|_| "Cannot retain the verified station authority.")?;
    std::fs::create_dir(root.join("packs")).map_err(|_| "Cannot prepare the runtime directory.")?;
    Ok(PreparedHandoff { root: root.into(), bootstrap_pack: bootstrap_pack.into(),
        bootstrap: verified, channel: channel.clone(), station, selected })
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::native_distribution::DistributionPack;
    use base64::{engine::general_purpose::STANDARD as BASE64, Engine as _};
    use ed25519_dalek::{Signer, SigningKey};

    fn channel() -> VerifiedDistribution {
        let mut names = REQUIRED.to_vec();
        names.extend(["captions-large-v3", "native-cuda-runtime"]);
        let mut index = VerifiedDistribution {
            sha256: "00".repeat(32), kind: "channel-index".into(), channel: "beta".into(),
            product_version: "test-version".into(), compatible_core: "test-version".into(),
            signing_key_id: "test".into(), created_epoch: 1,
            packs: names.into_iter().map(|name| DistributionPack {
                component: name.into(), filename: format!("{name}.ccpack"), bytes: 1,
                sha256: "00".repeat(32), required: REQUIRED.contains(&name),
                urls: vec![format!("https://example.invalid/{name}.ccpack")],
            }).collect(),
        };
        // Exercise the real signed authority parser before the transfer-plan
        // seam; these synthetic entries are never claimed to be model packs.
        let order = ["core", "captions-floor", "summary-gemma4-12b", "summary-gemma4-e4b",
            "translation-translategemma-4b"];
        index.packs.sort_by_key(|pack| (order.iter().position(|name| *name == pack.component)
            .unwrap_or(order.len()), pack.component.clone()));
        let key = SigningKey::from_bytes(&[7; 32]);
        index.signing_key_id = "development-test-key".into();
        let manifest = serde_json::json!({
            "schema_version":1, "product":"civiccast-native", "kind":index.kind,
            "channel":index.channel, "product_version":index.product_version,
            "compatible_core":index.compatible_core, "signing_key_id":index.signing_key_id,
            "created_epoch":index.created_epoch, "packs":index.packs,
        });
        let bytes = crate::native_distribution::canonical_json(&manifest).unwrap();
        let envelope = serde_json::json!({"manifest":manifest,
            "signature":BASE64.encode(key.sign(bytes.as_bytes()).to_bytes())});
        let raw = crate::native_distribution::canonical_json(&envelope).unwrap();
        crate::native_distribution::verify_distribution_bytes(raw.as_bytes(),
            &crate::native_packs::PackTrust {key_id:"development-test-key".into(),
                public_key:key.verifying_key()}, Some("channel-index"), Some("beta"),
            Some("test-version"), Some("test-version")).unwrap()
    }

    fn mandatory() -> Vec<String> {
        ["app_runtime", "server_binaries", "captions_medium", "local_ai_model"]
            .into_iter().map(str::to_string).collect()
    }

    #[test]
    fn first_install_entry_requires_explicit_https_authority_without_legacy_fallback() {
        let args = vec!["--civiccast-first-install".into(), "--channel-url".into(),
            "https://example.invalid/current.channel.json".into()];
        assert!(parse_mode(&args, Path::new("user-state")).unwrap().is_some());
        assert!(parse_mode(&["--civiccast-first-install".into()], Path::new("user-state")).is_err());
        let invalid = vec!["--civiccast-first-install".into(), "--channel-url".into(),
            "http://example.invalid/legacy".into()];
        assert!(parse_mode(&invalid, Path::new("user-state")).is_err());
        assert!(parse_mode(&[], Path::new("user-state")).unwrap().is_none());
    }

    #[test]
    fn first_install_double_click_hint_is_closed_and_version_bound() {
        let hint=serde_json::json!({"schema_version":1,"product_version":"test-version",
            "compatible_core":"test-version","channel":"beta","channel_url":"https://example.invalid/current.json"});
        assert!(read_entry_hint(&serde_json::to_vec(&hint).unwrap(),"test-version",Path::new("state")).is_ok());
        assert!(read_entry_hint(&serde_json::to_vec(&hint).unwrap(),"different-version",Path::new("state")).is_err());
        let mut extra=hint.clone();extra["download_anything"]=true.into();
        assert!(read_entry_hint(&serde_json::to_vec(&extra).unwrap(),"test-version",Path::new("state")).is_err());
    }

    #[test]
    fn first_install_handoff_verification_refuses_mutated_setup_bytes() {
        use sha2::{Digest,Sha256};
        let file=std::env::temp_dir().join(format!("civiccast-setup-verify-{}.exe",std::process::id()));
        std::fs::write(&file,b"original verified setup").unwrap();
        let hash=format!("{:x}",Sha256::digest(b"original verified setup"));
        let guard=verify_file(&file,23,&hash).unwrap();
        #[cfg(windows)] assert!(std::fs::write(&file,b"replacement").is_err());
        drop(guard);
        std::fs::write(&file,b"changed setup bytes").unwrap();
        assert!(verify_file(&file,23,&hash).is_err());
        std::fs::remove_file(file).unwrap();
    }

    #[test]
    fn first_install_active_acquisition_and_owned_setup_refuse_overlap() {
        ACTIVE.store(true,Ordering::SeqCst);
        let acquisition_block=launch_setup(SetupAction::Start);
        ACTIVE.store(false,Ordering::SeqCst);
        assert_eq!(acquisition_block.unwrap_err(),"Wait for the selected installation to finish downloading.");
        SETUP_RUNNING.store(true,Ordering::SeqCst);
        let retry_block=begin(mandatory());
        let closing=can_close();
        SETUP_RUNNING.store(false,Ordering::SeqCst);
        assert_eq!(retry_block.unwrap_err(),"Windows Setup is still running. Finish it before changing files.");
        assert!(!closing);
        assert!(!ACTIVE.load(Ordering::SeqCst));
    }

    #[test]
    fn first_install_check_preserves_failed_setup_without_starting_another_process() {
        *HANDOFF.lock().unwrap()=SetupTerminal::Failed;
        let checked=launch_setup(SetupAction::Check);
        let automatic=launch_setup(SetupAction::Start);
        *HANDOFF.lock().unwrap()=SetupTerminal::Idle;
        assert_eq!(checked.unwrap(),SetupOutcome::Failed);
        assert_eq!(automatic.unwrap(),SetupOutcome::Failed);
        // No prepared pack, mode, authority, file operation or process exists
        // in this fixture: both calls must return the retained terminal result.
    }

    #[test]
    fn first_install_owned_progress_preserves_retry_error_without_disk_or_service_reconciliation() {
        let snapshot=serde_json::json!({"components":[{"id":"app_runtime","state":"error",
            "bytes_done":23,"bytes_total":23,"elapsed_seconds":0,
            "error":{"kind":"write_failed","detail":"Could not save progress"}}]}).to_string();
        let state:serde_json::Value=serde_json::from_str(&progress_envelope(Some(snapshot)).unwrap()).unwrap();
        assert_eq!(state["schema_version"],1);
        assert_eq!(state["current_lane_id"],"acquisition");
        assert_eq!(state["acquisition"]["components"][0]["state"],"error");
        assert_eq!(state["acquisition"]["components"][0]["error"]["kind"],"write_failed");
        assert!(state.get("service_url").is_none());
        assert_eq!(progress_envelope(None).unwrap(),"null");
    }

    #[test]
    fn first_install_unchecked_optional_packs_never_enter_transfer_plan() {
        let plan = select_install_components(&channel(), &mandatory()).unwrap();
        assert_eq!(plan, REQUIRED.into_iter().map(str::to_string).collect());
    }

    #[test]
    fn first_install_station_selection_preserves_signed_optional_choice_and_outer_identity() {
        let channel = channel();
        let mut station = channel.clone();
        station.kind = "station-index".into();
        station.packs.retain(|pack| REQUIRED[..5].contains(&pack.component.as_str()));
        for pack in &mut station.packs { pack.urls.clear(); }
        assert!(validate_station_selection(&channel, &station, &mandatory()).is_ok());
        station.packs[0].sha256 = "ff".repeat(32);
        assert!(validate_station_selection(&channel, &station, &mandatory()).is_err());
        station.packs[0].sha256 = channel.packs[0].sha256.clone();
        station.packs.push(channel.packs.iter().find(|pack| pack.component == "captions-large-v3").unwrap().clone());
        assert!(validate_station_selection(&channel, &station, &mandatory()).is_err());
    }

    #[test]
    fn first_install_prepares_actual_signed_bootstrap_into_existing_nsis_side_load_layout() {
        let base = std::env::temp_dir().join(format!("civiccast-first-install-bootstrap-{}", std::process::id()));
        std::fs::create_dir_all(&base).unwrap();
        let key = SigningKey::from_bytes(&[7;32]);
        let trust = PackTrust {key_id:"development-test-key".into(), public_key:key.verifying_key()};
        let mut channel = channel();
        let entries: Vec<_> = channel.packs.iter()
            .filter(|pack| REQUIRED[..5].contains(&pack.component.as_str()))
            .map(|pack| serde_json::json!({"component":pack.component, "filename":pack.filename,
                "bytes":pack.bytes, "sha256":pack.sha256, "required":true, "urls":[]})).collect();
        let manifest = serde_json::json!({"schema_version":1,"product":"civiccast-native",
            "kind":"station-index","channel":"beta","product_version":"test-version",
            "compatible_core":"test-version","signing_key_id":"development-test-key",
            "created_epoch":1,"packs":entries});
        let signed = crate::native_distribution::canonical_json(&manifest).unwrap();
        let raw = crate::native_distribution::canonical_json(&serde_json::json!({"manifest":manifest,
            "signature":BASE64.encode(key.sign(signed.as_bytes()).to_bytes())})).unwrap();
        let pack = base.join("bootstrap.ccpack");
        let (bytes, hash) = crate::native_distribution::tests::build_signed_pack_with_identity(
            &pack, &key, "installer-bootstrap", "test-version", "test-version",
            &[("setup.exe", b"MZ synthetic setup bytes, never executed"),
                ("station-indexes/baseline.json", raw.as_bytes())]);
        let pin = channel.packs.iter_mut().find(|pack| pack.component == "installer-bootstrap").unwrap();
        pin.bytes = bytes;
        pin.sha256 = hash;
        let root = base.join("prepared");
        let prepared = prepare_bootstrap(&pack, &root, &channel, &mandatory(), &trust);
        assert!(prepared.is_ok(), "{:?}", prepared.err());
        assert_eq!(std::fs::read(root.join("station/station-index.json")).unwrap(), raw.as_bytes());
        assert_eq!(std::fs::read(root.join("setup.exe")).unwrap(), b"MZ synthetic setup bytes, never executed");
        // No fake setup is launched and no synthetic model is accepted here.
        std::fs::remove_dir_all(base).unwrap();
    }

    #[test]
    fn first_install_selected_optional_packs_are_explicit() {
        let mut selection = mandatory();
        selection.extend(["captions_large".into(), "cuda_runtime".into()]);
        assert_eq!(select_install_components(&channel(), &selection).unwrap().len(), 12);
    }

    #[test]
    fn first_install_missing_authority_or_component_is_not_a_legacy_fallback() {
        let mut index = channel();
        index.packs.retain(|pack| pack.component != "native-ffmpeg-runtime");
        assert!(select_install_components(&index, &mandatory()).is_err());
        let mut selection = mandatory();
        selection.push("https://example.invalid/not-a-component".into());
        assert!(select_install_components(&channel(), &selection).is_err());
    }
}
