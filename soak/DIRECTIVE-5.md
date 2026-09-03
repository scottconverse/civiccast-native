# DIRECTIVE 5 — soak72-9573d4a: report install status now

Trigger: START NOW

Ack (soak/ACK-5.md), then within 10 minutes commit and push `soak/STATUS-1.md` to your branch containing, verbatim:

```
$dst='C:\CivicCastSoak\kit'
"== kit verify"; $bad=0; Get-Content "$dst\SHA256SUMS.txt" | ForEach-Object { $h,$p = $_ -split '\s+',2; $f=Join-Path $dst ($p -replace '/','\'); if(-not (Test-Path $f) -or ((Get-FileHash $f -Algorithm SHA256).Hash.ToLower() -ne $h)){ "BAD $p"; $bad++ } }; "bad=$bad"
"== installer file"; Get-Item "$dst\CivicCast (Native)_1.0.0-beta.3_x64-setup.exe" -ErrorAction SilentlyContinue | Select-Object Length, LastWriteTime
"== install-progress.log (tail)"; Get-Content C:\ProgramData\CivicCast\install-progress.log -Tail 40 -ErrorAction SilentlyContinue
"== station-set.json"; Get-Content C:\CivicCastHostStore\install\station-set.json -ErrorAction SilentlyContinue
"== service"; Get-Service CivicCastSupervisor -ErrorAction SilentlyContinue | Select-Object Status, StartType
"== health"; try { Invoke-RestMethod http://127.0.0.1:8000/health -TimeoutSec 10 | ConvertTo-Json -Depth 4 } catch { $_.Exception.Message }
"== what I am doing right now and what is blocking me (one paragraph, plain words)"
```
If the silent install has NOT been started yet, start it right after committing STATUS-1.md (DIRECTIVE-2 step 4:
`Start-Process $exe -ArgumentList '/S /D=C:\CivicCastHostStore\install' -PassThru -Wait -Verb RunAs`), then commit
`soak/STATUS-2.md` with the installer exit code and the same log tail when it finishes. If it is running, wait for it
and then commit STATUS-2.md. Never wait for a human.
