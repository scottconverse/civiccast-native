seen=/c/Users/scott/Documents/Codex/2026-09-16/re/civiccast-ds-oversight/bin/monitors/station-seen.txt
touch $seen; first=1; end=$((SECONDS+1740))
while [ $SECONDS -lt $end ]; do
  out=$(powershell.exe -NoProfile -ExecutionPolicy Bypass -File "C:/Users/scott/Documents/Codex/2026-09-16/re/civiccast-ds-oversight/bin/trial-events.ps1" 2>&1 | tr -d '\r' | grep -v '^$' | grep -v '^\[h264 @' | grep -Ev 'Conform-cache warm failed|issued a seamless plan rollover|content-reload accepted|preparation for .* took|Caption tap discarded|Caption tap is behind|reload is still settling|Caption feed scan failed|tap_batch_diagnostic|Caption tap overload|Caption tap catch-up' | grep -E 'worker exited|ERROR|CRITICAL|PROBLEM|past due|relay child')
  new=""
  while IFS= read -r line; do
    [ -z "$line" ] && continue
    k=$(echo "$line" | sed -E 's/PROBLEM [0-9:]+:/PROBLEM/; s/age +[0-9]+s//g; s/a-v [-0-9.]+s//g; s/vtt [0-9]+B//g')
    case "$line" in PROBLEM*) k="$k $(date +%H%M | cut -c1-3)";; esac
    if ! grep -qxF "$k" $seen; then echo "$k" >> $seen; new="$new$line"$'\n'; fi
  done <<< "$out"
  if [ -n "$first" ]; then first=""; elif [ -n "$new" ]; then printf '%s' "$new" | head -8; fi
  sleep 30
done
