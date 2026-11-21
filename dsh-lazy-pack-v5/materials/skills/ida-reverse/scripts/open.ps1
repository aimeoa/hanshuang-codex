<#
.SYNOPSIS
Open binary file via IDA HTTP API (bypass MCP schema issue)
.PARAMETER Path
Binary file path (required)
.PARAMETER SessionId
Session ID (optional, auto-generated)
.PARAMETER NoAutoAnalysis
Skip automatic analysis (faster open for large files)
.PARAMETER TimeoutSeconds
Open timeout in seconds, returns timeout instead of blocking forever

Non-ASCII input paths are copied to an ASCII-only temporary path because some
idalib worker transports replace Unicode path components with question marks.
#>

param(
    [Parameter(Mandatory=$true)]
    [string]$Path,
    [string]$SessionId = "",
    [switch]$NoAutoAnalysis = $false,
    [int]$TimeoutSeconds = 120
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

if (-not [string]::IsNullOrWhiteSpace($env:IDADIR)) {
    $env:IDADIR = $env:IDADIR
}
else {
    # Fallback: check common IDA installation paths
    $idaCandidates = @(
        'C:\Program Files\IDA Pro',
        'C:\IDA Pro',
        'D:\IDA',
        (Join-Path $env:USERPROFILE 'Tools\IDA')
    )
    $foundIda = $idaCandidates | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
    if ($foundIda) {
        $env:IDADIR = $foundIda
    } else {
        Write-Error "ERR:IDADIR not set and IDA Pro not found at common paths. Set IDADIR environment variable to your IDA installation directory."
        exit 1
    }
}
$Port = 13337
$TempDir = Join-Path $env:TEMP 'reverse-skill'
if (-not (Test-Path -LiteralPath $TempDir)) {
    New-Item -ItemType Directory -Path $TempDir -Force | Out-Null
}
$PollIntervalMs = 2000
$ProgressIntervalSeconds = 10

function Get-OptionalProperty {
    param(
        [object]$Object,
        [string]$Name
    )

    if ($null -eq $Object) {
        return $null
    }
    $property = $Object.PSObject.Properties[$Name]
    if ($null -eq $property) {
        return $null
    }
    return $property.Value
}

function Get-StructuredContent {
    param([object]$Response)

    $result = Get-OptionalProperty -Object $Response -Name 'result'
    $structured = Get-OptionalProperty -Object $result -Name 'structuredContent'
    if ($null -ne $structured) {
        return $structured
    }

    $content = @(Get-OptionalProperty -Object $result -Name 'content')
    foreach ($item in $content) {
        $type = Get-OptionalProperty -Object $item -Name 'type'
        $text = Get-OptionalProperty -Object $item -Name 'text'
        if ($type -eq 'text' -and -not [string]::IsNullOrWhiteSpace($text)) {
            try {
                return $text | ConvertFrom-Json -ErrorAction Stop
            } catch {}
        }
    }
    return $null
}

function Test-AsciiPath {
    param([string]$InputPath)

    foreach ($character in $InputPath.ToCharArray()) {
        if ([int][char]$character -gt 0x7F) {
            return $false
        }
    }
    return $true
}

function Copy-ToAsciiTemp {
    param(
        [string]$SourcePath,
        [string]$DestinationDirectory
    )

    $guid = [System.Guid]::NewGuid().ToString('N').Substring(0, 8)
    $extension = [System.IO.Path]::GetExtension($SourcePath)
    $tempName = "$guid-input$extension"
    $tempPath = Join-Path $DestinationDirectory $tempName
    Copy-Item -LiteralPath $SourcePath -Destination $tempPath -Force
    return $tempPath
}

function Get-OpenReadySession {
    param(
        [string]$ExpectedSessionId,
        [string]$ExpectedPath,
        [int]$RequestPort
    )

    $listBody = '{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"idb_list","arguments":{}}}'
    $listResult = Invoke-RestMethod "http://127.0.0.1:$RequestPort/mcp" -Method Post -Body $listBody `
        -ContentType "application/json" -TimeoutSec 10 -ErrorAction Stop

    $structured = Get-StructuredContent -Response $listResult
    $sessions = @(Get-OptionalProperty -Object $structured -Name 'sessions')
    foreach ($candidate in $sessions) {
        if (-not $candidate) {
            continue
        }

        $candidateSession = Get-OptionalProperty -Object $candidate -Name 'session_id'
        $candidatePath = Get-OptionalProperty -Object $candidate -Name 'input_path'
        $isAnalyzing = Get-OptionalProperty -Object $candidate -Name 'is_analyzing'
        $sameSession = $candidateSession -eq $ExpectedSessionId
        $samePath = $candidatePath -eq $ExpectedPath
        $sameFile = -not [string]::IsNullOrWhiteSpace($candidatePath) -and `
            [System.IO.Path]::GetFileName($candidatePath) -eq [System.IO.Path]::GetFileName($ExpectedPath)
        if (($sameSession -or $samePath -or $sameFile) -and $isAnalyzing -eq $false) {
            return $candidate
        }
    }

    return $null
}

if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
    Write-Output "ERR:file_not_found"
    exit 1
}

$Path = (Resolve-Path -LiteralPath $Path).Path

if ($TimeoutSeconds -le 0) {
    Write-Output "ERR:invalid_timeout"
    exit 1
}

# 判断是否用了临时副本（避免递归复制）
$isTempCopy = $Path.StartsWith($TempDir, [StringComparison]::OrdinalIgnoreCase)

# System32 或非 ASCII 路径自动复制到 ASCII-only Temp 路径。
if (-not $isTempCopy -and (($Path -match "C:\\Windows\\System32") -or -not (Test-AsciiPath -InputPath $Path))) {
    $Path = Copy-ToAsciiTemp -SourcePath $Path -DestinationDirectory $TempDir
    $isTempCopy = $true
}

# 清理同名旧数据库文件（只在非 Temp 副本时尝试）
if (-not $isTempCopy) {
    $dir = [System.IO.Path]::GetDirectoryName($Path)
    $base = [System.IO.Path]::GetFileNameWithoutExtension($Path)
    $oldExts = @(".id0", ".id1", ".id2", ".nam", ".til", ".i64")
    $hasLocked = $false
    foreach ($ext in $oldExts) {
        $f = Join-Path $dir "$base$ext"
        if (Test-Path $f) {
            Remove-Item $f -Force -ErrorAction SilentlyContinue
            if (Test-Path $f) { $hasLocked = $true }
        }
    }
    # 旧数据库文件被锁，自动用 Temp 副本
    if ($hasLocked) {
        $Path = Copy-ToAsciiTemp -SourcePath $Path -DestinationDirectory $TempDir
        $isTempCopy = $true
    }
}

# 始终使用明确的会话 ID，便于超时时轮询会话状态判断是否已成功打开
if (-not $SessionId) {
    $SessionId = [System.Guid]::NewGuid().ToString("N").Substring(0, 8)
}

$requestArguments = @{
    input_path = $Path
    run_auto_analysis = -not [bool]$NoAutoAnalysis
    preferred_session_id = $SessionId
}
$body = @{
    jsonrpc = '2.0'
    id = 1
    method = 'tools/call'
    params = @{
        name = 'idb_open'
        arguments = $requestArguments
    }
} | ConvertTo-Json -Depth 10 -Compress

# 将打开请求放到后台，避免 HTTP 长时间不回包时阻塞整个脚本
$openJob = Start-Job -ScriptBlock {
    param($RequestBody, $RequestPort)
    try {
        Invoke-RestMethod "http://127.0.0.1:$RequestPort/mcp" -Method Post -Body $RequestBody `
            -ContentType "application/json" -ErrorAction Stop
    } catch {
        $_.Exception.Message
    }
} -ArgumentList $body, $Port

$deadline = (Get-Date).AddSeconds($TimeoutSeconds)
$openCompleted = $false
$startTime = Get-Date
$lastProgressAt = $startTime.AddSeconds(-$ProgressIntervalSeconds)

try {
    while ((Get-Date) -lt $deadline) {
        if (Wait-Job -Job $openJob -Timeout 1) {
            $openCompleted = $true
            break
        }

        try {
            $session = Get-OpenReadySession -ExpectedSessionId $SessionId -ExpectedPath $Path -RequestPort $Port
            if ($session) {
                $tag = if ($isTempCopy) { " (temp copy)" } else { "" }
                Stop-Job -Job $openJob -ErrorAction SilentlyContinue
                Remove-Job -Job $openJob -Force -ErrorAction SilentlyContinue
                Write-Output "OK:$($session.filename):$($session.session_id)$tag"
                exit 0
            }
        } catch {}

        $now = Get-Date
        if (($now - $lastProgressAt).TotalSeconds -ge $ProgressIntervalSeconds) {
            $elapsed = [math]::Floor(($now - $startTime).TotalSeconds)
            Write-Output "INFO:opening:$elapsed/${TimeoutSeconds}s"
            $lastProgressAt = $now
        }

        Start-Sleep -Milliseconds $PollIntervalMs
    }

    if (-not $openCompleted) {
        Stop-Job -Job $openJob -ErrorAction SilentlyContinue
        Remove-Job -Job $openJob -Force -ErrorAction SilentlyContinue

        try {
            $session = Get-OpenReadySession -ExpectedSessionId $SessionId -ExpectedPath $Path -RequestPort $Port
            if ($session) {
                $tag = if ($isTempCopy) { " (temp copy)" } else { "" }
                Write-Output "OK:$($session.filename):$($session.session_id)$tag"
                exit 0
            }
        } catch {}

        Write-Output "ERR:open_timeout_${TimeoutSeconds}s"
        exit 1
    }

    $jobResult = Receive-Job -Job $openJob
    Remove-Job -Job $openJob -Force -ErrorAction SilentlyContinue

    if ($jobResult -is [string]) {
        Write-Output "ERR:$jobResult"
        exit 1
    }

    if ($jobResult -is [System.Array]) {
        $jobResult = $jobResult | Select-Object -Last 1
    }
    $structured = Get-StructuredContent -Response $jobResult
    $success = Get-OptionalProperty -Object $structured -Name 'success'
    $session = Get-OptionalProperty -Object $structured -Name 'session'
    $responseError = Get-OptionalProperty -Object $structured -Name 'error'

    if (($success -eq $true -or $null -ne $session) -and $null -ne $session) {
        $tag = if ($isTempCopy) { " (temp copy)" } else { "" }
        Write-Output "OK:$($session.filename):$($session.session_id)$tag"
    } else {
        # 自动降级：非 Temp 副本失败时，复制到 Temp 重试
        if (-not $isTempCopy) {
            $tempPath = Copy-ToAsciiTemp -SourcePath $Path -DestinationDirectory $TempDir
            & $PSCommandPath -Path $tempPath -SessionId $SessionId -NoAutoAnalysis:$NoAutoAnalysis -TimeoutSeconds $TimeoutSeconds
        } else {
            if ([string]::IsNullOrWhiteSpace($responseError)) {
                $responseError = 'idb_open returned no session and no error'
            }
            Write-Output "ERR:$responseError"
        }
    }
} finally {
    if ($openJob) {
        Stop-Job -Job $openJob -ErrorAction SilentlyContinue
        Remove-Job -Job $openJob -Force -ErrorAction SilentlyContinue
    }
}
