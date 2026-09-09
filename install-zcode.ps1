[CmdletBinding()]
param(
    [string]$ZcodeHome,
    [string]$SourcePrompt,
    [string]$MemorySourcePrompt,
    [string]$WorkspacePath,
    [switch]$PatchSystemPrompt,
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

function Get-Sha256Hex([string]$Text) {
    $sha = [System.Security.Cryptography.SHA256]::Create()
    $bytes = $sha.ComputeHash([System.Text.Encoding]::UTF8.GetBytes($Text))
    return ($bytes | ForEach-Object { $_.ToString('x2') }) -join ''
}

function Get-SanitizedSlug([string]$Name) {
    $slug = $Name.ToLower() -replace '[^a-z0-9._-]+', '-' -replace '^-+|-+$', ''
    if ($slug.Length -gt 48) { $slug = $slug.Substring(0, 48) }
    if ($slug.Length -eq 0) { $slug = 'project' }
    return $slug
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

# 系统提示词（可选 patch）：自动检测 zcode 安装位置
$systemPromptPath = $null
# 1. 从运行中的 ZCode 进程定位
$zcProc = Get-Process ZCode -ErrorAction SilentlyContinue | Select-Object -First 1
if ($zcProc -and $zcProc.Path) {
    $candidate = Join-Path (Split-Path $zcProc.Path -Parent) 'resources\glm\zcode.cjs'
    if (Test-Path -LiteralPath $candidate) { $systemPromptPath = $candidate }
}
# 2. 注册表卸载项
if (-not $systemPromptPath) {
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
            if (Test-Path -LiteralPath $candidate) { $systemPromptPath = $candidate; break }
        }
    }
}
# 3. 常见安装位置
if (-not $systemPromptPath) {
    $candidates = @(
        'C:\Program Files\ZCode\resources\glm\zcode.cjs',
        'C:\Program Files (x86)\ZCode\resources\glm\zcode.cjs',
        "$env:LOCALAPPDATA\Programs\ZCode\resources\glm\zcode.cjs",
        "$env:APPDATA\ZCode\resources\glm\zcode.cjs"
    )
    $systemPromptPath = $candidates | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
}

# ---------- 卸载 ----------
if ($Uninstall) {
    $hadState = Test-Path -LiteralPath $statePath
    $state = $null
    if ($hadState) {
        try { $state = Read-Utf8 $statePath | ConvertFrom-Json } catch { $state = $null }
    }

    # 1. 恢复 AGENTS.md
    if ($state -and $state.agentsBackup -and (Test-Path -LiteralPath $state.agentsBackup)) {
        Copy-Item -LiteralPath $state.agentsBackup -Destination $agentsPath -Force
        Write-Host "Restored AGENTS.md from backup"
    } elseif (Test-Path -LiteralPath $agentsPath) {
        Remove-Item -LiteralPath $agentsPath -Force -ErrorAction SilentlyContinue
        Write-Host "Removed AGENTS.md (no backup found)"
    }

    # 2. 删除安装的记忆文件（只删我们装的）
    if ($state -and $state.installedMemories) {
        foreach ($m in $state.installedMemories) {
            $p = Join-Path $memoryRoot $m
            if (Test-Path -LiteralPath $p) {
                Remove-Item -LiteralPath $p -Force -ErrorAction SilentlyContinue
                Write-Host "Removed memory: $m"
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

    # 3. 恢复系统提示词
    if ($state -and $state.systemPromptBackup -and (Test-Path -LiteralPath $state.systemPromptBackup)) {
        Copy-Item -LiteralPath $state.systemPromptBackup -Destination $state.systemPromptPath -Force
        Write-Host "Restored system prompt: $($state.systemPromptPath)"
    }

    Remove-Item -LiteralPath $statePath -Force -ErrorAction SilentlyContinue
    Write-Host "Uninstalled. Restart ZCode to apply."
    exit 0
}

# ---------- 安装 ----------
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

# 2.5 同步技能到 zcode（codex-skills -> ~/.zcode/skills）
$installedSkills = @()
$skillsSource = Join-Path $PSScriptRoot 'codex-skills'
$skillsTarget = Join-Path $ZcodeHome 'skills'
if (Test-Path -LiteralPath $skillsSource) {
    New-Item -ItemType Directory -Force -Path $skillsTarget | Out-Null
    $skillDirs = @(Get-ChildItem -LiteralPath $skillsSource -Directory -ErrorAction SilentlyContinue |
        Where-Object { Test-Path -LiteralPath (Join-Path $_.FullName 'SKILL.md') })
    foreach ($d in $skillDirs) {
        $dest = Join-Path $skillsTarget $d.Name
        Copy-Item -LiteralPath $d.FullName -Destination $dest -Recurse -Force
        $installedSkills += $d.Name
    }
    Write-Host "[2.5/4] Synced $($installedSkills.Count) skills -> $skillsTarget"
} else {
    Write-Host "[2.5/4] No codex-skills dir, skipped"
}

# 3. 可选：patch 系统提示词
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
    } else {
        Write-Host "[3/4] u9o function not found, skipped"
    }
} else {
    Write-Host "[3/4] System prompt patch skipped (use -PatchSystemPrompt)"
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
