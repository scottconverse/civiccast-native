# SPDX-License-Identifier: Apache-2.0
# Start 3 detached ffmpeg encoders pointing color-bars + 1 kHz tone at the
# three channels declared in soak-4h/channels.yaml. Each encoder writes a
# .ts capture file for the post-soak tsanalyze sweep and a live UDP MPEG-TS
# egress stream for checkpoint verification.
#
# Required env:
#   $env:RUN_ROOT  - $Root\soak-4h-run (captures land in $RUN_ROOT\captures\)
#   $env:FFMPEG    - path to ffmpeg.exe (default: $env:CIVICCAST_FFMPEG
#                    or "ffmpeg" on PATH)
#
# Spawns 3 detached processes and writes their PIDs to
# $RUN_ROOT\state\encoders.json so the heartbeat + stop scripts can find
# them and prove the intended UDP sinks.

$ErrorActionPreference = "Stop"

if (-not $env:RUN_ROOT) {
    throw "RUN_ROOT must be set (e.g. C:\CivicCastTester\soak-4h-run)"
}
$ffmpeg = $env:FFMPEG
if (-not $ffmpeg) {
    $ffmpeg = (Get-Command ffmpeg -ErrorAction SilentlyContinue).Source
}
if (-not $ffmpeg) {
    throw "ffmpeg not found; set FFMPEG or put it on PATH"
}

# Resolve an H.264 encoder the way the shipped native stream code does
# (civiccast/stream/_ffmpeg.py resolve_h264_encoder + verify_h264_encoder_usable):
# NVENC -> Media Foundation -> OpenH264 -> libx264. `-encoders` only reports
# COMPILE-TIME availability — nvenc-enabled builds list h264_nvenc even with no
# NVIDIA runtime present — so each advertised candidate must also pass a
# one-frame probe encode before it is selected, mirroring the production
# resolver's usability gate. The bundled beta ffmpeg is the LGPL/version3 pack
# build: it has h264_nvenc + libopenh264 but NOT GPL libx264, so a hardcoded
# libx264 fails there. $env:VCODEC overrides the choice for testers who want a
# specific encoder (no probe; trust the operator).
$vcodec = $env:VCODEC
if (-not $vcodec) {
    $encoders = (& $ffmpeg -hide_banner -encoders 2>&1 | Out-String)
    foreach ($cand in @("h264_nvenc", "h264_mf", "libopenh264", "libx264")) {
        if ($encoders -notmatch ("(?m)^\s*[VAS][A-Z.]{5}\s+" + [regex]::Escape($cand) + "\b")) {
            continue
        }
        # Usability probe: encode a single tiny frame to the null muxer. An
        # advertised-but-unusable encoder (e.g. nvenc with no NVIDIA runtime)
        # fails here and we fall through to the next candidate.
        & $ffmpeg -hide_banner -v error -f lavfi -i "color=size=64x64:rate=5,format=yuv420p" `
            -frames:v 1 -c:v $cand -f null - *> $null
        if ($LASTEXITCODE -eq 0) {
            $vcodec = $cand
            break
        }
        Write-Host "encoder $cand advertised but failed the probe encode; trying next"
    }
}
if (-not $vcodec) {
    throw "no usable H.264 encoder found in $ffmpeg (probed h264_nvenc/h264_mf/libopenh264/libx264)"
}
Write-Host "using video encoder: $vcodec"

$captures = Join-Path $env:RUN_ROOT "captures"
$state = Join-Path $env:RUN_ROOT "state"
$logs = Join-Path $env:RUN_ROOT "logs"
$null = New-Item -ItemType Directory -Force -Path $captures, $state, $logs, (Join-Path $captures "public"), (Join-Path $captures "education"), (Join-Path $captures "government")

$encoders = @(
    @{ channel = "public";     udp_port = 9001; out = (Join-Path $captures "public\public.ts");     udp = "udp://127.0.0.1:9001?pkt_size=1316" }
    @{ channel = "education";  udp_port = 9002; out = (Join-Path $captures "education\education.ts");  udp = "udp://127.0.0.1:9002?pkt_size=1316" }
    @{ channel = "government"; udp_port = 9003; out = (Join-Path $captures "government\government.ts"); udp = "udp://127.0.0.1:9003?pkt_size=1316" }
)

$started = @()
foreach ($e in $encoders) {
    # Synthetic source: 1280x720 30 fps color bars + 1 kHz sine. Outputs:
    # MPEG-TS file capture plus UDP egress. The encoder runs at
    # real-time (-re) so 4h of wall clock = 4h of media.
    $args = @(
        "-y", "-hide_banner", "-loglevel", "warning",
        "-f", "lavfi", "-re", "-i", "color=size=1280x720:rate=30:color=#1A1A1A,format=yuv420p",
        "-f", "lavfi", "-re", "-i", "sine=frequency=1000:sample_rate=48000",
        "-map", "0:v:0", "-map", "1:a:0",
        "-c:v", $vcodec, "-b:v", "1500k", "-g", "60",
        "-c:a", "aac", "-b:a", "96k",
        "-f", "mpegts",
        "-fflags", "+genpts",
        "-flush_packets", "1",
        $e.out,
        "-map", "0:v:0", "-map", "1:a:0",
        "-c:v", $vcodec, "-b:v", "1500k", "-g", "60",
        "-c:a", "aac", "-b:a", "96k",
        "-f", "mpegts",
        "-fflags", "+genpts",
        "-flush_packets", "1",
        $e.udp
    )
    Write-Host "starting encoder for $($e.channel) -> $($e.out) + $($e.udp)"
    $proc = Start-Process -FilePath $ffmpeg -ArgumentList $args -PassThru -NoNewWindow `
        -RedirectStandardError (Join-Path $logs "ffmpeg-$($e.channel).log")
    $started += @{ channel = $e.channel; pid = $proc.Id; out = $e.out; udp_port = $e.udp_port; udp = $e.udp }
}

$json = @{ schema = "encoder-state-v1"; encoders = $started } | ConvertTo-Json -Depth 4
Set-Content -Path (Join-Path $state "encoders.json") -Value $json -Encoding utf8
Write-Host "wrote encoder state to $($state)\encoders.json"
