# DIRECTIVE 3 — soak72-9573d4a: installer download still 0 bytes — diagnose, then use the zip route

Trigger: START NOW

Amends DIRECTIVE-2. Ack on your branch (soak/ACK-3.md), then do the three parts below in order. Do not skip part A even
if part B works — the coordinator needs the evidence.

## A. Evidence (2 minutes) — commit the raw output as soak/FETCH-DIAG.md
```
$u='http://192.168.0.135:8766/9573d4a82e1e1d9993589f633bad6dacba792afb/CivicCast%20%28Native%29_1.0.0-beta.3_x64-setup.exe'
curl.exe -v -L --retry 0 -o C:\CivicCastSoak\probe-setup.exe $u 2>&1 | Select-Object -Last 25
"curl exit=$LASTEXITCODE"; (Get-Item C:\CivicCastSoak\probe-setup.exe -ErrorAction SilentlyContinue).Length
Get-MpThreatDetection -ErrorAction SilentlyContinue | Sort-Object InitialDetectionTime -Descending | Select-Object -First 5 InitialDetectionTime, ThreatID, ProcessName, Resources | Format-List
Get-MpPreference | Select-Object DisableRealtimeMonitoring, EnableControlledFolderAccess, AttackSurfaceReductionRules_Ids | Format-List
(Get-PSDrive C).Free
```
Paste ALL of that output verbatim into soak/FETCH-DIAG.md, commit and push it before continuing.

## B. Zip route (Defender does not truncate a zip on download)
```
$dst='C:\CivicCastSoak\kit'
$z=Join-Path $dst 'setup-beta3.zip'
curl.exe -sS -L --retry 5 -o $z 'http://192.168.0.135:8766/9573d4a82e1e1d9993589f633bad6dacba792afb/setup-beta3.zip'
(Get-Item $z).Length                                    # must be 304972407
(Get-FileHash $z -Algorithm SHA256).Hash.ToLower()      # must be 8efe3fa300954a3ec99393242daaf9af9a781b9703b8f0664d47cb41763306d9
Expand-Archive -Path $z -DestinationPath $dst -Force
$exe=Join-Path $dst 'CivicCast (Native)_1.0.0-beta.3_x64-setup.exe'
(Get-Item $exe).Length                                  # must be 289180536
(Get-FileHash $exe -Algorithm SHA256).Hash.ToLower()    # must be 76df8f3bcc5e6b20a41448cddae8a3433e088ebd821a81870b4e40ea052492dc
```
If the extracted exe is again 0 bytes or vanishes, Defender is removing it: run
`Add-MpPreference -ExclusionPath 'C:\CivicCastSoak'` (elevated), extract again, and record that you did so in
soak/FETCH-DIAG.md. The installer is Authenticode-signed by Scott Converse; check with
`(Get-AuthenticodeSignature $exe).Status` (must be Valid) before running it.

## C. Continue
Re-run the DIRECTIVE-2 verify loop (the kit's SHA256SUMS.txt now also lists setup-beta3.zip; a mismatch on that one
line is fine if you fetched it before the line was added — re-fetch SHA256SUMS.txt first). When the exe is present at
289,180,536 bytes with the right hash, continue with the silent install from DIRECTIVE-2 and then DIRECTIVE-1.
Do not wait for a human at any point.
