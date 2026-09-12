[CmdletBinding()]
param(
    [string]$ZcodeHome,
    [string]$SourcePrompt,
    [string]$MemorySourcePrompt,
    [string]$SkillsSource,
    [string]$WorkspacePath,
    [switch]$PatchSystemPrompt,
    [switch]$Uninstall
)

Set-StrictMode -Off
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'

$Utf8 = New-Object System.Text.UTF8Encoding($false)
$script:hadError = $false

function Read-Utf8([string]$Path) {
    return [System.IO.File]::ReadAllText($Path, [System.Text.Encoding]::UTF8)
}

function Write-Utf8NoBom([string]$Path, [string]$Text) {
    [System.IO.File]::WriteAllText($Path, $Text, $Utf8)
}

function Get-Sha256Hex([string]$Text) {
    $sha = [System.Security.Cryptography.SHA256]::Create()
    $bytes = $sha.ComputeHash([System.Text.Encoding]::UTF8.GetBytes($Text))
    return ($bytes | ForEach-Object { $_.ToString('x2') }) -join ''
}

# 快速复制技能目录：robocopy 多线程，比 Copy-Item 快 10 倍以上（杀软扫描也不会卡几十分钟）
function Copy-ManyFiles([string]$Src, [string]$Dest) {
    robocopy $Src $Dest /E /MIR /MT:16 /R:1 /W:1 /NFL /NDL /NJH /NJS /NC /NS /NP | Out-Null
    if ($LASTEXITCODE -ge 8) { throw "robocopy failed with exit code $LASTEXITCODE for $Src" }
}

# ---------- 路径解析 ----------
if ([string]::IsNullOrWhiteSpace($ZcodeHome)) {
    $ZcodeHome = Join-Path $HOME '.zcode'
}
$ZcodeHome = [System.IO.Path]::GetFullPath($ZcodeHome)
$cliRoot = Join-Path $ZcodeHome 'cli'
$agentsPath = Join-Path $ZcodeHome 'AGENTS.md'
$statePath = Join-Path $ZcodeHome 'install-state.json'

# 提示词源：默认取脚本旁的寒霜v1.2.md（完整版）/ AGENTS.md
if ([string]::IsNullOrWhiteSpace($SourcePrompt)) {
    $candidates = @(
        (Join-Path $PSScriptRoot '寒霜v1.2.md'),
        (Join-Path $PSScriptRoot 'AGENTS.md'),
        (Join-Path (Split-Path -Parent $PSScriptRoot) 'AGENTS.md')
    )
    $SourcePrompt = $candidates | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
}
if (-not $SourcePrompt -or -not (Test-Path -LiteralPath $SourcePrompt -PathType Leaf)) {
    throw "Prompt file not found. Pass -SourcePrompt or place AGENTS.md next to this script."
}

# 记忆源：完整版提示词（寒霜v1.2.md），包装成 seagull-agents.md 记忆
if ([string]::IsNullOrWhiteSpace($MemorySourcePrompt)) {
    $MemorySourcePrompt = Join-Path $PSScriptRoot '寒霜v1.2.md'
    if (-not (Test-Path -LiteralPath $MemorySourcePrompt)) {
        $MemorySourcePrompt = $SourcePrompt
    }
}

# 工作区路径（决定记忆目录 hash）：优先从 zcode bot-state 读取实际工作区
if ([string]::IsNullOrWhiteSpace($WorkspacePath)) {
    $botState = Join-Path $ZcodeHome 'v2\bot-state.v2.json'
    if (Test-Path -LiteralPath $botState) {
        try {
            $bs = Read-Utf8 $botState | ConvertFrom-Json
            $ws = $bs.bots.PSObject.Properties.Value.workspacePath | Select-Object -First 1
            if ($ws) { $WorkspacePath = $ws }
        } catch { }
    }
}
if ([string]::IsNullOrWhiteSpace($WorkspacePath)) {
    $WorkspacePath = Split-Path -Parent $PSScriptRoot
}
$WorkspacePath = [System.IO.Path]::GetFullPath($WorkspacePath)

# 记忆目录：全局（zcode.cjs 已 patch 为固定加载 memories/global/memory）
$memoryRoot = Join-Path $cliRoot 'memories\global\memory'

# 注入标记：出现在 cjs 里的标识（u9o 函数被替换为海鸥配置后的特征）
$cjsInjectMarker = 'CTF-LAB-2.0'

# 系统提示词（可选 patch）：自动检测 zcode 安装位置
function Get-ZcodeSystemPromptPath {
    $found = $null
    # 1. 从运行中的 ZCode 进程定位
    $zcProc = Get-Process ZCode -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($zcProc -and $zcProc.Path) {
        $candidate = Join-Path (Split-Path $zcProc.Path -Parent) 'resources\glm\zcode.cjs'
        if (Test-Path -LiteralPath $candidate) { return $candidate }
    }
    # 2. 注册表卸载项
    $regPaths = @(
        'HKLM:\Software\Microsoft\Windows\CurrentVersion\Uninstall\*',
        'HKLM:\Software\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall\*',
        'HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\*'
    )
    foreach ($rp in $regPaths) {
        $item = Get-ItemProperty $rp -ErrorAction SilentlyContinue |
            Where-Object { $_.DisplayName -like '*ZCode*' -and $_.InstallLocation } |
            Select-Object -First 1
        if ($item) {
            $candidate = Join-Path $item.InstallLocation 'resources\glm\zcode.cjs'
            if (Test-Path -LiteralPath $candidate) { return $candidate }
        }
        if ($found) { break }
    }
    # 3. 常见安装位置
    $candidates = @(
        'C:\Program Files\ZCode\resources\glm\zcode.cjs',
        'C:\Program Files (x86)\ZCode\resources\glm\zcode.cjs',
        "$env:LOCALAPPDATA\Programs\ZCode\resources\glm\zcode.cjs",
        "$env:APPDATA\ZCode\resources\glm\zcode.cjs"
    )
    foreach ($candidate in $candidates) {
        if (Test-Path -LiteralPath $candidate) { return $candidate }
    }
    # 4. 盘符扫描兜底：ZCode 常被装在 D:/E: 等自定义目录（如 E:\zcodess）
    #    跳过系统重目录，只扫每盘根目录下一级子目录的 1 层，避免全盘递归卡死
    try {
        $skip = @('Windows', '$RECYCLE.BIN', 'System Volume Information', 'ProgramData', 'MSOCache', '$SysReset')
        $drives = [System.IO.DriveInfo]::GetDrives() |
            Where-Object { $_.DriveType -eq [System.IO.DriveType]::Fixed -and $_.IsReady } |
            Select-Object -First 6
        foreach ($drv in $drives) {
            $root = $drv.RootDirectory.FullName
            if (-not $root) { continue }
            $topDirs = @(Get-ChildItem -LiteralPath $root -Directory -ErrorAction SilentlyContinue |
                Where-Object { $skip -notcontains $_.Name })
            foreach ($d in $topDirs) {
                # 目标形如 <topdir>\resources\glm\zcode.cjs，相对 topdir 是第 2 层
                $hits = @(Get-ChildItem -LiteralPath $d.FullName -Filter 'zcode.cjs' -Recurse -Depth 2 -ErrorAction SilentlyContinue |
                    Select-Object -First 2 -ExpandProperty FullName)
                foreach ($h in $hits) {
                    if ($h -match 'resources[\\/]glm[\\/]zcode\.cjs$') { return $h }
                }
            }
        }
    } catch { }
    return $null
}

$systemPromptPath = $null
if ($PatchSystemPrompt -or $Uninstall) {
    $systemPromptPath = Get-ZcodeSystemPromptPath
}

# ---------- 卸载 ----------
if ($Uninstall) {
    try {
        $hadState = Test-Path -LiteralPath $statePath
        $state = $null
        if ($hadState) {
            try { $state = Read-Utf8 $statePath | ConvertFrom-Json } catch { $state = $null }
        }

        # 1. 恢复 AGENTS.md：优先 state 备份，其次按「最老 → 最新」找第一份干净备份
        #    （反复注入过的电脑上，后面的备份本身也带注入标记，越老的越接近原文件）
        $restoredAgents = $false
        $agentsBackup = $null
        $candidates = @()
        if ($state -and $state.agentsBackup) { $candidates += [string]$state.agentsBackup }
        $candidates += @(Get-ChildItem -LiteralPath $ZcodeHome -Filter 'AGENTS.md.backup-*' -File -ErrorAction SilentlyContinue |
            Sort-Object LastWriteTime | Select-Object -ExpandProperty FullName)
        foreach ($cand in $candidates) {
            if (-not (Test-Path -LiteralPath $cand)) { continue }
            $clean = $false
            try { $clean = -not ((Read-Utf8 $cand) -match 'CTF-LAB|寒霜|Seagull') } catch { }
            if ($clean) { $agentsBackup = $cand; break }
        }
        if ($agentsBackup) {
            Copy-Item -LiteralPath $agentsBackup -Destination $agentsPath -Force -ErrorAction Stop
            Write-Host "Restored original AGENTS.md from backup: $agentsBackup"
            $restoredAgents = $true
        } elseif (Test-Path -LiteralPath $agentsPath) {
            $curAgents = Read-Utf8 $agentsPath
            if ($curAgents -match [regex]::Escape($cjsInjectMarker) -or $curAgents -match 'CTF-LAB|寒霜|Seagull') {
                # 所有备份都已被注入覆盖（说明首次注入早于备份机制）→ 只能删除注入文件
                Remove-Item -LiteralPath $agentsPath -Force -ErrorAction SilentlyContinue
                Write-Host "Deleted injected AGENTS.md (no clean backup available)"
                $restoredAgents = $true
            } else {
                Write-Host "AGENTS.md is not ours, kept as-is"
            }
        }

        # 2. 删除安装的记忆文件（只删我们装的）
        $memRemoved = $false
        if ($state -and $state.installedMemories) {
            foreach ($m in $state.installedMemories) {
                $p = Join-Path $memoryRoot $m
                if (Test-Path -LiteralPath $p) {
                    Remove-Item -LiteralPath $p -Force -ErrorAction SilentlyContinue
                    Write-Host "Removed memory: $m"
                    $memRemoved = $true
                }
            }
            # 重建 MEMORY.md 索引（去掉已删文件的指针）
            $indexPath = Join-Path $memoryRoot 'MEMORY.md'
            if (Test-Path -LiteralPath $indexPath) {
                $index = Read-Utf8 $indexPath
                foreach ($m in $state.installedMemories) {
                    $index = $index -replace "(?m)^.*\[.*\]\($([regex]::Escape($m))\).*`r?`n?", ''
                }
                Write-Utf8NoBom $indexPath $index.TrimEnd()
            }
        }

        # 2.5 删除安装的技能（只删我们装的）
        if ($state -and $state.installedSkills) {
            $skillsTarget = Join-Path $ZcodeHome 'skills'
            foreach ($s in $state.installedSkills) {
                $p = Join-Path $skillsTarget $s
                if (Test-Path -LiteralPath $p) {
                    Remove-Item -LiteralPath $p -Recurse -Force -ErrorAction SilentlyContinue
                    Write-Host "Removed skill: $s"
                }
            }
        }

        # 3. 恢复系统提示词（关键修复：state 缺 systemPromptPath 时必须重新探测，
        #    否则被 patch 的 zcode.cjs 残留 → 卸载后还是注入状态）
        $cjsFixed = $true
        if ($systemPromptPath -and (Test-Path -LiteralPath $systemPromptPath)) {
            $curCjs = [System.IO.File]::ReadAllText($systemPromptPath)
            if ($curCjs.Contains($cjsInjectMarker)) {
                $cjsBackup = $null
                if ($state -and $state.systemPromptBackup -and (Test-Path -LiteralPath $state.systemPromptBackup)) {
                    $cjsBackup = [string]$state.systemPromptBackup
                } else {
                    # state 缺备份时：取 ~/.zcode 下最近的 zcode.cjs.backup-*（不含注入标记的）
                    $cjsBackup = @(Get-ChildItem -LiteralPath $ZcodeHome -Filter 'zcode.cjs.backup-*' -File -ErrorAction SilentlyContinue |
                        Sort-Object LastWriteTime -Descending |
                        Where-Object {
                            try { -not ([System.IO.File]::ReadAllText($_.FullName).Contains($cjsInjectMarker)) } catch { $false }
                        } |
                        Select-Object -First 1 -ExpandProperty FullName)
                }
                if ($cjsBackup -and (Test-Path -LiteralPath $cjsBackup)) {
                    Copy-Item -LiteralPath $cjsBackup -Destination $systemPromptPath -Force -ErrorAction Stop
                    Write-Host "Restored system prompt -> $systemPromptPath"
                } else {
                    $cjsFixed = $false
                    Write-Host "!! 系统提示词仍含注入内容，但未找到可用备份。请到 $systemPromptPath 手动恢复，或重装 ZCode。" -ForegroundColor Red
                }
            } else {
                Write-Host "System prompt is clean, nothing to restore"
            }
        } else {
            Write-Host "System prompt file not found (ZCode 可能已卸载/换位置), skipped"
        }

        Remove-Item -LiteralPath $statePath -Force -ErrorAction SilentlyContinue

        # 4. 卸载结果校验（供上层 UI 显示真实状态）
        $verify = @()
        if (Test-Path -LiteralPath $agentsPath) {
            $a = Read-Utf8 $agentsPath
            if ($a -match 'CTF-LAB|寒霜|Seagull') { $verify += 'AGENTS.md 仍含注入内容' }
        }
        $memFile = Join-Path $memoryRoot 'seagull-agents.md'
        if (Test-Path -LiteralPath $memFile) { $verify += '记忆文件 seagull-agents.md 仍存在' }
        if ($systemPromptPath -and (Test-Path -LiteralPath $systemPromptPath)) {
            $c = [System.IO.File]::ReadAllText($systemPromptPath)
            if ($c.Contains($cjsInjectMarker)) { $verify += '系统提示词 zcode.cjs 仍被注入' }
        }
        if ($verify.Count -gt 0) {
            Write-Host ("残留: " + ($verify -join '; ')) -ForegroundColor Red
            exit 2
        }
        Write-Host "Uninstalled. Restart ZCode to apply."
        exit 0
    } catch {
        Write-Host ("卸载失败: " + $_.Exception.Message) -ForegroundColor Red
        Write-Host $_.ScriptStackTrace -ForegroundColor Red
        exit 1
    }
}

# ---------- 安装 ----------
try {
    Write-Host "=== ZCode 一键安装工具 ==="
    Write-Host "ZCode home:    $ZcodeHome"
    Write-Host "Prompt source: $SourcePrompt"
    Write-Host "Memory source: $MemorySourcePrompt"
    Write-Host "Workspace:     $WorkspacePath"
    Write-Host "Memory target: $memoryRoot"
    Write-Host ""

    # 1. 备份并安装 AGENTS.md
    $agentsBackup = $null
    if (Test-Path -LiteralPath $agentsPath) {
        $agentsBackup = Join-Path $ZcodeHome "AGENTS.md.backup-$(Get-Date -Format 'yyyyMMdd-HHmmss')"
        Copy-Item -LiteralPath $agentsPath -Destination $agentsBackup -Force
        Write-Host "[1/4] Backed up existing AGENTS.md -> $agentsBackup"
    }
    New-Item -ItemType Directory -Force -Path $ZcodeHome | Out-Null
    Copy-Item -LiteralPath $SourcePrompt -Destination $agentsPath -Force
    Write-Host "[1/4] Installed prompt -> $agentsPath"

    # 2. 安装记忆（从完整版提示词生成 seagull-agents.md）
    $installedMemories = @()
    if (Test-Path -LiteralPath $MemorySourcePrompt -PathType Leaf) {
        New-Item -ItemType Directory -Force -Path $memoryRoot | Out-Null
        # 开启 zcode 记忆功能（setting.json 的 memoryEnabled）
        $settingPath = Join-Path $ZcodeHome 'v2\setting.json'
        if (Test-Path -LiteralPath $settingPath) {
            try {
                $st = Read-Utf8 $settingPath
                if ($st -match '"memoryEnabled"\s*:\s*false') {
                    $st = $st -replace '"memoryEnabled"\s*:\s*false', '"memoryEnabled": true'
                    Write-Utf8NoBom $settingPath $st
                    Write-Host "      Memory enabled: setting.json -> true"
                }
            } catch { }
        }
        $memName = 'seagull-agents.md'
        $memPath = Join-Path $memoryRoot $memName
        $promptText = Read-Utf8 $MemorySourcePrompt
        $memText = "---`nname: seagull-agents`ndescription: 海鸥完整配置（CTF-LAB-2.0 Seagull Edition）——身份、路由、交付标准`nmetadata:`n  type: reference`n---`n`n" + $promptText
        Write-Utf8NoBom $memPath $memText
        $installedMemories += $memName
        # 更新 MEMORY.md 索引
        $indexPath = Join-Path $memoryRoot 'MEMORY.md'
        $indexLines = @()
        if (Test-Path -LiteralPath $indexPath) {
            $indexLines = @(Get-Content -LiteralPath $indexPath -Encoding UTF8 | Where-Object { $_ -and $_ -notmatch '^\s*$' })
        }
        $line = "- [seagull-agents]($memName) - 海鸥完整配置（CTF-LAB-2.0 Seagull Edition）——身份、路由、交付标准"
        $indexLines = @($indexLines | Where-Object { $_ -notmatch [regex]::Escape("($memName)") })
        $indexLines += $line
        Write-Utf8NoBom $indexPath (($indexLines -join [Environment]::NewLine) + [Environment]::NewLine)
        Write-Host "[2/4] Installed memory -> $memPath"
        Write-Host "      Index updated: MEMORY.md"
    } else {
        Write-Host "[2/4] No memory source at $MemorySourcePrompt, skipped"
    }

    # 2.5 同步技能到 zcode（默认 codex-skills，V4 可传 codex-skills-v4；robocopy 加速）
    $installedSkills = @()
    if ([string]::IsNullOrWhiteSpace($SkillsSource)) {
        $skillsSource = Join-Path $PSScriptRoot 'codex-skills'
    } else {
        $skillsSource = Join-Path $PSScriptRoot $SkillsSource
    }
    $skillsTarget = Join-Path $ZcodeHome 'skills'
    if (Test-Path -LiteralPath $skillsSource) {
        New-Item -ItemType Directory -Force -Path $skillsTarget | Out-Null
        $skillDirs = @(Get-ChildItem -LiteralPath $skillsSource -Directory -ErrorAction SilentlyContinue |
            Where-Object { Test-Path -LiteralPath (Join-Path $_.FullName 'SKILL.md') })
        foreach ($d in $skillDirs) {
            $dest = Join-Path $skillsTarget $d.Name
            if (Test-Path -LiteralPath $dest) {
                Remove-Item -LiteralPath $dest -Recurse -Force -ErrorAction SilentlyContinue
            }
            Copy-ManyFiles $d.FullName $dest
            $installedSkills += $d.Name
        }
        Write-Host "[2.5/4] Synced $($installedSkills.Count) skills -> $skillsTarget"
    } else {
        Write-Host "[2.5/4] No codex-skills dir, skipped"
    }

    # 3. 可选：patch 系统提示词（探测含盘符扫描，自定义安装位置也能找到）
    $systemPromptBackup = $null
    if ($PatchSystemPrompt -and $systemPromptPath) {
        $content = [System.IO.File]::ReadAllText($systemPromptPath)
        if ($content.Contains('CTF-LAB-2.0')) {
            Write-Host "[3/4] System prompt already replaced with Seagull config, skipped"
        } elseif ($content.Contains('function u9o') -and $content.Contains('function Alt')) {
            $systemPromptBackup = Join-Path $ZcodeHome "zcode.cjs.backup-$(Get-Date -Format 'yyyyMMdd-HHmmss')"
            Copy-Item -LiteralPath $systemPromptPath -Destination $systemPromptBackup -Force
            # 读取海鸥完整配置，生成 JS 字符串字面量（ConvertTo-Json 转义）
            $seagull = Read-Utf8 $MemorySourcePrompt
            $seagullJs = $seagull | ConvertTo-Json -Compress
            # 1. 整体替换 u9o 函数（直接返回海鸥配置）
            $start = $content.IndexOf('function u9o')
            $end = $content.IndexOf('function Alt', $start)
            $newFunc = 'function u9o(e){return' + $seagullJs + '}'
            $content = $content.Substring(0, $start) + $newFunc + $content.Substring($end)
            # 2. 清空 s9o（CLI Prefix: "You are ZCode, an interactive coding agent"）
            $content = $content.Replace('s9o="You are ZCode, an interactive coding agent"', 's9o=""')
            # 3. 清空 Xlt beforeDefault（沟通指南）
            $xIdx = $content.IndexOf('Xlt={')
            $bd = $content.IndexOf('beforeDefault:[', $xIdx)
            $j = $content.IndexOf('.join', $bd)
            if ($bd -ge 0 -and $j -gt $bd) {
                $arrEnd = $content.LastIndexOf(']', $j, ($j - $bd))
                if ($arrEnd -gt $bd) {
                    $content = $content.Substring(0, $bd) + 'beforeDefault:[]' + $content.Substring($arrEnd + 1)
                }
            }
            [System.IO.File]::WriteAllText($systemPromptPath, $content, $Utf8)
            Write-Host "[3/4] Replaced system prompt with Seagull config -> $systemPromptPath"
            Write-Host "      Backup: $systemPromptBackup"
            if (-not $content.Contains('CTF-LAB-2.0')) {
                Write-Host "      警告: 当前版本 ZCode 无 u9o/s9o 特征，可能未生效" -ForegroundColor Yellow
            }
        } else {
            Write-Host "[3/4] u9o function not found, skipped"
        }
    } else {
        if ($PatchSystemPrompt) {
            Write-Host "[3/4] 未找到 ZCode 安装目录（提示词 + 记忆 + 技能已注入，仅系统提示词未 patch）" -ForegroundColor Yellow
            Write-Host "      若 ZCode 装在非常规路径，请先启动一次 ZCode 再重新注入"
        } else {
            Write-Host "[3/4] System prompt patch skipped (use -PatchSystemPrompt)"
        }
    }

    # 4. 记录安装状态
    $state = [ordered]@{
        installedAt = (Get-Date).ToString('o')
        zcodeHome = $ZcodeHome
        agentsPath = $agentsPath
        agentsBackup = $agentsBackup
        memoryRoot = $memoryRoot
        installedMemories = $installedMemories
        installedSkills = $installedSkills
        systemPromptPath = $systemPromptPath
        systemPromptBackup = $systemPromptBackup
    }
    Write-Utf8NoBom $statePath (($state | ConvertTo-Json -Depth 3) + [Environment]::NewLine)
    Write-Host "[4/4] State saved -> $statePath"
    Write-Host ""
    Write-Host "=== 安装完成 ==="
    Write-Host "重启 ZCode 生效。"
    Write-Host "卸载：运行本脚本加 -Uninstall 参数。"
    exit 0
} catch {
    Write-Host ("安装失败: " + $_.Exception.Message) -ForegroundColor Red
    Write-Host $_.ScriptStackTrace -ForegroundColor Red
    exit 1
}
