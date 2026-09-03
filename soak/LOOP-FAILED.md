# LOOP FAILED — soak8-e1acfe6 bootstrap

- Hostname: DESKTOP-VBMA6O5
- UTC: 2026-09-03T19:11:06.1852897Z
- Bootstrap: C:\CivicCastSoak\bin\Install-SoakLoop.ps1
- Elevated helper job: $job
- Exit code: 1

## Result

The bootstrap registered CivicCastSoak-Poll, CivicCastSoak-Heartbeat, and CivicCastSoak-Boot, then failed its end-to-end proof. No corrective action was taken after the failure.

## Exact stderr

``text
fatal: ambiguous argument 'origin/soak8-e1acfe6-directives': unknown revision or path not in the working tree.
Use '--' to separate paths from revisions, like this:
'git <command> [<revision>...] -- [<file>...]'
fatal: 'origin/main' is not a commit and a branch 'tester/soak8-e1acfe6-DESKTOP-VBMA6O5' cannot be created from it
git.exe : fatal: couldn't find remote ref tester/soak8-e1acfe6-DESKTOP-VBMA6O5
At C:\dev\ClaudeElevatedHelper\Install-SoakLoop-soak8.ps1:319 char:3
+   & git -C $repo fetch --quiet origin $TesterBranch 2>&1 | Out-Null
+   ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
    + CategoryInfo          : NotSpecified: (fatal: couldn't...DESKTOP-VBMA6O5:String) [], RemoteException
    + FullyQualifiedErrorId : NativeCommandError
``

## Bootstrap stdout before failure

``text
[soak8] mission=soak8-e1acfe6 root=C:\CivicCastSoak branch=tester/soak8-e1acfe6-DESKTOP-VBMA6O5 dryrun=False
[soak8] unregistering any previous CivicCastSoak-* scheduled tasks
[soak8]   unregister CivicCastSoak-Boot
[soak8]   unregister CivicCastSoak-Heartbeat
[soak8]   unregister CivicCastSoak-Poll
[soak8] folders ready under C:\CivicCastSoak
[soak8] git available: yes
[soak8] tester branch checked out: tester/soak8-e1acfe6-DESKTOP-VBMA6O5
[soak8] loop scripts written (poll-directives.ps1, heartbeat.ps1, boot-marker.ps1)
[soak8]   parse OK: poll-directives.ps1
[soak8]   parse OK: heartbeat.ps1
[soak8]   parse OK: boot-marker.ps1
[soak8]   registered CivicCastSoak-Poll
[soak8]   registered CivicCastSoak-Heartbeat
[soak8]   registered CivicCastSoak-Boot

TaskName                State
--------                -----
CivicCastSoak-Boot      Ready
CivicCastSoak-Heartbeat Ready
CivicCastSoak-Poll      Ready



[soak8] proving the loop: starting Poll and Heartbeat once, then watching the remote branch
``
