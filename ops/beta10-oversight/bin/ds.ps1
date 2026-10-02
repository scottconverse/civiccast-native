# ds.ps1 - launch the DeepSeek coder as a headless Claude Code agent against local Ollama.
# Usage: ds.ps1 -Unit U01 [-Resume <session-id>] [-ResumeText <path to md fed on stdin>]
# Blocks until the coder exits, so run it in the background and wait for the exit notice.
param(
    [Parameter(Mandatory)] [string]$Unit,
    [string]$Resume,
    [string]$ResumeText,
    [string]$Model = 'deepseek-v4.1-flash:cloud',
    [string]$Worktree = 'C:\Users\scott\Documents\Codex\2026-09-16\re\civiccast-ds'
)
$ErrorActionPreference = 'Stop'
$Ov = Split-Path $PSScriptRoot -Parent
$Wt = $Worktree
$Claude = 'C:\Users\scott\.local\bin\claude.exe'
$HelperLog = 'C:\dev\ClaudeElevatedHelper\logs\helper.jsonl'

# Input fed on STDIN: the brief for a new unit, or the answer/continuation text on resume.
if ($Resume) {
    if (-not $ResumeText) { $ResumeText = Join-Path $Ov "questions\$Unit-answer.md" }
    $InputFile = $ResumeText
} else {
    $InputFile = Join-Path $Ov "briefs\$Unit.md"
}
if (-not (Test-Path -LiteralPath $InputFile)) { throw "Input file missing: $InputFile" }

# Next free run dir: runs\<unit>-N
$n = 1; while (Test-Path (Join-Path $Ov "runs\$Unit-$n")) { $n++ }
$RunDir = Join-Path $Ov "runs\$Unit-$n"
New-Item -ItemType Directory -Force $RunDir | Out-Null

# ---- Hazard strip: build the coder's environment from scratch ----
# Remove secrets and account-touching variables from this (child) process before launch.
foreach ($v in 'AWS_ACCESS_KEY_ID','AWS_SECRET_ACCESS_KEY','AWS_SESSION_TOKEN','CIVICCAST_STAFF_TOKENS',
               'CLAUDE_CODE_MESSAGING_TOKEN','CODEX_CLI_PATH','GH_TOKEN','GITHUB_TOKEN','OPENAI_API_KEY',
               'OPENAI_BASE_URL','OLLAMA_HOST','SSH_AUTH_SOCK') {
    Remove-Item "env:$v" -ErrorAction SilentlyContinue
}
# Minimal PATH: no gh, codex, npm/npx, scoop, winget, ssh, tailscale, ollama, claude, Python installs.
$env:PATH = @(
    "$Wt\.venv\Scripts",
    'C:\Program Files\Git\cmd',
    'C:\Users\scott\AppData\Local\Microsoft\WinGet\Packages\Gyan.FFmpeg.Essentials_Microsoft.Winget.Source_8wekyb3d8bbwe\ffmpeg-8.1.1-essentials_build\bin',
    'C:\Windows\System32',
    'C:\Windows',
    'C:\Windows\System32\WindowsPowerShell\v1.0'
) -join ';'
$env:CLAUDE_CODE_GIT_BASH_PATH = 'C:\Program Files\Git\bin\bash.exe'
$CoderHome = Join-Path $Ov 'coder-home'; New-Item -ItemType Directory -Force $CoderHome | Out-Null
$env:HOME = $CoderHome          # Git-bash ssh/git read ~ from HOME: no ssh keys, no global gitconfig creds
$env:VIRTUAL_ENV = "$Wt\.venv"
# Git: pushing is mechanically impossible; no credential helper; no interactive prompts.
$env:GIT_TERMINAL_PROMPT = '0'
$env:GCM_INTERACTIVE = 'never'
# No system gitconfig (Git for Windows puts credential.helper=manager there) and HOME points at an
# empty coder home, so no credential helper is configured at all. (PowerShell deletes an env var set
# to '', so an empty GIT_CONFIG_VALUE cannot be used to blank the helper.)
$env:GIT_CONFIG_NOSYSTEM = '1'
$env:GIT_CONFIG_COUNT = '3'
$env:GIT_CONFIG_KEY_0 = 'remote.origin.pushurl';  $env:GIT_CONFIG_VALUE_0 = 'blocked://coder-may-not-push'
$env:GIT_CONFIG_KEY_1 = 'user.name';              $env:GIT_CONFIG_VALUE_1 = 'DeepSeek coder (via Claude coordinator)'
$env:GIT_CONFIG_KEY_2 = 'user.email';             $env:GIT_CONFIG_VALUE_2 = 'coder@localhost.invalid'

# ---- Point Claude Code at local Ollama (Scott's 0.34.1 on 11435; 11434 is CivicCast's bundled Ollama) ----
$env:ANTHROPIC_BASE_URL = 'http://127.0.0.1:11435'   # [::1] does not answer on this box
$env:ANTHROPIC_AUTH_TOKEN = 'ollama'
Remove-Item env:ANTHROPIC_API_KEY -ErrorAction SilentlyContinue   # "empty" = absent (PowerShell cannot hold '')
foreach ($v in 'ANTHROPIC_MODEL','ANTHROPIC_DEFAULT_OPUS_MODEL','ANTHROPIC_DEFAULT_SONNET_MODEL',
               'ANTHROPIC_DEFAULT_HAIKU_MODEL','ANTHROPIC_SMALL_FAST_MODEL','CLAUDE_CODE_SUBAGENT_MODEL') {
    Set-Item "env:$v" $Model
}
$env:CLAUDE_CONFIG_DIR = Join-Path $Ov 'coder-config'   # never Scott's settings/hooks/skills; kept out of AppData
$env:CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC = '1'
$env:DISABLE_TELEMETRY = '1'
$env:DISABLE_AUTOUPDATER = '1'

$ArgList = @('-p', '--permission-mode', 'bypassPermissions', '--output-format', 'stream-json', '--verbose', '--model', $Model)
if ($Resume) { $ArgList += @('--resume', $Resume) }

# Side-channel baselines for the audit: elevated-helper activity and service identity.
$helperLines = if (Test-Path $HelperLog) { (Get-Content $HelperLog | Measure-Object).Count } else { 0 }
$svc = Get-CimInstance Win32_Service -Filter "Name='CivicCastSupervisor'" -ErrorAction SilentlyContinue

$meta = [ordered]@{
    unit = $Unit; run = "$Unit-$n"; model = $Model; resume = $Resume
    input_file = $InputFile; input_sha256 = (Get-FileHash -LiteralPath $InputFile).Hash
    worktree = $Wt; head_before = (& git -C $Wt rev-parse HEAD)
    started = (Get-Date).ToString('yyyy-MM-dd HH:mm:ss zzz')
    helper_log_lines_before = $helperLines
    service_pid_before = $svc.ProcessId
}
$p = Start-Process -FilePath $Claude -ArgumentList $ArgList -WorkingDirectory $Wt `
        -RedirectStandardInput $InputFile `
        -RedirectStandardOutput (Join-Path $RunDir 'stream.jsonl') `
        -RedirectStandardError (Join-Path $RunDir 'err.txt') `
        -WindowStyle Hidden -PassThru
$p.Id | Set-Content (Join-Path $RunDir 'pid.txt') -Encoding ascii
$meta.pid = $p.Id
$meta | ConvertTo-Json | Set-Content (Join-Path $RunDir 'meta.json') -Encoding utf8
"RUN $RunDir PID $($p.Id)"

$p.WaitForExit()
$svc2 = Get-CimInstance Win32_Service -Filter "Name='CivicCastSupervisor'" -ErrorAction SilentlyContinue
$meta.ended = (Get-Date).ToString('yyyy-MM-dd HH:mm:ss zzz')
$meta.exit_code = $p.ExitCode
$meta.head_after = (& git -C $Wt rev-parse HEAD)
$meta.helper_log_lines_after = if (Test-Path $HelperLog) { (Get-Content $HelperLog | Measure-Object).Count } else { 0 }
$meta.service_pid_after = $svc2.ProcessId
$meta | ConvertTo-Json | Set-Content (Join-Path $RunDir 'meta.json') -Encoding utf8
"EXIT $($p.ExitCode) $RunDir helper_lines $($meta.helper_log_lines_before)->$($meta.helper_log_lines_after) service_pid $($meta.service_pid_before)->$($meta.service_pid_after)"
