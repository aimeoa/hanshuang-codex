[CmdletBinding()]
param(
    [string]$SourcePrompt,
    [string]$ClaudeHome,
    [string]$SkillsSource,
    # 分号分隔的其他提示词绝对路径：CLAUDE.md 正文与之相同 = 之前贴的就是提示词，可直接整份改写
    [string]$KnownPrompts,
    [switch]$Uninstall
)

Set-StrictMode -Off
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'

$Utf8 = New-Object System.Text.UTF8Encoding($false)
# 子进程 stdout 会被上层（electron/main.cjs）按 UTF-8 解码，
# 必须先锁定控制台输出编码为 UTF-8，否则中文会以 GBK 写出而变成乱码（U+FFFD）。
try { [Console]::OutputEncoding = $Utf8 } catch {}
try { $OutputEncoding = $Utf8 } catch {}

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

# 定位 CLAUDE.md 里的注入块，返回起止下标。按 HANSHUANG-INJECT:BEGIN/END 匹配而不是
# 写死整行，这样老版本写下的 `<!-- HANSHUANG-INJECT:BEGIN -->` 也能被认出来并正确摘除。
function Find-InjectBlock([string]$Text) {
    if ([string]::IsNullOrEmpty($Text)) { return $null }
    $m = [regex]::Match($Text, '<!--[^\r\n]*HANSHUANG-INJECT:BEGIN[^\r\n]*-->')
    if (-not $m.Success) { return $null }
    # 注意：这里必须用两个两参 Match。写成 [regex]::Match($Text, $pat, $startat) 会命中
    # 「(string, string, RegexOptions)」重载，PowerShell 拿起始下标去转 RegexOptions 枚举
    # 直接抛「无法将值 2944 转换为 RegexOptions」——卸载就报退出码 1。
    $tail = $Text.Substring($m.Index + $m.Length)
    $e = [regex]::Match($tail, '<!--[^\r\n]*HANSHUANG-INJECT:END[^\r\n]*-->')
    if (-not $e.Success) { return $null }
    return @{ Start = $m.Index; End = $m.Index + $m.Length + $e.Index + $e.Length }
}

# 寒霜提示词独有的特征串。老版本是「整份覆盖」式注入，不留标记，只能靠内容认出来。
# 实测要覆盖到历届版本：V4/V3 的「拒绝话术全清单」「激活词」、V5 的「样例 A：给另一 AI」，
# 以及早期那份 SES-OS 规范（只含「寒霜」「SES-OS」两个词，漏了就认不出来）。
$injectSignatures = @(
    'HANSHUANG-INJECT',
    '拒绝话术全清单',
    '激活词',
    '寒霜',
    'SES-OS',
    '样例 A：给另一 AI',
    'CTF Lab'
)

# 判断一份文件是不是「寒霜注入产物」：带注入标记或命中特征串。
# 用途一：别把早先的注入产物当成「原始备份」还原回去（那样卸载等于没卸）。
# 用途二：认出没有标记的老式注入残渣，装/卸时都能正确处理而不是当用户内容追加。
function Test-InjectionArtifact([string]$Path) {
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) { return $false }
    try { $t = Read-Utf8 $Path } catch { return $false }
    if ([string]::IsNullOrWhiteSpace($t)) { return $false }
    foreach ($sig in $injectSignatures) {
        if ($t.Contains($sig)) { return $true }
    }
    return $false
}

# 找一份「干净的」原始 CLAUDE.md 备份（最新的优先）：覆盖各家备份命名，
# 排除注入产物与空文件；找不到返回 $null。
function Get-CleanClaudeBackup {
    $cands = @()
    foreach ($pat in @('CLAUDE.md.bak', 'CLAUDE.md.bak_*', 'CLAUDE.md.backup-*', 'CLAUDE.md.hanshuang.bak')) {
        $cands += @(Get-ChildItem -LiteralPath $ClaudeHome -Filter $pat -File -ErrorAction SilentlyContinue)
    }
    $managedBak = Join-Path $managedDir 'CLAUDE.md.bak'
    if (Test-Path -LiteralPath $managedBak -PathType Leaf) {
        $cands += @(Get-Item -LiteralPath $managedBak)
    }
    foreach ($c in ($cands | Where-Object { $_ -and $_.Length -gt 0 } | Sort-Object LastWriteTime -Descending)) {
        if ($c.FullName -eq $claudeMd) { continue }
        if (Test-InjectionArtifact $c.FullName) { continue }
        return $c.FullName
    }
    return $null
}

if ([string]::IsNullOrWhiteSpace($ClaudeHome)) {
    $ClaudeHome = Join-Path $HOME '.claude'
}
$claudeMd = Join-Path $ClaudeHome 'CLAUDE.md'
$managedDir = Join-Path $ClaudeHome 'managed-prompts'
$backupPath = Join-Path $managedDir 'CLAUDE.md.bak'
# 注入块的结束标记；开始标记由注入时生成，带提示词文件名（便于识别当前是哪一版）
$markerEnd = '<!-- HANSHUANG-INJECT:END -->'
if ([string]::IsNullOrWhiteSpace($SkillsSource)) {
    $SkillsSource = Join-Path $PSScriptRoot 'codex-skills'
} else {
    $SkillsSource = Join-Path $PSScriptRoot $SkillsSource
}
$skillsSource = $SkillsSource
$skillsTarget = Join-Path $ClaudeHome 'skills'
$skillsManifestKey = 'installedSkills'

# 单个技能目录已是最新时跳过删除+复制（重装时几乎所有技能都没变）。
# 省掉磁盘写入 = 省掉杀软实时扫描，实测重装从 7 秒级降到 1 秒级。
function Test-SkillCurrent([string]$SrcDir, [string]$DestDir) {
    # 只比 SKILL.md 的大小+时间戳当"这个技能没变过"的代理指标 —— 便宜且够用：
    # 真正逐文件的差异由 robocopy /MIR 自己判断（它是编译过的，比我用 PowerShell
    # 遍历几千个文件快得多，之前那样做反而成了瓶颈）。
    $srcFile = [System.IO.Path]::Combine($SrcDir, 'SKILL.md')
    $dstFile = [System.IO.Path]::Combine($DestDir, 'SKILL.md')
    if (-not [System.IO.File]::Exists($srcFile)) { return $false }
    if (-not [System.IO.File]::Exists($dstFile)) { return $false }
    $s = New-Object System.IO.FileInfo($srcFile)
    $d = New-Object System.IO.FileInfo($dstFile)
    if ($s.Length -ne $d.Length) { return $false }
    if ([Math]::Abs(($s.LastWriteTimeUtc - $d.LastWriteTimeUtc).TotalSeconds) -gt 2) { return $false }
    return $true
}

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
        if (Test-SkillCurrent $d.FullName $dest) {
            $installed += $d.Name
            continue
        }
        if (Test-Path -LiteralPath $dest) {
            Remove-Item -LiteralPath $dest -Recurse -Force
        }
        robocopy $d.FullName $dest /E /MT:16 /R:1 /W:1 /NFL /NDL /NJH /NJS /NC /NS /NP | Out-Null
        if ($LASTEXITCODE -ge 8) { throw "robocopy failed for $($d.FullName)" }
        $installed += $d.Name
    }
    return $installed
}

# 汇总随包分发的各版本技能库里的技能名，用来识别历史遗留。
# install-state.json 只记录最后一次安装，装了新版之后上一版的记录会被覆盖，
# 那些技能会永远留在目录里，所以不能只依赖清单。
function Get-ShippedSkillNames {
    $names = @()
    foreach ($lib in @('codex-skills', 'codex-skills-v3', 'codex-skills-v4', 'codex-skills-v5')) {
        $dir = Join-Path $PSScriptRoot $lib
        if (-not (Test-Path -LiteralPath $dir)) { continue }
        $names += @(Get-ChildItem -LiteralPath $dir -Directory -ErrorAction SilentlyContinue |
            Where-Object { Test-Path -LiteralPath (Join-Path $_.FullName 'SKILL.md') } |
            Select-Object -ExpandProperty Name)
    }
    return @($names | Select-Object -Unique)
}

# 候选 = 上次安装清单 ∩ 随包技能库。
# 只删同时满足三条的目录：上次由本工具装过、当前版本已不再分发、目录下确实有 SKILL.md。
# 用户自己放进来的、寒霜从未分发过的技能一条都不沾 —— 纯靠随包清单判断会误删
# 用户自建技能，所以必须先与上次安装清单取交集。
function Prune-StaleSkills([string[]]$Previous, [string[]]$Current) {
    $removedSkills = @()
    if (-not $Previous) { return $removedSkills }
    $shipped = Get-ShippedSkillNames
    foreach ($hsSkillName in $Previous) {
        if ([string]::IsNullOrWhiteSpace($hsSkillName)) { continue }
        if ($shipped -notcontains $hsSkillName) { continue }  # 非随包技能，不动
        if ($Current -contains $hsSkillName) { continue }
        $dest = Join-Path $skillsTarget $hsSkillName
        if (-not (Test-Path -LiteralPath $dest)) { continue }
        if (-not (Test-Path -LiteralPath (Join-Path $dest 'SKILL.md'))) { continue }
        Remove-Item -LiteralPath $dest -Recurse -Force -ErrorAction SilentlyContinue
        $removedSkills += $hsSkillName
    }
    return $removedSkills
}

# 卸载时只删「上次安装清单 ∩ 随包技能库」。
# 变量名不要用 $Names：PowerShell 动态作用域下，函数内 foreach 的迭代变量会写进
# 调用方同名变量（调用处 $Names 恰好是上一轮 Install-Skills 的返回值），
# 会把不属于本工具的技能一起删掉。
function Remove-Skills([string[]]$SkillNames) {
    $removedSkills = @()
    if (-not $SkillNames) { return $removedSkills }
    $shipped = Get-ShippedSkillNames
    foreach ($hsSkillName in $SkillNames) {
        if ([string]::IsNullOrWhiteSpace($hsSkillName)) { continue }
        if ($shipped -notcontains $hsSkillName) { continue }  # 非随包技能，不动
        $dest = Join-Path $skillsTarget $hsSkillName
        if (Test-Path -LiteralPath $dest) {
            Remove-Item -LiteralPath $dest -Recurse -Force
            $removedSkills += $hsSkillName
        }
    }
    return $removedSkills
}

if ([string]::IsNullOrWhiteSpace($SourcePrompt)) {
    $mdFiles = @(Get-ChildItem -LiteralPath $PSScriptRoot -Filter '*.md' -File | Sort-Object Name)
    if ($mdFiles.Count -eq 0) {
        throw "No .md prompt file found in $PSScriptRoot"
    }
    $SourcePrompt = $mdFiles[0].FullName
}

if ($Uninstall) {
    # 1. 摘掉注入块：只按标记删，块外用户自己写的内容原样保留。
    #    老版本是整份覆盖 + 整份还原备份，会把用户安装之后的编辑一起冲掉。
    if (Test-Path -LiteralPath $claudeMd) {
        $cur = Read-Utf8 $claudeMd
        $blk = Find-InjectBlock $cur
        if ($blk) {
            $left = ($cur.Substring(0, $blk.Start) + $cur.Substring($blk.End)).Trim()
            if ($left.Length -eq 0) {
                # 摘完什么都不剩 = 这份文件本来就是我们建的：能找回干净的原始文件就还原，否则删掉。
                # 注意用 Get-CleanClaudeBackup 而不是直接拿 managed-prompts 里那份备份 ——
                # 那份备份本身可能就是更早的一次注入，还原它等于没卸载。
                $clean = Get-CleanClaudeBackup
                if ($clean) {
                    Copy-Item -LiteralPath $clean -Destination $claudeMd -Force
                    Write-Host ("Restored original CLAUDE.md from " + (Split-Path -Leaf $clean))
                } else {
                    Remove-Item -LiteralPath $claudeMd -Force
                    Write-Host "Removed injected CLAUDE.md"
                }
            } else {
                Write-Utf8NoBom $claudeMd ($left + [Environment]::NewLine)
                Write-Host "Removed injected block from CLAUDE.md (user content kept)"
            }
        } elseif (Test-InjectionArtifact $claudeMd) {
            # 没有标记、但内容就是寒霜提示词（老版本覆盖式注入留下的）：挪到一边留证，
            # 能找回干净的原始文件就还原，找不到就让它不存在 —— 不能让注入内容赖着不走
            $aside = Join-Path $ClaudeHome ('CLAUDE.md.inject-' + (Get-Date -Format 'yyyyMMdd-HHmmss'))
            Move-Item -LiteralPath $claudeMd -Destination $aside -Force
            $clean = Get-CleanClaudeBackup
            if ($clean) {
                Copy-Item -LiteralPath $clean -Destination $claudeMd -Force
                Write-Host ("Restored original CLAUDE.md from " + (Split-Path -Leaf $clean) +
                    " (stale injection kept at " + (Split-Path -Leaf $aside) + ")")
            } else {
                Write-Host ("Removed stale injected CLAUDE.md (kept a copy at " + (Split-Path -Leaf $aside) + ")")
            }
        } else {
            Write-Host "No injection found, nothing to do"
        }
    } else {
        Write-Host "No CLAUDE.md found, nothing to do"
    }
    # 2. 删除同步安装的 skills
    $statePath = Join-Path $managedDir 'install-state.json'
    if (Test-Path -LiteralPath $statePath) {
        try {
            $state = Get-Content -LiteralPath $statePath -Raw -Encoding UTF8 | ConvertFrom-Json
            if ($state.$skillsManifestKey) {
                $removedSkills = Remove-Skills @($state.$skillsManifestKey)
                if ($removedSkills.Count -gt 0) {
                    Write-Host ("Removed managed skills: " + ($removedSkills -join ", "))
                } else {
                    Write-Host "No managed skills to remove"
                }
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

# 注入方式：带标记的块。原则和 install.ps1 写 AGENTS.md 一致 ——
#   · 用户自己写的内容一律保留（首次注入前备份一份原文件）
#   · 已经有块就只换块内内容
#   · 整份文件本来就是提示词（含老版本写下的「标记+提示词」形态）才整份改写
# 老版本是「整体覆盖 + 卸载整份还原备份」，既会吃掉用户原有内容，也会冲掉装完之后的编辑。
$promptText = (Read-Utf8 $SourcePrompt).TrimEnd()
$markerBegin = '<!-- HANSHUANG-INJECT:BEGIN prompt=' + (Split-Path -Leaf $SourcePrompt) + ' -->'
$block = $markerBegin + [Environment]::NewLine + $promptText + [Environment]::NewLine + $markerEnd
$norm = { param($s) ($s -replace "`r`n", "`n").Trim() }
$normBody = & $norm $promptText

$existing = ''
if (Test-Path -LiteralPath $claudeMd) { $existing = Read-Utf8 $claudeMd }
$normExisting = & $norm $existing

$isPromptOnly = $false
if ($normExisting.Length -gt 0) {
    if ($normExisting -eq $normBody) {
        $isPromptOnly = $true
    } else {
        # 去掉已有的注入块之后再比：老版本写下的「块内只有提示词」也算
        $blk0 = Find-InjectBlock $existing
        if ($blk0) {
            $outside = & $norm ($existing.Substring(0, $blk0.Start) + $existing.Substring($blk0.End))
            if ($outside.Length -eq 0) { $isPromptOnly = $true }
        }
        if (-not $isPromptOnly -and -not [string]::IsNullOrWhiteSpace($KnownPrompts)) {
            foreach ($k in ($KnownPrompts -split ';')) {
                if ([string]::IsNullOrWhiteSpace($k)) { continue }
                if (-not (Test-Path -LiteralPath $k)) { continue }
                if ($normExisting -eq (& $norm (Read-Utf8 $k))) { $isPromptOnly = $true; break }
            }
        }
    }
}

$blk = Find-InjectBlock $existing
if ($blk) {
    # 已有注入块：只换块内内容，块外的用户内容原样保留
    $existing = $existing.Substring(0, $blk.Start) + $block + $existing.Substring($blk.End)
    Write-Utf8NoBom $claudeMd ($existing.TrimEnd() + [Environment]::NewLine)
    Write-Host "Updated injected block in CLAUDE.md (user content kept)"
} elseif ($normExisting.Length -eq 0 -or $isPromptOnly) {
    Write-Utf8NoBom $claudeMd ($block + [Environment]::NewLine)
    Write-Host "Injected prompt -> $claudeMd"
} elseif (Test-InjectionArtifact $claudeMd) {
    # 老版本覆盖式注入留下的残渣（没标记、内容却就是提示词）：挪到一边留证再写新块，
    # 不能当成"用户自己的内容"往后追加，否则会越堆越长
    $aside = Join-Path $ClaudeHome ('CLAUDE.md.inject-' + (Get-Date -Format 'yyyyMMdd-HHmmss'))
    Move-Item -LiteralPath $claudeMd -Destination $aside -Force
    Write-Utf8NoBom $claudeMd ($block + [Environment]::NewLine)
    Write-Host ("Replaced stale injection -> " + $claudeMd + " (stale copy kept at " + (Split-Path -Leaf $aside) + ")")
} else {
    # 用户自己的内容：仅首次备份原文件，再把块追加到末尾
    if (-not (Test-Path -LiteralPath $backupPath)) {
        Copy-Item -LiteralPath $claudeMd -Destination $backupPath -Force
        Write-Host "Backed up original CLAUDE.md"
    }
    Write-Utf8NoBom $claudeMd ($existing.TrimEnd() + [Environment]::NewLine + [Environment]::NewLine + $block + [Environment]::NewLine)
    Write-Host "Appended injected block -> $claudeMd (original content kept)"
}

# 先读上一次安装写下的技能清单（新版装完要按它清理旧版遗留）
$prevSkills = @()
$prevStatePath = Join-Path $managedDir 'install-state.json'
if (Test-Path -LiteralPath $prevStatePath) {
    try {
        $prevState = Read-Utf8 $prevStatePath | ConvertFrom-Json
        if ($prevState.installedSkills) { $prevSkills = @($prevState.installedSkills) }
    } catch {}
}

# 同步安装 skills
$installedSkills = Install-Skills
if ($installedSkills.Count -gt 0) {
    Write-Host ("Installed skills: " + ($installedSkills -join ", "))
}

# 清掉上一版遗留、新版技能库里已移除的技能
$staleSkills = Prune-StaleSkills $prevSkills $installedSkills
if ($staleSkills.Count -gt 0) {
    Write-Host ("Pruned stale skills from previous version: " + ($staleSkills -join ", "))
}

$state = @{ $skillsManifestKey = $installedSkills }
$statePath = Join-Path $managedDir 'install-state.json'
$stateJson = $state | ConvertTo-Json
Write-Utf8NoBom $statePath $stateJson
