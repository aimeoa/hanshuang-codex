[CmdletBinding()]
param(
    [string]$SourcePrompt,
    [switch]$Uninstall
)

Set-StrictMode -Off
$ErrorActionPreference = 'Stop'

$Utf8 = New-Object System.Text.UTF8Encoding($false)

function Read-Utf8([string]$Path) {
    return [System.IO.File]::ReadAllText($Path, [System.Text.Encoding]::UTF8)
}

function Write-Utf8NoBom([string]$Path, [string]$Text) {
    [System.IO.File]::WriteAllText($Path, $Text, $Utf8)
}

$ClaudeHome = Join-Path $HOME '.claude'
$claudeMd = Join-Path $ClaudeHome 'CLAUDE.md'
$managedDir = Join-Path $ClaudeHome 'managed-prompts'
$backupPath = Join-Path $managedDir 'CLAUDE.md.bak'
$marker = '<!-- HANSHUANG-INJECT:BEGIN -->'

if ([string]::IsNullOrWhiteSpace($SourcePrompt)) {
    $mdFiles = @(Get-ChildItem -LiteralPath $PSScriptRoot -Filter '*.md' -File | Sort-Object Name)
    if ($mdFiles.Count -eq 0) {
        throw "No .md prompt file found in $PSScriptRoot"
    }
    $SourcePrompt = $mdFiles[0].FullName
}

if ($Uninstall) {
    if (Test-Path -LiteralPath $backupPath) {
        Copy-Item -LiteralPath $backupPath -Destination $claudeMd -Force
        Remove-Item -LiteralPath $backupPath -Force
        Write-Host "Restored original CLAUDE.md"
    } else {
        if (Test-Path -LiteralPath $claudeMd) {
            $cur = Read-Utf8 $claudeMd
            if ($cur -match [regex]::Escape($marker)) {
                Remove-Item -LiteralPath $claudeMd -Force
                Write-Host "Removed injected CLAUDE.md"
            } else {
                Write-Host "No injection found, nothing to do"
            }
        } else {
            Write-Host "No CLAUDE.md found, nothing to do"
        }
    }
    exit 0
}

if (-not (Test-Path -LiteralPath $SourcePrompt)) {
    throw "Prompt file not found: $SourcePrompt"
}

New-Item -ItemType Directory -Force -Path $ClaudeHome | Out-Null
New-Item -ItemType Directory -Force -Path $managedDir | Out-Null

# 备份原始 CLAUDE.md（仅首次注入时备份）
if (Test-Path -LiteralPath $claudeMd) {
    $cur = Read-Utf8 $claudeMd
    if ($cur -match [regex]::Escape($marker)) {
        Write-Host "CLAUDE.md already injected, updating content"
    } elseif (-not (Test-Path -LiteralPath $backupPath)) {
        Copy-Item -LiteralPath $claudeMd -Destination $backupPath -Force
        Write-Host "Backed up original CLAUDE.md"
    }
} else {
    Write-Host "No existing CLAUDE.md, creating new"
}

$promptText = Read-Utf8 $SourcePrompt
$injected = $marker + "`n" + $promptText.TrimEnd("`r", "`n") + "`n" + '<!-- HANSHUANG-INJECT:END -->' + "`n"
Write-Utf8NoBom $claudeMd $injected
Write-Host "Injected prompt -> $claudeMd"
