#!/usr/bin/env bash
# build-chain.sh <full main sha>
# 1) dispatch the self-hosted kit build on main; 2) wait for it; 3) add samples + SHA256SUMS to
# kit-staging/<sha>; 4) after-build.ps1 (kit-safe copy+verify, kit-mirror); 5) HEAD-check every
# served URL; 6) print the Gate A run id when it appears. Each step prints one line; exit non-zero on failure.
set -u
SHA="${1:?full main sha}"; SHORT="${SHA:0:7}"
S="/c/Users/scott/AppData/Local/Temp/claude/C--Users-scott-Desktop-Code/9e39825a-17bf-473c-8ada-72211a0f3e03/scratchpad"
cd /c/Users/scott/Desktop/Code/civiccast-native || exit 2
git fetch -q origin main
[ "$(git rev-parse origin/main)" = "$SHA" ] || { echo "CHAIN ABORT: origin/main is $(git rev-parse --short origin/main), not $SHORT"; exit 3; }
gh workflow run native-beta-candidate-artifacts.yml --ref main -f build_target=self-hosted >/dev/null || { echo "CHAIN ABORT: dispatch failed"; exit 4; }
sleep 60
run=$(gh run list --workflow native-beta-candidate-artifacts.yml --limit 3 --json databaseId,headSha,createdAt --jq ".[]|select(.headSha==\"$SHA\")|.databaseId" | head -1)
[ -n "$run" ] || { echo "CHAIN ABORT: no build run found for $SHORT"; exit 5; }
echo "BUILD RUN $run started for $SHORT"
while true; do st=$(gh run view "$run" --json status,conclusion --jq '.status+" "+(.conclusion//"")'); case "$st" in completed*) break;; esac; sleep 120; done
echo "BUILD $run => $st"
case "$st" in *success*) ;; *) exit 6;; esac
K="/c/CivicCastTester/kit-staging/$SHA"
[ -f "$K/CivicCast (Native)_1.0.0-beta.5_x64-setup.exe" ] || ls "$K"/*_x64-setup.exe >/dev/null 2>&1 || { echo "CHAIN ABORT: no installer in $K"; exit 7; }
cp -r /c/CivicCastTester/kit-safe/4e03ef90cb4b591d60f0c1cdced0cbb739a80838/samples "$K/samples" 2>/dev/null || true
( cd "$K" && find . -type f ! -name SHA256SUMS.txt -printf '%P\n' | sort | while IFS= read -r f; do sha256sum -b "$f"; done > SHA256SUMS.txt && sha256sum -c --quiet SHA256SUMS.txt ) || { echo "CHAIN ABORT: manifest failed"; exit 8; }
echo "MANIFEST $(grep -c . "$K/SHA256SUMS.txt") lines verified"
powershell -NoProfile -File "$(cygpath -w "$S/after-build.ps1")" -Sha "$SHA" 2>&1 | tail -3
[ -f "/c/CivicCastTester/kit-safe/$SHA/SHA256SUMS.txt" ] || { echo "CHAIN ABORT: kit-safe copy missing"; exit 9; }
base="http://192.168.0.135:8766/$SHA/"; bad=0; n=0
while IFS= read -r line; do rel="${line#* }"; rel="${rel#\*}"; url="$base$(python -c "import sys,urllib.parse; print('/'.join(urllib.parse.quote(p, safe='') for p in sys.argv[1].split('/')))" "$rel")"; code=$(curl -s -o /dev/null -I -w '%{http_code}' "$url"); n=$((n+1)); [ "$code" = "200" ] || bad=$((bad+1)); done < "$K/SHA256SUMS.txt"
echo "SERVED HEAD checks: $n ok=$((n-bad)) bad=$bad"
[ "$bad" = 0 ] || exit 10
for i in $(seq 1 20); do gate=$(gh run list --workflow gate-a-station-acceptance.yml --limit 3 --json databaseId,headSha --jq ".[]|select(.headSha==\"$SHA\")|.databaseId" | head -1); [ -n "$gate" ] && break; sleep 60; done
echo "GATE A run ${gate:-NOT FOUND} for $SHORT"
echo "CHAIN DONE $SHORT"
