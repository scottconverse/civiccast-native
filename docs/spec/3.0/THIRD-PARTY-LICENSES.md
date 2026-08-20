# THIRD-PARTY-LICENSES — CivicCast 3.0

> CivicCast core is **Apache-2.0**. This manifest (from the pre-build licensing audit, 2026-06-14)
> records every third-party component and how an Apache-2.0 product may use it. **No GPLv3 anywhere;
> the core stays Apache-2.0-distributable.** At ship, this becomes the repo `NOTICE` /
> `THIRD-PARTY-LICENSES`, with each linked dependency's full license text bundled.

## Linked (LGPL / MPL / permissive — redistributable with CivicCast)
| Component | License | How used |
|---|---|---|
| GStreamer core + plugins-base/good/bad | LGPL-2.1+ | Dynamically loaded via PyGObject (external shared libs; end-user can relink) — LGPL-compliant for an Apache product |
| gst-plugins-rs (`ndisink`/`srtsink`/`hlssink3`) | MPL-2.0 | File-level copyleft; Apache-compatible (disclose modified MPL files only) |
| libcaption | MIT | Linked (CEA-608/708) |
| faster-whisper / whisper.cpp | MIT / Apache-2.0 | Linked (ASR/captions) |
| Gemma 4 (via Ollama) | Apache-2.0 | Model runtime (verified 2026-06-13) |
| TSDuck | LGPL-2.0+ | BYO binary, invoked as a separate process (compliance verify) |
| FFmpeg (`ffprobe` ingest) | LGPL build | Read-only metadata inspect; no encode |

## Runtime plugins — NOT bundled or redistributed by CivicCast
| Component | License | Posture |
|---|---|---|
| `x264enc` (software H.264) | GPL-2.0 | Loaded **only** as a GStreamer runtime plugin if the operator provides it — never compiled into or shipped by CivicCast (same posture as OBS / VLC / Jellyfin). Recommend hardware encoders or openh264 instead. |
| gst-plugins-ugly | GPL-2.0 | **NOT used.** |

## Proprietary runtime SDKs — BYO-install, never redistributed
| Component | License | Posture |
|---|---|---|
| Blackmagic Desktop Video SDK (DeckLink/SDI) | Proprietary EULA | Operator downloads + installs; commissioning prompts, `doctor` detects. **(Open question for Scott: confirm commercial-product redistribution terms with Blackmagic.)** |
| NDI SDK / Runtime | Proprietary (free) | Operator installs NDI Tools; "NDI®" attribution required. |

## Codec patent caveat (H.264/AVC · HEVC/H.265 · AAC)
Encoding **and distributing** patented codecs may incur MPEG-LA / Via-LA / Access-Advance licensing.
**This is the deploying station's liability, not CivicCast's** — identical to how OBS, Jellyfin, and
FFmpeg operate. CivicCast's responsibility is good defaults + transparency:
- **Default to hardware encoders** (NVENC / VA-API / QSV) — the GPU vendor's licensing covers the codec royalty; **zero direct exposure**.
- **openh264** (Cisco patent-shield binary) as the clean software fallback.
- **Royalty-free codecs** (VP9 / AV1 / Opus) offered for stations wanting zero exposure.
- For **cable**, the operator is the distributor (carries MPEG-LA); for **YouTube/Internet Archive**, those platforms carry their own licensing.
- Operator doc/commissioning note: *"If you encode H.264 commercially using the x264 software encoder, verify codec licensing with your organization. Hardware encoders and openh264 avoid this."*

## Verdict (audit)
Apache-2.0 posture **holds**; no license forces the core to GPL; the only real exposure is codec
patents, which is the station's liability and is mitigated by the defaults above.
