param([string]$Out='C:\Users\scott\Documents\Codex\2026-09-16\re\civiccast-ds-oversight\evidence\rung-30m-c17-20261002-030259\recheck')
$Wt='C:\Users\scott\Documents\Codex\2026-09-16\re\civiccast-ds'
New-Item -ItemType Directory -Force $Out | Out-Null
Start-Process -WindowStyle Hidden -FilePath "$Wt\.venv\Scripts\python.exe" -ArgumentList @("`"$Wt\scripts\capture_emitted_hls_audio_proof.py`"",'--hls-root','"C:\ProgramData\CivicCast\data\egress\live-hls"','--out',"`"$Out\loudness-02.json`"",'--duration-seconds','240','--scratch-dir',"`"$env:TEMP\cc-rung-loud2`"") -RedirectStandardOutput "$Out\loudness-02.txt" -RedirectStandardError "$Out\loudness-02.err.txt"
