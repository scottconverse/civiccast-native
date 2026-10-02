param([Parameter(Mandatory)][string]$Pids)
foreach ($p in ($Pids -split ',')) {
  $proc = Get-CimInstance Win32_Process -Filter "ProcessId=$p"
  if ($proc) { "kill $p $($proc.Name) parent=$($proc.ParentProcessId) cmd=$($proc.CommandLine)"; Stop-Process -Id $p -Force } else { "gone $p" }
}
