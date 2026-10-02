# Emits: slate entries, past-due rollovers, and preparations > 30 s, from control_plane-app.log (shared-read, new bytes only)
end=$((SECONDS+1740)); ps=/c/Users/scott/Documents/Codex/2026-09-16/re/civiccast-ds-oversight/bin/monitors/sched-read.ps1
cat > $ps <<'PS'
param([long]$From)
$fs=[IO.File]::Open('C:\ProgramData\CivicCast\logs\control_plane-app.log','Open','Read','ReadWrite')
if ($From -le 0 -or $From -gt $fs.Length) { $From = $fs.Length }
$fs.Seek($From,'Begin')|Out-Null; $t=(New-Object IO.StreamReader($fs)).ReadToEnd(); $len=$fs.Length; $fs.Dispose()
"POS $len"
($t -split "`n") | Where-Object { $_ -match 'past due|preparation for .* took [0-9]{2,}\.|worker exited' -or ($_ -match 'FALLBACK_SLATE' -and $_ -match 'egress state') } | ForEach-Object { $_.Substring(0,[Math]::Min(230,$_.Length)).TrimEnd() }
PS
pos=0; declare -A slate
while [ $SECONDS -lt $end ]; do
  out=$(powershell.exe -NoProfile -ExecutionPolicy Bypass -File "$(cygpath -w $ps)" -From $pos 2>&1 | tr -d '\r')
  pos=$(echo "$out" | sed -n 's/^POS //p'); pos=${pos:-0}
  echo "$out" | grep -v '^POS ' | while IFS= read -r l; do
    [ -z "$l" ] && continue
    if echo "$l" | grep -q FALLBACK_SLATE; then ch=$(echo "$l" | sed -E 's/.*channel ([a-z]+):.*/\1/'); f=/tmp/slate-$ch; if [ ! -f $f ] || [ $(( $(date +%s) - $(stat -c %Y $f) )) -gt 120 ]; then echo "SLATE ON AIR $ch: $l"; fi; touch $f
    else echo "$l"; fi
  done
  sleep 20
done; exit 0
