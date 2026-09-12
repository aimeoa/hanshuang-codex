[CmdletBinding()]
param(
    [string]$SourcePrompt,
    [switch]$Uninstall
)

Set-StrictMode -Off
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'

$Utf8 = New-Object System.Text.UTF8Encoding($false)

function Read-Utf8([string]$Path) {
    return [System.IO.File]::ReadAllText($Path, [System.Text.Encoding]::UTF8)
}

function Write-Utf8NoBom([string]$Path, [string]$Text) {
    [System.IO.File]::WriteAllText($Path, $Text, $Utf8)
}

# Cursor 全局 User Rules 目录探测（覆盖标准安装 / 便携版 / 自定义 --user-data-dir）
$ruleFile = '寒霜注入.mdc'
$legacyRuleFile = '.cursorrules'
$marker = '<!-- HANSHUANG-CURSOR-INJECT -->'
$statePath = Join-Path $env:APPDATA 'Cursor\hs-install-state.json'

function Get-RulesCandidates {
    $cands = @()
    # 官方全局规则目录（用户主目录）——主路径，Cursor 实际读取这里
    if (-not [string]::IsNullOrWhiteSpace($HOME)) {
        $cands += (Join-Path $HOME '.cursor\rules')
    }
    foreach ($base in @($env:APPDATA, $env:LOCALAPPDATA)) {
        if ([string]::IsNullOrWhiteSpace($base)) { continue }
        $cands += (Join-Path $base 'Cursor\User\rules')
        $cands += (Join-Path $base 'Cursor\rules')
    }
    # 正在运行的 Cursor 若用了自定义 --user-data-dir，规则目录跟它走
    try {
        $procs = Get-Process -Name 'Cursor','cursor' -ErrorAction SilentlyContinue
        foreach ($p in $procs) {
            $cmd = $null
            try {
                $cmd = (Get-CimInstance Win32_Process -Filter "ProcessId=$($p.Id)" -ErrorAction SilentlyContinue).CommandLine
            } catch { }
            if ($cmd -and $cmd -match '--user-data-dir[= ]"?([^"\s]+)"?') {
                $ud = $Matches[1].Trim('"')
                if ($ud) {
                    $cands += (Join-Path $ud 'User\rules')
                    $cands += (Join-Path $ud 'rules')
                }
            }
        }
    } catch { }
    return @($cands | Select-Object -Unique)
}

function Get-CursorProjects {
    # 从 Cursor 工作区记录自动探测用户打开过的所有项目（免手工指定）
    $projects = @()
    foreach ($base in @($env:APPDATA, $env:LOCALAPPDATA)) {
        if ([string]::IsNullOrWhiteSpace($base)) { continue }
        $wsRoot = Join-Path $base 'Cursor\User\workspaceStorage'
        if (-not (Test-Path -LiteralPath $wsRoot)) { continue }
        try {
            foreach ($wdir in (Get-ChildItem -LiteralPath $wsRoot -Directory -ErrorAction SilentlyContinue)) {
                $wsJson = Join-Path $wdir.FullName 'workspace.json'
                if (-not (Test-Path -LiteralPath $wsJson)) { continue }
                try {
                    $w = Get-Content -LiteralPath $wsJson -Raw -Encoding UTF8 | ConvertFrom-Json
                } catch { continue }
                $loc = $null
                if ($w.folder) { $loc = [string]$w.folder }
                elseif ($w.workspace) { $loc = [string]$w.workspace }
                if (-not $loc) { continue }
                if ($loc -match '^file:///(.+)') { $loc = $Matches[1] }
                $loc = $loc -replace '/', '\'
                $loc = [uri]::UnescapeDataString($loc)
                if (Test-Path -LiteralPath $loc) { $projects += $loc }
            }
        } catch { }
    }
    return @($projects | Select-Object -Unique)
}

function Get-TargetPaths {
    # 1) 安装记录里写过的路径（卸载兜底）；2) 已存在的候选目录；3) 标准默认
    $result = @()
    if (Test-Path -LiteralPath $statePath) {
        try {
            $st = Get-Content -LiteralPath $statePath -Raw -Encoding UTF8 | ConvertFrom-Json
            foreach ($p in @($st.writtenPaths)) {
                # state 里存的是完整目标文件路径（含文件名），直接使用
                $full = [string]$p
                if ([string]::IsNullOrWhiteSpace($full)) { continue }
                if (-not $full.EndsWith('.mdc', [System.StringComparison]::OrdinalIgnoreCase)) {
                    $full = Join-Path $full $ruleFile
                }
                if ($result -notcontains $full) { $result += $full }
            }
        } catch { }
    }
    foreach ($d in (Get-RulesCandidates)) {
        $existPath = Join-Path $d $ruleFile
        if ($result -notcontains $existPath -and (Test-Path -LiteralPath $d)) {
            $result += $existPath
        }
    }
    # 项目级规则也纳入卸载清理（自动探测当前打开过的项目）
    foreach ($p in (Get-ProjectRulePaths)) {
        if ($result -notcontains $p) { $result += $p }
    }
    # 盘符根祖先规则纳入卸载清理
    foreach ($p in (Get-DriveRulePaths)) {
        if ($result -notcontains $p -and (Test-Path -LiteralPath (Split-Path -Parent $p))) {
            $result += $p
        }
    }
    if ($result.Count -eq 0) {
        $result += (Join-Path $env:APPDATA 'Cursor\User\rules\寒霜注入.mdc')
        $result += (Join-Path $env:APPDATA 'Cursor\rules\寒霜注入.mdc')
    }
    return @($result | Select-Object -Unique)
}

function Get-ProjectRulePaths {
    # 项目级规则：Cursor 打开过的每个项目 → {项目}/.cursor/rules/寒霜注入.mdc
    $result = @()
    foreach ($proj in (Get-CursorProjects)) {
        $result += (Join-Path $proj ".cursor\rules\$ruleFile")
    }
    return @($result | Select-Object -Unique)
}

function Get-LegacyRulePaths {
    # 旧版 Cursor（<0.42）只认项目根目录的 .cursorrules 单文件；
    # 仅在项目里原本没有 .cursorrules（或是我们装的）时写入，避免覆盖用户自有规则
    $result = @()
    foreach ($proj in (Get-CursorProjects)) {
        $legacy = Join-Path $proj $legacyRuleFile
        $exists = Test-Path -LiteralPath $legacy
        $isOurs = $false
        if ($exists) {
            try { $isOurs = (Read-Utf8 $legacy) -match [regex]::Escape($marker) } catch { }
        }
        if (-not $exists -or $isOurs) { $result += $legacy }
    }
    return @($result | Select-Object -Unique)
}

function Get-DriveRulePaths {
    # 盘符根祖先规则：Cursor 规则沿「工作区 → 父目录 → ... → 盘符根」链条向上加载，
    # 在盘符根 .cursor/rules 放置规则 = 该盘任意文件夹（含今后新建的）打开都会自动加载
    $result = @()
    try {
        $drives = [System.IO.DriveInfo]::GetDrives() | Where-Object { $_.DriveType -eq [System.IO.DriveType]::Fixed -and $_.IsReady }
        if (-not $drives) { $drives = @((New-Object System.IO.DriveInfo($env:SystemDrive))) }
        foreach ($drv in $drives) {
            $result += (Join-Path $drv.RootDirectory.FullName ".cursor\rules\$ruleFile")
        }
    } catch { }
    return @($result | Select-Object -Unique)
}

function Test-IsPrimary([string]$Path) {
    # 主路径 = 全局 User Rules（决定注入是否真的全局生效）
    $p = $Path
    foreach ($d in (Get-RulesCandidates)) {
        if ($p -ieq (Join-Path $d $ruleFile)) { return $true }
    }
    return $false
}

if ($Uninstall) {
    try {
        $removedAny = $false
        $restoredAny = $false
        foreach ($p in (Get-TargetPaths)) {
            if (-not (Test-Path -LiteralPath $p)) { continue }
            $bak = $p + '.bak'
            if (Test-Path -LiteralPath $bak) {
                Copy-Item -LiteralPath $bak -Destination $p -Force
                Remove-Item -LiteralPath $bak -Force
                Write-Host ("Restored original rule: " + $p)
                $restoredAny = $true
            } else {
                $content = Read-Utf8 $p
                if ($content -match [regex]::Escape($marker)) {
                    Remove-Item -LiteralPath $p -Force
                    Write-Host ("Removed injected rule: " + $p)
                    $removedAny = $true
                } else {
                    Write-Host ("No injection found, skipped: " + $p)
                }
            }
        }
        # 卸载旧版 .cursorrules（含我们标记的）
        foreach ($p in (Get-LegacyRulePaths)) {
            if (-not (Test-Path -LiteralPath $p)) { continue }
            $content = Read-Utf8 $p
            if ($content -match [regex]::Escape($marker)) {
                $bak = $p + '.bak'
                if (Test-Path -LiteralPath $bak) {
                    Copy-Item -LiteralPath $bak -Destination $p -Force
                    Remove-Item -LiteralPath $bak -Force
                } else {
                    Remove-Item -LiteralPath $p -Force
                }
                Write-Host ("Removed legacy rule: " + $p)
                $removedAny = $true
            }
        }
        Remove-Item -LiteralPath $statePath -Force -ErrorAction SilentlyContinue
        if (-not ($removedAny -or $restoredAny)) {
            Write-Host "No Cursor rule injection found, nothing to do"
        }
        Write-Host "Cursor 注入卸载完成"
        exit 0
    } catch {
        Write-Host ("卸载失败: " + $_.Exception.Message) -ForegroundColor Red
        exit 1
    }
}

if (-not (Test-Path -LiteralPath $SourcePrompt -PathType Leaf)) {
    throw "Prompt file not found: $SourcePrompt"
}

try {
    $body = Read-Utf8 $SourcePrompt
    # .mdc 格式：description + globs + alwaysApply frontmatter + 正文（带注入标记便于卸载识别）
    $mdc = "---" + [Environment]::NewLine +
           "description: 寒霜工作规范（自动注入 · 全局生效）" + [Environment]::NewLine +
           'globs: "**/*"' + [Environment]::NewLine +
           "alwaysApply: true" + [Environment]::NewLine +
           "---" + [Environment]::NewLine + [Environment]::NewLine +
           $marker + [Environment]::NewLine +
           $body.TrimEnd() + [Environment]::NewLine

    $written = @()
    $failed = @()
    $primaryOk = $false
    function Write-RuleFile([string]$target, [bool]$legacy = $false) {
        New-Item -ItemType Directory -Force -Path (Split-Path -Parent $target) | Out-Null
        if (Test-Path -LiteralPath $target) {
            $cur = Read-Utf8 $target
            if ($cur -notmatch [regex]::Escape($marker)) {
                # 已存在非注入文件（用户自建规则撞名）：先备份
                Copy-Item -LiteralPath $target -Destination ($target + '.bak') -Force
            }
        }
        try {
            if ($legacy) {
                # 旧版 .cursorrules 是纯 markdown，不带 frontmatter
                $content = $marker + [Environment]::NewLine + $body.TrimEnd() + [Environment]::NewLine
            } else {
                $content = $mdc
            }
            Write-Utf8NoBom $target $content
            if (-not (Test-Path -LiteralPath $target)) { throw '写入后文件不存在（被占用或权限不足）' }
            $script:written += $target
            if (-not $legacy -and (Test-IsPrimary $target)) { $script:primaryOk = $true }
            Write-Host ("OK: " + $target)
        } catch {
            $script:failed += "$target -> $($_.Exception.Message)"
            Write-Host ("跳过(非致命): " + $target + " -> " + $_.Exception.Message) -ForegroundColor Yellow
        }
    }
    # 1) 全局规则目录（User Rules + ~/.cursor/rules 等全部候选）——决定新文件夹全局生效
    foreach ($d in (Get-RulesCandidates)) {
        Write-RuleFile (Join-Path $d $ruleFile)
    }
    # 2) 项目级规则：自动探测 Cursor 打开过的每个项目
    foreach ($target in (Get-ProjectRulePaths)) {
        Write-RuleFile $target
    }
    # 3) 旧版兼容：项目根目录 .cursorrules（只写没有用户自有规则的，纯文本格式）
    foreach ($target in (Get-LegacyRulePaths)) {
        Write-RuleFile $target $true
    }
    # 4) 盘符根祖先规则：让「该盘任意新文件夹」都自动继承（失败不致命）
    foreach ($target in (Get-DriveRulePaths)) {
        Write-RuleFile $target
    }
    # 记录实际写入路径，供卸载精确清理
    try {
        $stateDir = Split-Path -Parent $statePath
        New-Item -ItemType Directory -Force -Path $stateDir | Out-Null
        $st = [ordered]@{ installedAt = (Get-Date).ToString('o'); writtenPaths = $written }
        Write-Utf8NoBom $statePath (($st | ConvertTo-Json -Depth 3) + [Environment]::NewLine)
    } catch {
        Write-Host ("警告: 安装状态未记录（卸载时将无法精确清理）- " + $_.Exception.Message) -ForegroundColor Yellow
    }
    Write-Host ("Cursor rules installed: " + ($written.Count) + " 处")
    if ($failed.Count -gt 0) {
        Write-Host ("以下 " + $failed.Count + " 处写入被跳过（不影响全局生效，多为系统盘权限）:") -ForegroundColor Yellow
        $failed | ForEach-Object { Write-Host ("  " + $_) -ForegroundColor Yellow }
    }
    if ($primaryOk -and $written.Count -gt 0) {
        Write-Host "全局 User Rules 注入成功 - 新开任意文件夹都会自动加载"
        Write-Host "重启 Cursor 生效（Rules → User 可见「寒霜注入」）"
        exit 0
    }
    if ($written.Count -gt 0) {
        Write-Host "主路径写入失败但部分规则已写入（可能不全局生效），请检查 Cursor 安装目录权限" -ForegroundColor Yellow
        exit 2
    }
    Write-Host "全部写入失败 - 请确认 Cursor 已安装且你有写入权限" -ForegroundColor Red
    exit 1
} catch {
    Write-Host ("安装失败: " + $_.Exception.Message) -ForegroundColor Red
    exit 1
}
