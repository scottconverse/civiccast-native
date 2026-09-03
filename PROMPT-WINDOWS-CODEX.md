# Paste this into the Codex desktop agent on the tester box

You are a Codex agent on a Windows 11 box for the CivicCast fleet soak
`soak8-e1acfe6`. There is exactly one thing to do. Do it now.

1. Open an ELEVATED PowerShell 5.1 (Run as administrator).

2. Run these three lines exactly:

```
New-Item -Force -ItemType Directory C:\CivicCastSoak\bin | Out-Null
Invoke-WebRequest -UseBasicParsing -Uri 'https://raw.githubusercontent.com/scottconverse/civiccast-native/soak8-e1acfe6-directives/bootstrap/Install-SoakLoop.ps1' -OutFile C:\CivicCastSoak\bin\Install-SoakLoop.ps1
powershell -NoProfile -ExecutionPolicy Bypass -File C:\CivicCastSoak\bin\Install-SoakLoop.ps1
```

It takes a few minutes. It installs git if the box has none, clears any
`CivicCastSoak-*` tasks left over from an earlier mission, clones the repo,
registers a 10-minute directive-poll task (which also EXECUTES new orders), a
30-minute heartbeat task and a boot task, then proves the loop end to end
against GitHub before it returns.

3. Read the last line it prints.

- If it prints **LOOP PROVEN**: you are done. Say so and stop. The scheduled
  tasks now run the whole mission — kit download, silent install, three-channel
  playout, TSDuck egress proof, reports — with no further input from anyone.
  Do not run anything else. Do not unregister the `CivicCastSoak-*` tasks.

- If it prints **LOOP FAILED**: paste the printed reason lines into your reply
  and stop. Do not improvise a fix.

A likely one-time snag: `git push` may need a GitHub sign-in for this user. If
LOOP FAILED says that, run the exact `git -C ... push -u origin ...` line it
prints, complete the sign-in, then re-run the bootstrap.

Background, if you want it (you do not need it to act):
- Directives branch (read only): `soak8-e1acfe6-directives`
- Your branch (the tasks push here): `tester/soak8-e1acfe6-<YOUR-HOSTNAME>`
- Full mission description: `soak/DIRECTIVE-1.md` on the directives branch

Trigger: START NOW
