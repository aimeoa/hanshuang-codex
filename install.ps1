[CmdletBinding()]
param(
    [string]$CodexHome,
    [string]$SourcePrompt,
    [switch]$Uninstall
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$Utf8 = New-Object System.Text.UTF8Encoding($false)

function Read-Utf8([string]$Path) {
    return [System.IO.File]::ReadAllText($Path, [System.Text.Encoding]::UTF8)
}

function Write-Utf8NoBom([string]$Path, [string]$Text) {
    [System.IO.File]::WriteAllText($Path, $Text, $Utf8)
}

function Get-ConfigValueLine([string]$Text) {
    $match = [regex]::Match($Text, '(?m)^\s*model_instructions_file\s*=\s*.*$')
    if ($match.Success) { return $match.Value }
    return $null
}

if ([string]::IsNullOrWhiteSpace($CodexHome)) {
    if ($env:CODEX_HOME) {
        $CodexHome = $env:CODEX_HOME
    } else {
        $CodexHome = Join-Path $HOME '.codex'
    }
}
if ([string]::IsNullOrWhiteSpace($SourcePrompt)) {
    $mdFiles = @(Get-ChildItem -LiteralPath $PSScriptRoot -Filter '*.md' -File | Sort-Object Name)
    if ($mdFiles.Count -eq 0) {
        throw "No .md prompt file found in $PSScriptRoot"
    }
    $SourcePrompt = $mdFiles[0].FullName
}

$CodexHome = [System.IO.Path]::GetFullPath($CodexHome)
$configPath = Join-Path $CodexHome 'config.toml'
$managedDir = Join-Path $CodexHome 'managed-prompts'
$targetPrompt = Join-Path $managedDir (Split-Path -Leaf $SourcePrompt)
$statePath = Join-Path $managedDir 'install-state.json'

if ($Uninstall) {
    if (-not (Test-Path -LiteralPath $statePath)) {
        throw "No installation state found at $statePath"
    }
    $state = Read-Utf8 $statePath | ConvertFrom-Json
    if (Test-Path -LiteralPath $configPath) {
        $current = Read-Utf8 $configPath
        $pattern = '(?m)^\s*model_instructions_file\s*=\s*.*(?:\r?\n|$)'
        if ($state.hadLine) {
            $replacement = [string]$state.previousLine + [Environment]::NewLine
            $current = [regex]::Replace($current, $pattern, $replacement, 1)
        } else {
            $current = [regex]::Replace($current, $pattern, '', 1)
        }
        Write-Utf8NoBom $configPath ($current.TrimEnd() + [Environment]::NewLine)
    }
    Remove-Item -LiteralPath $targetPrompt -Force -ErrorAction SilentlyContinue
    Remove-Item -LiteralPath $statePath -Force
    if (-not (Get-ChildItem -Force -LiteralPath $managedDir | Select-Object -First 1)) {
        Remove-Item -LiteralPath $managedDir -Force
    }
    Write-Host "Uninstalled managed prompt from $CodexHome"
    exit 0
}

if (-not (Test-Path -LiteralPath $SourcePrompt -PathType Leaf)) {
    throw "Prompt file not found: $SourcePrompt"
}

New-Item -ItemType Directory -Force -Path $CodexHome, $managedDir | Out-Null
$configExisted = Test-Path -LiteralPath $configPath
$configText = if ($configExisted) { Read-Utf8 $configPath } else { '' }
$previousLine = Get-ConfigValueLine $configText

Copy-Item -LiteralPath $SourcePrompt -Destination $targetPrompt -Force
$configPromptPath = $targetPrompt.Replace('\', '/')
$newLine = 'model_instructions_file = "' + $configPromptPath.Replace('"', '\"') + '"'
$linePattern = '(?m)^\s*model_instructions_file\s*=\s*.*$'
if ([regex]::IsMatch($configText, $linePattern)) {
    $configText = [regex]::Replace($configText, $linePattern, $newLine, 1)
} else {
    $configText = $newLine + [Environment]::NewLine + $configText
}
Write-Utf8NoBom $configPath ($configText.TrimEnd() + [Environment]::NewLine)

$state = [ordered]@{
    installedAt = (Get-Date).ToString('o')
    configPath = $configPath
    targetPrompt = $targetPrompt
    configExisted = $configExisted
    hadLine = ($null -ne $previousLine)
    previousLine = $previousLine
}
Write-Utf8NoBom $statePath (($state | ConvertTo-Json -Depth 3) + [Environment]::NewLine)

Write-Host "Installed prompt: $targetPrompt"
Write-Host "Updated config:   $configPath"
Write-Host "Restart Codex to load the configured instruction file."

# Launch floating window UI (non-blocking)
# Auto-detect the .py launcher (filename-independent, in case it was renamed)
$uiScript = Get-ChildItem -LiteralPath $PSScriptRoot -Filter '*.py' -File |
    Where-Object {
        [System.IO.File]::ReadAllText($_.FullName, [System.Text.Encoding]::UTF8) -match 'FloatWindow|Floating Window'
    } |
    Sort-Object Name |
    Select-Object -First 1 -ExpandProperty FullName
if (-not $uiScript) {
    $uiScript = Get-ChildItem -LiteralPath $PSScriptRoot -Filter '*.py' -File |
        Sort-Object Name |
        Select-Object -First 1 -ExpandProperty FullName
}
if ($uiScript) {
    $pyw = 'pythonw.exe'
    try {
        Start-Process -FilePath $pyw -ArgumentList @('"' + $uiScript + '"') -WindowStyle Hidden
    } catch {
        Start-Process -FilePath 'python' -ArgumentList @('"' + $uiScript + '"') -WindowStyle Hidden
    }
    Write-Host "Launched floating window: $uiScript"
} else {
    Write-Host "No .py launcher found in $PSScriptRoot"
}
