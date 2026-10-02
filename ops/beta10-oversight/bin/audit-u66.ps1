$O='C:\Users\scott\Documents\Codex\2026-09-16\re\civiccast-ds-oversight'
$Py='C:\Python314\python.exe'
New-Item -ItemType Directory -Force "$O\evidence\audit-U66" | Out-Null
foreach($rev in 'base','staged'){
  $d = if($rev -eq 'base'){"$O\bin"}else{"$O\staging\U66"}
  $t = @('test_loudness_window_adjudicate.py','test_rung_check_caption.py'); if($rev -eq 'staged'){$t += 'test_rung_check_air_audio.py'}
  $p=Start-Process -FilePath $Py -ArgumentList (@('-m','pytest','-p','no:cacheprovider','-q','--no-header','-p','no:randomly')+$t) -WorkingDirectory $d -RedirectStandardOutput "$O\evidence\audit-U66\$rev.out" -RedirectStandardError "$O\evidence\audit-U66\$rev.err" -PassThru -WindowStyle Hidden
  $p.PriorityClass='Idle'; $p.WaitForExit(900000)|Out-Null
}
'done' | Out-File "$O\evidence\audit-U66\done.txt"
