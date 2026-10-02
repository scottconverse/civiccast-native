# peek.ps1 - liveness + recent activity of a coder run. Usage: peek.ps1 -Run U01-2 [-Last 15]
param([Parameter(Mandatory)] [string]$Run, [int]$Last = 15)
$rd = Join-Path (Split-Path $PSScriptRoot -Parent) "runs\$Run"
$procId = Get-Content "$rd\pid.txt"
$p = Get-Process -Id $procId -ErrorAction SilentlyContinue
"pid $procId alive: $([bool]$p)  started: $(if ($p) { $p.StartTime.ToString('HH:mm:ss') })  stream bytes: $((Get-Item "$rd\stream.jsonl").Length)"
$n = 0; $tin = 0; $tcache = 0; $tout = 0; $models = @{}
$lines = Get-Content "$rd\stream.jsonl" | ForEach-Object {
    try { $j = $_ | ConvertFrom-Json } catch { return }
    if ($j.type -eq 'assistant') {
        $n++; $models[[string]$j.message.model] = 1
        foreach ($c in $j.message.content) {
            if ($c.type -eq 'tool_use') { $s = ($c.input | ConvertTo-Json -Compress); "T $($c.name) $($s.Substring(0,[Math]::Min(160,$s.Length)))" }
            elseif ($c.type -eq 'text' -and $c.text) { "X $($c.text.Substring(0,[Math]::Min(160,$c.text.Length)) -replace '\s+',' ')" }
        }
    } elseif ($j.type -eq 'result') {
        "RESULT subtype=$($j.subtype) turns=$($j.num_turns) ms=$($j.duration_ms) in=$($j.usage.input_tokens) cache_read=$($j.usage.cache_read_input_tokens) out=$($j.usage.output_tokens) session=$($j.session_id)"
    }
}
$lines | Select-Object -Last $Last
"assistant msgs: $n  models seen: $($models.Keys -join ',')"
$err = Get-Content "$rd\err.txt" -Raw; if ($err) { "stderr: $($err.Trim())" }
