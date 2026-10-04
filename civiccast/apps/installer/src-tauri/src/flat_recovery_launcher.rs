// SPDX-License-Identifier: Apache-2.0
// Copyright (c) The CivicCast Authors
//! Protected incoming executor staging only: no recovery authority or process launch.
//!
//! The expected bootstrap digest comes from the signed NSIS build binding, never
//! a recovery journal or discovered sidecar. Windows CommonAppData independently
//! anchors CivicCast/flat-recovery/executor-<owner>. Only that new feature parent
//! and child receive protected SYSTEM/Administrators security; existing ancestors
//! are admitted read-only. Python admission and all rollback operations remain
//! separate, and NSIS must launch retained Python as its own immediate child.

use std::collections::BTreeMap;
use std::fs::{self, File, OpenOptions};
use std::path::{Component, Path, PathBuf};

use crate::{native_install_verify, native_pack_staging, native_packs};

const COMMAND: &str = "--civiccast-stage-flat-recovery-executor";

#[derive(Debug)]
struct Request {
    expected_hash: String,
    app_pack: PathBuf,
    server_pack: PathBuf,
    incoming: Option<(PathBuf, String)>,
    executor_root: PathBuf,
    install_root: PathBuf,
    owner: String,
}

fn validate_identity(request: &Request) -> Result<(), &'static str> {
    if request.expected_hash.len() != 64
        || !request
            .expected_hash
            .bytes()
            .all(|byte| byte.is_ascii_hexdigit())
        || request.owner.is_empty()
        || request.owner.len() > 128
        || !request.owner.as_bytes()[0].is_ascii_alphanumeric()
        || !request
            .owner
            .bytes()
            .all(|byte| byte.is_ascii_alphanumeric() || byte == b'_' || byte == b'-')
    {
        return Err("Invalid retained executor identity.");
    }
    Ok(())
}

fn parse(args: &[String]) -> Result<Request, &'static str> {
    if args.first().map(String::as_str) != Some(COMMAND) || args.len() != 13 {
        return Err("Invalid retained executor arguments.");
    }
    let mut values = BTreeMap::new();
    for pair in args[1..].chunks_exact(2) {
        if !matches!(
            pair[0].as_str(),
            "--expected-bootstrap-sha256"
                | "--app-pack"
                | "--server-pack"
                | "--executor-root"
                | "--install-root"
                | "--owner-run-id"
                | "--installer-dir"
                | "--incoming-version"
        ) || pair[1].is_empty()
            || values.insert(pair[0].as_str(), pair[1].as_str()).is_some()
        {
            return Err("Invalid retained executor arguments.");
        }
    }
    if values.len() != 6 {
        return Err("Invalid retained executor arguments.");
    }
    let explicit = values.contains_key("--app-pack") && values.contains_key("--server-pack");
    let discovery =
        values.contains_key("--installer-dir") && values.contains_key("--incoming-version");
    if explicit == discovery
        || (explicit
            && (values.contains_key("--installer-dir")
                || values.contains_key("--incoming-version")))
        || (discovery
            && (values.contains_key("--app-pack") || values.contains_key("--server-pack")))
        || ![
            "--expected-bootstrap-sha256",
            "--executor-root",
            "--install-root",
            "--owner-run-id",
        ]
        .iter()
        .all(|key| values.contains_key(key))
    {
        return Err("Retained executor requires either both explicit packs or incoming installer discovery, never both.");
    }
    let request = Request {
        expected_hash: values["--expected-bootstrap-sha256"].to_ascii_lowercase(),
        app_pack: values
            .get("--app-pack")
            .map(|value| PathBuf::from(*value))
            .unwrap_or_default(),
        server_pack: values
            .get("--server-pack")
            .map(|value| PathBuf::from(*value))
            .unwrap_or_default(),
        incoming: discovery.then(|| {
            (
                PathBuf::from(values["--installer-dir"]),
                values["--incoming-version"].to_string(),
            )
        }),
        executor_root: PathBuf::from(values["--executor-root"]),
        install_root: PathBuf::from(values["--install-root"]),
        owner: values["--owner-run-id"].to_string(),
    };
    validate_identity(&request)?;
    Ok(request)
}

fn safe_absolute(path: &Path) -> Result<PathBuf, &'static str> {
    if !path.is_absolute()
        || path
            .components()
            .any(|part| matches!(part, Component::ParentDir | Component::CurDir))
    {
        return Err("Retained executor paths must be absolute and unambiguous.");
    }
    #[cfg(windows)]
    if !matches!(path.components().next(), Some(Component::Prefix(prefix)) if matches!(prefix.kind(), std::path::Prefix::Disk(_) | std::path::Prefix::VerbatimDisk(_)))
    {
        return Err("Retained executor requires local disk paths.");
    }
    for ancestor in path.ancestors() {
        match fs::symlink_metadata(ancestor) {
            Ok(_) => native_packs::reject_reparse_path(ancestor)
                .map_err(|_| "Retained executor path is unsafe.")?,
            Err(error) if error.kind() == std::io::ErrorKind::NotFound => (),
            Err(_) => return Err("Retained executor path is unreadable."),
        }
    }
    let mut absent = Vec::new();
    let mut existing = path;
    while !existing.exists() {
        absent.push(
            existing
                .file_name()
                .ok_or("Retained executor path is invalid.")?
                .to_os_string(),
        );
        existing = existing
            .parent()
            .ok_or("Retained executor path is invalid.")?;
    }
    let mut canonical = existing
        .canonicalize()
        .map_err(|_| "Retained executor path is unreadable.")?;
    for name in absent.into_iter().rev() {
        canonical.push(name);
    }
    Ok(canonical)
}

/// Recovery refuses duplicate signed sources; ordinary discovery's first-wins
/// policy is deliberately unchanged. Never consult the installed pack tree.
fn discover_recovery_packs(
    installer: &Path,
    trust: &native_packs::PackTrust,
    version: &str,
) -> Result<(PathBuf, PathBuf), &'static str> {
    let source = safe_absolute(&installer.join("packs"))?;
    let entries = fs::read_dir(&source).map_err(|_| {
        "Incoming installer packs are unavailable; supply both signed recovery packs."
    })?;
    let mut admitted = BTreeMap::new();
    for entry in entries {
        let path = entry
            .map_err(|_| "Incoming installer pack enumeration failed.")?
            .path();
        if !path
            .extension()
            .and_then(|ext| ext.to_str())
            .is_some_and(|ext| ext.eq_ignore_ascii_case("ccpack"))
        {
            continue;
        }
        let path = safe_absolute(&path)?;
        if let Ok(pack) =
            native_packs::verify_pack(&path, trust, None, Some(version), Some(version))
        {
            if matches!(
                pack.component.as_str(),
                "native-app-payload" | "native-server-binaries"
            ) && admitted.insert(pack.component.clone(), pack).is_some()
            {
                return Err("Incoming installer has ambiguous signed recovery pack sources.");
            }
        }
    }
    let found =
        native_pack_staging::discover_offline_pack_sources(&source, trust, version, version);
    let selected = |component: &str| {
        let expected = admitted
            .get(component)
            .ok_or("Incoming installer is missing an exact-version signed recovery component.")?;
        let actual = found
            .get(component)
            .ok_or("Incoming installer signed recovery source changed during discovery.")?;
        if actual.path != expected.path || actual.sha256 != expected.sha256 {
            return Err("Incoming installer signed recovery source changed during discovery.");
        }
        Ok(actual.path.clone())
    };
    Ok((
        selected("native-app-payload")?,
        selected("native-server-binaries")?,
    ))
}

fn overlaps(left: &Path, right: &Path) -> bool {
    let key = |path: &Path| path.to_string_lossy().replace('\\', "/").to_lowercase();
    let left = key(left);
    let right = key(right);
    left == right || left.starts_with(&(right.clone() + "/")) || right.starts_with(&(left + "/"))
}

fn digest(path: &Path) -> Result<String, &'static str> {
    let mut file = File::open(path).map_err(|_| "Retained executor bytes are unreadable.")?;
    native_packs::sha256_reader(&mut file, "retained executor")
        .map_err(|_| "Retained executor bytes are unreadable.")
}

fn untrusted_grant_is_unsafe(mask: u32, owned: bool) -> bool {
    owned || mask & 0x100d0040 != 0
}

fn copy_new(source: &Path, destination: &Path) -> Result<(), &'static str> {
    let mut input = File::open(source).map_err(|_| "Retained executor input is unreadable.")?;
    let mut output = OpenOptions::new()
        .write(true)
        .create_new(true)
        .open(destination)
        .map_err(|_| "Retained executor destination is not vacant.")?;
    std::io::copy(&mut input, &mut output).map_err(|_| "Retained executor copy failed.")?;
    output
        .sync_all()
        .map_err(|_| "Retained executor copy was not durable.")
}

fn stage_with(
    request: &Request,
    bootstrap: &Path,
    protect: impl Fn(&Path) -> Result<(), &'static str>,
    verify: impl Fn(&Path, &Path, &str) -> Result<(), &'static str>,
) -> Result<(), &'static str> {
    validate_identity(request)?;
    let root = safe_absolute(&request.executor_root)?;
    let install = safe_absolute(&request.install_root)?;
    let bootstrap = safe_absolute(bootstrap)?;
    let app = safe_absolute(&request.app_pack)?;
    let server = safe_absolute(&request.server_pack)?;
    if overlaps(&root, &install)
        || root.exists()
        || !root.parent().is_some_and(|parent| {
            parent.is_dir() || (!parent.exists() && parent.parent().is_some_and(Path::is_dir))
        })
        || !bootstrap.is_file()
        || !app.is_file()
        || !server.is_file()
    {
        return Err("Retained executor roots or inputs are not independently safe.");
    }
    if digest(&bootstrap)? != request.expected_hash.to_ascii_lowercase() {
        return Err("Retained executor bootstrap binding changed.");
    }
    protect(&root)?;
    native_packs::reject_reparse_path(&root).map_err(|_| "Retained executor root changed.")?;
    let retained_bootstrap = root.join("CivicCast Native.exe");
    copy_new(&bootstrap, &retained_bootstrap)?;
    if digest(&retained_bootstrap)? != request.expected_hash.to_ascii_lowercase() {
        return Err("Retained executor copied bootstrap binding changed.");
    }
    for (input, component, directory) in [
        (app, "native-app-payload", "runtime"),
        (server, "native-server-binaries", "server"),
    ] {
        let retained_pack = root.join(format!("{component}.ccpack"));
        copy_new(&input, &retained_pack)?;
        verify(&retained_pack, &root.join(directory), component)?;
    }
    let python = root.join("runtime").join("python.exe");
    native_packs::reject_reparse_path(&python)
        .map_err(|_| "Retained executor interpreter is absent or unsafe.")?;
    if !python.is_file() || !root.join("server").is_dir() {
        return Err("Retained executor verified runtime is incomplete.");
    }
    Ok(())
}

#[cfg(windows)]
fn create_protected_root(path: &Path) -> Result<(), &'static str> {
    use std::os::windows::ffi::OsStrExt;
    use windows_sys::Win32::Foundation::LocalFree;
    use windows_sys::Win32::Security::Authorization::{
        ConvertStringSecurityDescriptorToSecurityDescriptorW, SDDL_REVISION_1,
    };
    use windows_sys::Win32::Security::{PSECURITY_DESCRIPTOR, SECURITY_ATTRIBUTES};
    use windows_sys::Win32::Storage::FileSystem::CreateDirectoryW;
    // Protected, inheritable SYSTEM/Administrators-only permissions at creation:
    // no initially user-writable directory can be swapped before hardening.
    let sddl: Vec<u16> = "O:BAG:BAD:P(A;OICI;FA;;;SY)(A;OICI;FA;;;BA)"
        .encode_utf16()
        .chain(Some(0))
        .collect();
    let wide_path: Vec<u16> = path.as_os_str().encode_wide().chain(Some(0)).collect();
    let mut descriptor: PSECURITY_DESCRIPTOR = std::ptr::null_mut();
    let converted = unsafe {
        ConvertStringSecurityDescriptorToSecurityDescriptorW(
            sddl.as_ptr(),
            SDDL_REVISION_1,
            &mut descriptor,
            std::ptr::null_mut(),
        )
    };
    if converted == 0 {
        return Err("Retained executor security descriptor is unavailable.");
    }
    let attributes = SECURITY_ATTRIBUTES {
        nLength: std::mem::size_of::<SECURITY_ATTRIBUTES>() as u32,
        lpSecurityDescriptor: descriptor,
        bInheritHandle: 0,
    };
    let created = unsafe { CreateDirectoryW(wide_path.as_ptr(), &attributes) };
    unsafe {
        LocalFree(descriptor as _);
    }
    if created == 0 {
        return Err("Retained executor protected root could not be created.");
    }
    Ok(())
}

#[cfg(not(windows))]
fn create_protected_root(_path: &Path) -> Result<(), &'static str> {
    Err("Retained executor staging requires Windows security.")
}

#[cfg(windows)]
mod admission {
    use super::*;
    use std::os::windows::ffi::{OsStrExt, OsStringExt};
    use windows_sys::Win32::Foundation::{CloseHandle, LocalFree, HANDLE, INVALID_HANDLE_VALUE};
    use windows_sys::Win32::Security::Authorization::{
        ConvertSidToStringSidW, GetNamedSecurityInfoW, SE_FILE_OBJECT,
    };
    use windows_sys::Win32::Security::{
        CheckTokenMembership, CreateWellKnownSid, GetAce, GetSecurityDescriptorControl,
        IsWellKnownSid, WinBuiltinAdministratorsSid, WinLocalSystemSid, ACCESS_ALLOWED_ACE,
        ACE_HEADER, ACL, DACL_SECURITY_INFORMATION, INHERIT_ONLY_ACE, OWNER_SECURITY_INFORMATION,
        PSECURITY_DESCRIPTOR, PSID, SE_DACL_PROTECTED,
    };
    use windows_sys::Win32::Storage::FileSystem::{
        CreateFileW, FILE_FLAG_BACKUP_SEMANTICS, FILE_READ_ATTRIBUTES, FILE_SHARE_READ,
        OPEN_EXISTING,
    };
    use windows_sys::Win32::UI::Shell::{SHGetFolderPathW, CSIDL_COMMON_APPDATA};

    pub(super) struct DirectoryGuard(HANDLE);
    impl Drop for DirectoryGuard {
        fn drop(&mut self) {
            unsafe {
                CloseHandle(self.0);
            }
        }
    }

    fn privileged() -> bool {
        for kind in [WinBuiltinAdministratorsSid, WinLocalSystemSid] {
            let mut sid = [0_u32; 17];
            let mut length = std::mem::size_of_val(&sid) as u32;
            let mut member = 0;
            unsafe {
                if CreateWellKnownSid(
                    kind,
                    std::ptr::null_mut(),
                    sid.as_mut_ptr() as PSID,
                    &mut length,
                ) != 0
                    && CheckTokenMembership(
                        std::ptr::null_mut(),
                        sid.as_mut_ptr() as PSID,
                        &mut member,
                    ) != 0
                    && member != 0
                {
                    return true;
                }
            }
        }
        false
    }

    unsafe fn trusted_sid(sid: PSID, allow_installer: bool) -> bool {
        if sid.is_null() {
            return false;
        }
        if IsWellKnownSid(sid, WinLocalSystemSid) != 0
            || IsWellKnownSid(sid, WinBuiltinAdministratorsSid) != 0
        {
            return true;
        }
        if !allow_installer {
            return false;
        }
        let mut rendered = std::ptr::null_mut();
        if ConvertSidToStringSidW(sid, &mut rendered) == 0 {
            return false;
        }
        let mut length = 0;
        while *rendered.add(length) != 0 {
            length += 1;
        }
        let value = String::from_utf16_lossy(std::slice::from_raw_parts(rendered, length));
        LocalFree(rendered as _);
        // Windows Modules Installer owns standard drive ancestors on Windows.
        value == "S-1-5-80-956008885-3418522649-1831038044-1853292631-2271478464"
    }

    pub(super) fn check_directory_security(path: &Path, owned: bool) -> Result<(), &'static str> {
        let wide: Vec<u16> = path.as_os_str().encode_wide().chain(Some(0)).collect();
        let mut owner: PSID = std::ptr::null_mut();
        let mut acl: *mut ACL = std::ptr::null_mut();
        let mut descriptor: PSECURITY_DESCRIPTOR = std::ptr::null_mut();
        let status = unsafe {
            GetNamedSecurityInfoW(
                wide.as_ptr(),
                SE_FILE_OBJECT,
                OWNER_SECURITY_INFORMATION | DACL_SECURITY_INFORMATION,
                &mut owner,
                std::ptr::null_mut(),
                &mut acl,
                std::ptr::null_mut(),
                &mut descriptor,
            )
        };
        if status != 0 {
            return Err("Retained executor ancestor security is unreadable.");
        }
        let result = (|| {
            unsafe {
                if !trusted_sid(owner, !owned) || acl.is_null() {
                    return Err("Retained executor ancestor owner or DACL is unsafe.");
                }
                if owned {
                    let mut control = 0;
                    let mut revision = 0;
                    if GetSecurityDescriptorControl(descriptor, &mut control, &mut revision) == 0
                        || control & SE_DACL_PROTECTED == 0
                    {
                        return Err("Retained executor parent DACL is not protected.");
                    }
                }
                for index in 0..(*acl).AceCount as u32 {
                    let mut raw = std::ptr::null_mut();
                    if GetAce(acl, index, &mut raw) == 0 || raw.is_null() {
                        return Err("Retained executor ancestor ACE is unreadable.");
                    }
                    let header = &*(raw as *const ACE_HEADER);
                    if header.AceFlags as u32 & INHERIT_ONLY_ACE != 0 && !owned {
                        continue;
                    }
                    if header.AceType == 1 {
                        continue;
                    } // Deny ACE cannot grant mutation.
                    if header.AceType != 0
                        || (header.AceSize as usize) < std::mem::size_of::<ACCESS_ALLOWED_ACE>()
                    {
                        return Err("Retained executor ancestor ACE is unsupported.");
                    }
                    let ace = &*(raw as *const ACCESS_ALLOWED_ACE);
                    let sid = std::ptr::addr_of!(ace.SidStart) as PSID;
                    // DELETE_CHILD, DELETE, WRITE_DAC, WRITE_OWNER, GENERIC_ALL.
                    // Ordinary ancestor AddFile/CreateDirectories/WriteData grants
                    // alone do not authorize replacement of our protected child.
                    if !trusted_sid(sid, !owned) && untrusted_grant_is_unsafe(ace.Mask, owned) {
                        return Err("Retained executor ancestor permits untrusted replacement.");
                    }
                }
            }
            Ok(())
        })();
        unsafe {
            LocalFree(descriptor as _);
        }
        result
    }

    pub(super) fn hold_directory(path: &Path) -> Result<DirectoryGuard, &'static str> {
        let wide: Vec<u16> = path.as_os_str().encode_wide().chain(Some(0)).collect();
        // Share only reads: neither delete/rename nor a reparse-writing handle
        // may be opened while the verified directory chain is in use.
        let handle = unsafe {
            CreateFileW(
                wide.as_ptr(),
                FILE_READ_ATTRIBUTES | 0x20000 | 0x1,
                FILE_SHARE_READ,
                std::ptr::null(),
                OPEN_EXISTING,
                FILE_FLAG_BACKUP_SEMANTICS,
                std::ptr::null_mut(),
            )
        };
        if handle == INVALID_HANDLE_VALUE {
            return Err("Retained executor ancestor could not be held safely.");
        }
        Ok(DirectoryGuard(handle))
    }

    pub(super) fn prepare(
        request: &Request,
        root: &Path,
    ) -> Result<Vec<DirectoryGuard>, &'static str> {
        if !privileged() {
            return Err("Retained executor staging requires an enabled privileged token.");
        }
        let common = common_appdata()?;
        let parent = safe_absolute(&common.join("CivicCast").join("flat-recovery"))?;
        let expected = parent.join(format!("executor-{}", request.owner));
        if root != expected {
            return Err("Retained executor is outside its fixed owned location.");
        }
        let civiccast = parent
            .parent()
            .ok_or("Retained executor parent is invalid.")?;
        if !civiccast.is_dir() {
            return Err("Retained executor station parent is absent.");
        }
        let mut guards = Vec::new();
        let mut ancestors: Vec<_> = civiccast.ancestors().collect();
        ancestors.reverse();
        for ancestor in ancestors {
            guards.push(hold_directory(ancestor)?);
            native_packs::reject_reparse_path(ancestor)
                .map_err(|_| "Retained executor ancestor changed.")?;
            check_directory_security(ancestor, false)?;
        }
        if !parent.exists() {
            create_protected_root(&parent)?;
        }
        guards.push(hold_directory(&parent)?);
        native_packs::reject_reparse_path(&parent)
            .map_err(|_| "Retained executor parent changed.")?;
        check_directory_security(&parent, true)?;
        // After our handles close, protected undeletable descendants keep
        // every admitted ancestor nonempty. Windows rejects setting a reparse
        // point on a nonempty directory; no ancestor ACL is changed here.
        Ok(guards)
    }

    pub(super) fn common_appdata() -> Result<PathBuf, &'static str> {
        let mut buffer = [0_u16; 260];
        if unsafe {
            SHGetFolderPathW(
                std::ptr::null_mut(),
                CSIDL_COMMON_APPDATA as i32,
                std::ptr::null_mut(),
                0,
                buffer.as_mut_ptr(),
            )
        } < 0
        {
            return Err("Windows shared application-data identity is unavailable.");
        }
        let length = buffer
            .iter()
            .position(|character| *character == 0)
            .ok_or("Windows shared application-data identity is invalid.")?;
        Ok(PathBuf::from(std::ffi::OsString::from_wide(
            &buffer[..length],
        )))
    }
}

pub(crate) fn run_cli(args: &[String], version: &str) -> Option<i32> {
    if !args.iter().any(|arg| arg == COMMAND) {
        return None;
    }
    match parse(args) {
        Ok(mut request) => {
            if request
                .incoming
                .as_ref()
                .is_some_and(|(_, incoming)| incoming != version)
            {
                eprintln!("Incoming recovery version must equal this bootstrap's compiled product version.");
                return Some(64);
            }
            let result = (|| {
                let bootstrap = std::env::current_exe()
                    .map_err(|_| "Retained executor bootstrap identity is unavailable.")?;
                let trust = native_packs::embedded_pack_trust()
                    .map_err(|_| "Retained executor signed trust is unavailable.")?;
                if let Some((installer, _)) = &request.incoming {
                    let installer = safe_absolute(installer)?;
                    let install = safe_absolute(&request.install_root)?;
                    if overlaps(&installer, &install) {
                        return Err(
                            "Incoming installer discovery cannot use the installed product tree.",
                        );
                    }
                    (request.app_pack, request.server_pack) =
                        discover_recovery_packs(&installer, &trust, version)?;
                }
                #[cfg(windows)]
                let guards = std::cell::RefCell::new(Vec::new());
                stage_with(
                    &request,
                    &bootstrap,
                    |root| {
                        #[cfg(windows)]
                        {
                            let mut held = admission::prepare(&request, root)?;
                            create_protected_root(root)?;
                            held.push(admission::hold_directory(root)?);
                            admission::check_directory_security(root, true)?;
                            *guards.borrow_mut() = held;
                            Ok(())
                        }
                        #[cfg(not(windows))]
                        {
                            create_protected_root(root)
                        }
                    },
                    |pack, destination, component| {
                        native_packs::verify_and_extract_pack(
                            pack,
                            destination,
                            &trust,
                            Some(component),
                            Some(version),
                            Some(version),
                        )
                        .map_err(|_| "Retained executor signed pack verification failed.")?;
                        native_install_verify::verify_component_pack_tree(
                            pack,
                            destination,
                            &trust,
                            Some(component),
                            Some(version),
                            Some(version),
                        )
                        .map_err(|_| "Retained executor extracted pack verification failed.")?;
                        Ok(())
                    },
                )
            })();
            match result {
                Ok(()) => Some(0),
                Err(message) => {
                    eprintln!("{message}");
                    Some(66)
                }
            }
        }
        Err(message) => {
            eprintln!("{message}");
            Some(64)
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use sha2::{Digest, Sha256};
    use std::fs;
    use std::sync::atomic::{AtomicUsize, Ordering};

    static NEXT: AtomicUsize = AtomicUsize::new(0);

    fn fixture() -> (PathBuf, Request, PathBuf) {
        let root = std::env::temp_dir().join(format!(
            "civiccast-flat-launcher-{}-{}",
            std::process::id(),
            NEXT.fetch_add(1, Ordering::SeqCst)
        ));
        fs::create_dir(&root).unwrap();
        let bootstrap = root.join("incoming.exe");
        fs::write(&bootstrap, b"synthetic bootstrap").unwrap();
        let app = root.join("incoming-app.ccpack");
        let server = root.join("incoming-server.ccpack");
        fs::write(&app, b"synthetic app").unwrap();
        fs::write(&server, b"synthetic server").unwrap();
        let install = root.join("install");
        fs::create_dir(&install).unwrap();
        let request = Request {
            expected_hash: format!("{:x}", Sha256::digest(b"synthetic bootstrap")),
            app_pack: app,
            server_pack: server,
            incoming: None,
            executor_root: root.join("retained"),
            install_root: install,
            owner: "owned-installer".into(),
        };
        (root, request, bootstrap)
    }

    fn argv(request: &Request) -> Vec<String> {
        [
            COMMAND.to_string(),
            "--expected-bootstrap-sha256".into(),
            request.expected_hash.clone(),
            "--app-pack".into(),
            request.app_pack.display().to_string(),
            "--server-pack".into(),
            request.server_pack.display().to_string(),
            "--executor-root".into(),
            request.executor_root.display().to_string(),
            "--install-root".into(),
            request.install_root.display().to_string(),
            "--owner-run-id".into(),
            request.owner.clone(),
        ]
        .to_vec()
    }

    #[test]
    fn incoming_installer_discovery_is_a_closed_alternative() {
        let (root, request, _) = fixture();
        let mut incoming = argv(&request);
        incoming[3] = "--installer-dir".into();
        incoming[4] = root.display().to_string();
        incoming[5] = "--incoming-version".into();
        incoming[6] = "fixture-version".into();
        assert!(
            parse(&incoming).is_ok(),
            "incoming discovery contract must be admitted"
        );
        assert_eq!(run_cli(&incoming, "other-version"), Some(64));
        let mut partial = incoming.clone();
        partial[5] = "--server-pack".into();
        assert!(parse(&partial).is_err());
        let mut mixed = incoming;
        mixed.extend(["--app-pack".into(), request.app_pack.display().to_string()]);
        assert!(parse(&mixed).is_err());
        fs::remove_dir_all(root).unwrap();
    }

    // Same signed ZIP fixture contract as native_pack_staging's existing tests.
    fn signed_recovery_pack(
        path: &Path,
        component: &str,
        version: &str,
    ) -> native_packs::PackTrust {
        use base64::Engine;
        use ed25519_dalek::{Signer, SigningKey};
        use std::io::Write;
        let key = SigningKey::from_bytes(&[7_u8; 32]);
        let bytes = b"signed fixture payload";
        let source = "a".repeat(40);
        let metadata = if component == "native-app-payload" {
            serde_json::json!({"source_sha": source, "civiccast_source_head": source})
        } else {
            serde_json::json!({"source_sha": source})
        };
        let manifest = native_packs::canonical_json(&serde_json::json!({
            "schema_version": 1, "product": "civiccast-native", "component": component,
            "product_version": version, "compatible_core": version, "signing_key_id": "test-key",
            "file_count": 1, "total_bytes": bytes.len(), "metadata": metadata,
            "files": [{"path": "python.exe", "bytes": bytes.len(), "sha256": format!("{:x}", Sha256::digest(bytes))}]
        })).unwrap();
        let sig = base64::engine::general_purpose::STANDARD
            .encode(key.sign(manifest.as_bytes()).to_bytes());
        let mut zip = zip::ZipWriter::new(File::create(path).unwrap());
        let options = zip::write::SimpleFileOptions::default()
            .compression_method(zip::CompressionMethod::Stored);
        for (name, data) in [
            ("manifest.json", manifest.as_bytes()),
            ("manifest.sig", sig.as_bytes()),
            ("payload/python.exe", bytes.as_slice()),
        ] {
            zip.start_file(name, options).unwrap();
            zip.write_all(data).unwrap();
        }
        zip.finish().unwrap();
        native_packs::PackTrust {
            key_id: "test-key".into(),
            public_key: key.verifying_key(),
        }
    }

    #[test]
    fn incoming_discovery_requires_unique_exact_signed_components() {
        let (root, mut request, bootstrap) = fixture();
        let packs = root.join("packs");
        fs::create_dir(&packs).unwrap();
        let app = packs.join("renamed-app.ccpack");
        let server = packs.join("renamed-server.ccpack");
        let trust = signed_recovery_pack(&app, "native-app-payload", "incoming");
        assert!(discover_recovery_packs(&root, &trust, "incoming").is_err());
        signed_recovery_pack(&server, "native-server-binaries", "old-installed");
        assert!(discover_recovery_packs(&root, &trust, "incoming").is_err());
        signed_recovery_pack(&server, "unrelated-component", "incoming");
        assert!(discover_recovery_packs(&root, &trust, "incoming").is_err());
        signed_recovery_pack(&server, "native-server-binaries", "incoming");
        assert_eq!(
            discover_recovery_packs(&root, &trust, "incoming").unwrap(),
            (
                safe_absolute(&app).unwrap(),
                safe_absolute(&server).unwrap()
            )
        );
        (request.app_pack, request.server_pack) =
            discover_recovery_packs(&root, &trust, "incoming").unwrap();
        stage_with(
            &request,
            &bootstrap,
            |path| {
                fs::create_dir(path).unwrap();
                Ok(())
            },
            |pack, destination, component| {
                native_packs::verify_and_extract_pack(
                    pack,
                    destination,
                    &trust,
                    Some(component),
                    Some("incoming"),
                    Some("incoming"),
                )
                .map_err(|_| "signed fixture extraction failed")?;
                native_install_verify::verify_component_pack_tree(
                    pack,
                    destination,
                    &trust,
                    Some(component),
                    Some("incoming"),
                    Some("incoming"),
                )
                .map_err(|_| "signed fixture tree failed")?;
                Ok(())
            },
        )
        .expect("discovered signed pair consumed by existing retained staging");
        assert!(request.executor_root.join("runtime/python.exe").is_file());
        assert!(request.executor_root.join("server/python.exe").is_file());
        signed_recovery_pack(
            &packs.join("duplicate-app.ccpack"),
            "native-app-payload",
            "incoming",
        );
        assert!(
            discover_recovery_packs(&root, &trust, "incoming").is_err(),
            "two verified sources cannot be silently first-wins"
        );
        fs::remove_dir_all(root).unwrap();
    }

    #[test]
    fn closed_arguments_accept_the_exact_contract() {
        let (root, request, _) = fixture();
        let parsed = parse(&argv(&request)).expect("valid closed launcher contract");
        assert_eq!(parsed.owner, request.owner);
        fs::remove_dir_all(root).unwrap();
    }

    #[test]
    fn stages_only_after_protection_and_requires_verified_python() {
        let (root, request, bootstrap) = fixture();
        stage_with(
            &request,
            &bootstrap,
            |path| {
                fs::create_dir(path).unwrap();
                fs::write(path.join("protected-marker"), b"owned fixture ACL boundary").unwrap();
                Ok(())
            },
            |pack, destination, component| {
                assert!(request.executor_root.join("protected-marker").is_file());
                assert!(pack.is_file());
                fs::create_dir(destination).unwrap();
                if component == "native-app-payload" {
                    fs::write(destination.join("python.exe"), b"verified fixture python").unwrap();
                }
                Ok(())
            },
        )
        .expect("retained verified executor");
        assert_eq!(
            fs::read(request.executor_root.join("CivicCast Native.exe")).unwrap(),
            fs::read(bootstrap).unwrap()
        );
        fs::remove_dir_all(root).unwrap();
    }

    #[test]
    fn mixed_duplicate_missing_and_unsafe_arguments_are_closed() {
        let (root, request, _) = fixture();
        let valid = argv(&request);
        let mut mixed = valid.clone();
        mixed.extend(["--civiccast-stop-native-service".into()]);
        assert!(parse(&mixed).is_err());
        assert_eq!(run_cli(&mixed, "fixture-version"), Some(64));
        assert_eq!(
            run_cli(
                &["--civiccast-stop-native-service".into()],
                "fixture-version"
            ),
            None
        );
        let mut duplicate = valid.clone();
        duplicate[3] = "--app-pack".into();
        duplicate[5] = "--app-pack".into();
        assert!(parse(&duplicate).is_err());
        assert!(parse(&valid[..valid.len() - 1]).is_err());
        for unsafe_owner in ["../outside", "bad.token", "-bad", "bad space", ""] {
            let mut bad = valid.clone();
            *bad.last_mut().unwrap() = unsafe_owner.into();
            assert!(parse(&bad).is_err());
        }
        let mut bad_hash = valid;
        bad_hash[2] = "z".repeat(64);
        assert!(parse(&bad_hash).is_err());
        fs::remove_dir_all(root).unwrap();
    }

    #[test]
    fn bad_binding_or_overlap_cannot_create_executor_bytes() {
        let (root, mut request, bootstrap) = fixture();
        request.expected_hash = "0".repeat(64);
        let result = stage_with(
            &request,
            &bootstrap,
            |_| panic!("created before admission"),
            |_, _, _| panic!("verified before admission"),
        );
        assert_eq!(result, Err("Retained executor bootstrap binding changed."));
        assert!(!request.executor_root.exists());
        request.expected_hash = format!("{:x}", Sha256::digest(b"synthetic bootstrap"));
        request.executor_root = request.install_root.join("nested-executor");
        assert!(stage_with(
            &request,
            &bootstrap,
            |_| panic!("created overlapping root"),
            |_, _, _| panic!("verified overlapping root")
        )
        .is_err());
        assert!(!request.executor_root.exists());
        fs::remove_dir_all(root).unwrap();
    }

    #[test]
    fn protection_failure_does_not_copy_executable_or_packs() {
        let (root, request, bootstrap) = fixture();
        let result = stage_with(
            &request,
            &bootstrap,
            |_| Err("synthetic protection failure"),
            |_, _, _| panic!("verification after failed protection"),
        );
        assert_eq!(result, Err("synthetic protection failure"));
        assert!(!request.executor_root.exists());
        fs::remove_dir_all(root).unwrap();
    }

    #[test]
    fn failed_verification_retains_protected_bytes_but_never_returns_success() {
        let (root, request, bootstrap) = fixture();
        let result = stage_with(
            &request,
            &bootstrap,
            |path| fs::create_dir(path).map_err(|_| "fixture root"),
            |_, _, _| Err("synthetic signed-pack rejection"),
        );
        assert_eq!(result, Err("synthetic signed-pack rejection"));
        assert!(request.executor_root.join("CivicCast Native.exe").is_file());
        assert!(request
            .executor_root
            .join("native-app-payload.ccpack")
            .is_file());
        assert!(!request
            .executor_root
            .join("native-server-binaries.ccpack")
            .exists());
        fs::remove_dir_all(root).unwrap();
    }

    #[test]
    fn missing_python_is_not_a_verified_executor() {
        let (root, request, bootstrap) = fixture();
        let result = stage_with(
            &request,
            &bootstrap,
            |path| fs::create_dir(path).map_err(|_| "fixture root"),
            |_, destination, _| fs::create_dir(destination).map_err(|_| "fixture destination"),
        );
        assert_eq!(
            result,
            Err("Retained executor interpreter is absent or unsafe.")
        );
        assert!(request
            .executor_root
            .join("native-server-binaries.ccpack")
            .is_file());
        fs::remove_dir_all(root).unwrap();
    }

    #[test]
    fn preexisting_root_or_ambiguous_path_is_refused() {
        let (root, request, bootstrap) = fixture();
        fs::create_dir(&request.executor_root).unwrap();
        fs::write(request.executor_root.join("unrelated"), b"keep").unwrap();
        assert!(stage_with(
            &request,
            &bootstrap,
            |_| panic!("overwrote existing root"),
            |_, _, _| panic!("verified existing root")
        )
        .is_err());
        assert_eq!(
            fs::read(request.executor_root.join("unrelated")).unwrap(),
            b"keep"
        );
        assert!(safe_absolute(Path::new("relative-root")).is_err());
        assert!(safe_absolute(&root.join("..").join("outside")).is_err());
        fs::remove_dir_all(root).unwrap();
    }

    #[test]
    fn input_names_cannot_overwrite_the_retained_bootstrap() {
        let (root, mut request, bootstrap) = fixture();
        request.app_pack = root.join("CivicCast Native.exe");
        fs::write(
            &request.app_pack,
            b"synthetic app pack with colliding input basename",
        )
        .unwrap();
        let result = stage_with(
            &request,
            &bootstrap,
            |path| fs::create_dir(path).map_err(|_| "fixture root"),
            |pack, destination, component| {
                assert_eq!(
                    pack.file_name().unwrap(),
                    format!("{component}.ccpack").as_str()
                );
                fs::create_dir(destination).unwrap();
                if component == "native-app-payload" {
                    fs::write(destination.join("python.exe"), b"fixture").unwrap();
                }
                Ok(())
            },
        );
        assert!(result.is_ok());
        assert_eq!(
            fs::read(request.executor_root.join("CivicCast Native.exe")).unwrap(),
            fs::read(bootstrap).unwrap()
        );
        fs::remove_dir_all(root).unwrap();
    }

    #[test]
    fn ancestor_acl_policy_distinguishes_sibling_creation_from_replacement() {
        for dangerous in [0x40, 0x10000, 0x40000, 0x80000, 0x10000000] {
            assert!(untrusted_grant_is_unsafe(dangerous, false));
        }
        for sibling_only in [0x2, 0x4, 0x116, 0x120116] {
            assert!(!untrusted_grant_is_unsafe(sibling_only, false));
            assert!(untrusted_grant_is_unsafe(sibling_only, true));
        }
    }

    #[cfg(windows)]
    #[test]
    fn actual_directory_guard_allows_creation_but_blocks_replacement() {
        let (root, request, _) = fixture();
        fs::create_dir(&request.executor_root).unwrap();
        let guard =
            admission::hold_directory(&request.executor_root).expect("owned directory guard");
        fs::create_dir(request.executor_root.join("runtime"))
            .expect("directory creation while held");
        fs::write(
            request.executor_root.join("runtime/python.exe"),
            b"owned test bytes",
        )
        .expect("file creation while held");
        let replacement = root.join("replacement");
        assert!(
            fs::rename(&request.executor_root, &replacement).is_err(),
            "held directory must not be renamed"
        );
        drop(guard);
        fs::rename(&request.executor_root, &replacement)
            .expect("rename succeeds only after guard release");
        fs::remove_dir_all(root).unwrap();
    }

    #[cfg(windows)]
    #[test]
    fn actual_default_ancestor_admission_is_read_only_and_compatible() {
        let common = safe_absolute(&admission::common_appdata().unwrap()).unwrap();
        let station = common.join("CivicCast");
        let leaf = if station.is_dir() {
            station.as_path()
        } else {
            common.as_path()
        };
        let mut guards = Vec::new();
        for ancestor in leaf.ancestors() {
            guards.push(
                admission::hold_directory(ancestor).expect("read-only default ancestor guard"),
            );
            native_packs::reject_reparse_path(ancestor).expect("default ancestor is not reparse");
            admission::check_directory_security(ancestor, false)
                .expect("default ancestor security admission");
        }
    }

    #[cfg(windows)]
    #[test]
    fn actual_nonempty_ancestor_rejects_reparse_after_guards_close() {
        use std::os::windows::ffi::OsStrExt;
        use windows_sys::Win32::Foundation::{CloseHandle, GetLastError, INVALID_HANDLE_VALUE};
        use windows_sys::Win32::Storage::FileSystem::{
            CreateFileW, FILE_FLAG_BACKUP_SEMANTICS, FILE_FLAG_OPEN_REPARSE_POINT, OPEN_EXISTING,
        };
        #[link(name = "kernel32")]
        extern "system" {
            fn DeviceIoControl(
                handle: windows_sys::Win32::Foundation::HANDLE,
                code: u32,
                input: *const core::ffi::c_void,
                input_len: u32,
                output: *mut core::ffi::c_void,
                output_len: u32,
                returned: *mut u32,
                overlapped: *mut core::ffi::c_void,
            ) -> i32;
        }
        let (root, request, _) = fixture();
        fs::create_dir(&request.executor_root).unwrap();
        fs::write(
            request.executor_root.join("undeletable-child-model"),
            b"owned equivalent of retained descendant",
        )
        .unwrap();
        let guard = admission::hold_directory(&request.executor_root).unwrap();
        drop(guard); // Exercise the post-staging lifetime, not a sharing failure.
        let target = root.join("redirect-target");
        fs::create_dir(&target).unwrap();
        let rendered = target
            .canonicalize()
            .unwrap()
            .to_string_lossy()
            .into_owned();
        let print = rendered.strip_prefix(r"\\?\").unwrap_or(&rendered);
        let substitute: Vec<u16> = format!(r"\??\{print}").encode_utf16().collect();
        let printable: Vec<u16> = print.encode_utf16().collect();
        let mut paths = substitute.clone();
        paths.push(0);
        paths.extend(&printable);
        paths.push(0);
        let mut buffer = Vec::new();
        buffer.extend(0xA0000003_u32.to_le_bytes());
        buffer.extend(((8 + paths.len() * 2) as u16).to_le_bytes());
        buffer.extend(0_u16.to_le_bytes());
        for value in [
            0_u16,
            (substitute.len() * 2) as u16,
            ((substitute.len() + 1) * 2) as u16,
            (printable.len() * 2) as u16,
        ] {
            buffer.extend(value.to_le_bytes());
        }
        for value in paths {
            buffer.extend(value.to_le_bytes());
        }
        let wide: Vec<u16> = request
            .executor_root
            .as_os_str()
            .encode_wide()
            .chain(Some(0))
            .collect();
        let handle = unsafe {
            CreateFileW(
                wide.as_ptr(),
                0x40000000,
                7,
                std::ptr::null(),
                OPEN_EXISTING,
                FILE_FLAG_BACKUP_SEMANTICS | FILE_FLAG_OPEN_REPARSE_POINT,
                std::ptr::null_mut(),
            )
        };
        assert_ne!(
            handle, INVALID_HANDLE_VALUE,
            "owned reparse probe requires actual write access"
        );
        let mut returned = 0;
        let changed = unsafe {
            DeviceIoControl(
                handle,
                0x900a4,
                buffer.as_ptr() as _,
                buffer.len() as u32,
                std::ptr::null_mut(),
                0,
                &mut returned,
                std::ptr::null_mut(),
            )
        };
        let error = unsafe { GetLastError() };
        unsafe {
            CloseHandle(handle);
        }
        assert_eq!(
            changed, 0,
            "nonempty directory unexpectedly accepted reparse redirect"
        );
        assert_eq!(
            error, 145,
            "rejection must be DIRECTORY_NOT_EMPTY, not a missing privilege or malformed buffer"
        );
        native_packs::reject_reparse_path(&request.executor_root).unwrap();
        fs::remove_dir_all(root).unwrap();
    }

    #[cfg(windows)]
    #[test]
    fn actual_owned_root_security_or_disabled_token_fails_closed() {
        let (root, request, _) = fixture();
        match create_protected_root(&request.executor_root) {
            Ok(()) => {
                admission::check_directory_security(&request.executor_root, true)
                    .expect("actual owned root owner/protected DACL readback");
                println!("actual SYSTEM/Administrators owned-root ACL creation/readback executed");
            }
            Err(_) => {
                assert!(
                    !request.executor_root.exists(),
                    "failed security creation must not leave an unhardened root"
                );
                let result = admission::prepare(&request, &request.executor_root);
                assert!(matches!(result, Err("Retained executor staging requires an enabled privileged token.")), "root security failure may not be classified as a disabled token unless actually refused there");
                println!("actual token gate refused staging; positive protected-root creation not proven in this token");
            }
        }
        fs::remove_dir_all(root).unwrap();
    }

    #[test]
    fn absent_owned_parent_can_be_created_by_protected_admission() {
        let (root, mut request, bootstrap) = fixture();
        request.executor_root = root
            .join("new-owned-parent")
            .join("executor-owned-installer");
        let result = stage_with(
            &request,
            &bootstrap,
            |path| {
                fs::create_dir(path.parent().unwrap()).unwrap();
                fs::create_dir(path).unwrap();
                Ok(())
            },
            |_, destination, component| {
                fs::create_dir(destination).unwrap();
                if component == "native-app-payload" {
                    fs::write(destination.join("python.exe"), b"fixture").unwrap();
                }
                Ok(())
            },
        );
        assert!(
            result.is_ok(),
            "protected admission must create the feature's absent parent: {result:?}"
        );
        fs::remove_dir_all(root).unwrap();
    }
}
