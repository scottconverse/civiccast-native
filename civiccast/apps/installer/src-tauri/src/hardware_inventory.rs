// SPDX-License-Identifier: Apache-2.0
// Copyright (c) The CivicCast Authors

//! Native hardware inventory for CivicCast (Native).
//!
//! Owner-settled installer architecture: the installer ships a small base
//! (the app payload, which carries the embedded CPython interpreter, is
//! NOT on disk yet at this point) and downloads big components -- caption
//! models chief among them -- during setup, with an explain+progress UI for
//! the big ones. Deciding WHICH caption tier to default to therefore has to
//! happen before Python exists on the target machine, so this probe is
//! native Rust, not the existing Python probe.
//!
//! This module is a MIRROR of `civiccast.platform.hardware`'s `probe()` /
//! `_tier_for()` (see `civiccast/platform/hardware.py`) -- never a rival.
//! The Python module stays the single authority for the GPU/VRAM deployment
//! tier decision tree (spec §7.7); the VRAM-GB threshold constants below are
//! pinned bidirectionally against `hardware.py`'s `_tier_for` (hardware.py
//! lines 349-357) by `tests/policy/test_hardware_inventory_policy.py`.
//!
//! ## Known, documented divergence from `civiccast.platform.hardware`
//!
//! `hardware.py`'s GPU probe is NVIDIA-only via NVML (ADR 0005, see that
//! module's top docstring): on a machine with only an AMD or Intel GPU,
//! `probe()` returns `gpu = None` and therefore always recommends
//! `tier-0`, regardless of that GPU's actual VRAM. This module collects GPU
//! facts via DXGI (`IDXGIFactory1::EnumAdapters1` / `DXGI_ADAPTER_DESC1`),
//! which sees every vendor's adapter with dedicated VRAM -- so `gpus` in the
//! returned inventory legitimately lists AMD/Intel cards too, for operator
//! visibility in the frontend. But `recommended_caption_tier` mirrors
//! hardware.py's NVIDIA-only bias exactly: only NVIDIA-vendor entries (PCI
//! vendor id 0x10DE) count toward the VRAM-GB tier thresholds. An
//! AMD/Intel-only capable box will therefore show its GPU in `gpus` yet
//! still recommend the caption `floor` tier, matching what `hardware.py`'s
//! `probe()` would independently compute (GPU probed as `None` -> `tier-0`).
//! This is a deliberate, honest mirror of a real Python limitation -- not an
//! attempt to fake a CUDA/tensor-core probe DXGI cannot see.
//!
//! A second, narrower divergence: on a machine with more than one NVIDIA
//! GPU, `hardware.py` uses NVML device index 0 (whichever GPU NVML
//! enumerates first). DXGI's adapter enumeration order is not guaranteed to
//! match NVML's, so this module instead uses the HIGHEST-VRAM NVIDIA
//! adapter as the representative GPU for the tier decision. On the common
//! single-dGPU target hardware this is exactly equivalent to hardware.py's
//! choice; only a multi-NVIDIA-GPU box could see a different GPU picked as
//! "the" GPU, and even then never a different TIER outcome for a
//! same-or-larger-VRAM alternate pick, since VRAM class is what actually
//! feeds the ladder.

use serde::Serialize;

use crate::native_packs::{FLOOR_TIER_ID, LARGE_V3_TIER_ID};

/// One GPU's facts as collected via DXGI adapter enumeration. Field
/// casing/names are the wire contract consumed by the TypeScript frontend
/// (see `src/types.ts`).
#[derive(Debug, Clone, Serialize)]
pub struct GpuFacts {
    pub name: String,
    pub dedicated_vram_mb: u64,
    pub vendor: String,
}

/// Pure input to [`recommend_caption_tier`] -- everything the recommendation
/// needs, decoupled from HOW it was collected, so the recommendation logic
/// is testable on any machine without touching real hardware (see the
/// table-driven unit tests below).
#[derive(Debug, Clone, Default)]
pub struct HardwareFacts {
    pub gpus: Vec<GpuFacts>,
}

/// Full hardware inventory returned to the frontend by the
/// `native_hardware_inventory` Tauri command, serialized as JSON with
/// serde's default (snake_case, matching these Rust field names verbatim --
/// the same convention `InstallerProgress` already uses in `src/types.ts`,
/// as opposed to the `rename_all = "camelCase"` commands elsewhere in this
/// crate).
///
/// ## Every measured field is an `Option` on purpose (G011.1)
///
/// A probe that cannot obtain a value reports `None`, which the frontend
/// renders as "Unavailable". It never picks a stand-in number. The previous
/// shape had no way to express "unknown", so every collector fell back to a
/// fabricated value on failure -- `0` free bytes (which the frontend's disk
/// guard reads as a completely full drive and blocks first run on), `0.0` GB
/// of RAM, `"unknown CPU (registry read failed)"` printed verbatim as the
/// processor, and an EMPTY GPU list that is indistinguishable from "this
/// machine genuinely has no dedicated GPU". Those are four different lies of
/// the same kind and this type is what makes them unrepresentable.
///
/// `gpus: None` specifically means "the DXGI probe could not run at all";
/// `Some(vec![])` means "the probe ran and this machine has no adapter with
/// dedicated VRAM". Only the second one licenses the frontend to say "No
/// dedicated graphics card".
#[derive(Debug, Clone, Serialize)]
pub struct HardwareInventory {
    pub cpu_model: Option<String>,
    pub physical_cores: Option<u32>,
    pub logical_cores: Option<u32>,
    pub ram_gb: Option<f64>,
    pub gpus: Option<Vec<GpuFacts>>,
    /// Free bytes on the volume hosting the install target, straight from
    /// `GetDiskFreeSpaceExW`'s `lpFreeBytesAvailableToCaller` -- BYTES, not
    /// the old whole-rounded GB, so the frontend's disk guard compares a real
    /// measurement against a real payload size instead of two roundings.
    pub free_disk_bytes: Option<u64>,
    /// Which directory that free-space figure was taken on, so the screen can
    /// name the drive it is talking about instead of "this drive".
    pub install_target: Option<String>,
    /// The tier CivicCast will actually install -- always one the production
    /// acquisition catalog can deliver (see [`recommend_caption_tier`]).
    pub recommended_caption_tier: String,
    /// The tier this machine's hardware could RUN, before obtainability is
    /// considered. Equal to `recommended_caption_tier` in the ordinary case;
    /// when they differ, the frontend says why rather than silently implying
    /// the hardware was not good enough.
    pub hardware_capable_caption_tier: String,
}

fn round1(value: f64) -> f64 {
    (value * 10.0).round() / 10.0
}

// ---------------------------------------------------------------------------
// Recommendation logic (pure, hardware-independent -- mirrors hardware.py's
// `_tier_for`, hardware.py:349-357).
// ---------------------------------------------------------------------------

/// PCI vendor id for NVIDIA -- the ONLY vendor `hardware.py`'s NVML-based GPU
/// probe ever recognizes (ADR 0005). Only GPUs with this vendor id count
/// toward the caption-tier VRAM thresholds below.
pub(crate) const NVIDIA_PCI_VENDOR_ID: u32 = 0x10DE;

/// Mirrors `gpu.vram_total_gb < 8` in hardware.py's `_tier_for`
/// (`civiccast/platform/hardware.py:351`). Pinned bidirectionally against
/// that literal by `tests/policy/test_hardware_inventory_policy.py`.
pub(crate) const HARDWARE_TIER_VRAM_GB_TIER0_MAX: u64 = 8;
/// Mirrors `gpu.vram_total_gb < 16` in hardware.py's `_tier_for`
/// (`civiccast/platform/hardware.py:353`).
pub(crate) const HARDWARE_TIER_VRAM_GB_TIER1_MAX: u64 = 16;
/// Mirrors `gpu.vram_total_gb < 24` in hardware.py's `_tier_for`
/// (`civiccast/platform/hardware.py:355`).
pub(crate) const HARDWARE_TIER_VRAM_GB_TIER1_PLUS_MAX: u64 = 24;

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub(crate) enum DeploymentTier {
    Tier0,
    Tier1,
    Tier1Plus,
    Tier2,
}

/// Mirrors `_tier_for` (hardware.py:349-357) exactly: one NVIDIA GPU's VRAM
/// (in rounded GB; `None` when there is no qualifying NVIDIA GPU) in, one
/// tier out.
pub(crate) fn deployment_tier_for_nvidia_vram_gb(vram_gb: Option<f64>) -> DeploymentTier {
    match vram_gb {
        None => DeploymentTier::Tier0,
        Some(v) if v < HARDWARE_TIER_VRAM_GB_TIER0_MAX as f64 => DeploymentTier::Tier0,
        Some(v) if v < HARDWARE_TIER_VRAM_GB_TIER1_MAX as f64 => DeploymentTier::Tier1,
        Some(v) if v < HARDWARE_TIER_VRAM_GB_TIER1_PLUS_MAX as f64 => DeploymentTier::Tier1Plus,
        Some(_) => DeploymentTier::Tier2,
    }
}

/// The best (highest-VRAM) NVIDIA GPU's VRAM in GB, rounded to 1 decimal
/// place exactly like `hardware.py`'s `round(mem.total / 1024**3, 1)`
/// (hardware.py:201) -- so boundary VRAM sizes round the same way on both
/// sides of the mirror.
fn best_nvidia_vram_gb(gpus: &[GpuFacts]) -> Option<f64> {
    gpus.iter()
        .filter(|gpu| gpu.vendor == "NVIDIA")
        .map(|gpu| round1(gpu.dedicated_vram_mb as f64 / 1024.0))
        .fold(None, |best: Option<f64>, candidate| {
            Some(best.map_or(candidate, |current| current.max(candidate)))
        })
}

/// The caption tier this machine's HARDWARE could run (`"floor"` or
/// `"large-v3"`, the exact ids
/// `civiccast.native.caption_tiers.CAPTION_TIER_REGISTRY` uses), before any
/// question of whether that tier can actually be obtained. CPU-only or
/// non-NVIDIA-GPU boxes get the mandatory CPU floor tier (medium); a capable
/// NVIDIA GPU (>=8GB VRAM, i.e. not hardware.py's `tier-0`) reaches the
/// quality tier (large-v3).
pub fn hardware_capable_caption_tier(facts: &HardwareFacts) -> &'static str {
    match deployment_tier_for_nvidia_vram_gb(best_nvidia_vram_gb(&facts.gpus)) {
        DeploymentTier::Tier0 => FLOOR_TIER_ID,
        DeploymentTier::Tier1 | DeploymentTier::Tier1Plus | DeploymentTier::Tier2 => {
            LARGE_V3_TIER_ID
        }
    }
}

/// The frontend catalog component id (`components-catalog.ts`'s `ComponentId`)
/// that DELIVERS a given caption tier. The two tier ids and the two component
/// ids are separate vocabularies that have to be joined somewhere; this is
/// the one place that does it.
pub fn caption_component_id_for_tier(tier: &str) -> &'static str {
    if tier == LARGE_V3_TIER_ID {
        "captions_large"
    } else {
        "captions_medium"
    }
}

/// Whether a caption tier can actually be downloaded on a fresh install --
/// i.e. whether the component that carries it is in the production
/// acquisition catalog `main.rs`'s `run_production_acquisition` drives.
///
/// Derived from [`crate::acquisition_catalog::PRODUCTION_CATALOG_IDS`], never
/// a second hand-maintained list, so re-enrolling `captions_large` there is
/// all it takes for this to start returning `true` for `large-v3`.
pub fn caption_tier_is_obtainable(tier: &str) -> bool {
    crate::acquisition_catalog::PRODUCTION_CATALOG_IDS
        .contains(&caption_component_id_for_tier(tier))
}

/// The tier CivicCast will actually install: the hardware-capable tier when
/// that tier can be obtained, and the floor tier otherwise.
///
/// G011.1. `captions_large` is not in the production acquisition catalog (see
/// `acquisition_catalog.rs`'s module doc: `captions_large` "is intentionally
/// NOT in this catalog"), yet this function recommended `large-v3` on every
/// >=8GB NVIDIA box, the frontend's `defaultSelectedComponentIds` duly
/// pre-selected `captions_large`, and the downloading screen then showed a
/// row nothing on the backend would ever drive -- a permanently "Waiting"
/// row on the exact hardware the product is proudest of. Recommending only
/// obtainable tiers is the honest fix; the hardware's real capability is
/// still reported separately as
/// [`HardwareInventory::hardware_capable_caption_tier`] so the screen can
/// explain the gap rather than imply the GPU was not good enough.
pub fn recommend_caption_tier(facts: &HardwareFacts) -> &'static str {
    let capable = hardware_capable_caption_tier(facts);
    if caption_tier_is_obtainable(capable) {
        capable
    } else {
        FLOOR_TIER_ID
    }
}

/// Classify a PCI vendor id the way an operator would recognize it. Never
/// consumed by the recommendation logic above (which keys on the exact
/// `"NVIDIA"` string produced here for the one vendor id it cares about) --
/// this exists purely so `gpus[]` is legible in the frontend.
fn vendor_name_for_pci_id(vendor_id: u32) -> String {
    match vendor_id {
        NVIDIA_PCI_VENDOR_ID => "NVIDIA".to_string(),
        // ATI Technologies (0x1002) covers essentially every AMD/ATI Radeon
        // GPU in the wild; 0x1022 is AMD's own vendor id, seen on some
        // integrated/APU parts.
        0x1002 | 0x1022 => "AMD".to_string(),
        0x8086 => "Intel".to_string(),
        other => format!("Unknown (0x{other:04X})"),
    }
}

// ---------------------------------------------------------------------------
// Windows collectors -- real Win32/DXGI calls, no mocks.
// ---------------------------------------------------------------------------

#[cfg(target_os = "windows")]
pub(crate) mod windows_collectors {
    use super::{round1, vendor_name_for_pci_id, GpuFacts};
    use std::os::windows::ffi::OsStrExt;
    use std::path::Path;

    /// CPU brand string via the registry -- dependency-free, no subprocess.
    /// `HKLM\HARDWARE\DESCRIPTION\System\CentralProcessor\0`'s
    /// `ProcessorNameString` is the same friendly name Windows itself shows
    /// in Task Manager / System Information.
    /// `None` when the registry read fails -- never a sentinel string that
    /// would be printed on screen as if it were this machine's processor.
    pub fn collect_cpu_model() -> Option<String> {
        use winreg::enums::HKEY_LOCAL_MACHINE;
        use winreg::RegKey;

        let hklm = RegKey::predef(HKEY_LOCAL_MACHINE);
        let read = hklm
            .open_subkey(r"HARDWARE\DESCRIPTION\System\CentralProcessor\0")
            .and_then(|key| key.get_value::<String, _>("ProcessorNameString"));
        match read {
            Ok(name) if !name.trim().is_empty() => Some(name.trim().to_string()),
            _ => None,
        }
    }

    /// Logical processor count (includes SMT/hyperthreads), via
    /// `GetSystemInfo`. `None` when the call reports no processors at all,
    /// which is not a real machine -- reporting the old `.max(1)` would be
    /// inventing a core.
    pub fn collect_logical_cores() -> Option<u32> {
        use windows_sys::Win32::System::SystemInformation::{GetSystemInfo, SYSTEM_INFO};

        unsafe {
            let mut info: SYSTEM_INFO = std::mem::zeroed();
            GetSystemInfo(&mut info);
            if info.dwNumberOfProcessors == 0 {
                None
            } else {
                Some(info.dwNumberOfProcessors)
            }
        }
    }

    /// Physical core count via `GetLogicalProcessorInformationEx`
    /// (`RelationProcessorCore`): each returned record represents ONE
    /// physical core, regardless of how many logical processors (SMT
    /// siblings) it hosts, so the record count IS the physical core count.
    /// Records are variable-length; each record's own `Size` field (not
    /// `size_of::<SYSTEM_LOGICAL_PROCESSOR_INFORMATION_EX>()`) is the only
    /// correct way to advance through the buffer.
    ///
    /// `None` when the API cannot be read at all -- it falls back to the
    /// LOGICAL count (a real, if coarser, measurement of the same machine),
    /// and only reports `None` when that is unavailable too.
    pub fn collect_physical_cores() -> Option<u32> {
        use windows_sys::Win32::System::SystemInformation::{
            GetLogicalProcessorInformationEx, RelationProcessorCore,
            SYSTEM_LOGICAL_PROCESSOR_INFORMATION_EX,
        };

        unsafe {
            let mut needed: u32 = 0;
            // Expected to fail (ERROR_INSUFFICIENT_BUFFER) with a null
            // buffer -- that is this API's documented way of reporting the
            // size it actually needs.
            GetLogicalProcessorInformationEx(
                RelationProcessorCore,
                std::ptr::null_mut(),
                &mut needed,
            );
            if needed == 0 {
                return collect_logical_cores();
            }
            let mut buffer = vec![0u8; needed as usize];
            let ok = GetLogicalProcessorInformationEx(
                RelationProcessorCore,
                buffer.as_mut_ptr() as *mut SYSTEM_LOGICAL_PROCESSOR_INFORMATION_EX,
                &mut needed,
            );
            if ok == 0 {
                return collect_logical_cores();
            }

            // GetLogicalProcessorInformationEx guarantees a successful call
            // fills exactly `needed` bytes with whole, back-to-back records,
            // each self-describing its own length via `Size` -- that field,
            // never `size_of::<SYSTEM_LOGICAL_PROCESSOR_INFORMATION_EX>()`,
            // is the only correct stride (the real payload is a flexible
            // array member this binding models as a fixed 1-element tail).
            let mut physical = 0u32;
            let mut offset = 0usize;
            while offset < buffer.len() {
                let record = &*(buffer.as_ptr().add(offset)
                    as *const SYSTEM_LOGICAL_PROCESSOR_INFORMATION_EX);
                if record.Relationship == RelationProcessorCore {
                    physical += 1;
                }
                if record.Size == 0 {
                    break; // malformed record -- stop rather than loop forever
                }
                offset += record.Size as usize;
            }
            if physical == 0 {
                collect_logical_cores()
            } else {
                Some(physical)
            }
        }
    }

    /// Total system RAM in GB via `GlobalMemoryStatusEx`, rounded to 1
    /// decimal place exactly like hardware.py's `_probe_ram` (hardware.py:
    /// 146-151). `None` when the call fails -- reporting `0.0` printed
    /// "0 GB" of memory on screen as a finding.
    pub fn collect_ram_gb() -> Option<f64> {
        use windows_sys::Win32::System::SystemInformation::{GlobalMemoryStatusEx, MEMORYSTATUSEX};

        unsafe {
            let mut status: MEMORYSTATUSEX = std::mem::zeroed();
            status.dwLength = std::mem::size_of::<MEMORYSTATUSEX>() as u32;
            if GlobalMemoryStatusEx(&mut status) == 0 || status.ullTotalPhys == 0 {
                return None;
            }
            Some(round1(status.ullTotalPhys as f64 / 1024f64.powi(3)))
        }
    }

    /// Free BYTES available to the calling user on the filesystem hosting
    /// `target_dir`, via `GetDiskFreeSpaceExW`'s
    /// `lpFreeBytesAvailableToCaller` -- the quota-aware figure, which is
    /// what actually governs whether this non-elevated process can write the
    /// payload.
    ///
    /// `None` when the call fails (an unreachable/nonexistent volume, a
    /// revoked mount). G011.1: this used to return `0`, and `0` is not
    /// "unknown" downstream -- `diskSpaceCheck` reads it as a completely full
    /// drive and blocks the install with "free up space" on a machine whose
    /// free space was never actually read.
    pub fn collect_free_disk_bytes(target_dir: &Path) -> Option<u64> {
        use windows_sys::Win32::Storage::FileSystem::GetDiskFreeSpaceExW;

        let wide: Vec<u16> = target_dir
            .as_os_str()
            .encode_wide()
            .chain(std::iter::once(0))
            .collect();
        unsafe {
            let mut free_available: u64 = 0;
            let mut total_bytes: u64 = 0;
            let mut total_free: u64 = 0;
            let ok = GetDiskFreeSpaceExW(
                wide.as_ptr(),
                &mut free_available,
                &mut total_bytes,
                &mut total_free,
            );
            if ok == 0 {
                return None;
            }
            Some(free_available)
        }
    }

    /// Every DXGI adapter with nonzero dedicated VRAM, skipping the
    /// software/WARP "Microsoft Basic Render Driver" adapter (it is not real
    /// hardware -- `DXGI_ADAPTER_FLAG_SOFTWARE` is how DXGI marks it).
    /// `CreateDXGIFactory1`/`EnumAdapters1` need no prior COM initialization
    /// (they are plain `dxgi.dll` exports, not `CoCreateInstance`-activated),
    /// so this is a self-contained collector with no ordering dependency on
    /// anything else in the process.
    /// `None` when the DXGI factory itself could not be created (a
    /// stripped-down sandbox/CI image with no display driver) -- that is "the
    /// graphics probe could not run", which is a different fact from
    /// `Some(vec![])`, "the probe ran and there is no adapter with dedicated
    /// VRAM". Collapsing the two let the screen tell a machine with a GPU
    /// that it had no dedicated graphics card.
    pub fn collect_gpus() -> Option<Vec<GpuFacts>> {
        use windows::Win32::Graphics::Dxgi::{
            CreateDXGIFactory1, IDXGIFactory1, DXGI_ADAPTER_FLAG_SOFTWARE,
        };

        let factory: windows::core::Result<IDXGIFactory1> = unsafe { CreateDXGIFactory1() };
        let Ok(factory) = factory else {
            return None;
        };

        let mut gpus = Vec::new();
        // F-05 (newcomer walkthrough): a machine with no discrete GPU at all
        // showed "NVIDIA GeForce RTX 5070 Ti (16 GB)" listed three times on
        // the "Checking This Computer" screen. `AdapterLuid` is the stable
        // per-boot-session identity DXGI itself uses to mean "this is the
        // same adapter object" (MSDN: "The locally unique identifier (LUID)
        // ... is only unique until the OS is restarted"); a virtualized or
        // projected adapter -- GPU-PV, the mechanism Windows Sandbox and
        // similar hosts use to hand a host GPU to a guest, is exactly the
        // kind of environment a newcomer walkthrough runs in -- can hand
        // `EnumAdapters1` the same LUID more than once. Tracking seen LUIDs
        // here stops a duplicate from ever entering `hardware.gpus`, so
        // every downstream consumer (this screen's Graphics line AND the
        // caption-tier recommendation) sees one entry per real adapter.
        let mut seen_luids: Vec<i64> = Vec::new();
        let mut index = 0u32;
        loop {
            let adapter = unsafe { factory.EnumAdapters1(index) };
            index += 1;
            let adapter = match adapter {
                Ok(adapter) => adapter,
                Err(_) => break, // DXGI_ERROR_NOT_FOUND: enumeration exhausted
            };
            let desc = match unsafe { adapter.GetDesc1() } {
                Ok(desc) => desc,
                Err(_) => continue,
            };
            if (desc.Flags as i32 & DXGI_ADAPTER_FLAG_SOFTWARE.0) != 0 {
                continue;
            }
            if desc.DedicatedVideoMemory == 0 {
                continue;
            }
            let luid = ((desc.AdapterLuid.HighPart as i64) << 32) | (desc.AdapterLuid.LowPart as i64);
            if seen_luids.contains(&luid) {
                continue;
            }
            seen_luids.push(luid);
            let nul_at = desc
                .Description
                .iter()
                .position(|&unit| unit == 0)
                .unwrap_or(desc.Description.len());
            let name = String::from_utf16_lossy(&desc.Description[..nul_at]);
            gpus.push(GpuFacts {
                name,
                dedicated_vram_mb: (desc.DedicatedVideoMemory as u64) / (1024 * 1024),
                vendor: vendor_name_for_pci_id(desc.VendorId),
            });
        }
        Some(gpus)
    }

    /// The drive the native product installs onto (perMachine, D1) --
    /// `%ProgramFiles%`, falling back to `C:\` if that variable is somehow
    /// unset.
    pub fn install_target_dir() -> std::path::PathBuf {
        std::env::var_os("ProgramFiles")
            .map(std::path::PathBuf::from)
            .unwrap_or_else(|| std::path::PathBuf::from(r"C:\"))
    }
}

/// Collect the full native hardware inventory. Real Win32/DXGI calls on
/// Windows; a placeholder (zeroed, floor-tier) result on any other target so
/// the crate still compiles (and `cargo check`/`cargo test` still run) on a
/// non-Windows dev machine or CI runner -- this installer only ever ships
/// for Windows.
pub fn collect_hardware_inventory() -> HardwareInventory {
    #[cfg(target_os = "windows")]
    {
        let gpus = windows_collectors::collect_gpus();
        // An unavailable GPU probe contributes no GPUs to the tier decision,
        // which lands on the conservative floor tier -- the same outcome as a
        // machine with no NVIDIA GPU, and the honest one when nothing is
        // known. `gpus: None` still travels to the frontend so the SCREEN can
        // distinguish the two.
        let facts = HardwareFacts {
            gpus: gpus.clone().unwrap_or_default(),
        };
        let install_target = windows_collectors::install_target_dir();
        HardwareInventory {
            cpu_model: windows_collectors::collect_cpu_model(),
            physical_cores: windows_collectors::collect_physical_cores(),
            logical_cores: windows_collectors::collect_logical_cores(),
            ram_gb: windows_collectors::collect_ram_gb(),
            gpus,
            free_disk_bytes: windows_collectors::collect_free_disk_bytes(&install_target),
            install_target: Some(install_target.display().to_string()),
            recommended_caption_tier: recommend_caption_tier(&facts).to_string(),
            hardware_capable_caption_tier: hardware_capable_caption_tier(&facts).to_string(),
        }
    }
    #[cfg(not(target_os = "windows"))]
    {
        // Nothing was measured on this platform, so nothing is reported.
        HardwareInventory {
            cpu_model: None,
            physical_cores: None,
            logical_cores: None,
            ram_gb: None,
            gpus: None,
            free_disk_bytes: None,
            install_target: None,
            recommended_caption_tier: FLOOR_TIER_ID.to_string(),
            hardware_capable_caption_tier: FLOOR_TIER_ID.to_string(),
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn gpu(name: &str, vendor: &str, vram_mb: u64) -> GpuFacts {
        GpuFacts {
            name: name.to_string(),
            dedicated_vram_mb: vram_mb,
            vendor: vendor.to_string(),
        }
    }

    // ---- table-driven recommendation logic: pure, no hardware needed ----

    #[test]
    fn recommend_caption_tier_no_gpu_is_floor() {
        let facts = HardwareFacts { gpus: vec![] };
        assert_eq!(recommend_caption_tier(&facts), "floor");
    }

    #[test]
    fn recommend_caption_tier_nvidia_under_8gb_is_floor() {
        let facts = HardwareFacts {
            gpus: vec![gpu("GeForce GTX 1650", "NVIDIA", 4096)],
        };
        assert_eq!(recommend_caption_tier(&facts), "floor");
    }

    #[test]
    fn hardware_capable_caption_tier_nvidia_exactly_8gb_is_large_v3() {
        // hardware.py: `< 8` is tier-0, so exactly 8 is NOT tier-0.
        let facts = HardwareFacts {
            gpus: vec![gpu("GeForce RTX 3070", "NVIDIA", 8192)],
        };
        assert_eq!(hardware_capable_caption_tier(&facts), "large-v3");
    }

    #[test]
    fn hardware_capable_caption_tier_nvidia_16gb_is_large_v3() {
        let facts = HardwareFacts {
            gpus: vec![gpu("GeForce RTX 4080", "NVIDIA", 16384)],
        };
        assert_eq!(hardware_capable_caption_tier(&facts), "large-v3");
    }

    #[test]
    fn hardware_capable_caption_tier_nvidia_24gb_is_large_v3() {
        let facts = HardwareFacts {
            gpus: vec![gpu("RTX 4090", "NVIDIA", 24576)],
        };
        assert_eq!(hardware_capable_caption_tier(&facts), "large-v3");
    }

    /// DELIBERATE update, 2026-08-15 (this test's own prior message demanded
    /// it): `captions_large` was enrolled in the production acquisition
    /// catalog by owner ruling ("the user should get the better caption
    /// model if the hardware supports it"), so the capability verdict and
    /// the recommendation now agree on a large-v3-capable box. The clamp in
    /// `recommend_caption_tier` stays: were the tier ever un-enrolled again,
    /// the recommendation would honestly drop back to the floor tier.
    #[test]
    fn a_large_v3_capable_box_is_recommended_large_v3_now_that_it_is_obtainable() {
        let facts = HardwareFacts {
            gpus: vec![gpu("RTX 4090", "NVIDIA", 24576)],
        };
        assert_eq!(hardware_capable_caption_tier(&facts), LARGE_V3_TIER_ID);
        assert!(
            caption_tier_is_obtainable(LARGE_V3_TIER_ID),
            "captions_large is enrolled in PRODUCTION_CATALOG_IDS (2026-08-15 \
             owner ruling); if it is deliberately un-enrolled, restore this \
             test's previous floor-clamp form -- do not just flip assertions"
        );
        assert_eq!(recommend_caption_tier(&facts), LARGE_V3_TIER_ID);
    }

    #[test]
    fn the_floor_tier_is_always_obtainable() {
        assert!(caption_tier_is_obtainable(FLOOR_TIER_ID));
        assert_eq!(caption_component_id_for_tier(FLOOR_TIER_ID), "captions_medium");
        assert_eq!(caption_component_id_for_tier(LARGE_V3_TIER_ID), "captions_large");
    }

    #[test]
    fn recommend_caption_tier_amd_only_capable_gpu_is_still_floor() {
        // The documented divergence: hardware.py never sees a non-NVIDIA
        // GPU at all (NVML-only), so it always lands on tier-0/floor here,
        // regardless of the AMD card's actual VRAM.
        let facts = HardwareFacts {
            gpus: vec![gpu("Radeon RX 7900 XTX", "AMD", 24576)],
        };
        assert_eq!(recommend_caption_tier(&facts), "floor");
    }

    #[test]
    fn recommend_caption_tier_intel_only_capable_gpu_is_still_floor() {
        let facts = HardwareFacts {
            gpus: vec![gpu("Arc A770", "Intel", 16384)],
        };
        assert_eq!(recommend_caption_tier(&facts), "floor");
    }

    #[test]
    fn hardware_capable_caption_tier_picks_the_highest_vram_nvidia_gpu_when_several_present() {
        let facts = HardwareFacts {
            gpus: vec![
                gpu("GeForce GTX 1650", "NVIDIA", 4096),
                gpu("RTX 4090", "NVIDIA", 24576),
            ],
        };
        assert_eq!(hardware_capable_caption_tier(&facts), "large-v3");
    }

    #[test]
    fn recommend_caption_tier_ignores_non_nvidia_when_an_nvidia_gpu_also_present() {
        let facts = HardwareFacts {
            gpus: vec![
                gpu("Radeon RX 7900 XTX", "AMD", 24576),
                gpu("GeForce GTX 1650", "NVIDIA", 4096),
            ],
        };
        // The AMD card would qualify for large-v3 on VRAM alone, but only
        // the (small) NVIDIA card counts -- matches hardware.py, which would
        // never see the AMD card in the first place.
        assert_eq!(recommend_caption_tier(&facts), "floor");
    }

    #[test]
    fn deployment_tier_boundaries_match_hardware_py_exactly() {
        assert_eq!(
            deployment_tier_for_nvidia_vram_gb(None),
            DeploymentTier::Tier0
        );
        assert_eq!(
            deployment_tier_for_nvidia_vram_gb(Some(7.9)),
            DeploymentTier::Tier0
        );
        assert_eq!(
            deployment_tier_for_nvidia_vram_gb(Some(8.0)),
            DeploymentTier::Tier1
        );
        assert_eq!(
            deployment_tier_for_nvidia_vram_gb(Some(15.9)),
            DeploymentTier::Tier1
        );
        assert_eq!(
            deployment_tier_for_nvidia_vram_gb(Some(16.0)),
            DeploymentTier::Tier1Plus
        );
        assert_eq!(
            deployment_tier_for_nvidia_vram_gb(Some(23.9)),
            DeploymentTier::Tier1Plus
        );
        assert_eq!(
            deployment_tier_for_nvidia_vram_gb(Some(24.0)),
            DeploymentTier::Tier2
        );
        assert_eq!(
            deployment_tier_for_nvidia_vram_gb(Some(48.0)),
            DeploymentTier::Tier2
        );
    }

    #[test]
    fn vendor_name_for_pci_id_classifies_the_known_vendors() {
        assert_eq!(vendor_name_for_pci_id(0x10DE), "NVIDIA");
        assert_eq!(vendor_name_for_pci_id(0x1002), "AMD");
        assert_eq!(vendor_name_for_pci_id(0x1022), "AMD");
        assert_eq!(vendor_name_for_pci_id(0x8086), "Intel");
        assert_eq!(vendor_name_for_pci_id(0x1234), "Unknown (0x1234)");
    }

    #[test]
    fn round1_matches_pythons_round_to_one_decimal() {
        assert_eq!(round1(8.04), 8.0);
        assert_eq!(round1(7.96), 8.0);
        assert_eq!(round1(7.94), 7.9);
    }

    // ---- collector smoke tests: real Win32/DXGI calls on THIS box ----

    #[cfg(target_os = "windows")]
    #[test]
    fn collect_hardware_inventory_returns_plausible_facts_on_this_machine() {
        let inventory = collect_hardware_inventory();

        let cpu_model = inventory
            .cpu_model
            .expect("expected a real CPU brand string on this Windows machine");
        assert!(!cpu_model.trim().is_empty());
        let physical = inventory.physical_cores.expect("physical cores");
        let logical = inventory.logical_cores.expect("logical cores");
        assert!(physical >= 1);
        assert!(logical >= physical);
        assert!(inventory.ram_gb.expect("ram") > 0.0);
        assert!(inventory.free_disk_bytes.expect("free disk") > 0);
        assert!(inventory.install_target.is_some());
        // The recommendation must be one of the two real caption tier ids --
        // never an arbitrary string -- regardless of what GPU (if any) this
        // particular test machine has, AND must be obtainable.
        assert!(
            inventory.recommended_caption_tier == "floor"
                || inventory.recommended_caption_tier == "large-v3"
        );
        assert!(caption_tier_is_obtainable(&inventory.recommended_caption_tier));
        // `Some(vec![])` is an explicitly OK outcome (no dedicated GPU); so is
        // `None` (no DXGI factory in a headless/sandboxed image). This
        // assertion just proves the collector ran without panicking and
        // produced a well-formed result either way.
        for gpu in inventory.gpus.iter().flatten() {
            assert!(!gpu.name.trim().is_empty());
            assert!(gpu.dedicated_vram_mb > 0);
            assert!(!gpu.vendor.trim().is_empty());
        }
    }

    #[cfg(target_os = "windows")]
    #[test]
    fn collect_physical_cores_is_plausible_on_this_machine() {
        let physical = windows_collectors::collect_physical_cores().expect("physical cores");
        let logical = windows_collectors::collect_logical_cores().expect("logical cores");
        assert!(physical >= 1);
        assert!(logical >= physical);
    }

    #[cfg(target_os = "windows")]
    #[test]
    fn collect_ram_gb_is_plausible_on_this_machine() {
        // Any real Windows machine running this test has well over 1GB of
        // RAM; this is a floor, not a tight bound.
        assert!(windows_collectors::collect_ram_gb().expect("ram") > 1.0);
    }

    #[cfg(target_os = "windows")]
    #[test]
    fn collect_free_disk_bytes_is_plausible_for_the_install_target_drive() {
        let target = windows_collectors::install_target_dir();
        let free = windows_collectors::collect_free_disk_bytes(&target).expect("free bytes");
        // Bytes, not rounded GB: a real volume with any headroom at all
        // reports far more than a gigabyte's worth of bytes.
        assert!(free > 1024 * 1024);
    }

    /// G011.1. A failed `GetDiskFreeSpaceExW` returned `0`, and `0` is not
    /// "unknown" to anything downstream -- `diskSpaceCheck` reads it as a
    /// completely full drive and blocks first run outright. A probe that
    /// cannot get a value must say so, never pick a number.
    #[cfg(target_os = "windows")]
    #[test]
    fn a_free_disk_probe_that_fails_reports_unavailable_never_a_fabricated_zero() {
        let unreadable = std::path::Path::new(r"Z:\civiccast-no-such-volume-g011");
        assert_eq!(
            windows_collectors::collect_free_disk_bytes(unreadable),
            None,
            "a failed GetDiskFreeSpaceExW must be reported as unavailable, never \
             as 0 free bytes -- the disk guard reads 0 as a full drive and blocks \
             the install"
        );
    }

    /// G011.1. `recommend_caption_tier` named `large-v3` on any >=8GB NVIDIA
    /// box, but `acquisition_catalog::production_catalog` has no
    /// `captions_large` component at all, so the frontend selected a row the
    /// backend can never deliver and the download screen never completed.
    #[test]
    fn the_recommended_caption_tier_is_always_one_the_production_catalog_can_deliver() {
        for facts in [
            HardwareFacts { gpus: vec![] },
            HardwareFacts {
                gpus: vec![gpu("RTX 4090", "NVIDIA", 24576)],
            },
            HardwareFacts {
                gpus: vec![gpu("Radeon RX 7900 XTX", "AMD", 24576)],
            },
        ] {
            let recommended = recommend_caption_tier(&facts);
            let component = caption_component_id_for_tier(recommended);
            assert!(
                crate::acquisition_catalog::PRODUCTION_CATALOG_IDS.contains(&component),
                "recommended tier {recommended:?} maps to catalog component \
                 {component:?}, which production_catalog never delivers"
            );
        }
    }

    #[cfg(target_os = "windows")]
    #[test]
    fn collect_gpus_produces_well_formed_entries_or_an_explicit_empty_list() {
        // Real DXGI call, no mocks -- `Some(vec![])` is an explicitly OK
        // outcome (documented in the module doc comment) for a machine/CI
        // runner with no dedicated GPU, and `None` for one with no DXGI
        // factory at all.
        for gpu in windows_collectors::collect_gpus().iter().flatten() {
            assert!(!gpu.name.trim().is_empty());
            assert!(gpu.dedicated_vram_mb > 0);
        }
    }
}
