[CmdletBinding()]
param(
    [string]$SourcePrompt,
    [string]$ClaudeHome,
    [string]$SkillsSource,
    [switch]$Uninstall
)

Set-StrictMode -Off
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'

$Utf8 = New-Object System.Text.UTF8Encoding($false)

# 顶层错误捕获：任何失败打印原因并以非零码退出，界面能立即看到真实错误
trap {
    Write-Host ("寒霜工具错误: " + $_.Exception.Message) -ForegroundColor Red
    Write-Host $_.ScriptStackTrace -ForegroundColor Red
    exit 1
}

function Read-Utf8([string]$Path) {
    return [System.IO.File]::ReadAllText($Path, [System.Text.Encoding]::UTF8)
}

function Write-Utf8NoBom([string]$Path, [string]$Text) {
    [System.IO.File]::WriteAllText($Path, $Text, $Utf8)
}

if ([string]::IsNullOrWhiteSpace($ClaudeHome)) {
    $ClaudeHome = Join-Path $HOME '.claude'
}
$claudeMd = Join-Path $ClaudeHome 'CLAUDE.md'
$managedDir = Join-Path $ClaudeHome 'managed-prompts'
$backupPath = Join-Path $managedDir 'CLAUDE.md.bak'
$marker = '<!-- HANSHUANG-INJECT:BEGIN -->'
if ([string]::IsNullOrWhiteSpace($SkillsSource)) {
    $SkillsSource = Join-Path $PSScriptRoot 'codex-skills'
} else {
    $SkillsSource = Join-Path $PSScriptRoot $SkillsSource
}
$skillsSource = $SkillsSource
$skillsTarget = Join-Path $ClaudeHome 'skills'
$skillsManifestKey = 'installedSkills'

function Get-SkillDirs {
    if (-not (Test-Path -LiteralPath $skillsSource)) { return @() }
    return @(Get-ChildItem -LiteralPath $skillsSource -Directory -ErrorAction SilentlyContinue |
        Where-Object { Test-Path -LiteralPath (Join-Path $_.FullName 'SKILL.md') })
}

function Install-Skills {
    $installed = @()
    $dirs = Get-SkillDirs
    if ($dirs.Count -eq 0) { return $installed }
    New-Item -ItemType Directory -Force -Path $skillsTarget | Out-Null
    foreach ($d in $dirs) {
        $dest = Join-Path $skillsTarget $d.Name
        if (Test-Path -LiteralPath $dest) {
            Remove-Item -LiteralPath $dest -Recurse -Force
        }
        robocopy $d.FullName $dest /E /MT:16 /R:1 /W:1 /NFL /NDL /NJH /NJS /NC /NS /NP | Out-Null
        if ($LASTEXITCODE -ge 8) { throw "robocopy failed for $($d.FullName)" }
        $installed += $d.Name
    }
    return $installed
}

function Remove-Skills([string[]]$Names) {
    foreach ($n in $Names) {
        $dest = Join-Path $skillsTarget $n
        if (Test-Path -LiteralPath $dest) {
            Remove-Item -LiteralPath $dest -Recurse -Force
        }
    }
}

if ([string]::IsNullOrWhiteSpace($SourcePrompt)) {
    $mdFiles = @(Get-ChildItem -LiteralPath $PSScriptRoot -Filter '*.md' -File | Sort-Object Name)
    if ($mdFiles.Count -eq 0) {
        throw "No .md prompt file found in $PSScriptRoot"
    }
    $SourcePrompt = $mdFiles[0].FullName
}

if ($Uninstall) {
    # 1. 恢复/删除注入的提示词
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
    # 2. 删除同步安装的 skills
    $statePath = Join-Path $managedDir 'install-state.json'
    if (Test-Path -LiteralPath $statePath) {
        try {
            $state = Get-Content -LiteralPath $statePath -Raw -Encoding UTF8 | ConvertFrom-Json
            if ($state.$skillsManifestKey) {
                Remove-Skills @($state.$skillsManifestKey)
                Write-Host ("Removed managed skills: " + ($state.$skillsManifestKey -join ", "))
            }
        } catch {
            Write-Host "Failed to read install-state.json, skipping skill removal"
        }
        Remove-Item -LiteralPath $statePath -Force
    }
    exit 0
}

if (-not (Test-Path -LiteralPath $SourcePrompt)) {
    throw "Prompt file not found: $SourcePrompt"
}

New-Item -ItemType Directory -Force -Path $ClaudeHome | Out-Null
New-Item -ItemType Directory -Force -Path $managedDir | Out-Null

# 备份原始 CLAUDE.md（仅首次注入时备份），然后整体覆盖为提示词内容
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

# 整体覆盖：CLAUDE.md 只保留注入的提示词
$promptText = Read-Utf8 $SourcePrompt
$injected = $marker + "`n" + $promptText.TrimEnd("`r", "`n") + "`n" + '<!-- HANSHUANG-INJECT:END -->' + "`n"
Write-Utf8NoBom $claudeMd $injected
Write-Host "Injected prompt -> $claudeMd"

# 同步安装 skills
$installedSkills = Install-Skills
if ($installedSkills.Count -gt 0) {
    Write-Host ("Installed skills: " + ($installedSkills -join ", "))
}
$state = @{ $skillsManifestKey = $installedSkills }
$statePath = Join-Path $managedDir 'install-state.json'
$stateJson = $state | ConvertTo-Json
Write-Utf8NoBom $statePath $stateJson
