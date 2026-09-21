[CmdletBinding()]
param(
    [string]$SourcePrompt,
    [string]$DshHome,
    [string]$SkillsSource,
    # 指定则按「懒人包模式」部署：提示词取 <KitRoot>/materials/AGENTS.md，
    # 技能取 <KitRoot>/materials/skills，并附带 shield-protocol 与 prompt-inject 模板
    [string]$KitRoot,
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

# detectEncodingFromByteOrderMarks:$true —— 文件带 UTF-8 BOM 时自动去掉，
# 否则读出来首字符是 ﻿，SKILL.md 的 "---" 判断会失配，DSH 直接把该技能拒收。
function Read-Utf8([string]$Path) {
    return [System.IO.File]::ReadAllText($Path, (New-Object System.Text.UTF8Encoding($false, $true)))
}

function Write-Utf8NoBom([string]$Path, [string]$Text) {
    [System.IO.File]::WriteAllText($Path, $Text, $Utf8)
}

# DSH 的全局记忆文件是 <DshHome>/AGENTS.md（@deepseek-ai/dsh-agent-instructions
# 里的 USER_GLOBAL_FILE），技能目录是 <DshHome>/skills（dsh-skill-filesystem 的 user 根）。
if ([string]::IsNullOrWhiteSpace($DshHome)) {
    $DshHome = Join-Path $HOME '.dsh'
}
$agentsMd = Join-Path $DshHome 'AGENTS.md'
$managedDir = Join-Path $DshHome 'managed-prompts'
$backupPath = Join-Path $managedDir 'AGENTS.md.bak'
$marker = '<!-- HANSHUANG-INJECT:BEGIN -->'
$markerEnd = '<!-- HANSHUANG-INJECT:END -->'

# 未显式传 -KitRoot 时，自动找随包分发的懒人包目录（打包后在 resources/ 下）
function Test-KitAt([string]$Dir) {
    if ([string]::IsNullOrWhiteSpace($Dir)) { return $false }
    return (Test-Path -LiteralPath (Join-Path $Dir 'materials\AGENTS.md'))
}
# 包的实际位置有两种：随打包进 resources\（与脚本同级），或开发时与项目目录平级的
# 兄弟目录 —— 后者少了父目录那一跳，只按脚本同级找会在卸载（不带 -KitRoot）时落空。
$packageRoot = $KitRoot
if ([string]::IsNullOrWhiteSpace($packageRoot)) {
    $parent = Split-Path $PSScriptRoot -Parent
    foreach ($cand in @(
        (Join-Path $PSScriptRoot 'dsh-lazy-pack-v5'),
        (Join-Path $parent 'dsh-lazy-pack-v5'),
        (Join-Path (Split-Path $parent -Parent) 'dsh-lazy-pack-v5')
    )) {
        if (Test-KitAt $cand) { $packageRoot = $cand; break }
    }
}
if ([string]::IsNullOrWhiteSpace($packageRoot) -and $env:HS_DSH_KIT) {
    if (Test-KitAt $env:HS_DSH_KIT) { $packageRoot = $env:HS_DSH_KIT }
}
$isKitMode = -not [string]::IsNullOrWhiteSpace($packageRoot)
$kitPrompt = ''
$kitName = 'dsh-lazy-pack-v5'
# 包相关路径不分模式都要先算出来：卸载时不会传 -KitRoot，$isKitMode 为假，
# 但还原/清理包文件仍然要用这些路径，留空会直接抛错中断卸载。
$shieldSrc = ''
$injectSrc = ''
$coffeeSrc = ''
if ($isKitMode) {
    $kitPrompt = Join-Path $packageRoot 'materials\AGENTS.md'
    if (-not (Test-Path -LiteralPath $kitPrompt)) {
        throw "KitRoot 里找不到 materials/AGENTS.md: $packageRoot"
    }
    $shieldSrc = Join-Path $packageRoot 'materials\shield-protocol.md'
    $injectSrc = Join-Path $packageRoot 'prompts\operator-config-v5.md'
    $coffeeSrc = Join-Path $packageRoot 'prompts\cold-coffee.md'
}
$shieldDst = Join-Path $DshHome 'shield-protocol.md'
$shieldBak = Join-Path $managedDir 'shield-protocol.md.bak'
$injectDst = Join-Path $DshHome 'prompt-inject.md'
$injectCfg = Join-Path $DshHome 'dsh-prompt-inject.json'
$injectBak = Join-Path $managedDir 'prompt-inject.md.bak'
$cfgBak = Join-Path $managedDir 'dsh-prompt-inject.json.bak'
$markerBegin = if ($isKitMode) { '<!-- HANSHUANG-INJECT:BEGIN pack=' + $kitName + ' -->' } else { $marker }
if ([string]::IsNullOrWhiteSpace($SkillsSource)) {
    $SkillsSource = Join-Path $PSScriptRoot 'codex-skills'
} else {
    $SkillsSource = Join-Path $PSScriptRoot $SkillsSource
}
# 懒人包模式：技能取包内 materials/skills，忽略 -SkillsSource
$skillsSource = if ($isKitMode) { Join-Path $packageRoot 'materials\skills' } else { $SkillsSource }
$skillsTarget = Join-Path $DshHome 'skills'
$skillsManifestKey = 'installedSkills'
# 懒人包自带的技能清单单独记账：换回单文件版时照它清理，不误删用户自己放的技能
$packSkillsKey = 'kitSkills'

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
    # 包内 skills 目录里还套了一层主控目录（materials/skills/skills）：
    # 它自己的 SKILL.md 没有 frontmatter，DSH 会整层拒收，里面独有的技能就永远加载不到。
    # 这里把该层里合规的技能提升到顶层，其余（旧格式 / 无 SKILL.md）跳过。
    $nested = Join-Path $skillsSource 'skills'
    if (Test-Path -LiteralPath $nested) {
        # 先枚举再处理：夹层目录在本函数末尾会被删掉，列表必须先取出来
        $nestedDirs = @(Get-ChildItem -LiteralPath $nested -Directory -ErrorAction SilentlyContinue)
        foreach ($nd in $nestedDirs) {
            $nFile = Join-Path $nd.FullName 'SKILL.md'
            if (-not (Test-Path -LiteralPath $nFile)) { continue }
            $raw = Read-Utf8 $nFile
            if (-not $raw.StartsWith('---')) { continue }
            $end = $raw.IndexOf("`n---", 3)
            if ($end -lt 0) { continue }
            $fm = $raw.Substring(3, $end - 3)
            if ($fm -notmatch '(?m)^name:\s*\S' -or $fm -notmatch '(?m)^description:\s*\S') { continue }
            $dest = Join-Path $skillsTarget $nd.Name
            if (Test-Path -LiteralPath $dest) { continue }  # 顶层已有同名，跳过
            robocopy $nd.FullName $dest /E /MT:16 /R:1 /W:1 /NFL /NDL /NJH /NJS /NC /NS /NP | Out-Null
            if ($LASTEXITCODE -ge 8) { throw "robocopy failed for $($nd.FullName)" }
            $installed += $nd.Name
        }
        # 夹层本身不是有效技能包，删掉，避免 ~/.dsh/skills 下留一堆加载不到的目录
        Remove-Item -LiteralPath (Join-Path $skillsTarget 'skills') -Recurse -Force -ErrorAction SilentlyContinue
        # 夹层里的旧格式目录（SKILL.md 没有 frontmatter）会被 DSH 拒收；只要顶层有同名目录
        # 且同样不合规，就一并清掉，免得用户看到一堆"装了但用不了"的技能。
        foreach ($nd in $nestedDirs) {
            $dest = Join-Path $skillsTarget $nd.Name
            if (-not (Test-Path -LiteralPath $dest)) { continue }
            $destFile = Join-Path $dest 'SKILL.md'
            if (-not (Test-Path -LiteralPath $destFile)) { continue }
            $destRaw = Read-Utf8 $destFile
            if ($destRaw.StartsWith('---')) { continue }  # 顶层是合规技能，别动
            Remove-Item -LiteralPath $dest -Recurse -Force -ErrorAction SilentlyContinue
        }
    }
    # 收尾：清掉带 SKILL.md 但没 frontmatter 的目录（旧版懒人包遗留的夹层技能），
    # DSH 会拒收它们 —— 留着只会让用户看到一堆"装了但用不了"的技能。
    # 同时把 SKILL.md 开头的 UTF-8 BOM 去掉：有 BOM 时首行不是 "---"，
    # frontmatter 会被当成正文，技能同样加载不到（包里的 browser-automation /
    # docs-generator 就是这个毛病）。
    $noBom = New-Object System.Text.UTF8Encoding($false)
    foreach ($sk in (Get-ChildItem -LiteralPath $skillsTarget -Directory -ErrorAction SilentlyContinue)) {
        $skFile = Join-Path $sk.FullName 'SKILL.md'
        if (-not (Test-Path -LiteralPath $skFile)) { continue }
        $bytes = [System.IO.File]::ReadAllBytes($skFile)
        if ($bytes.Length -ge 3 -and $bytes[0] -eq 0xEF -and $bytes[1] -eq 0xBB -and $bytes[2] -eq 0xBF) {
            $text = $noBom.GetString($bytes, 3, $bytes.Length - 3)
            [System.IO.File]::WriteAllText($skFile, $text, $noBom)
            Write-Host ("Stripped BOM: " + $sk.Name)
        }
        if (-not (Read-Utf8 $skFile).StartsWith('---')) {
            Remove-Item -LiteralPath $sk.FullName -Recurse -Force -ErrorAction SilentlyContinue
            Write-Host ("Removed non-loadable skill dir: " + $sk.Name)
        }
    }
    # 上下文瘦身：DSH 每轮都会把「技能目录」（名字+说明）塞进系统提示词，
    # 150 个技能 ≈ 4.9 万字符 ≈ 33k tokens，直接拖慢每一次回复。
    # 这两类属于窄场景/纯文档，装完后移进 skills-disabled 停用（可随时搬回）：
    #   competition-*               CTF 竞技场窄场景
    #   eni-redteam-*-detail-pack   标注 [DOCUMENTATION ONLY] 的边界说明
    $disabledDir = Join-Path $DshHome 'skills-disabled'
    $movedOut = @()
    foreach ($sk in (Get-ChildItem -LiteralPath $skillsTarget -Directory -ErrorAction SilentlyContinue)) {
        $isHeavy = $sk.Name.StartsWith('competition-') -or ($sk.Name.StartsWith('eni-redteam-') -and $sk.Name.EndsWith('-detail-pack'))
        if (-not $isHeavy) { continue }
        New-Item -ItemType Directory -Force -Path $disabledDir | Out-Null
        $dst = Join-Path $disabledDir $sk.Name
        if (Test-Path -LiteralPath $dst) { Remove-Item -LiteralPath $dst -Recurse -Force -ErrorAction SilentlyContinue }
        Move-Item -LiteralPath $sk.FullName -Destination $dst -Force -ErrorAction SilentlyContinue
        $movedOut += $sk.Name
    }
    if ($movedOut.Count -gt 0) {
        Write-Host ("Context-trimmed skills moved to skills-disabled: " + $movedOut.Count + " items")
    }
    return $installed
}

# 收集包内夹层（materials/skills/skills）里合规的技能名。
# 这些会被 Install-Skills 提升到顶层安装，所以卸载白名单必须也算上它们，
# 否则切换版本/卸载时它们不在白名单里，永远删不掉。
function Get-NestedKitSkillNames {
    $nestedNames = @()
    foreach ($base in @($PSScriptRoot, (Split-Path $PSScriptRoot -Parent), (Split-Path (Split-Path $PSScriptRoot -Parent) -Parent))) {
        if ([string]::IsNullOrWhiteSpace($base)) { continue }
        $nested = Join-Path $base 'dsh-lazy-pack-v5\materials\skills\skills'
        if (-not (Test-Path -LiteralPath $nested)) { continue }
        foreach ($nd in (Get-ChildItem -LiteralPath $nested -Directory -ErrorAction SilentlyContinue)) {
            $nFile = Join-Path $nd.FullName 'SKILL.md'
            if (-not (Test-Path -LiteralPath $nFile)) { continue }
            $raw = Read-Utf8 $nFile
            if (-not $raw.StartsWith('---')) { continue }
            $end = $raw.IndexOf("`n---", 3)
            if ($end -lt 0) { continue }
            $fm = $raw.Substring(3, $end - 3)
            if ($fm -notmatch '(?m)^name:\s*\S' -or $fm -notmatch '(?m)^description:\s*\S') { continue }
            $nestedNames += $nd.Name
        }
    }
    return @($nestedNames | Select-Object -Unique)
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
    # 懒人包技能库同样算「随包分发」，切换版本时才能按清单清干净。
    # 按脚本旁 / 上级 / 上上级三处找包：开发时包是项目目录的兄弟目录，
    # 只找脚本同级会漏（$packageRoot 在卸载时不带 -KitRoot，只能靠自动探测）。
    foreach ($base in @($PSScriptRoot, (Split-Path $PSScriptRoot -Parent), (Split-Path (Split-Path $PSScriptRoot -Parent) -Parent))) {
        if ([string]::IsNullOrWhiteSpace($base)) { continue }
        $kitSkills = Join-Path $base 'dsh-lazy-pack-v5\materials\skills'
        if (-not (Test-Path -LiteralPath $kitSkills)) { continue }
        $names += @(Get-ChildItem -LiteralPath $kitSkills -Directory -ErrorAction SilentlyContinue |
            Where-Object { Test-Path -LiteralPath (Join-Path $_.FullName 'SKILL.md') } |
            Select-Object -ExpandProperty Name)
    }
    if ($packageRoot -and (Test-Path -LiteralPath $packageRoot)) {
        $pkgSkills = Join-Path $packageRoot 'materials\skills'
        if (Test-Path -LiteralPath $pkgSkills) {
            $names += @(Get-ChildItem -LiteralPath $pkgSkills -Directory -ErrorAction SilentlyContinue |
                Where-Object { Test-Path -LiteralPath (Join-Path $_.FullName 'SKILL.md') } |
                Select-Object -ExpandProperty Name)
        }
    }
    $names += Get-NestedKitSkillNames
    return @($names | Select-Object -Unique)
}

# 懒人包模式下写入 prompt-inject 模板库（~/.dsh/dsh-prompt-inject.json）。
# 格式对齐包内 tools/json-edit.js：templates[{id,name,text,order}] + sessions + defaultTemplate。
# 已存在同名 id 就覆盖内容（升级时旧文案不留存），其他模板原样保留。
function Set-PromptInjectConfig([string]$CfgPath, [string]$TemplateId, [string]$TemplateName, [string]$Text, [bool]$MakeDefault) {
    $cfg = $null
    if (Test-Path -LiteralPath $CfgPath) {
        try { $cfg = ConvertFrom-Json (Read-Utf8 $CfgPath) } catch { $cfg = $null }
    }
    if ($null -eq $cfg) {
        $templates = @()
        $sessions = [pscustomobject]@{}
        $default = ''
    } else {
        $templates = @()
        if ($cfg.templates) { $templates = @($cfg.templates) }
        $sessions = if ($cfg.sessions) { $cfg.sessions } else { [pscustomobject]@{} }
        $default = if ($cfg.defaultTemplate) { [string]$cfg.defaultTemplate } else { '' }
    }
    $hit = $false
    foreach ($t in $templates) {
        if ($t.id -eq $TemplateId) {
            $t.text = $Text
            $t.name = $TemplateName
            $hit = $true
        }
    }
    if (-not $hit) {
        $templates += [pscustomobject]@{ id = $TemplateId; name = $TemplateName; text = $Text; order = 1 }
    }
    if ($MakeDefault -and [string]::IsNullOrWhiteSpace($default)) { $default = $TemplateId }
    $out = [pscustomobject]@{ templates = $templates; sessions = $sessions; defaultTemplate = $default }
    Write-Utf8NoBom $CfgPath (($out | ConvertTo-Json -Depth 8) + "`n")
}

# 懒人包模式的非技能文件部署（shield 载荷 + 注入模板）。
# 每个文件首次部署前备份进 managed-prompts，卸载时还原。
function Install-KitFiles {
    $deployed = @()
    Copy-Item -LiteralPath $shieldSrc -Destination $shieldDst -Force
    $deployed += 'shield-protocol.md'
    if (-not (Test-Path -LiteralPath $shieldBak)) { Copy-Item -LiteralPath $shieldDst -Destination $shieldBak -Force }
    if (Test-Path -LiteralPath $injectDst) {
        if (-not (Test-Path -LiteralPath $injectBak)) { Copy-Item -LiteralPath $injectDst -Destination $injectBak -Force }
    }
    Copy-Item -LiteralPath $injectSrc -Destination $injectDst -Force
    $deployed += 'prompt-inject.md'
    if ((Test-Path -LiteralPath $injectCfg) -and -not (Test-Path -LiteralPath $cfgBak)) {
        Copy-Item -LiteralPath $injectCfg -Destination $cfgBak -Force
    }
    $injectText = Read-Utf8 $injectSrc
    Set-PromptInjectConfig $injectCfg 'pojia-default' 'pojia' $injectText $true
    $deployed += 'dsh-prompt-inject.json'
    if ((Test-Path -LiteralPath $coffeeSrc) -and (Test-Path -LiteralPath $injectCfg)) {
        $coffeeText = Read-Utf8 $coffeeSrc
        Set-PromptInjectConfig $injectCfg 'cold-coffee' '冷咖啡' $coffeeText $false
    }
    return $deployed
}

# 候选 = 上次安装清单 ∩ 随包技能库。
# 只删同时满足三条的目录：上次由本工具装过、当前版本已不再分发、目录下确实有 SKILL.md。
# 用户自己放进来的、寒霜从未分发过的技能一条都不沾 —— 纯靠随包清单判断会误删
# 用户自建技能，所以必须先与上次安装清单取交集。
function Prune-StaleSkills([string[]]$Previous, [string[]]$Current) {
    $removedSkills = @()
    if (-not $Previous) { return $removedSkills }
    $shipped = Get-ShippedSkillNames
    # 循环变量用带前缀的唯一名：PowerShell 动态作用域会把循环变量的最后一次
    # 赋值写进调用方同名变量，撞名会静默污染调用方的清单。
    foreach ($hsStaleSkill in $Previous) {
        if ([string]::IsNullOrWhiteSpace($hsStaleSkill)) { continue }
        if ($shipped -notcontains $hsStaleSkill) { continue }  # 非随包技能，不动
        if ($Current -contains $hsStaleSkill) { continue }
        $dest = Join-Path $skillsTarget $hsStaleSkill
        if (-not (Test-Path -LiteralPath $dest)) { continue }
        if (-not (Test-Path -LiteralPath (Join-Path $dest 'SKILL.md'))) { continue }
        Remove-Item -LiteralPath $dest -Recurse -Force -ErrorAction SilentlyContinue
        $removedSkills += $hsStaleSkill
    }
    return $removedSkills
}

# 卸载时只删「上次安装清单 ∩ 随包技能库」。
# 变量名不要用 $Names：PowerShell 动态作用域下，函数内 foreach 的迭代变量会写进
# 调用方同名变量（上游脚本里 $Names 恰好是上一轮 Install-Skills 的返回值），
# 会把不属于本工具的技能一起删掉。
function Remove-Skills([string[]]$SkillNames) {
    $removedSkills = @()
    $shipped = Get-ShippedSkillNames
    foreach ($hsRemoveSkill in $SkillNames) {
        if ([string]::IsNullOrWhiteSpace($hsRemoveSkill)) { continue }
        if ($shipped -notcontains $hsRemoveSkill) { continue }  # 非随包技能，不动
        $dest = Join-Path $skillsTarget $hsRemoveSkill
        if (Test-Path -LiteralPath $dest) {
            Remove-Item -LiteralPath $dest -Recurse -Force
            $removedSkills += $hsRemoveSkill
        }
    }
    return $removedSkills
}

# 懒人包模式下提示词固定取包内 materials/AGENTS.md
if ($isKitMode) {
    $SourcePrompt = $kitPrompt
}
if ([string]::IsNullOrWhiteSpace($SourcePrompt)) {
    $mdFiles = @(Get-ChildItem -LiteralPath $PSScriptRoot -Filter '*.md' -File | Sort-Object Name)
    if ($mdFiles.Count -eq 0) {
        throw "No .md prompt file found in $PSScriptRoot"
    }
    $SourcePrompt = $mdFiles[0].FullName
}

$statePath = Join-Path $managedDir 'install-state.json'

# 读上一次安装的状态：技能清单 + 上次是不是懒人包模式（决定要不要收走包专属文件）
$prevSkills = @()
if (Test-Path -LiteralPath $statePath) {
    try {
        $prevState = Read-Utf8 $statePath | ConvertFrom-Json
        if ($prevState.installedSkills) { $prevSkills = @($prevState.installedSkills) }
    } catch {}
}

if ($Uninstall) {
    # 0. 重复卸载兜底：上一次卸载如果在清理途中失败，状态文件可能已丢，
    # 但 marker 还在 —— 此时按「随包分发的技能 ∩ 技能目录里存在的」重建清单，
    # 否则残留的技能与包文件再也没人认领（点第二次「卸载」也清不掉）。
    if ($prevSkills.Count -eq 0) {
        $leftover = @()
        foreach ($nm in Get-ShippedSkillNames) {
            if (Test-Path -LiteralPath (Join-Path $skillsTarget $nm)) { $leftover += $nm }
        }
        if ($leftover.Count -gt 0) {
            $prevSkills = $leftover
            Write-Host ("Recovered skill inventory from disk: " + $leftover.Count + " items")
        }
    }
    # 1. 恢复/删除注入的提示词
    $curText = ''
    if (Test-Path -LiteralPath $agentsMd) {
        try { $curText = Read-Utf8 $agentsMd } catch { $curText = '' }
    }
    $curIsKit = $curText -match [regex]::Escape('pack=' + $kitName)
    if (Test-Path -LiteralPath $backupPath) {
        Copy-Item -LiteralPath $backupPath -Destination $agentsMd -Force
        Remove-Item -LiteralPath $backupPath -Force
        Write-Host "Restored original AGENTS.md"
    } elseif ($curText -match [regex]::Escape($marker)) {
        Remove-Item -LiteralPath $agentsMd -Force
        Write-Host "Removed injected AGENTS.md"
    } else {
        Write-Host "No injection found, nothing to do"
    }
    # 2. 懒人包专属文件：仅当当前注入的确实是懒人包时处理（$curIsKit 取自覆盖前的原文）
    if ($curIsKit) {
        if (Test-Path -LiteralPath $shieldBak) {
            Copy-Item -LiteralPath $shieldBak -Destination $shieldDst -Force
            Remove-Item -LiteralPath $shieldBak -Force
            Write-Host "Restored original shield-protocol.md"
        } elseif (Test-Path -LiteralPath $shieldDst) {
            Remove-Item -LiteralPath $shieldDst -Force
            Write-Host "Removed shield-protocol.md"
        }
        if (Test-Path -LiteralPath $injectBak) {
            Copy-Item -LiteralPath $injectBak -Destination $injectDst -Force
            Remove-Item -LiteralPath $injectBak -Force
            Write-Host "Restored original prompt-inject.md"
        } elseif (Test-Path -LiteralPath $injectDst) {
            Remove-Item -LiteralPath $injectDst -Force
            Write-Host "Removed prompt-inject.md"
        }
        # 注入模板库只摘掉本包注册的模板，用户自建模板保留
        if (Test-Path -LiteralPath $injectCfg) {
            if (Test-Path -LiteralPath $cfgBak) {
                Copy-Item -LiteralPath $cfgBak -Destination $injectCfg -Force
                Remove-Item -LiteralPath $cfgBak -Force
                Write-Host "Restored original dsh-prompt-inject.json"
            } else {
                try {
                    $cfg = ConvertFrom-Json (Read-Utf8 $injectCfg)
                    $keep = @()
                    if ($cfg.templates) {
                        foreach ($t in @($cfg.templates)) {
                            if ($t.id -ne 'pojia-default' -and $t.id -ne 'cold-coffee') { $keep += $t }
                        }
                    }
                    $default = ''
                    if ($cfg.defaultTemplate -and $cfg.defaultTemplate -ne 'pojia-default' -and $cfg.defaultTemplate -ne 'cold-coffee') {
                        $default = [string]$cfg.defaultTemplate
                    }
                    $sessions = if ($cfg.sessions) { $cfg.sessions } else { [pscustomobject]@{} }
                    $out = [pscustomobject]@{ templates = $keep; sessions = $sessions; defaultTemplate = $default }
                    Write-Utf8NoBom $injectCfg (($out | ConvertTo-Json -Depth 8) + "`n")
                    Write-Host "Removed kit templates from dsh-prompt-inject.json"
                } catch {
                    Write-Host "Failed to clean dsh-prompt-inject.json, left as-is"
                }
            }
        }
    }
    # 3. 删除同步安装的 skills（清单已在前面读好，这里不再依赖状态文件）
    if ($prevSkills.Count -gt 0) {
        $removedSkills = Remove-Skills $prevSkills
        if ($removedSkills.Count -gt 0) {
            Write-Host ("Removed managed skills: " + ($removedSkills -join ", "))
        } else {
            Write-Host "No managed skills to remove"
        }
    } else {
        Write-Host "No managed skills to remove"
    }
    # 4. 落墓碑记录：全部清理跑完才写，中途出错时状态文件仍在，重跑卸载还能接着清
    try {
        $tomb = @{ uninstalled = $true; $skillsManifestKey = $prevSkills }
        Write-Utf8NoBom $statePath (($tomb | ConvertTo-Json -Depth 5) + "`n")
    } catch {
        Write-Host "Failed to write uninstall marker, next run will recover from disk"
    }
    exit 0
}

if (-not (Test-Path -LiteralPath $SourcePrompt)) {
    throw "Prompt file not found: $SourcePrompt"
}

New-Item -ItemType Directory -Force -Path $DshHome | Out-Null
New-Item -ItemType Directory -Force -Path $managedDir | Out-Null

# 备份原始 AGENTS.md（仅首次注入时备份），然后整体覆盖为提示词内容。
# 注意：DSH 的 AGENTS.md 是 DSH 全局记忆的唯一文件，其他工具写进去的内容
# 会一并被覆盖 —— 原文件已存进 managed-prompts，卸载即可完整还原。
$curAgents = ''
if (Test-Path -LiteralPath $agentsMd) {
    try { $curAgents = Read-Utf8 $agentsMd } catch { $curAgents = '' }
    if ($curAgents -match [regex]::Escape($marker)) {
        if (($curAgents -match [regex]::Escape('pack=' + $kitName)) -ne $isKitMode) {
            # 换模式了（单文件版 <-> 懒人包版）：备份必须留「注入前的原文件」。
            # 若当前文件是上一轮注入的产物，把它写回备份等于丢掉原文件，
            # 卸载时会还原成石井人设而不是用户自己的 AGENTS.md，所以只在备份
            # 不存在时才写。
            if (-not (Test-Path -LiteralPath $backupPath)) {
                Copy-Item -LiteralPath $agentsMd -Destination $backupPath -Force
                Write-Host "Injection mode changed, recorded pre-injection backup"
            } else {
                Write-Host "Injection mode changed, keeping original pre-injection backup"
            }
        } else {
            Write-Host "AGENTS.md already injected, updating content"
        }
    } elseif (-not (Test-Path -LiteralPath $backupPath)) {
        # 只在当前文件「不是本工具注入的产物」时才存为原始备份。
        # 少了这个判断，一旦备份被删（或前一次卸载失败），重装会把刚注入的
        # 内容写成备份，之后卸载就会"还原"成注入态、甚至当作无原始文件删掉。
        if ($curAgents -match [regex]::Escape($marker)) {
            Write-Host "AGENTS.md is an earlier injection and no pre-injection backup exists; skipping backup"
        } else {
            Copy-Item -LiteralPath $agentsMd -Destination $backupPath -Force
            Write-Host "Backed up original AGENTS.md"
        }
    }
} else {
    Write-Host "No existing AGENTS.md, creating new"
}

# 整体覆盖：AGENTS.md 只保留注入的提示词
$promptText = Read-Utf8 $SourcePrompt
$injected = $markerBegin + "`n" + $promptText.TrimEnd("`r", "`n") + "`n" + $markerEnd + "`n"
Write-Utf8NoBom $agentsMd $injected
Write-Host "Injected prompt -> $agentsMd"

# 同步安装 skills
$__t0=[DateTime]::Now
$installedSkills = Install-Skills
Write-Host ("[TIME] 技能安装: " + [int](([DateTime]::Now-$__t0).TotalMilliseconds) + " ms")
if ($installedSkills.Count -gt 0) {
    Write-Host ("Installed skills: " + ($installedSkills -join ", "))
}

# 清掉上一版遗留、新版技能库里已移除的技能
$staleSkills = Prune-StaleSkills $prevSkills $installedSkills
if ($staleSkills.Count -gt 0) {
    Write-Host ("Pruned stale skills from previous version: " + ($staleSkills -join ", "))
}

# 懒人包模式：额外部署 shield 载荷与注入模板（非技能文件另记账）
$__t1=[DateTime]::Now
$kitFiles = @()
if ($isKitMode) {
    $kitFiles = Install-KitFiles
    Write-Host ("[TIME] 包文件部署: " + [int](([DateTime]::Now-$__t1).TotalMilliseconds) + " ms")
    if ($kitFiles.Count -gt 0) {
        Write-Host ("Deployed kit files: " + ($kitFiles -join ", "))
    }
    Write-Host "提示：prompt-inject.md 与 dsh-prompt-inject.json 需装 dsh-prompt-inject 插件才注入系统提示词；AGENTS.md 与 shield-protocol.md 无需插件。"
}

$state = @{
    $skillsManifestKey = $installedSkills
    kit                 = $isKitMode
    kitFiles            = $kitFiles
    prompt              = (Split-Path $SourcePrompt -Leaf)
}
$__t2=[DateTime]::Now
$stateJson = $state | ConvertTo-Json -Depth 5
Write-Host ("[TIME] 状态写入: " + [int](([DateTime]::Now-$__t2).TotalMilliseconds) + " ms")
Write-Utf8NoBom $statePath $stateJson
Write-Host "DSH injection complete"
