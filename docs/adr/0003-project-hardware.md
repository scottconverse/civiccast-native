# ADR 0003 — Project development hardware and primary deployment OS target

**Status:** Superseded (by ADR-0021, native Windows runtime)
**Date:** 2026-05-08
**Deciders:** Scott Converse (human director)
**Related rung:** Day 0 bootstrap / 0.1 — Foundation
**Related spec section:** §17.2 Tier 1 Streaming reference build, §17.3 Hardware profiles
**Supersedes:** N/A
**Superseded by:** [ADR-0021](0021-native-windows-runtime.md) — the native-Windows program falsified this ADR's 'native benefit is marginal' premise

**Execution addendum (2026-07-29):** The owner-approved native Windows
recovery contract makes CPU-only caption operation mandatory. Hardware
acceleration, including CUDA, is optional and cannot gate installation,
caption generation, or native beta readiness. The GPU-required framing below
is retained as historical context for the 2026-05-08 development-machine
selection; it is not a current native Windows product requirement. ADR 0021
separately supersedes this ADR's rejection of native Windows.

---

## Context

The spec's §17.2 defines a "Tier 1 Streaming" reference build as a commodity Linux machine (Ryzen 7 7700, RTX 4060 8GB, ECC RAM, ZFS storage). That reference was written assuming the typical CivicCast operator is comfortable installing and maintaining Ubuntu Server. Field reality is different: the organizations CivicCast targets — school boards, HOA boards, nonprofit boards, public access TV stations, and community broadcast groups — predominantly run Windows. A Linux-first deployment story creates an adoption barrier for the people most likely to benefit from the platform.

Separately, the project needed a development and validation hardware baseline that covers all rungs of the 0.1→1.0 release ladder, including the AI-intensive rungs (0.5+) that require a CUDA-capable GPU with sufficient VRAM to run Whisper large-v3 and a mid-size local LLM (Gemma or equivalent) concurrently. The spec's reference RTX 4060 (8GB VRAM) is the floor; anything above it is preferable.

The PowerSpec G730 (Ryzen 7 7800X3D, RTX 5070 Ti 16GB GDDR7, 32GB DDR5-6000, 2TB SSD, Windows 11) was evaluated against the five hardware options documented in the Day 0 prompt and exceeds the spec's Tier 1 Streaming reference on both GPU VRAM (16GB vs 8GB) and CPU architecture (3D V-Cache vs standard). At approximately $2,000 it is within budget for almost any community organization.

The deployment OS question resolves directly from the hardware decision: native Windows as a deployment target requires maintaining Windows-specific service management (Windows Services vs systemd), path handling, and a separate installer surface — a sustained maintenance cost with no proportional benefit, since Windows 11 ships WSL2 as a built-in feature that provides a full Ubuntu 24.04 environment. The CivicCast installer can automate WSL2 bootstrap, making the Windows experience a single-file download with one prompted reboot.

## Decision

CivicCast development and reference validation run on the PowerSpec G730 (Windows 11). The primary deployment target for Windows machines is Windows 11 + WSL2 Ubuntu 24.04, with the CivicCast installer automating WSL2 installation and configuration. The codebase is a single Linux-targeted implementation that runs without modification on WSL2, native Linux, and macOS. There is no native Windows (non-WSL2) deployment path.

## Alternatives considered

**Option A — Original spec Linux build (Ryzen 7 7700, RTX 4060 8GB, ~$2,520).** The canonical reference target in §17.2. Correct for operators already running Linux infrastructure. Rejected as the primary development target because it doesn't reflect the Windows-dominant environment of the target audience; rejected as the reference machine because the PowerSpec G730 exceeds its specs at a lower price point.

**Option B — Native Windows deployment (no WSL2).** Would reach Windows users without requiring WSL2. Rejected because it requires a permanently forked code path: Windows-native service management (Windows Services), path separator handling, Windows-specific NATS/PostgreSQL service wrappers, and a separate CI matrix. The maintenance surface grows with every rung and the benefit is marginal given WSL2's ubiquity on Windows 11.

**Option C — Docker-primary on Windows.** Docker Desktop on Windows provides a Linux container runtime. Rejected as the primary path because it requires Docker Desktop (a separate install, license considerations for commercial use, and higher resource overhead than WSL2). Docker remains available as an optional deployment method for operators who prefer it.

**Option D — Apple Silicon (M4 Pro Mac mini, 24GB, ~$1,399).** Comfortable for AI workloads; unified memory architecture maps well to the Whisper + LLM working set. Rejected as primary because macOS is less common than Windows in the target audience, and the 24GB unified memory is below the spec's documented Apple Silicon floor (48GB). Remains a supported secondary target.

**Option E — Cloud GPU for AI rungs only (~$200–400 total).** Develop locally, rent GPU for Sprints 0.5+. Rejected because the G730's RTX 5070 Ti 16GB covers all AI rungs locally, eliminating cloud cost and latency from the development loop.

## Consequences

### Positive

- Single Linux codebase runs on WSL2/Windows, native Linux, and macOS — no OS-specific branching in the application code.
- 16GB GDDR7 VRAM on the RTX 5070 Ti handles Whisper large-v3 + Gemma concurrently with headroom; no rung of the 0.1→1.0 ladder requires external GPU resources.
- Windows installer with automatic WSL2 bootstrap removes the biggest adoption barrier for community organizations: "install Linux" becomes "run this file."
- Development environment (WSL2 Ubuntu 24.04) is identical to the Linux deployment environment; CI (GitHub Actions, Ubuntu runner) matches both.
- The G730's ~$2,000 price point is achievable by a school district AV budget, an HOA reserve fund, or a public access TV station grant.
- Ryzen 7 7800X3D 3D V-Cache improves ffmpeg encoding throughput and ABR ladder generation compared to the spec's reference Ryzen 7 7700.

### Negative

- The spec's §17.2 Tier 1 Streaming reference build section requires a footnote update: the canonical development and validation machine is now the PowerSpec G730 (Windows 11 + WSL2), not the Linux-native build. The Linux-native build remains a supported and documented deployment target.
- Windows installer must implement WSL2 detection, `wsl --install` invocation, reboot handling, and post-reboot resume — additional Sprint 0.1 engineering surface not in the original rung scope.
- One mandatory reboot during first-time Windows installation (WSL2 kernel install requirement, not eliminable).

### Risks

- **RTX 5070 Ti (Blackwell) CUDA compatibility.** The 5000-series architecture is new. CTranslate2 and faster-whisper depend on CUDA 12.x; CUDA 12.x supports Blackwell, but specific builds may need verification at Sprint 0.5 before the AI rungs begin. Mitigation: verify CTranslate2 and faster-whisper wheel compatibility against the installed CUDA driver before Sprint 0.5 begins; treat incompatibility as a Sprint 0.5 blocker if found.
- **WSL2 networking.** The CivicCast web UI runs inside WSL2 but must be reachable from the Windows browser. WSL2 forwards ports automatically on Windows 11 22H2+; older builds may require manual `netsh` rules. Mitigation: `civiccast doctor` checks and reports WSL2 port-forwarding status on Windows; installer documents the Windows build requirement.
- **WSL2 systemd support.** CivicCast services (NATS, PostgreSQL, civiccast-stream) run as systemd units inside WSL2. WSL2 systemd support requires WSL 0.67.6+ and a `[boot] systemd=true` entry in `/etc/wsl.conf`. Mitigation: installer verifies and configures `wsl.conf` automatically.

## Compliance

- The `civiccast doctor` CLI (Sprint 0.1) reports the detected OS, WSL2 version, systemd status, CUDA driver version, and GPU VRAM — catching deployment mismatches at install time.
- The installer test suite (Sprint 0.1) includes a WSL2-detection and bootstrap smoke test.
- CI runs on Ubuntu (GitHub Actions). Any code that would require a non-Linux code path is a violation of this ADR and must be flagged in PR review.
- The spec's §17.2 is updated in Sprint 0.1 with a footnote recording this decision. The original Linux build spec remains as the documented Linux-native deployment path.

## References

- [`docs/spec/spec.md`](../spec/spec.md) Section 17.2 Tier 1 Streaming reference build
- [`docs/spec/spec.md`](../spec/spec.md) Section 17.3 Hardware profiles
- [`docs/spec/release-plan.md`](../spec/release-plan.md) - rung 0.1 Foundation scope, "Architecture decisions baked in"
- CivicCast Day 0 prompt — Phase 2 hardware decision, five-option analysis
- [NATS JetStream on Windows/WSL2](https://docs.nats.io/running-a-nats-service/introduction/installation)
- [NVIDIA CUDA on WSL2](https://docs.nvidia.com/cuda/wsl-user-guide/index.html)
- [WSL2 systemd support](https://devblogs.microsoft.com/commandline/systemd-support-is-now-available-in-wsl/)
- ADR 0001 — NATS JetStream as messaging substrate
- ADR 0002 — faster-whisper as canonical Whisper runtime

---

*ADRs are immutable once Accepted. Reversing or superseding requires a new ADR that references this one. Do not edit the substance of an Accepted ADR — only its Status field and a one-line note pointing to the superseding ADR.*
