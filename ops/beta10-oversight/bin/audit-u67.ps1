# Coordinator audit of U67: same tests at LIVE daemon.py vs candidate daemon.py, in the u67 worktree. Restores the worktree file after.
$ErrorActionPreference='Continue'
$W='C:\Users\scott\Documents\Codex\2026-09-16\re\civiccast-ds-u67'
$O='C:\Users\scott\Documents\Codex\2026-09-16\re\civiccast-ds-oversight'
$Out="$O\evidence\audit-U67"
$live='C:\Program Files\CivicCast (Native)\runtime\Lib\site-packages\civiccast\egress\daemon.py'
$cand="$O\staging\U67\candidate\civiccast\egress\daemon.py"
$tgt="$W\civiccast\egress\daemon.py"
$bak="$Out\worktree-daemon.py.orig"
Copy-Item $tgt $bak -Force
$files='tests/egress/test_u67_reload_stall_recovery.py','tests/egress/test_daemon.py','tests/egress/test_daemon_command_isolation.py','tests/egress/test_daemon_reload_commit_timeout_relaunch.py','tests/egress/test_automation.py','tests/egress/test_automation_rollover_retry_log_cadence.py'
foreach($rev in 'LIVE','CAND'){
  Copy-Item $(if($rev -eq 'LIVE'){$live}else{$cand}) $tgt -Force
  $h=(git hash-object $tgt).Substring(0,8)
  "[$rev] daemon.py blob $h" | Out-File "$Out\$rev.txt" -Encoding utf8
  Push-Location $W
  $p=Start-Process -FilePath 'C:\Python314\python.exe' -ArgumentList (@('-m','pytest')+$files+@('-p','no:randomly','-q','--no-header','-p','no:cacheprovider','-x','--maxfail=200')) -WorkingDirectory $W -RedirectStandardOutput "$Out\$rev.out" -RedirectStandardError "$Out\$rev.err" -PassThru -WindowStyle Hidden
  $p.PriorityClass='BelowNormal'; $p.WaitForExit(1500000) | Out-Null
  Pop-Location
}
Copy-Item $bak $tgt -Force
"restored worktree daemon.py blob $((git hash-object $tgt).Substring(0,8))" | Out-File "$Out\done.txt" -Encoding utf8
