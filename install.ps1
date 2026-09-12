[CmdletBinding()]
param(
    [string]$CodexHome,
    [string]$SourcePrompt,
    [string]$SkillsSource,
    [switch]$Uninstall
)

Set-StrictMode -Off
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'

$Utf8 = New-Object System.Text.UTF8Encoding($false)

function Copy-ManyFiles([string]$Src, [string]$Dest) {
    robocopy $Src $Dest /E /MIR /MT:16 /R:1 /W:1 /NFL /NDL /NJH /NJS /NC /NS /NP | Out-Null
    if ($LASTEXITCODE -ge 8) { throw "robocopy failed with exit code $LASTEXITCODE for $Src" }
}

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

function Get-ConfigValueLine([string]$Text) {
    $match = [regex]::Match($Text, '(?m)^\s*model_instructions_file\s*=\s*[^\r\n]*')
    if ($match.Success) { return $match.Value.TrimEnd("`r") }
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
if ([string]::IsNullOrWhiteSpace($SkillsSource)) {
    $SkillsSource = Join-Path $PSScriptRoot 'codex-skills'
} else {
    $SkillsSource = Join-Path $PSScriptRoot $SkillsSource
}
$skillsSource = $SkillsSource
$skillsTarget = Join-Path $CodexHome 'skills'
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
        Copy-ManyFiles $d.FullName $dest
        $installed += $d.Name
    }
    return $installed
}

function Remove-Skills([string[]]$Names) {
    if (-not $Names -or $Names.Count -eq 0) { return }
    foreach ($n in $Names) {
        $dest = Join-Path $skillsTarget $n
        if (Test-Path -LiteralPath $dest) {
            Remove-Item -LiteralPath $dest -Recurse -Force -ErrorAction SilentlyContinue
        }
    }
}

function Get-DisabledSkills {
    $result = @()
    if (-not (Test-Path -LiteralPath $configPath)) { return $result }
    $current = Read-Utf8 $configPath
    $blocks = [regex]::Split($current, '(?m)^\[\[skills\.config\]\]\s*$')
    for ($i = 1; $i -lt $blocks.Count; $i++) {
        $blk = $blocks[$i]
        $mPath = [regex]::Match($blk, '(?m)^\s*path\s*=\s*"([^"]+)"')
        if (-not $mPath.Success) { continue }
        $mEn = [regex]::Match($blk, '(?m)^\s*enabled\s*=\s*(true|false)')
        $enabled = if ($mEn.Success) { $mEn.Groups[1].Value -eq 'true' } else { $true }
        if (-not $enabled) {
            $dir = Split-Path -Parent ($mPath.Groups[1].Value -replace '/', '\')
            $name = Split-Path -Leaf $dir
            $parentName = ''
            try { $parentName = Split-Path -Leaf (Split-Path -Parent $dir) } catch {}
            # Only accept .../skills/<name>/SKILL.md structure; skip malformed entries
            if ($name -and $parentName -eq 'skills' -and $name -ne 'skills') {
                $result += $name
            }
        }
    }
    return $result
}
function Set-SkillsEnabledState([string[]]$DisabledNames) {
    if (-not (Test-Path -LiteralPath $configPath)) { return }
    $current = Read-Utf8 $configPath
    $pattern = '(?ms)^\[\[skills\.config\]\]\s*.*?(?=^\[\[|\z)'
    $current = [regex]::Replace($current, $pattern, '')
    $current = $current.TrimEnd() + [Environment]::NewLine
    foreach ($n in $DisabledNames) {
        $p = (Join-Path $skillsTarget ($n + '\SKILL.md')).Replace('\', '/')
        if ([string]::IsNullOrWhiteSpace($n) -or $n -eq 'skills') { continue }
        $current += '[[skills.config]]' + [Environment]::NewLine +
            'path = "' + $p + '"' + [Environment]::NewLine + 'enabled = false' + [Environment]::NewLine
    }
    Write-Utf8NoBom $configPath $current
}

function Disable-NonManagedSkills([string[]]$ManagedNames) {
    $all = @()
    if (Test-Path -LiteralPath $skillsTarget) {
        $all = @(Get-ChildItem -LiteralPath $skillsTarget -Directory -ErrorAction SilentlyContinue |
            Where-Object { Test-Path -LiteralPath (Join-Path $_.FullName 'SKILL.md') } |
            Select-Object -ExpandProperty Name)
    }
    $toDisable = @($all | Where-Object { $ManagedNames -notcontains $_ })
    Set-SkillsEnabledState $toDisable
    return $toDisable
}

if ($Uninstall) {
    $hadState = Test-Path -LiteralPath $statePath
    $state = $null
    if ($hadState) {
        try {
            $state = Read-Utf8 $statePath | ConvertFrom-Json
        } catch {
            $state = $null
        }
    }
    if (Test-Path -LiteralPath $configPath) {
        $current = Read-Utf8 $configPath
        $pattern = '(?m)^\s*model_instructions_file\s*=\s*.*(?:\r?\n|$)'
    $isOwnPrev = $false
    if ($state -and $state.previousLine) {
        $pl = [string]$state.previousLine
        if ($pl -match "managed-prompts") { $isOwnPrev = $true }
    }
    if ($state -and $state.hadLine -and $state.previousLine -and -not $isOwnPrev) {
            $replacement = [string]$state.previousLine + [Environment]::NewLine
            $current = [regex]::Replace($current, $pattern, $replacement, 1)
        } else {
            $current = [regex]::Replace($current, $pattern, '', 1)
        }
        Write-Utf8NoBom $configPath ($current.TrimEnd() + [Environment]::NewLine)
    }
    # 删除提示词文件：优先按安装时记录的 targetPrompt（卸载时 -SourcePrompt 为空，
    # Split-Path -Leaf 派生会失效，导致 managed-prompts 下的文件残留）
    $promptToRemove = $targetPrompt
    if ($state -and $state.targetPrompt) {
        $promptToRemove = [string]$state.targetPrompt
    }
    if ($promptToRemove) {
        Remove-Item -LiteralPath $promptToRemove -Force -ErrorAction SilentlyContinue
    }
    Remove-Item -LiteralPath $statePath -Force -ErrorAction SilentlyContinue
    # 只移除寒霜安装的 skills，绝不动其他 skills
    if ($state -and $state.installedSkills) {
        Remove-Skills @($state.installedSkills)
        Write-Host ("Removed managed skills: " + ($state.installedSkills -join ", "))
    }
    # 清除 Codex 记忆注入段（memory_summary.md 中所有标题含「寒霜注入」的章节）
    $memSummary = Join-Path $CodexHome 'memories\memory_summary.md'
    if (Test-Path -LiteralPath $memSummary) {
        try {
            $memTxt = Read-Utf8 $memSummary
            $memNew = [regex]::Replace($memTxt, '(?ms)^## [^\r\n]*寒霜注入[^\r\n]*\r?\n.*?(?=^## |\z)', '')
            $memNew = [regex]::Replace($memNew, '(\r?\n){3,}', "`r`n`r`n")
            if ($memNew.Trim() -ne $memTxt.Trim()) {
                Write-Utf8NoBom $memSummary ($memNew.TrimEnd() + [Environment]::NewLine)
                Write-Host "Removed injected Codex memory blocks"
            }
        } catch {
            Write-Host "Memory cleanup skipped: $_"
        }
    }
    # 恢复安装前的 skills 启用状态（卸载我们加的禁用条目，还原之前的禁用）
    $restoreDisabled = @()
    if ($state -and $state.previousDisabledSkills) {
        $restoreDisabled = @($state.previousDisabledSkills | Where-Object {
            $_ -is [string] -and -not [string]::IsNullOrWhiteSpace($_) -and $_ -ne 'skills'
        })
    }
    Set-SkillsEnabledState $restoreDisabled
    if ($restoreDisabled.Count -gt 0) {
        Write-Host ("Restored previous disabled skills: " + ($restoreDisabled -join ", "))
    } else {
        Write-Host "All non-managed skills re-enabled"
    }
    if ($hadState -and (Test-Path -LiteralPath $managedDir) -and -not (Get-ChildItem -Force -LiteralPath $managedDir | Select-Object -First 1)) {
        Remove-Item -LiteralPath $managedDir -Force -ErrorAction SilentlyContinue
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

# 部署寒霜 skills 到 Codex skills 目录
$installedSkills = Install-Skills
if ($installedSkills.Count -gt 0) {
    Write-Host ("Installed skills: " + ($installedSkills -join ", "))
}

# 记录安装前的禁用状态（用于卸载恢复），然后禁用所有非寒霜 skills
$prevDisabled = Get-DisabledSkills
$disabledNow = Disable-NonManagedSkills @($installedSkills)
if ($disabledNow.Count -gt 0) {
    Write-Host ("Disabled non-managed skills: " + ($disabledNow -join ", "))
}

$state = [ordered]@{
    installedAt = (Get-Date).ToString('o')
    configPath = $configPath
    targetPrompt = $targetPrompt
    configExisted = $configExisted
    hadLine = ($null -ne $previousLine)
    previousLine = $previousLine
    installedSkills = $installedSkills
    previousDisabledSkills = $prevDisabled
}
Write-Utf8NoBom $statePath (($state | ConvertTo-Json -Depth 3) + [Environment]::NewLine)

Write-Host "Installed prompt: $targetPrompt"
Write-Host "Updated config:   $configPath"
Write-Host "Restart Codex to load the configured instruction file."
exit 0

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
# 修复: 探测不到浮窗脚本时不得误启主程序 fj_tool.py（否则会占住单实例锁，
# 导致之后双击 exe 无窗口直接退出）
if ($uiScript -and (Split-Path -Leaf $uiScript) -ne 'fj_tool.py') {
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
