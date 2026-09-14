# Rotation-aware capture for CivicCast logs. The active *.log file is generation
# zero; standard log rotation retains up to ten older files as *.log.1 through
# *.log.10. A checkpoint is identified by the SHA-256 of its exact byte prefix.

function Get-R16PrefixSha256 {
    param([Parameter(Mandatory)][string]$Path,[Parameter(Mandatory)][int64]$Length)
    $stream=[IO.File]::Open($Path,[IO.FileMode]::Open,[IO.FileAccess]::Read,[IO.FileShare]::ReadWrite)
    try {
        if($Length -lt 0 -or $stream.Length -lt $Length){throw "Checkpoint prefix is unavailable: $Path (wanted $Length bytes, found $($stream.Length))."}
        $sha=[Security.Cryptography.SHA256]::Create()
        try {
            $remaining=$Length;$buffer=New-Object byte[] 65536
            while($remaining -gt 0){
                $read=$stream.Read($buffer,0,[int][math]::Min($buffer.Length,$remaining))
                if($read -le 0){throw "Checkpoint prefix read ended early: $Path"}
                [void]$sha.TransformBlock($buffer,0,$read,$buffer,0);$remaining-=$read
            }
            [void]$sha.TransformFinalBlock((New-Object byte[] 0),0,0)
            return (($sha.Hash|ForEach-Object{$_.ToString('x2')})-join '')
        } finally {$sha.Dispose()}
    } finally {$stream.Dispose()}
}

function Get-R16LogCheckpoint {
    param([Parameter(Mandatory)][string]$ProgramDataRoot)
    $sources=@()
    foreach($folder in @('logs','data/egress')){
        $root=Join-Path $ProgramDataRoot $folder
        if(Test-Path -LiteralPath $root){
            foreach($file in Get-ChildItem -LiteralPath $root -Recurse -File -Filter '*.log'){
                $rootWithoutSlash=$ProgramDataRoot.TrimEnd([char[]]@('\','/'))
                $relative=$file.FullName.Substring($rootWithoutSlash.Length).TrimStart([char[]]@('\','/'))
                $sources += [pscustomobject]@{path=$file.FullName;relative_path=$relative;length=[int64]$file.Length;prefix_sha256=(Get-R16PrefixSha256 -Path $file.FullName -Length $file.Length)}
            }
        }
    }
    return [pscustomobject]@{schema='civiccast-log-checkpoint-r16-v1';captured_utc=[datetime]::UtcNow.ToString('o');sources=@($sources|Sort-Object path)}
}

function Get-R16LogFamily {
    param([Parameter(Mandatory)][string]$ActivePath)
    $directory=Split-Path -Parent $ActivePath;$name=Split-Path -Leaf $ActivePath
    $escaped=[regex]::Escape($name);$members=@()
    foreach($file in Get-ChildItem -LiteralPath $directory -File){
        $match=[regex]::Match($file.Name,"^$escaped(?:\.(\d+))?$")
        if($match.Success){
            $generation=0
            if($match.Groups[1].Success){$generation=[int]$match.Groups[1].Value}
            $members += [pscustomobject]@{path=$file.FullName;generation=$generation}
        }
    }
    return @($members)
}

function Read-R16LogSuffix {
    param([Parameter(Mandatory)][string]$Path,[Parameter(Mandatory)][int64]$Offset)
    $stream=[IO.File]::Open($Path,[IO.FileMode]::Open,[IO.FileAccess]::Read,[IO.FileShare]::ReadWrite)
    try {if($Offset -lt 0 -or $stream.Length -lt $Offset){throw "Log suffix is unavailable: $Path"};[void]$stream.Seek($Offset,[IO.SeekOrigin]::Begin);$reader=New-Object IO.StreamReader($stream,[Text.UTF8Encoding]::new($false),$true,65536,$true);try{return $reader.ReadToEnd()}finally{$reader.Dispose()}}finally{$stream.Dispose()}
}

function Copy-R16LogsSinceCheckpoint {
    param([Parameter(Mandatory)]$Checkpoint,[Parameter(Mandatory)][string]$RunRoot,[Parameter(Mandatory)][string]$Phase)
    if("$($Checkpoint.schema)" -ne 'civiccast-log-checkpoint-r16-v1'){throw 'Unrecognized R16 log checkpoint schema.'}
    $result=@();$receipt=@()
    foreach($source in @($Checkpoint.sources)){
        $family=@(Get-R16LogFamily -ActivePath ([string]$source.path))
        $matches=@($family|Where-Object {try{(Get-R16PrefixSha256 -Path $_.path -Length ([int64]$source.length)) -ceq [string]$source.prefix_sha256}catch{$false}})
        if($matches.Count -eq 0){throw "Checkpoint generation is missing, truncated, or evicted: $($source.path)"}
        if($matches.Count -ne 1){throw "Checkpoint generation is ambiguous: $($source.path)"}
        $match=$matches[0];$expectedGenerations=@(0..$match.generation)
        $available=@($family.generation|Sort-Object -Unique)
        if(@($expectedGenerations|Where-Object {$_ -notin $available}).Count){throw "A newer log generation is missing after checkpoint: $($source.path)"}
        $parts=@();$partReceipt=@()
        foreach($member in @($family|Where-Object {$_.generation -le $match.generation}|Sort-Object generation -Descending)){
            $offset=if($member.generation -eq $match.generation){[int64]$source.length}else{0L}
            $text=Read-R16LogSuffix -Path $member.path -Offset $offset
            $parts += $text;$partReceipt += @{path=$member.path;generation=$member.generation;offset=$offset;bytes=[Text.UTF8Encoding]::new($false).GetByteCount($text)}
        }
        $body=($parts -join '')
        $destination=Join-Path $RunRoot (Join-Path "$Phase/raw" ([string]$source.relative_path))
        New-Item -ItemType Directory -Path (Split-Path -Parent $destination) -Force|Out-Null
        [IO.File]::WriteAllText($destination,$body,[Text.UTF8Encoding]::new($false))
        $result += [pscustomobject]@{path=$destination;text=$body}
        $receipt += @{source_path=$source.path;relative_path=$source.relative_path;checkpoint_length=[int64]$source.length;checkpoint_prefix_sha256=$source.prefix_sha256;matched_generation=$match.generation;parts=$partReceipt}
    }
    $receiptPath=Join-Path $RunRoot "$Phase/LOG-COLLECTION.json";New-Item -ItemType Directory -Path (Split-Path -Parent $receiptPath) -Force|Out-Null;@{schema='civiccast-log-collection-r16-v1';phase=$Phase;collected_utc=[datetime]::UtcNow.ToString('o');sources=$receipt}|ConvertTo-Json -Depth 20|Set-Content -LiteralPath $receiptPath -Encoding utf8
    return @($result)
}

function Invoke-R16RotationAwareLogFixtures {
    $root=Join-Path ([IO.Path]::GetTempPath()) ('civiccast-r16-rotation-'+[guid]::NewGuid().ToString('N'));$program=Join-Path $root 'program';$run=Join-Path $root 'run';$logs=Join-Path $program 'logs';New-Item -ItemType Directory -Path $logs -Force|Out-Null
    try {
        $active=Join-Path $logs 'control_plane-app.log'
        function Set-R16Fixture([string]$Path,[string]$Text){[IO.File]::WriteAllText($Path,$Text,[Text.UTF8Encoding]::new($false))}
        function Assert-R16Fixture([bool]$Condition,[string]$Message){if(-not $Condition){throw "R16 rotation fixture failed: $Message"}}
        Set-R16Fixture $active 'before|';$checkpoint=Get-R16LogCheckpoint $program;Set-R16Fixture $active 'before|after|';$logsOut=@(Copy-R16LogsSinceCheckpoint $checkpoint $run 'no-rotation');Assert-R16Fixture ($logsOut.Count -eq 1 -and $logsOut[0].text -ceq 'after|') 'no rotation did not collect the active suffix.'
        Set-R16Fixture $active 'before|';$checkpoint=Get-R16LogCheckpoint $program;Move-Item -LiteralPath $active -Destination "$active.1";Set-R16Fixture $active 'new|';$logsOut=@(Copy-R16LogsSinceCheckpoint $checkpoint $run 'one-rotation');Assert-R16Fixture ($logsOut[0].text -ceq 'new|') 'one rotation did not concatenate the newer active generation.'
        Remove-Item -LiteralPath "$active.1","$active.2" -Force -ErrorAction SilentlyContinue;Set-R16Fixture $active 'before|';$checkpoint=Get-R16LogCheckpoint $program;Move-Item -LiteralPath $active -Destination "$active.1";Set-R16Fixture $active 'middle|';Move-Item -LiteralPath "$active.1" -Destination "$active.2";Move-Item -LiteralPath $active -Destination "$active.1";Set-R16Fixture $active 'new|';$logsOut=@(Copy-R16LogsSinceCheckpoint $checkpoint $run 'two-rotations');Assert-R16Fixture ($logsOut[0].text -ceq 'middle|new|') 'two rotations were not concatenated chronologically.'
        Set-R16Fixture $active 'before|';Remove-Item -LiteralPath "$active.1","$active.2" -Force -ErrorAction SilentlyContinue;$checkpoint=Get-R16LogCheckpoint $program;Move-Item -LiteralPath $active -Destination "$active.1";Set-R16Fixture $active 'new-active-regrown-past-checkpoint|';$logsOut=@(Copy-R16LogsSinceCheckpoint $checkpoint $run 'regrown-active');Assert-R16Fixture ($logsOut[0].text -ceq 'new-active-regrown-past-checkpoint|') 'regrown active log confused the checkpoint generation.'
        Remove-Item -LiteralPath "$active.1","$active.2","$active.11" -Force -ErrorAction SilentlyContinue;Set-R16Fixture $active 'before|';$checkpoint=Get-R16LogCheckpoint $program;Set-R16Fixture $active 'truncated|';$failed=$false;try{Copy-R16LogsSinceCheckpoint $checkpoint $run 'truncated'|Out-Null}catch{$failed=$true};Assert-R16Fixture $failed 'truncated source did not fail closed.'
        Remove-Item -LiteralPath "$active.1","$active.2","$active.11" -Force -ErrorAction SilentlyContinue;Set-R16Fixture $active 'before|';$checkpoint=Get-R16LogCheckpoint $program;Move-Item -LiteralPath $active -Destination "$active.11";Set-R16Fixture $active 'new|';$failed=$false;try{Copy-R16LogsSinceCheckpoint $checkpoint $run 'evicted'|Out-Null}catch{$failed=$true};Assert-R16Fixture $failed 'evicted checkpoint did not fail closed.'
        Set-R16Fixture $active 'healthy|';$checkpoint=Get-R16LogCheckpoint $program;Move-Item -LiteralPath $active -Destination "$active.1";Set-R16Fixture $active "WORKER_RESULT failure across rotation|";$logsOut=@(Copy-R16LogsSinceCheckpoint $checkpoint $run 'failure-marker');Assert-R16Fixture ($logsOut[0].text -match 'WORKER_RESULT') 'failure marker across rotation was lost.'
        return [pscustomobject]@{verdict='PASS';checks=@('no rotation','one rotation','two rotations','regrown active','truncated source','evicted checkpoint','failure marker across rotation')}
    } finally {Remove-Item -LiteralPath $root -Recurse -Force -ErrorAction SilentlyContinue}
}
