# DIRECTIVE 2 — soak72-9573d4a: fix the zero-byte installer, then continue DIRECTIVE-1

Trigger: START NOW

This directive AMENDS DIRECTIVE-1. Everything in DIRECTIVE-1 still applies; this file only fixes the kit-fetch step
and adds four standing rules. Acknowledge it on your branch (soak/ACK-2.md), then act.

## What happened
Your download of the installer produced a ZERO-BYTE file. The server side is verified good: the installer at
  http://192.168.0.135:8766/9573d4a82e1e1d9993589f633bad6dacba792afb/CivicCast%20%28Native%29_1.0.0-beta.3_x64-setup.exe
is 289,180,536 bytes with SHA-256 76df8f3bcc5e6b20a41448cddae8a3433e088ebd821a81870b4e40ea052492dc (pulled and checked from
HALO at 2026-09-03 05:05Z). The listing-walk download saves files under the URL-ENCODED name or aborts on names with
spaces/parentheses. Do NOT look for the kit anywhere else (GitHub has no beta.3 assets; there is no other server).

## Do this now (PowerShell 5.1, exactly)
```
$dst='C:\CivicCastSoak\kit'
$base='http://192.168.0.135:8766/9573d4a82e1e1d9993589f633bad6dacba792afb/'
# 1) delete any zero-byte or wrongly-named leftovers
Get-ChildItem $dst -Recurse -File | Where-Object { $_.Length -eq 0 -or $_.Name -match '%' } | Remove-Item -Force
# 2) fetch every file named in SHA256SUMS.txt with curl, decoded local name, encoded URL
curl.exe -sS -L -o "$dst\SHA256SUMS.txt" ($base + 'SHA256SUMS.txt')
Get-Content "$dst\SHA256SUMS.txt" | ForEach-Object {
  $h,$rel = $_ -split '\s+',2
  $local = Join-Path $dst ($rel -replace '/','\')
  New-Item -Force -ItemType Directory (Split-Path $local) | Out-Null
  $url = $base + (($rel -split '/') | ForEach-Object { [uri]::EscapeDataString($_) }) -join '/'
  if (-not (Test-Path $local) -or (Get-Item $local).Length -eq 0 -or ((Get-FileHash $local -Algorithm SHA256).Hash.ToLower() -ne $h)) {
    "fetching $rel"; curl.exe -sS -L --retry 5 --retry-delay 5 -o $local $url
  }
}
# 3) verify (must print bad=0; if not, run step 2 again — it only re-fetches the bad ones)
$bad=0; Get-Content "$dst\SHA256SUMS.txt" | ForEach-Object { $h,$p = $_ -split '\s+',2; $f=Join-Path $dst ($p -replace '/','\')
  if(-not (Test-Path $f) -or ((Get-FileHash $f -Algorithm SHA256).Hash.ToLower() -ne $h)){ "BAD $p"; $bad++ } }; "bad=$bad"
```
When bad=0, continue with DIRECTIVE-1 section 3 (install). The install is SILENT — no screen clicking is needed:
```
$exe="$dst\CivicCast (Native)_1.0.0-beta.3_x64-setup.exe"; Unblock-File $exe
$p=Start-Process -FilePath $exe -ArgumentList '/S /D=C:\CivicCastHostStore\install' -PassThru -Wait -Verb RunAs; "installer exit=$($p.ExitCode)"
```
(`-Verb RunAs` asks for elevation; if your shell is already elevated it just runs.) Expect exit 0, then poll
`Invoke-RestMethod http://127.0.0.1:8000/health` every 30 s (up to 20 min) until `status` is `healthy` AND
`schema` is `current`. The `station\` folder beside the exe makes activation automatic; there is no separate
"CivicCast Installer" window to drive when you install silently with the full kit.

## Standing rules (apply for the rest of the mission)
1. The kit comes ONLY from `http://192.168.0.135:8766/...`. Never look on GitHub, never try other hosts or ports.
   If that URL fails, commit soak/KIT-FETCH-BLOCKED.md with the exact error and keep polling directives.
2. If you do not have a computer-use (screen-clicking) tool, that is fine: every step in this mission can be done
   from the shell. Silent install above; first-admin setup via the API (`POST http://127.0.0.1:8000/api/setup/first-admin`
   is loopback-admitted on first run — read `http://127.0.0.1:8000/openapi.json` for the exact body); channels and
   schedules via the staff API using the token you get back. `sandbox-lab/soak-4h/` in your full clone has the
   heartbeat and egress scripts. If a step truly needs a screen you cannot drive, commit soak/STALLED.md naming the
   exact step and KEEP polling directives — do not invent workarounds.
3. If `git push` asks for a GitHub sign-in and nobody is here: write every ack/heartbeat/report to
   `C:\CivicCastSoak\reports\` with the same file names, retry the push once per hour, and never stop the soak for git.
4. Nobody is watching this machine until Friday morning. Do not wait for a human at any point.

Ack this directive (soak/ACK-2.md), then continue. DIRECTIVE-1 remains the full instruction set.
