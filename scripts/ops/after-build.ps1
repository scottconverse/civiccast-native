# after-build.ps1 -Sha <full sha>
# 1) prune-proof copy: kit-staging\<sha> -> kit-safe\<sha> (robocopy, verified by SHA256SUMS)
# 2) publisher mirror: kit-mirror\<sha> = setup.exe hardlink + QUICKSTART copy + junctions to kit-safe packs/station
param([Parameter(Mandatory)][string]$Sha)
$ErrorActionPreference = 'Stop'
$stg  = "C:\CivicCastTester\kit-staging\$Sha"
$safe = "C:\CivicCastTester\kit-safe\$Sha"
$mir  = "C:\CivicCastTester\kit-mirror\$Sha"
if (-not (Test-Path "$stg\SHA256SUMS.txt")) { throw "no kit at $stg" }

robocopy $stg $safe /E /MT:16 /R:2 /W:5 /NFL /NDL /NJH /NP | Out-Null
if ($LASTEXITCODE -ge 8) { throw "robocopy failed rc=$LASTEXITCODE" }

# verify every manifest line in kit-safe
$bad = 0; $n = 0
foreach ($line in (Get-Content "$safe\SHA256SUMS.txt" | Where-Object { $_.Trim() })) {
  $h, $rel = $line -split '\s+', 2
  if (-not $rel) { continue }
  $f = Join-Path $safe ($rel.Trim().TrimStart('*') -replace '/', '\')
  $n++
  if (-not (Test-Path $f) -or (Get-FileHash $f -Algorithm SHA256).Hash.ToLower() -ne $h.ToLower()) { $bad++; Write-Host "BAD $rel" }
}
Write-Host "kit-safe verify: files=$n bad=$bad"
if ($bad -ne 0) { throw "kit-safe verify failed" }

$exe = Get-ChildItem $safe -Filter '*_x64-setup.exe' | Select-Object -First 1
if (-not $exe) { throw "no installer in $safe" }
New-Item -Force -ItemType Directory $mir | Out-Null
if (Test-Path "$mir\setup.exe") { Remove-Item "$mir\setup.exe" -Force }
cmd /c mklink /H "$mir\setup.exe" "$($exe.FullName)" | Out-Null
Copy-Item "$safe\QUICKSTART-OPERATOR.md" "$mir\QUICKSTART-OPERATOR.md" -Force
foreach ($d in 'packs','station') {
  if (Test-Path "$mir\$d") { cmd /c rmdir "$mir\$d" | Out-Null }
  cmd /c mklink /J "$mir\$d" "$safe\$d" | Out-Null
}
Write-Host "mirror ready: $mir"
cmd /c dir $mir
Write-Host ("setup.exe sha256: " + (Get-FileHash "$mir\setup.exe" -Algorithm SHA256).Hash.ToLower())
