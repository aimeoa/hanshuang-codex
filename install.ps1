[CmdletBinding()]
param(
    [string]$CodexHome,
    [string]$SourcePrompt,
    [string]$SkillsSource,
    [string]$BundleSource,
    # 只注入提示词：不装技能库、不装随附包，也不动 skills 目录里已有的东西
    [switch]$NoSkills,
    # 额外把提示词注入 <CodexHome>\AGENTS.md（Codex 原生全局指令文件）
    [switch]$InjectAgents,
    # 分号分隔的其他提示词绝对路径：AGENTS.md 正文与之相同 = 之前手工贴的，可直接覆盖
    [string]$AgentsKnown,
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

# 目标已是最新时跳过整棵树的复制。重装时绝大多数文件没变，跳过能省掉全部磁盘写入 ——
# 实测这是被杀软实时扫描拖慢的主因，跳过比复制快一个数量级。
function Test-TreeCurrent([string]$Src, [string]$Dest) {
    if (-not (Test-Path -LiteralPath $Dest)) { return $false }
    $srcFiles = @(Get-ChildItem -LiteralPath $Src -Recurse -File -ErrorAction SilentlyContinue)
    if ($srcFiles.Count -eq 0) { return $true }
    foreach ($f in $srcFiles) {
        $rel = $f.FullName.Substring($Src.Length).TrimStart([char]92)
        $d = Join-Path $Dest $rel
        if (-not (Test-Path -LiteralPath $d)) { return $false }
        $di = Get-Item -LiteralPath $d -ErrorAction SilentlyContinue
        if ($null -eq $di) { return $false }
        if ($di.Length -ne $f.Length) { return $false }
        if ([Math]::Abs(($di.LastWriteTimeUtc - $f.LastWriteTimeUtc).TotalSeconds) -gt 2) { return $false }
    }
    return $true
}

function Copy-ManyFiles([string]$Src, [string]$Dest) {
    if (Test-TreeCurrent $Src $Dest) {
        Write-Host ("  up-to-date, skipped: " + (Split-Path $Dest -Leaf))
        return
    }
    robocopy $Src $Dest /E /MIR /MT:16 /R:1 /W:1 /NFL /NDL /NJH /NJS /NC /NS /NP | Out-Null
    if ($LASTEXITCODE -ge 8) { throw "robocopy failed with exit code $LASTEXITCODE for $Src" }
}

# 顶层错误捕获：任何失败打印原因并以非零码退出，界面能立即看到真实错误
trap {
    Write-Host ("寒霜工具错误: " + $_.Exception.Message) -ForegroundColor Red
    Write-Host $_.ScriptStackTrace -ForegroundColor Red
    exit 1
}

# 定位 AGENTS.md 里的注入块，返回起止下标。按「寒霜破甲…注入开始/结束」匹配而不是
# 写死整行，这样早先版本写下的「寒霜破甲 V5 注入开始」标记也能被认出来并正确摘除。
function Find-AgentsBlock([string]$Text) {
    if ([string]::IsNullOrEmpty($Text)) { return $null }
    $m = [regex]::Match($Text, '<!--[^\r\n]*寒霜破甲[^\r\n]*注入开始[^\r\n]*-->')
    if (-not $m.Success) { return $null }
    # 必须用两个两参 Match：写成 [regex]::Match($Text, $pat, $startat) 会命中
    # 「(string, string, RegexOptions)」重载，PowerShell 拿起始下标去当枚举值转，
    # 偏移小的时候碰巧能过、超过 RegexOptions 已定义范围（如 2944）立刻抛异常，
    # 表现就是卸载/重装报退出码 1。
    $tail = $Text.Substring($m.Index + $m.Length)
    $e = [regex]::Match($tail, '<!--[^\r\n]*寒霜破甲[^\r\n]*注入结束[^\r\n]*-->')
    if (-not $e.Success) { return $null }
    return @{ Start = $m.Index; End = $m.Index + $m.Length + $e.Index + $e.Length }
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
    } elseif (Test-Path -LiteralPath (Join-Path $HOME '.codex')) {
        $CodexHome = Join-Path $HOME '.codex'
    } else {
        # 默认位置不存在时，看是不是被迁到别的盘的根目录了 —— 用户可能直接把 .codex
        # 放在某个盘下（C 盘紧张时的常见做法）。都没找到就回落到默认位置，由后续步骤新建。
        $CodexHome = Join-Path $HOME '.codex'
        try {
            foreach ($d in [IO.DriveInfo]::GetDrives()) {
                if ($d.DriveType -ne [IO.DriveType]::Fixed -or -not $d.IsReady) { continue }
                $p = Join-Path $d.RootDirectory.FullName '.codex'
                if (Test-Path -LiteralPath $p) { $CodexHome = $p; break }
            }
        } catch { }
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
# AGENTS.md 注入块标记（安装与卸载共用同一对标记）
$agentsPath = Join-Path $CodexHome 'AGENTS.md'
$agentsBegin = '<!-- 寒霜破甲注入开始'
$agentsEnd = '<!-- 寒霜破甲注入结束 -->'

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

# 随附包：装在 $CodexHome 下、但【不在 skills/ 树内】的支持目录（如 breaker-kit）。
# 这些目录自带大量嵌套 SKILL.md，放进 skills/ 会被技能发现机制扫成重名技能，故隔离部署。
function Install-Bundles([string]$Source) {
    $installed = @()
    if ([string]::IsNullOrWhiteSpace($Source)) { return $installed }
    $srcDir = Join-Path $PSScriptRoot $Source
    if (-not (Test-Path -LiteralPath $srcDir)) { return $installed }

    # Copy-ManyFiles 用 robocopy /MIR，会删除目标目录里不属于源的文件。
    # 若目标已存在且不是上次寒霜装的，先整目录改名备份，绝不静默吃掉用户文件。
    $prev = @()
    if (Test-Path -LiteralPath $statePath) {
        try {
            $ps = Read-Utf8 $statePath | ConvertFrom-Json
            if ($ps.installedBundles) { $prev = @($ps.installedBundles) }
        } catch {}
    }

    foreach ($d in Get-ChildItem -LiteralPath $srcDir -Directory -ErrorAction SilentlyContinue) {
        $dest = Join-Path $CodexHome $d.Name
        if ((Test-Path -LiteralPath $dest) -and ($prev -notcontains $d.Name)) {
            $bak = $dest + '.bak-' + (Get-Date -Format 'yyyyMMdd-HHmmss')
            Move-Item -LiteralPath $dest -Destination $bak -Force
            Write-Host ("Backed up existing " + $d.Name + " -> " + (Split-Path -Leaf $bak)) -ForegroundColor Yellow
        }
        Copy-ManyFiles $d.FullName $dest
        $installed += $d.Name
    }
    return $installed
}

function Remove-Bundles([string[]]$Names) {
    if (-not $Names -or $Names.Count -eq 0) { return }
    foreach ($n in $Names) {
        if ([string]::IsNullOrWhiteSpace($n) -or $n -eq '.' -or $n -eq '..') { continue }
        $dest = Join-Path $CodexHome $n
        if (Test-Path -LiteralPath $dest) {
            Remove-Item -LiteralPath $dest -Recurse -Force -ErrorAction SilentlyContinue
        }
    }
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

# 清理「上一版寒霜装过、这一版技能库里已经没有了」的技能。
# 双保险，只删同时满足两条的目录：
#   1) 出现在上一次安装写下的 installedSkills 清单里（= 寒霜自己装的）
#   2) 目录下确实有 SKILL.md（= 长得像技能）
# 因此用户自己放进 skills 目录的东西绝不会被删。
# 汇总随包分发的各版本技能库里的技能名，用来识别历史遗留。
# 单靠 install-state.json 不够：它只记录最后一次安装，装了新版之后
# 上一版的记录就被覆盖了，那些技能会永远留在目录里。
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

# 候选 = 上次安装清单 ∪ 随包各版本技能库。
# 只删同时满足三条的目录：
#   1) 属于上面这个候选集合（= 寒霜发过的东西）
#   2) 当前版本技能库里已经没有
#   3) 目录下确实有 SKILL.md（= 长得像技能）
# 用户自己放进 skills 目录、寒霜从未分发过的，一条都不沾。
function Prune-StaleSkills([string[]]$Previous, [string[]]$Current) {
    $removed = @()
    $candidates = @()
    if ($Previous) { $candidates += $Previous }
    $candidates += Get-ShippedSkillNames
    $candidates = @($candidates | Where-Object { -not [string]::IsNullOrWhiteSpace($_) } | Select-Object -Unique)
    if ($candidates.Count -eq 0) { return $removed }
    foreach ($n in $candidates) {
        if ($Current -contains $n) { continue }
        $dest = Join-Path $skillsTarget $n
        if (-not (Test-Path -LiteralPath $dest)) { continue }
        if (-not (Test-Path -LiteralPath (Join-Path $dest 'SKILL.md'))) { continue }
        Remove-Item -LiteralPath $dest -Recurse -Force -ErrorAction SilentlyContinue
        $removed += $n
    }
    return $removed
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
    # 只摘掉「path 指向本工具 skills 目录」的块。用户自己写的 [[skills.config]]（指向别处，
    # 比如自建技能库）必须原样保留 —— 早期写法是把所有块一起删掉再按清单重建，
    # 用户自己配的条目就这样永久丢了，而且他无从察觉。
    $skillsPrefix = $skillsTarget.Replace('\', '/').TrimEnd('/') + '/'
    $blocks = [regex]::Split($current, '(?m)(?=^\[\[skills\.config\]\]\s*$)')
    $kept = New-Object System.Collections.Generic.List[string]
    foreach ($b in $blocks) {
        if ($b.StartsWith('[[skills.config]]')) {
            $mPath = [regex]::Match($b, '(?m)^\s*path\s*=\s*"([^"]+)"')
            if ($mPath.Success -and
                ($mPath.Groups[1].Value -replace '\\', '/').StartsWith($skillsPrefix, [StringComparison]::OrdinalIgnoreCase)) {
                continue   # 本工具管的技能条目，摘掉
            }
        }
        $kept.Add($b)
    }
    $current = ($kept -join '').TrimEnd() + [Environment]::NewLine
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
    $promptFiles = @()
    if ($state -and $state.promptHistory) { $promptFiles += @($state.promptHistory) }
    if ($state -and $state.targetPrompt) { $promptFiles += [string]$state.targetPrompt }
    if ($promptFiles.Count -eq 0) { $promptFiles = @($targetPrompt) }
    foreach ($f in ($promptFiles | Where-Object { -not [string]::IsNullOrWhiteSpace($_) } | Select-Object -Unique)) {
        Remove-Item -LiteralPath $f -Force -ErrorAction SilentlyContinue
    }
    # 摘掉 AGENTS.md 里的注入块：只按标记删除，用户自己的内容原样保留
    if (Test-Path -LiteralPath $agentsPath) {
        $agentsText = Read-Utf8 $agentsPath
        $blk = Find-AgentsBlock $agentsText
        if ($blk) {
            $left = ($agentsText.Substring(0, $blk.Start) + $agentsText.Substring($blk.End)).Trim()
            if ($left.Length -eq 0) {
                Remove-Item -LiteralPath $agentsPath -Force -ErrorAction SilentlyContinue
                Write-Host "Removed injected AGENTS.md (it only held the prompt)"
            } else {
                Write-Utf8NoBom $agentsPath ($left + [Environment]::NewLine)
                Write-Host "Removed injected block from AGENTS.md"
            }
        }
    }
    Remove-Item -LiteralPath $statePath -Force -ErrorAction SilentlyContinue
    # 只移除寒霜安装的 skills，绝不动其他 skills
    if ($state -and $state.installedSkills) {
        Remove-Skills @($state.installedSkills)
        Write-Host ("Removed managed skills: " + ($state.installedSkills -join ", "))
    }
    # 移除随附包（skills 树之外的自有目录）
    if ($state -and $state.installedBundles) {
        Remove-Bundles @($state.installedBundles)
        Write-Host ("Removed managed bundles: " + ($state.installedBundles -join ", "))
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

# 提示词里的 __CODEX_HOME__ 按本机实际安装位置展开（技能库 → <CODEX_HOME>\skills，
# 随附包 → <CODEX_HOME>\breaker-kit）。不展开的话提示词会指向打包者的机器路径，
# 换机安装后路由到不了 skills。
$codexHomeFwd = $CodexHome.Replace('\', '/')
$promptText = Read-Utf8 $targetPrompt
if ($promptText.Contains('__CODEX_HOME__')) {
    Write-Utf8NoBom $targetPrompt ($promptText.Replace('__CODEX_HOME__', $codexHomeFwd))
    Write-Host ("Prompt paths   : __CODEX_HOME__ -> " + $codexHomeFwd)
}

$configPromptPath = $targetPrompt.Replace('\', '/')
$newLine = 'model_instructions_file = "' + $configPromptPath.Replace('"', '\"') + '"'
$linePattern = '(?m)^\s*model_instructions_file\s*=\s*.*$'
if ([regex]::IsMatch($configText, $linePattern)) {
    $configText = [regex]::Replace($configText, $linePattern, $newLine, 1)
} else {
    $configText = $newLine + [Environment]::NewLine + $configText
}
Write-Utf8NoBom $configPath ($configText.TrimEnd() + [Environment]::NewLine)

# ---------- AGENTS.md 注入（-InjectAgents，V5 双提示词用）----------
# Codex 原生会读 <CodexHome>\AGENTS.md 作为全局指令；config.toml 里的
# model_instructions_file 会被 Codex 自己重写 config.toml 时丢掉，所以 V5 额外往
# AGENTS.md 写一份。用带标记的块，卸载时按标记摘除，绝不整体吞掉用户自己的内容。
$agentsResult = ''

if ($InjectAgents) {
    $body = (Read-Utf8 $targetPrompt).TrimEnd()
    $block = $agentsBegin + ' · ' + (Split-Path -Leaf $targetPrompt) + ' -->' +
        [Environment]::NewLine + $body + [Environment]::NewLine + $agentsEnd
    $norm = { param($s) ($s -replace "`r`n", "`n").Trim() }
    $normBody = & $norm $body

    $existing = ''
    if (Test-Path -LiteralPath $agentsPath) { $existing = Read-Utf8 $agentsPath }
    $normExisting = & $norm $existing

    # 正文和要装的一模一样 = 这份 AGENTS.md 已经就是提示词本身
    # （用户手工贴过，或者装了另一份 V5 提示词），可以直接整份换成带标记的块
    $isPromptOnly = $false
    if ($normExisting.Length -gt 0) {
        if ($normExisting -eq $normBody) {
            $isPromptOnly = $true
        } elseif (-not [string]::IsNullOrWhiteSpace($AgentsKnown)) {
            foreach ($k in ($AgentsKnown -split ';')) {
                if ([string]::IsNullOrWhiteSpace($k)) { continue }
                if (-not (Test-Path -LiteralPath $k)) { continue }
                if ($normExisting -eq (& $norm (Read-Utf8 $k))) { $isPromptOnly = $true; break }
            }
        }
    }

    $blk = Find-AgentsBlock $existing
    if ($blk) {
        # 已注入过：只换标记之间那一段，标记外的内容原样保留
        $existing = $existing.Substring(0, $blk.Start) + $block + $existing.Substring($blk.End)
        Write-Utf8NoBom $agentsPath ($existing.TrimEnd() + [Environment]::NewLine)
        $agentsResult = 'updated'
    } elseif ($normExisting.Length -eq 0 -or $isPromptOnly) {
        # 空文件 / 只有提示词正文：整份写成带标记的块
        Write-Utf8NoBom $agentsPath ($block + [Environment]::NewLine)
        $agentsResult = if ($isPromptOnly) { 'replaced-manual' } else { 'created' }
    } else {
        # 用户自己的 AGENTS.md：先备份，再把块追加到末尾（不动原有内容）
        $bak = Join-Path $CodexHome ('AGENTS.md.backup-' + (Get-Date -Format 'yyyyMMdd-HHmmss'))
        Copy-Item -LiteralPath $agentsPath -Destination $bak -Force
        Write-Utf8NoBom $agentsPath ($existing.TrimEnd() + [Environment]::NewLine + [Environment]::NewLine + $block + [Environment]::NewLine)
        $agentsResult = 'appended (backup: ' + (Split-Path -Leaf $bak) + ')'
    }
    Write-Host ("Injected into AGENTS.md: " + $agentsResult + " -> " + $agentsPath)
}

# 先读上一次安装写下的技能清单（新版装完要按它清理旧版遗留）
$prevSkills = @()
$prevBundles = @()
$prevState = $null
if (Test-Path -LiteralPath $statePath) {
    try {
        $prevState = Read-Utf8 $statePath | ConvertFrom-Json
        if ($prevState.installedSkills) { $prevSkills = @($prevState.installedSkills) }
        if ($prevState.installedBundles) { $prevBundles = @($prevState.installedBundles) }
    } catch {}
}

# 提示词历史：managed-prompts 下凡是我们写进去的都记下来。
# 换版本时（V4 <-> V5、V5 的六 <-> 5.6）清掉上一份，卸载时也按这份清单删干净，
# 否则只记最后一次的 targetPrompt，前面的文件会永远留在目录里。
$promptHistory = @()
if ($prevState -and $prevState.promptHistory) {
    $promptHistory = @($prevState.promptHistory)
} elseif ($prevState -and $prevState.targetPrompt) {
    $promptHistory = @([string]$prevState.targetPrompt)
}
if ($promptHistory -notcontains $targetPrompt) { $promptHistory += $targetPrompt }
foreach ($old in $promptHistory) {
    if ($old -ne $targetPrompt -and (Test-Path -LiteralPath $old)) {
        Remove-Item -LiteralPath $old -Force -ErrorAction SilentlyContinue
        Write-Host ("Removed previous prompt: " + (Split-Path -Leaf $old))
    }
}

# 记录安装前的禁用状态（用于卸载恢复）；必须在禁用动作之前读
$prevDisabled = Get-DisabledSkills

if ($NoSkills) {
    # 只写提示词：不装技能、不装随附包、也不清理或禁用 skills 目录里已有的任何技能。
    # 上次安装的清单原样带进 state —— 那是寒霜装过的东西，卸载时仍要能清干净。
    Write-Host "Skills disabled (-NoSkills): prompt only, existing skills left untouched"
    $installedSkills = $prevSkills
    $installedBundles = $prevBundles
} else {
    # 部署寒霜 skills 到 Codex skills 目录
    $installedSkills = Install-Skills
    if ($installedSkills.Count -gt 0) {
        Write-Host ("Installed skills: " + ($installedSkills -join ", "))
    }

    # 清掉上一版遗留、新版技能库里已移除的技能
    $staleSkills = Prune-StaleSkills $prevSkills $installedSkills
    if ($staleSkills.Count -gt 0) {
        Write-Host ("Pruned stale skills from previous version: " + ($staleSkills -join ", "))
    }

    # 部署随附包到 $CodexHome\<name>（skills 树之外，避免被技能发现机制扫到）
    $installedBundles = Install-Bundles $BundleSource
    if ($installedBundles.Count -gt 0) {
        Write-Host ("Installed bundles: " + ($installedBundles -join ", "))
    }

    # 应用随附包内的提示词路径占位符替换（__CODEX_HOME__ -> 实际路径，正斜杠）
    $codexHomeFwd = $CodexHome.Replace('\', '/')
    foreach ($b in $installedBundles) {
        Get-ChildItem -LiteralPath (Join-Path $CodexHome $b) -Recurse -File -Include '*.md' -ErrorAction SilentlyContinue |
            ForEach-Object {
                try {
                    $t = Read-Utf8 $_.FullName
                    if ($t.Contains('__CODEX_HOME__')) {
                        Write-Utf8NoBom $_.FullName ($t.Replace('__CODEX_HOME__', $codexHomeFwd))
                    }
                } catch {}
            }
    }

    # 禁用所有非寒霜 skills（只装了提示词时不能走这里，否则会把用户自己的技能全禁用）
    $disabledNow = Disable-NonManagedSkills @($installedSkills)
    if ($disabledNow.Count -gt 0) {
        Write-Host ("Disabled non-managed skills: " + ($disabledNow -join ", "))
    }
}

$state = [ordered]@{
    installedAt = (Get-Date).ToString('o')
    configPath = $configPath
    targetPrompt = $targetPrompt
    promptHistory = $promptHistory
    configExisted = $configExisted
    hadLine = ($null -ne $previousLine)
    previousLine = $previousLine
    installedSkills = $installedSkills
    installedBundles = $installedBundles
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
