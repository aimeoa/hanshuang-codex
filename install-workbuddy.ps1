# install-workbuddy.ps1 — WorkBuddy AI 破甲：全局记忆 + 文件记忆 + skills 一键装/卸
#
# 注入点（全部实测确认，见 app.asar 内 user-memory-collector.ts / path-resolver.ts /
# working-memory-reminder-section.ts / domains-skills skill-overrides.ts）：
#   1) <ConfigDir>\memory\<uid>_memory.md          账号级云记忆档案；memoryBlock 每轮自动包成
#                                                  <memory>…</memory> 注入系统提示词（上限 10000 字符）
#                                                  写入 Version: 999999 触发 stale_version 守卫，防云端回写覆盖
#   2) <ConfigDir>\MEMORY.md                       用户级文件记忆（每轮提醒 AI 主动读，兜底）
#   3) <ConfigDir>\app\app-config.json             generateMemoryEnabled（云记忆总闸）/ localMemoryEnabled
#   4) <ConfigDir>\skills\<name>\SKILL.md          用户级 Skills；开关态在 settings.json 的 skillOverrides
#
# <ConfigDir> 解析：-ConfigDir > cli\product.json 的 dataFolderName > ~\.workbuddy-ai > ~\.workbuddy
# uid 解析：-Uid > <ConfigDir>\memory\*_memory.md 文件名 > 未找到则跳过云记忆（明确打印「未执行」）
#
# 用法：
#   .\install-workbuddy.ps1                                  # 一键：寒霜V4 + V4 技能库
#   .\install-workbuddy.ps1 -SourcePrompt .\寒霜v3.md        # 指定提示词
#   .\install-workbuddy.ps1 -SkillsSource codex-skills-v4    # 指定技能库目录
#   .\install-workbuddy.ps1 -NoSkills                        # 只注入记忆，不装 skills
#   .\install-workbuddy.ps1 -KillApp -Restart                # 注入前结束进程、注入后拉起
#   .\install-workbuddy.ps1 -Uninstall                       # 一键还原（记忆 + 开关 + skills）
#   .\install-workbuddy.ps1 -Status                          # 只读状态

[CmdletBinding()]
param(
    [ValidateSet('v4', 'v3', 'v2')]
    [string]$Version = 'v4',
    [string]$SourcePrompt,
    [string]$SkillsSource,
    [string]$Uid,
    [string]$ConfigDir,
    [string]$InstallRoot,
    [string]$ScriptRoot,
    [switch]$NoSkills,
    [switch]$KillApp,
    [switch]$Restart,
    [switch]$Uninstall,
    [switch]$Status
)

$ErrorActionPreference = 'Stop'

# 诊断日志：出错时让对方把 %TEMP%\workbuddy-inject.log 发回来（UTF-8 落盘，不受控制台编码影响）
$LogFile = Join-Path $env:TEMP 'workbuddy-inject.log'
function Write-Log([string]$m) {
    try {
        Add-Content -LiteralPath $LogFile -Value ("[{0}] {1}" -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'), $m) -Encoding UTF8
    } catch { }
}
trap {
    $errText = ($_ | Out-String)
    Write-Log "FATAL: $errText"
    Write-Host "[致命错误] 详情已写入 $LogFile" -ForegroundColor Red
    Write-Host $errText -ForegroundColor Red
    exit 1
}
Write-Log ("=== 启动 === PSVersion={0} UICulture={1} Script={2} Temp={3}" -f `
    $PSVersionTable.PSVersion, [System.Globalization.CultureInfo]::CurrentUICulture.Name, $PSCommandPath, $env:TEMP)

# 环境门槛：ConvertFrom-Json / [ordered] / Get-FileHash 需要 PowerShell 3+，这里按 5.1 要求
if ($PSVersionTable.PSVersion.Major -lt 5) {
    Write-Host "[环境不满足] 需要 PowerShell 5.1 及以上（当前 $($PSVersionTable.PSVersion.Major).$($PSVersionTable.PSVersion.Minor)）" -ForegroundColor Red
    Write-Host "             Win7 自带的 2.0 不支持，请先装 WMF 5.1（KB3191566）后重试" -ForegroundColor Red
    Write-Log "FATAL: PowerShell too old: $($PSVersionTable.PSVersion)"
    exit 3
}
$Root = if ($ScriptRoot) { $ScriptRoot } else { $PSScriptRoot }
if (-not $Root) { $Root = Split-Path -Parent $MyInvocation.MyCommand.Path }
$Utf8NoBom = New-Object System.Text.UTF8Encoding($false)
$MEM_VERSION = 999999      # 高版本号：程序写档案时 incoming < existing 会被判 stale_version 拒绝
$SKILL_MANIFEST = '.hanshuang-skills.json'

function Write-Utf8([string]$Path, [string]$Text) {
    $dir = Split-Path -Parent $Path
    if ($dir -and -not (Test-Path -LiteralPath $dir)) { New-Item -ItemType Directory -Path $dir -Force | Out-Null }
    $tmp = "$Path.tmp"
    [System.IO.File]::WriteAllText($tmp, $Text, $Utf8NoBom)
    Move-Item -LiteralPath $tmp -Destination $Path -Force
}
function Read-Utf8([string]$Path) { return [System.IO.File]::ReadAllText($Path, [System.Text.Encoding]::UTF8) }
function Get-Sha([string]$Path) {
    if (-not (Test-Path -LiteralPath $Path)) { return '' }
    return (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash
}
function Set-ArchiveReadOnly([string]$Path, [bool]$ReadOnly) {
    # 只读锁属于加固项：文件被运行中的应用占用 / 权限不足时会失败，
    # 这种情况只告警不中断（守护线程仍会按需补注入）
    if (-not (Test-Path -LiteralPath $Path)) { return }
    try {
        Set-ItemProperty -LiteralPath $Path -Name IsReadOnly -Value $ReadOnly -ErrorAction Stop
    } catch {
        Write-Host "  [提示] 只读锁设置失败(不影响注入生效): $(Split-Path -Leaf $Path)" -ForegroundColor Yellow
        Write-Log "只读锁失败 $Path"
    }
}
function Set-AppConfigFlags([string]$Path, [hashtable]$Patch) {
    # 不假设原文件结构：对象就合并，数组/字符串/坏 JSON 就留证据后重建，
    # 避免 `Add-Member`（对非对象会静默无效）或属性赋值（PropertyAssignmentException）出问题
    $cfg = $null
    if (Test-Path -LiteralPath $Path) {
        try { $cfg = Read-Utf8 $Path | ConvertFrom-Json } catch { $cfg = $null }
    }
    $merged = [ordered]@{}
    if ($cfg -is [System.Management.Automation.PSCustomObject]) {
        foreach ($prop in $cfg.PSObject.Properties) { $merged[$prop.Name] = $prop.Value }
    } elseif ($null -ne $cfg) {
        if (Test-Path -LiteralPath $Path) { Copy-Item -LiteralPath $Path -Destination "$Path.broken-inject" -Force }
        Write-Host "  [警告] app-config.json 结构异常，已另存 .broken-inject 并重建" -ForegroundColor Yellow
        Write-Log "app-config 结构异常，已重建"
    }
    foreach ($k in $Patch.Keys) { $merged[$k] = $Patch[$k] }
    if (-not $merged.Contains('locale')) { $merged['locale'] = 'zh-CN' }
    Write-Utf8 $Path (([pscustomobject]$merged | ConvertTo-Json -Depth 8) + "`n")
}

function Get-NowIso { return (Get-Date).ToUniversalTime().ToString('yyyy-MM-ddTHH:mm:ss.000Z') }

function Resolve-InstallRoot([string]$explicit) {
    # 只返回"真实存在"的目录：注册表常残留指向已卸载盘符的 InstallLocation
    # （例如 D:\ 但机器没有 D 盘），直接拿去 Join-Path 会抛 DriveNotFoundException 把安装打断
    $cands = @()
    if ($explicit) { $cands += $explicit }
    $proc = Get-Process WorkBuddyAI -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($proc -and $proc.Path) { $cands += (Split-Path -Parent $proc.Path) }
    foreach ($rp in @('HKLM:\Software\Microsoft\Windows\CurrentVersion\Uninstall\*',
                      'HKLM:\Software\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall\*',
                      'HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\*')) {
        $item = Get-ItemProperty $rp -ErrorAction SilentlyContinue |
            Where-Object { $_.DisplayName -like '*WorkBuddy*' -and $_.InstallLocation } | Select-Object -First 1
        if ($item) { $cands += ($item.InstallLocation -replace '^"|"$', '').TrimEnd('\') }
    }
    foreach ($c in $cands) {
        if (-not $c) { continue }
        try {
            if (Test-Path -LiteralPath $c -ErrorAction SilentlyContinue) { return (Resolve-Path -LiteralPath $c).Path }
            Write-Log "跳过无效安装目录(不存在): $c"
        } catch { Write-Log "跳过无效安装目录(异常): $c" }
    }
    return ''
}
function Resolve-ConfigDir([string]$explicit, [string]$root) {
    if ($explicit) { return $explicit }
    if ($root) {
        try {
            $pj = Join-Path $root 'resources\app.asar.unpacked\cli\product.json'
            if (Test-Path -LiteralPath $pj) {
                $name = (Read-Utf8 $pj | ConvertFrom-Json).dataFolderName
                if ($name) { return (Join-Path $env:USERPROFILE $name) }
            }
        } catch { Write-Log "读取 product.json 失败(忽略, 走默认目录)" }
    }
    foreach ($cand in @('.workbuddy-ai', '.workbuddy')) {
        $p = Join-Path $env:USERPROFILE $cand
        if (Test-Path -LiteralPath $p) { return $p }
    }
    return (Join-Path $env:USERPROFILE '.workbuddy')
}
function Find-OtherProfileConfigDirs([string]$primary) {
    # 以管理员身份运行时 $env:USERPROFILE 可能是 Administrator，
    # 而 WorkBuddy 的真实数据在别的 Windows 账户目录下 —— 这里把其它账户的配置目录也找出来
    $found = @()
    $usersRoot = Join-Path $env:SystemDrive 'Users'
    if (-not (Test-Path -LiteralPath $usersRoot)) { return $found }
    foreach ($u in (Get-ChildItem -LiteralPath $usersRoot -Directory -ErrorAction SilentlyContinue)) {
        foreach ($n in @('.workbuddy-ai', '.workbuddy')) {
            $cand = Join-Path $u.FullName $n
            if ((Test-Path -LiteralPath $cand) -and ($cand -ne $primary)) { $found += $cand }
        }
    }
    return $found
}

function Resolve-Uid([string]$explicit, [string]$configDir, [string]$root) {
    if ($explicit) { return $explicit }
    $memDir = Join-Path $configDir 'memory'
    if (Test-Path -LiteralPath $memDir) {
        $f = Get-ChildItem -LiteralPath $memDir -Filter '*_memory.md' -File -ErrorAction SilentlyContinue |
            Sort-Object LastWriteTime -Descending | Select-Object -First 1
        if ($f) { return ($f.Name -replace '_memory\.md$', '') }
    }
    if ($root) {
        $st = Join-Path $configDir 'settings.json'
        if (Test-Path -LiteralPath $st) {
            try {
                $s = Read-Utf8 $st | ConvertFrom-Json
                if ($s.claw.legacyOwnerUid) { return $s.claw.legacyOwnerUid }
            } catch { }
        }
    }
    return ''
}

# ---------- 解析 ----------
$promptMap = @{ 'v4' = '寒霜v4.md'; 'v3' = '寒霜v3.md'; 'v2' = '寒霜v1.2.md' }
if (-not $SourcePrompt) { $SourcePrompt = Join-Path $Root $promptMap[$Version] }
if (-not (Test-Path -LiteralPath $SourcePrompt)) { throw "提示词文件不存在: $SourcePrompt" }
if (-not $SkillsSource) { $SkillsSource = if ($Version -eq 'v4') { 'codex-skills-v4' } else { 'codex-skills' } }
$skillsSourceDir = Join-Path $Root $SkillsSource

$InstallRoot = Resolve-InstallRoot $InstallRoot
$ConfigDir = Resolve-ConfigDir $ConfigDir $InstallRoot
# 跨账户兜底：本账户目录里没有 WorkBuddy 数据（memory 子目录）时，改用它账户下真实存在的那份
if (-not (Test-Path -LiteralPath (Join-Path $ConfigDir 'memory'))) {
    $others = @(Find-OtherProfileConfigDirs $ConfigDir |
        Where-Object { Test-Path -LiteralPath (Join-Path $_ 'memory') })
    if ($others.Count -gt 0) {
        Write-Host "  [跨账户] 本账户($env:USERPROFILE)无 WorkBuddy 数据，改用: $($others[0])" -ForegroundColor Yellow
        Write-Log "跨账户切换: $ConfigDir -> $($others[0])"
        $ConfigDir = $others[0]
    }
}
$Uid = Resolve-Uid $Uid $ConfigDir $InstallRoot
$memDir = Join-Path $ConfigDir 'memory'
# 云记忆档案：指定 uid 时用该 uid 的文件（不存在则新建）；未指定则扫描该目录下所有 <uid>_memory.md
# （换机器/换账号时 uid 不同，靠扫描而不是硬编码，别人的机器同样能用）
$archFiles = @()
if ($Uid) {
    $archFiles = @(Join-Path $memDir "$Uid`_memory.md")
} elseif (Test-Path -LiteralPath $memDir) {
    $archFiles = @(Get-ChildItem -LiteralPath $memDir -Filter '*_memory.md' -File -ErrorAction SilentlyContinue |
        Where-Object { $_.Name -notlike '*.bak*' } |
        Sort-Object LastWriteTime -Descending | ForEach-Object { $_.FullName })
}
$fileMem = Join-Path $ConfigDir 'MEMORY.md'
$fileMemBak = "$fileMem.bak-inject"
$cfgFile = Join-Path $ConfigDir 'app\app-config.json'
$cfgBak = "$cfgFile.bak-inject"
$skillsDir = Join-Path $ConfigDir 'skills'
$settingsFile = Join-Path $ConfigDir 'settings.json'
$manifestFile = Join-Path $skillsDir $SKILL_MANIFEST
$stateFile = Join-Path $ConfigDir '.hanshuang-state.json'   # 给 fj_tool 守护线程读的注入状态

Write-Host "== WorkBuddy 破甲 ==" -ForegroundColor Cyan
Write-Host "  安装目录 : $(if ($InstallRoot) { $InstallRoot } else { '未找到（不影响注入）' })"
Write-Host "  配置目录 : $ConfigDir"
$variant = if ((Split-Path -Leaf $ConfigDir) -eq '.workbuddy') { '国版' } elseif ((Split-Path -Leaf $ConfigDir) -eq '.workbuddy-ai') { '国际版' } else { '自定义/品牌版' }
Write-Host "  版本判定 : $variant（数据目录 $(Split-Path -Leaf $ConfigDir)）" -ForegroundColor Cyan
Write-Host "  用户 uid : $(if ($Uid) { $Uid } elseif ($archFiles.Count -gt 0) { "自动扫描到 $($archFiles.Count) 个记忆档案" } else { '未找到 → 云记忆注入将跳过（脚本会自动重扫）' })"
Write-Host "  提示词   : $SourcePrompt"
Write-Host "  技能库   : $(if ($NoSkills) { '已禁用 (-NoSkills)' } elseif (Test-Path -LiteralPath $skillsSourceDir) { $skillsSourceDir } else { "找不到 $skillsSourceDir → 跳过" })"
if (-not $InstallRoot -and -not (Test-Path -LiteralPath $ConfigDir)) {
    Write-Host "  [警告] 未检测到 WorkBuddy 安装或其数据目录 —— 目标机器可能没装 WorkBuddy，注入将无效" -ForegroundColor Yellow
}

$proc = Get-Process WorkBuddyAI -ErrorAction SilentlyContinue
if ($proc) { Write-Host "  [注意] WorkBuddyAI 正在运行（$($proc.Count) 个进程），写入后需重启才生效" -ForegroundColor Yellow }
Write-Log ("解析结果 InstallRoot={0} ConfigDir={1} Uid={2} 档案数={3}" -f $InstallRoot, $ConfigDir, $Uid, $archFiles.Count)

function Set-SkillOverrides([string]$path, [string[]]$keys, [bool]$remove) {
    if (-not (Test-Path -LiteralPath $path)) { return }
    try { $obj = Read-Utf8 $path | ConvertFrom-Json } catch { return }
    if (-not $obj.skillOverrides) { return }
    $changed = $false
    foreach ($k in $keys) {
        if ($obj.skillOverrides.PSObject.Properties.Name -contains $k) {
            $obj.skillOverrides.PSObject.Properties.Remove($k); $changed = $true
        }
    }
    if ($changed) { Write-Utf8 $path (($obj | ConvertTo-Json -Depth 12) + "`n") }
}
function Get-SkillNames([string]$dir) {
    if (-not (Test-Path -LiteralPath $dir)) { return @() }
    return @(Get-ChildItem -LiteralPath $dir -Directory -ErrorAction SilentlyContinue |
        Where-Object { Test-Path -LiteralPath (Join-Path $_.FullName 'SKILL.md') } | ForEach-Object { $_.Name })
}

# ---------- 状态 ----------
if ($Status) {
    $srcHash = Get-Sha $SourcePrompt
    Write-Host "`n[状态]" -ForegroundColor Cyan
    $live = @($archFiles | Where-Object { Test-Path -LiteralPath $_ })
    if ($live.Count -eq 0) { Write-Host "  云记忆档案          : 未找到（该账号还没生成过记忆档案，或 WorkBuddy 未登录过）" }
    foreach ($af in $live) {
        $archText = Read-Utf8 $af
        $ver = [regex]::Match($archText, '(?m)^>\s*Version:\s*(\d+)').Groups[1].Value
        $mb = [regex]::Match($archText, '(?s)## Memory Block\r?\n\r?\n(.*?)\r?\n\r?\n---').Groups[1].Value
        Write-Host "  云记忆档案          : $af"
        Write-Host "  档案 Version        : $(if ($ver) { $ver } else { '-' })"
        Write-Host "  memoryBlock 字符数  : $($mb.Trim().Length)  (上限 10000)"
        Write-Host "  memoryBlock 首行    : $(($mb.Trim() -split "`n")[0])"
        Write-Host "  档案只读锁          : $((Get-Item -LiteralPath $af).IsReadOnly)   (True = 已挡住程序回写)"
    }
    Write-Host "  注入状态文件        : $(if (Test-Path -LiteralPath $stateFile) { '存在（守护会重注入）' } else { '不存在（守护不工作）' })"
    $cfg = if (Test-Path -LiteralPath $cfgFile) { Read-Utf8 $cfgFile | ConvertFrom-Json } else { $null }
    Write-Host "  generateMemoryEnabled: $(if ($cfg) { $cfg.generateMemoryEnabled } else { '-' })   (必须是 True 否则整条链路 skip)"
    Write-Host "  localMemoryEnabled  : $(if ($cfg) { $cfg.localMemoryEnabled } else { '-' })"
    Write-Host "  MEMORY.md           : $(if (Test-Path -LiteralPath $fileMem) { "$((Get-Item $fileMem).Length) bytes / 与提示词一致=$((Get-Sha $fileMem) -eq $srcHash)" } else { '不存在' })"
    $names = Get-SkillNames $skillsDir
    Write-Host "  skills 已装         : $($names.Count) 个  ($($names -join ', '))"
    $archBakCount = @($archFiles | Where-Object { Test-Path -LiteralPath "$_.bak-inject" }).Count
    Write-Host "  备份                : 档案=$archBakCount 个 开关=$(Test-Path -LiteralPath $cfgBak) 记忆=$(Test-Path -LiteralPath $fileMemBak)"
    return
}

# ---------- 卸载 ----------
if ($Uninstall) {
    $done = @()
    # 目标档案 = 本次扫描到的 + 状态文件里记录过的（换账号/换机器后仍能清干净）
    $targets = New-Object System.Collections.Generic.List[string]
    foreach ($a in $archFiles) { if ($a) { $targets.Add($a) } }
    if (Test-Path -LiteralPath $stateFile) {
        try {
            $st = Read-Utf8 $stateFile | ConvertFrom-Json
            foreach ($a in @($st.archives)) { if ($a -and -not $targets.Contains($a)) { $targets.Add($a) } }
            if ($st.archive -and -not $targets.Contains($st.archive)) { $targets.Add($st.archive) }
        } catch { }
    }
    foreach ($af in $targets) {
        Set-ArchiveReadOnly $af $false
        $bak = "$af.bak-inject"
        if (Test-Path -LiteralPath $bak) {
            Move-Item -LiteralPath $bak -Destination $af -Force
            $done += "档案已从备份还原: $(Split-Path -Leaf $af)"
        } elseif (Test-Path -LiteralPath $af) {
            $uidNow = (Split-Path -Leaf $af) -replace '_memory\.md$', ''
            $now = Get-NowIso
            $empty = "# User Memory Profile`n> Last updated: $now`n> Version: $MEM_VERSION`n`n## Memory Block`n`n`n`n---`n`n<!-- RAW_JSON_START`n{`n  `"uid`": `"$uidNow`",`n  `"memoryBlock`": `"`",`n  `"updatedAt`": `"$now`",`n  `"version`": $MEM_VERSION`n}`nRAW_JSON_END -->`n"
            Write-Utf8 $af $empty
            $done += "档案 memoryBlock 已清空: $(Split-Path -Leaf $af)"
        }
    }
    if ($targets.Count -eq 0) { $done += '云记忆档案未执行（该账号还没有档案文件）' }
    if (Test-Path -LiteralPath $stateFile) { Remove-Item -LiteralPath $stateFile -Force; $done += '注入状态文件已删除（守护停止重注入）' }

    if (Test-Path -LiteralPath $fileMemBak) {
        Move-Item -LiteralPath $fileMemBak -Destination $fileMem -Force
        $done += 'MEMORY.md 已从备份还原'
    } elseif (Test-Path -LiteralPath $fileMem) {
        Remove-Item -LiteralPath $fileMem -Force
        $done += 'MEMORY.md 已删除（无备份）'
    }

    if (Test-Path -LiteralPath $cfgBak) {
        Move-Item -LiteralPath $cfgBak -Destination $cfgFile -Force
        $done += 'app-config.json 已从备份还原'
    } elseif (Test-Path -LiteralPath $cfgFile) {
        Set-AppConfigFlags $cfgFile @{ generateMemoryEnabled = $false; localMemoryEnabled = $false }
        $done += 'app-config.json 无备份：两个记忆开关已置 false'
    }

    if (Test-Path -LiteralPath $manifestFile) {
        $manifest = Read-Utf8 $manifestFile | ConvertFrom-Json
        $removed = 0; $kept = 0
        foreach ($p in $manifest.skills.PSObject.Properties) {
            $name = $p.Name; $sha = $p.Value.sha256
            $dir = Join-Path $skillsDir $name
            $skillMd = Join-Path $dir 'SKILL.md'
            if ((Test-Path -LiteralPath $skillMd) -and (Get-Sha $skillMd) -eq $sha) {
                Remove-Item -LiteralPath $dir -Recurse -Force; $removed++
            } elseif (Test-Path -LiteralPath $dir) { $kept++ }
        }
        Remove-Item -LiteralPath $manifestFile -Force
        Set-SkillOverrides $settingsFile @($manifest.skills.PSObject.Properties.Name) $true
        $done += "skills 已卸载 $removed 个（用户自行改过的保留 $kept 个）"
    } else { $done += 'skills 未执行（无安装清单）' }

    Write-Host "`n[还原结果]" -ForegroundColor Green
    $done | ForEach-Object { Write-Host "  - $_" }
    if (Test-Path -LiteralPath $cfgFile) {
        $c = Read-Utf8 $cfgFile | ConvertFrom-Json
        Write-Host "  现值: generateMemoryEnabled=$($c.generateMemoryEnabled) localMemoryEnabled=$($c.localMemoryEnabled)"
    }
    return
}

# ---------- 安装 ----------
if ($KillApp -and $proc) {
    Stop-Process -Name WorkBuddyAI -Force -ErrorAction SilentlyContinue
    Start-Sleep -Seconds 3
    Write-Host "  已结束 WorkBuddyAI 进程" -ForegroundColor Yellow
}

$srcText = Read-Utf8 $SourcePrompt
$srcHash = Get-Sha $SourcePrompt
$now = Get-NowIso
$steps = 0

# 1) 账号级云记忆档案（真正被自动注入的全局记忆）
if ($archFiles.Count -gt 0) {
    if (-not (Test-Path -LiteralPath $memDir)) { New-Item -ItemType Directory -Path $memDir -Force | Out-Null }
    $archFailed = @()
    foreach ($af in $archFiles) {
        $afBak = "$af.bak-inject"
        if ((Test-Path -LiteralPath $af) -and -not (Test-Path -LiteralPath $afBak)) {
            try {
                $oldBlock = [regex]::Match((Read-Utf8 $af), '(?s)## Memory Block\r?\n\r?\n(.*?)\r?\n\r?\n---').Groups[1].Value.Trim()
                if ($oldBlock -ne $srcText.Trim()) { Copy-Item -LiteralPath $af -Destination $afBak -Force }
            } catch { Write-Log "读取/备份档案失败(继续): $af" }
        }
        Set-ArchiveReadOnly $af $false
        $uidOfFile = if (Test-Path -LiteralPath $af) { ((Read-Utf8 $af) | Select-String -Pattern '"uid"\s*:\s*"([^"]+)"' | ForEach-Object { $_.Matches[0].Groups[1].Value } | Select-Object -First 1) } else { $null }
        if (-not $uidOfFile) { $uidOfFile = (Split-Path -Leaf $af) -replace '_memory\.md$', '' }
        $raw = [ordered]@{ uid = $uidOfFile; memoryBlock = $srcText; updatedAt = $now; version = $MEM_VERSION }
        $md = "# User Memory Profile`n> Last updated: $now`n> Version: $MEM_VERSION`n`n## Memory Block`n`n$srcText`n`n---`n`n<!-- RAW_JSON_START`n" +
              ($raw | ConvertTo-Json -Depth 6) + "`nRAW_JSON_END -->`n"
        # 档案可能被运行中的 WorkBuddy 占用（共享冲突）→ 重试 3 次，仍失败只记不中断
        $written = $false
        for ($try = 1; $try -le 3; $try++) {
            try { Write-Utf8 $af $md; $written = $true; break }
            catch { Write-Log "档案写入失败(第 $try 次): $af"; Start-Sleep -Milliseconds 800 }
        }
        if (-not $written) {
            $archFailed += $af
            Write-Host "  [失败] 档案被占用，写入失败: $(Split-Path -Leaf $af)" -ForegroundColor Red
            continue
        }
        # 只读锁定：程序写档案走 tmp+rename，Windows 上 rename 覆盖只读文件会 EPERM，从而挡住空档案回写
        Set-ArchiveReadOnly $af $true
    }
    $steps++
    Write-Host "[$steps] 云记忆档案已注入 memoryBlock：$($archFiles.Count) 个（$($srcText.Trim().Length) 字符，Version $MEM_VERSION，已设只读）" -ForegroundColor Green
    foreach ($af in $archFiles) { Write-Host "      - $af" -ForegroundColor DarkGray }
} else {
    Write-Host "[1] 云记忆档案未执行：该账号还没有记忆档案文件（WorkBuddy 未登录或从未产生记忆）" -ForegroundColor Yellow
    Write-Host "      处理：先在 WorkBuddy 里发一句话再重跑本脚本；或安装后由 fj_tool 守护自动补注入" -ForegroundColor DarkGray
}

# 2) 用户级文件记忆（AI 主动读取的兜底）
if ((Test-Path -LiteralPath $fileMem) -and -not (Test-Path -LiteralPath $fileMemBak) -and (Get-Sha $fileMem) -ne $srcHash) {
    Copy-Item -LiteralPath $fileMem -Destination $fileMemBak -Force
}
try { Write-Utf8 $fileMem $srcText }
catch { Write-Host "  [提示] MEMORY.md 写入失败（可能被占用），已跳过" -ForegroundColor Yellow; Write-Log "MEMORY.md 写入失败" }
$steps++
Write-Host "[$steps] MEMORY.md 已写入 $((Get-Item $fileMem).Length) bytes" -ForegroundColor Green

# 3) 记忆总闸
if (-not (Test-Path -LiteralPath (Split-Path -Parent $cfgFile))) {
    New-Item -ItemType Directory -Path (Split-Path -Parent $cfgFile) -Force | Out-Null
}
if ((Test-Path -LiteralPath $cfgFile) -and -not (Test-Path -LiteralPath $cfgBak)) {
    Copy-Item -LiteralPath $cfgFile -Destination $cfgBak -Force
}
Set-AppConfigFlags $cfgFile @{ generateMemoryEnabled = $true; localMemoryEnabled = $true }
$steps++
Write-Host "[$steps] generateMemoryEnabled = true（备份: $cfgBak）" -ForegroundColor Green

# 4) Skills
$installedNames = @()
if ($NoSkills) {
    Write-Host "[$steps] skills 未执行（-NoSkills）" -ForegroundColor DarkGray
} elseif (-not (Test-Path -LiteralPath $skillsSourceDir)) {
    Write-Host "[$steps] skills 未执行（找不到 $skillsSourceDir）" -ForegroundColor Yellow
} else {
    New-Item -ItemType Directory -Path $skillsDir -Force | Out-Null
    $manifest = [ordered]@{ source = $SkillsSource; installedAt = $now; prompt = (Split-Path -Leaf $SourcePrompt); skills = [ordered]@{} }
    foreach ($name in Get-SkillNames $skillsSourceDir) {
        $s = Join-Path $skillsSourceDir $name; $d = Join-Path $skillsDir $name
        if (-not (Test-Path -LiteralPath $d)) { New-Item -ItemType Directory -Path $d -Force | Out-Null }
        Copy-Item -Path (Join-Path $s '*') -Destination $d -Recurse -Force
        $manifest.skills[$name] = [ordered]@{ sha256 = (Get-Sha (Join-Path $d 'SKILL.md')) }
    }
    Write-Utf8 $manifestFile (($manifest | ConvertTo-Json -Depth 6) + "`n")
    $installedNames = @($manifest.skills.Keys)
    # 清掉可能把这些技能禁用的 override（settings.json 的 skillOverrides：无 key = 启用）
    Set-SkillOverrides $settingsFile $installedNames $true
    $steps++
    Write-Host "[$steps] skills 已装 $($installedNames.Count) 个 → $skillsDir" -ForegroundColor Green
}

# 5) 注入状态文件（fj_tool 守护线程据此自动重注入）
$state = [ordered]@{
    prompt       = (Split-Path -Leaf $SourcePrompt)
    promptSha256 = $srcHash
    configDir    = $ConfigDir
    uid          = $Uid
    memoryDir    = $memDir
    archives     = $archFiles
    archive      = $(if ($archFiles.Count -gt 0) { $archFiles[0] } else { '' })
    memoryFile   = $fileMem
    appConfig    = $cfgFile
    version      = $MEM_VERSION
    skills       = $installedNames
    installedAt  = $now
}
Write-Utf8 $stateFile (($state | ConvertTo-Json -Depth 6) + "`n")
$steps++
Write-Host "[$steps] 注入状态已记录 → $stateFile" -ForegroundColor Green

# ---------- 校验 ----------
Write-Host "`n[校验]" -ForegroundColor Cyan
$ok = $true
foreach ($af in @($archFiles | Where-Object { Test-Path -LiteralPath $_ })) {
    $t = Read-Utf8 $af
    $blockOk = [regex]::Match($t, '(?s)## Memory Block\r?\n\r?\n(.*?)\r?\n\r?\n---').Groups[1].Value.Trim() -eq $srcText.Trim()
    $rawOk = $t -match '"memoryBlock"'
    Write-Host "  档案 memoryBlock 可解析 : $blockOk  ($(Split-Path -Leaf $af))"
    Write-Host "  档案 RAW_JSON 存在      : $rawOk"
    if (-not ($blockOk -and $rawOk)) { $ok = $false }
}
$c = Read-Utf8 $cfgFile | ConvertFrom-Json
Write-Host "  generateMemoryEnabled   : $($c.generateMemoryEnabled)"
if ($c.generateMemoryEnabled -ne $true) { $ok = $false }
Write-Host "  MEMORY.md 哈希一致      : $((Get-Sha $fileMem) -eq $srcHash)"
if ($installedNames.Count -gt 0) { Write-Host "  skills 落盘             : $((Get-SkillNames $skillsDir).Count) 个" }

if ($ok -and $archFailed.Count -gt 0) {
    Write-Log "部分完成: 档案写入失败 $($archFailed.Count) 个"
    Write-Host "`n[部分完成] 云记忆档案被占用，未能写入：" -ForegroundColor Yellow
    foreach ($x in $archFailed) { Write-Host "           - $x" -ForegroundColor Yellow }
    Write-Host "           最常见原因：WorkBuddy 正在运行并占用该文件。" -ForegroundColor Yellow
    Write-Host "           处理：完全退出 WorkBuddy（托盘右键退出）后重跑；开关/记忆文件/skills 已生效。" -ForegroundColor Yellow
    exit 2
}
if ($ok) {
    Write-Log "完成: 校验全部通过"
    Write-Host "`n[完成] WorkBuddy 破甲注入成功" -ForegroundColor Green
    if ($proc -and -not $KillApp) { Write-Host "  下一步：完全退出 WorkBuddyAI（托盘右键退出）后重新启动" -ForegroundColor Yellow }
    if ($Restart) {
        $exe = if ($InstallRoot) { Join-Path $InstallRoot 'WorkBuddyAI.exe' } else { '' }
        if ($exe -and (Test-Path -LiteralPath $exe)) {
            Start-Process -FilePath $exe | Out-Null
            Write-Host "  已重新拉起 WorkBuddyAI" -ForegroundColor Green
        } else { Write-Host "  未执行：未找到 WorkBuddyAI.exe，请手动启动" -ForegroundColor Yellow }
    }
    Write-Host "  生效验证：发一句话后看日志 memory_injection_success" -ForegroundColor DarkGray
    Write-Host "  还原命令：.\install-workbuddy.ps1 -Uninstall" -ForegroundColor DarkGray
} else {
    Write-Log "中断: 校验未通过（见上方失败项）"
    Write-Host "`n[中断] 校验未通过，检查上面的失败项" -ForegroundColor Red
    exit 1
}
