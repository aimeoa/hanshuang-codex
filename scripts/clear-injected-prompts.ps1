# =============================================================================
#  寒霜破甲工具 · 清除全部注入提示词（零提示词）
#
#  各目标（codex / zcode / cursor / claude / workbuddy / dsh / doubao / omp）各有一套安装脚本、
#  各有自己的注入点。这个脚本把它们全部还原到「没有注入过任何提示词」的状态。
#
#  安全规则（硬约束，改脚本时不要放宽）：
#    * 白名单式：只处理下面明确列出的注入点，不做「扫到像的就删」。
#    * AGENTS.md / CLAUDE.md 只按注入标记块摘除；没有标记的文件一个字节都不碰。
#    * managed-prompts 是本工具自己的目录，提示词整目录清空。
#    * .bak 不是提示词 —— 它是注入前用户原文的备份。要先验证它确实干净（不含注入
#      痕迹）才能用来还原；备份自己就是旧注入的话还原等于没卸载，那种直接删。
#      （install-claude.ps1 的卸载逻辑里专门写了这一条。）
#    * WorkBuddy 记忆档案只清 «## Memory Block» 段内容，档案文件本身、uid 和
#      RAW_JSON 都保留 —— 那是 WorkBuddy 的文件，不是我们的。
#    * 默认先 dry-run，加 -Apply 才真删。
#
#  用法：
#    powershell -NoProfile -ExecutionPolicy Bypass -File scripts\clear-injected-prompts.ps1
#    powershell ... -File scripts\clear-injected-prompts.ps1 -Apply
# =============================================================================
[CmdletBinding()]
param(
  [switch]$Apply,
  [int]$ScanDepth = 4,
  # 只处理指定目标（codex / zcode / claude / dsh / doubao / workbuddy / cursor / omp）。
  # 留空 = 全部。app 里点单个目标的「卸载」时会传对应目标，避免连带清掉别的目标。
  [string[]]$Targets = @(),
  # 只把「待清除项」的路径按行输出（每行一个绝对路径），供 verify-uninstall.ps1 之类的
  # 程序解析。不带这个开关时行为完全不变。这样「什么算提示词」只有这一处判定，不会两套结论打架。
  [switch]$ListOnly
)

$ErrorActionPreference = 'SilentlyContinue'
try { [Console]::OutputEncoding = [Text.Encoding]::UTF8 } catch {}

# -File 模式下 `-Targets codex,zcode` 会作为「一个字符串」传进来（PowerShell 不会自动按逗号拆分），
# 结果 Want() 对所有目标都返回 false —— 脚本什么都不做，却报告「没有发现任何注入提示词残留」。
# 静默的假阴性比报错更危险，这里统一拆一次。
$Targets = @($Targets | ForEach-Object { $_ -split ',' } | Where-Object { $_ } | Select-Object -Unique)

$mode = if ($Apply) { 'APPLY（真删）' } else { 'DRY-RUN（只看不删，加 -Apply 执行）' }
$H = $env:USERPROFILE
$plan = New-Object System.Collections.Generic.List[object]
$kept = New-Object System.Collections.Generic.List[string]

function Plan([string]$kind, [string]$path, [string]$note, [string]$src = '') {
  $script:plan.Add([pscustomobject]@{ Kind = $kind; Path = $path; Note = $note; Src = $src })
}
function Keep([string]$what) { $script:kept.Add($what) }

# 注入痕迹判定 —— 这个判断直接决定「还原原文」还是「当注入删掉」，判错就是丢用户数据。
# 两层判据：
#   1) 硬标记：注入块/提示词正文的特征行，命中即注入
#   2) 内容比对：拿候选文件里最长的几行去随包提示词里找，找得到就是提示词正文。
#      这一层是为了覆盖「旧版注入」—— 旧版提示词没有新版标记行，只靠第 1 层认不出来，
#      结果会把一份旧的注入当成「用户原文」还原回去，等于没卸载（实测踩过）。
# 只认「逐字出现在随包提示词里」的内容，用户自己的笔记不会被误判。
$script:BundledPrompts = $null
function Get-BundledPrompts {
  if ($null -ne $script:BundledPrompts) { return $script:BundledPrompts }
  $root = Split-Path -Parent $PSScriptRoot   # scripts\.. = 项目根 / 打包后的 resources
  $list = @()
  foreach ($pat in '寒霜*.md', 'gpt-6-astra-v1\*.md', 'gpt-*.md') {
    foreach ($f in @(Get-ChildItem -LiteralPath $root -Filter $pat -File -Recurse -Depth 1 -ErrorAction SilentlyContinue)) {
      try { $list += [pscustomobject]@{ Name = $f.Name; Text = [IO.File]::ReadAllText($f.FullName) } } catch { }
    }
  }
  $script:BundledPrompts = $list
  return $list
}
function Test-InjectionArtifact([string]$path) {
  try { $t = [IO.File]::ReadAllText($path) } catch { return $false }
  if ([string]::IsNullOrWhiteSpace($t)) { return $false }
  # 1) 硬标记
  if ($t -match 'HANSHUANG-INJECT' -or $t -match '寒霜破甲注入开始' -or $t -match '激活词（唯一例外') { return $true }
  # 2) 与随包提示词逐字比对（取最长的 8 行，见下方阈值说明）
  $prompts = Get-BundledPrompts
  if ($prompts.Count -eq 0) { return $false }
  $lines = @($t -split "\r?\n" | ForEach-Object { $_.Trim() } | Where-Object { $_.Length -ge 20 } |
             Sort-Object Length -Descending | Select-Object -First 8)
  if ($lines.Count -eq 0) { return $false }
  $best = 0
  foreach ($bp in $prompts) {
    $n = 0
    foreach ($l in $lines) { if ($bp.Text.Contains($l)) { $n++ } }
    if ($n -gt $best) { $best = $n }
  }
  # 阈值 3 行，实测标定：真·旧版提示词 8/8，别家产品的注入只有 1/8（同一作者的不同
  # 产品会共用 few-shot 这类样板段），用户自己的文件 0/8。用 1 行当阈值会去删别家
  # 工具的注入文件 —— 那是越界，不是卸载。
  return ($best -ge 3)
}
# 摘掉注入块后只剩空白 / 残缺注释（例如注入时把文件截断留下的 "<!--"）时，
# 视为「这份文件本来就是我们建的」，应当还原备份而不是留下这点垃圾
function Test-Trivial([string]$text) {
  return ([string]::IsNullOrWhiteSpace($text) -or $text.Trim() -match '^(<!--|-->|<!---->|\s)*$')
}
# 「本工具在注入前留的主文件备份，且主文件已经还原干净」—— 两者同时成立时备份已无用途。
# 两道硬条件，缺一不可：
#   1) 命名必须是本工具的格式：<主文件>.backup-<yyyyMMdd-HHmmss> / .bak_<yyyyMMdd_HHmmss>。
#      用户自己起名的备份（AGENTS.md.bak-routing-fix 之类）不匹配，永远不碰。
#   2) 主文件必须已不含任何注入痕迹。主文件还带着注入 = 备份是唯一的还原依据，留着。
function Test-SpentBackup([string]$path) {
  $dir = Split-Path -Parent $path
  $name = Split-Path -Leaf $path
  $m = [regex]::Match($name, '^(?<main>.+?)\.(backup|bak)[-_.]\d{8}')
  if (-not $m.Success) { return $false }
  # 只认本工具真正会注入的那两个主文件。别的名字一律不碰 ——
  # `<名>.bak-<8位数字>` 是很常见的备份命名，config.toml.bak-20260420-125143 这种
  # 是用户/别家工具的备份，按格式匹配会把它们一起卷进来。
  $mainName = $m.Groups['main'].Value
  if ($mainName -ne 'AGENTS.md' -and $mainName -ne 'CLAUDE.md') { return $false }
  $mainPath = Join-Path $dir $mainName
  if (-not (Test-Path -LiteralPath $mainPath)) { return $false }
  $t = ''
  try { $t = [IO.File]::ReadAllText($mainPath) } catch { return $false }
  return (-not ($t -match '寒霜破甲注入|HANSHUANG-INJECT|CTF-LAB-2\.0'))
}

Write-Host ("=== 清除全部注入提示词 [{0}] ===" -f $mode) -ForegroundColor Cyan
Write-Host ''

# Codex 配置目录。不能写死 ~/.codex：用户可能把 CODEX_HOME 指到别的盘
# （C 盘紧张时的常见做法），也可能把 .codex 直接放在某个盘的根目录。
# 顺序与 electron/main.cjs 的 codexHome() 保持一致。
function Resolve-CodexHome {
  if ($env:CODEX_HOME -and (Test-Path -LiteralPath $env:CODEX_HOME)) { return $env:CODEX_HOME }
  $def = Join-Path $H '.codex'
  if (Test-Path -LiteralPath $def) { return $def }
  try {
    foreach ($d in [IO.DriveInfo]::GetDrives()) {
      if ($d.DriveType -eq [IO.DriveType]::Fixed -and $d.IsReady) {
        $p = Join-Path $d.RootDirectory.FullName '.codex'
        if (Test-Path -LiteralPath $p) { return $p }
      }
    }
  } catch { }
  return $def
}
$codexHome = Resolve-CodexHome
$allHomes = [ordered]@{
  codex  = $codexHome
  zcode  = (Join-Path $H '.zcode')
  claude = (Join-Path $H '.claude')
  dsh    = (Join-Path $H '.dsh')
}
function Want([string]$name) {
  return ($Targets.Count -eq 0) -or ($Targets -contains $name)
}
$homes = [ordered]@{}
foreach ($k in $allHomes.Keys) { if (Want $k) { $homes[$k] = $allHomes[$k] } }

# -----------------------------------------------------------------------------
# 1. managed-prompts：提示词实体 + 安装前备份
# -----------------------------------------------------------------------------
Write-Host '[1/5] managed-prompts（提示词实体 + 安装前备份）'
$restoreTargets = New-Object System.Collections.Generic.List[string]
foreach ($k in $homes.Keys) {
  $mp = Join-Path $homes[$k] 'managed-prompts'
  if (-not (Test-Path -LiteralPath $mp)) { continue }
  $files = @(Get-ChildItem -LiteralPath $mp -Force -ErrorAction SilentlyContinue)
  if ($files.Count -eq 0) { continue }
  foreach ($f in $files) {
    # 备份命名：<原文名>.bak / .bak_20260101 / .backup-xxx
    if ($f.Name -match '^(?<base>.+?)\.(bak|backup)([_.-].*)?$') {
      $baseName = $Matches['base']
      $target = Join-Path $homes[$k] $baseName
      if (Test-InjectionArtifact $f.FullName) {
        # 备份自己就是旧注入：还原它等于没卸载，直接删
        Plan '删除（备份本身是旧注入）' $f.FullName ''
      } else {
        $restoreTargets.Add($target)
        Plan '恢复原文（用安装前备份）' $target ("备份源: {0}" -f $f.Name) $f.FullName
      }
      continue
    }
    Plan '提示词文件' $f.FullName ("{0} / {1}" -f $k, $f.Name)
  }
  Plan '清空目录' $mp ("{0} / 清空后若为空则删除" -f $k)
}

# -----------------------------------------------------------------------------
# 2. AGENTS.md / CLAUDE.md：摘标记块；摘完只剩垃圾的就还原备份
# -----------------------------------------------------------------------------
Write-Host '[2/5] 标记块（AGENTS.md / CLAUDE.md）'
$markedAll = @(
  @{ T = 'codex'; Path = (Join-Path $codexHome 'AGENTS.md');  Begin = '<!-- 寒霜破甲注入开始'; End = '<!-- 寒霜破甲注入结束 -->' },
  @{ T = 'dsh';   Path = (Join-Path $H '.dsh\AGENTS.md');     Begin = '<!-- 寒霜破甲注入开始'; End = '<!-- 寒霜破甲注入结束 -->' },
  @{ T = 'zcode'; Path = (Join-Path $H '.zcode\AGENTS.md');   Begin = '<!-- 寒霜破甲注入开始'; End = '<!-- 寒霜破甲注入结束 -->' },
  @{ T = 'claude';Path = (Join-Path $H '.claude\CLAUDE.md');  Begin = 'HANSHUANG-INJECT:BEGIN'; End = 'HANSHUANG-INJECT:END' }
)
$marked = @($markedAll | Where-Object { Want $_.T })
foreach ($m in $marked) {
  if (-not (Test-Path -LiteralPath $m.Path)) { continue }
  if ($restoreTargets -contains $m.Path) { continue }   # 已由备份还原处理
  $t = [IO.File]::ReadAllText($m.Path)
  $i = $t.IndexOf($m.Begin)
  if ($i -lt 0) {
    if (Test-InjectionArtifact $m.Path) { Plan '注入文件（无标记但内容是提示词）' $m.Path '整份挪走' }
    else { Keep ("无注入标记，保留原样：{0}" -f $m.Path) }
    continue
  }
  # END 必须从 BEGIN 之后开始找。找不到就当作「没有完整的注入块」，一个字节都不动 ——
  # 早期写法是「找不到 END 就取文件尾」，那会把用户写在标记之后的内容整段删掉；
  # 而从文件开头找 END 还会在「END 出现在 BEGIN 之前」时算出重叠区间，把内容搅乱。
  $tailStart = $i + $m.Begin.Length
  $tail = $t.Substring($tailStart)
  $j = $tail.IndexOf($m.End)
  if ($j -lt 0) { Keep ("有开始标记但无结束标记，保留原样（不动一个字节）：{0}" -f $m.Path); continue }
  $end = $tailStart + $j + $m.End.Length
  $left = $t.Substring(0, $i) + $t.Substring($end)
  if (Test-Trivial $left) {
    Plan '注入文件（摘除后仅剩垃圾）' $m.Path '删除文件'
  } else {
    Plan '注入块' $m.Path ("摘除 {0} 字节，保留你自己的 {1} 字节" -f ($end - $i), $left.Trim().Length)
  }
}

# -----------------------------------------------------------------------------
# 3. config.toml：只在真有指向提示词的行时才动
# -----------------------------------------------------------------------------
Write-Host '[3/5] config.toml 提示词指针'
foreach ($ct in @(
    $(if (Want 'codex') { Join-Path $codexHome 'config.toml' }),
    $(if (Want 'claude') { Join-Path $H '.claude\config.toml' })
  ) | Where-Object { $_ }) {
  if (-not (Test-Path -LiteralPath $ct)) { continue }
  $lines = [IO.File]::ReadAllLines($ct)
  $idx = @()
  for ($n = 0; $n -lt $lines.Count; $n++) {
    if ($lines[$n] -match '^\s*model_instructions_file\s*=') { $idx += $n }
  }
  if ($idx.Count -eq 0) { Keep ("无提示词指针，整文件保留（{0} 行）：{1}" -f $lines.Count, $ct); continue }
  Plan '提示词指针行' $ct ("删除第 {0} 行，其余 {1} 行原样保留" -f (($idx | ForEach-Object { $_ + 1 }) -join ','), ($lines.Count - $idx.Count))
}

# -----------------------------------------------------------------------------
# 3.5 Cursor：固定文件名的注入规则文件（install-cursor.ps1 写的就这几个）
# -----------------------------------------------------------------------------
if (Want 'cursor') {
  Write-Host '[3.5/5] Cursor 注入规则文件'
  $ruleFile = '寒霜注入.mdc'
  $cand = New-Object System.Collections.Generic.List[string]

  # (a) 全局规则目录：官方读 $HOME\.cursor\rules；旧版/变体还会看 APPDATA 与 LOCALAPPDATA
  $cand.Add((Join-Path $H ".cursor\rules\$ruleFile"))
  foreach ($base in @($env:APPDATA, $env:LOCALAPPDATA)) {
    if ([string]::IsNullOrWhiteSpace($base)) { continue }
    $cand.Add((Join-Path $base "Cursor\User\rules\$ruleFile"))
    $cand.Add((Join-Path $base "Cursor\rules\$ruleFile"))
  }

  # (a2) 安装时记下的路径清单。install-cursor.ps1 把每次写过的路径存进
  #      %APPDATA%\Cursor\hs-install-state.json 的 writtenPaths —— 那是「确定写过」的记录，
  #      比反解 workspaceStorage 可靠：项目被删/挪走、或 Cursor 清掉了 workspace 记录时，
  #      只剩这份清单还认得它们。state 本身也是本工具写的，一并销掉。
  foreach ($base in @($env:APPDATA, $env:LOCALAPPDATA)) {
    if ([string]::IsNullOrWhiteSpace($base)) { continue }
    $st = Join-Path $base 'Cursor\hs-install-state.json'
    if (-not (Test-Path -LiteralPath $st)) { continue }
    Plan 'Cursor 安装状态' $st ''
    try {
      $j = [IO.File]::ReadAllText($st) | ConvertFrom-Json
      foreach ($w in @($j.writtenPaths)) {
        if ([string]::IsNullOrWhiteSpace([string]$w)) { continue }
        $p = [string]$w
        if (Test-Path -LiteralPath $p -PathType Container) { $p = Join-Path $p $ruleFile }
        if (Test-Path -LiteralPath $p) { $cand.Add($p) }
      }
    } catch { }
  }

  # (b) 项目级：Cursor 打开过的每个项目 -> {项目}\.cursor\rules\<规则文件>。
  #     项目清单没有落库，只能从 workspaceStorage 的 workspace.json 反解（可能在任意盘）。
  foreach ($base in @($env:APPDATA, $env:LOCALAPPDATA)) {
    if ([string]::IsNullOrWhiteSpace($base)) { continue }
    $wsRoot = Join-Path $base 'Cursor\User\workspaceStorage'
    if (-not (Test-Path -LiteralPath $wsRoot)) { continue }
    foreach ($wd in @(Get-ChildItem -LiteralPath $wsRoot -Directory -ErrorAction SilentlyContinue)) {
      $wsJson = Join-Path $wd.FullName 'workspace.json'
      if (-not (Test-Path -LiteralPath $wsJson)) { continue }
      try { $w = [IO.File]::ReadAllText($wsJson) | ConvertFrom-Json } catch { continue }
      $loc = $null
      if ($w.folder) { $loc = [string]$w.folder }
      elseif ($w.workspace) { $loc = [string]$w.workspace }
      if (-not $loc) { continue }
      if ($loc -match '^file:///(.+)') { $loc = $Matches[1] }
      $loc = [uri]::UnescapeDataString(($loc -replace '/', '\'))
      if (Test-Path -LiteralPath $loc) { $cand.Add((Join-Path $loc ".cursor\rules\$ruleFile")) }
    }
  }

  # (c) 盘符根祖先规则：规则沿「工作区 -> 父目录 -> ... -> 盘符根」向上加载，
  #     放在盘符根 = 该盘任意目录打开都会自动加载，所以每个固定盘都要检查
  try {
    foreach ($drv in [IO.DriveInfo]::GetDrives()) {
      if ($drv.DriveType -eq [IO.DriveType]::Fixed -and $drv.IsReady) {
        $cand.Add((Join-Path $drv.RootDirectory.FullName ".cursor\rules\$ruleFile"))
      }
    }
  } catch { }

  foreach ($f in ($cand | Select-Object -Unique)) {
    if (Test-Path -LiteralPath $f) { Plan 'Cursor 规则文件' $f '' }
  }

  # (d) 旧版往用户主目录写过 .cursorrules；只在内容确实带注入痕迹时才动
  $legacy = Join-Path $H '.cursorrules'
  if ((Test-Path -LiteralPath $legacy) -and (Test-InjectionArtifact $legacy)) {
    Plan 'Cursor 规则文件（旧版）' $legacy ''
  }
}

# -----------------------------------------------------------------------------
# 4. 记忆文件里的提示词注入
# -----------------------------------------------------------------------------
Write-Host '[4/5] 记忆文件注入'
$memSummary = Join-Path $codexHome 'memories\memory_summary.md'
if ((Want 'codex') -and (Test-Path -LiteralPath $memSummary)) {
  $t = [IO.File]::ReadAllText($memSummary)
  $hits = [regex]::Matches($t, '(?m)^## [^\r\n]*寒霜注入[^\r\n]*')
  if ($hits.Count -gt 0) { Plan '记忆注入章节' $memSummary ("删除 {0} 个章节" -f $hits.Count) }
  else { Keep ("无寒霜注入章节：{0}" -f $memSummary) }
}

# WorkBuddy 档案路径自适应：先读 state（可能在任意盘），读不到才限深扫盘
$wbHomes = if (Want 'workbuddy') { @((Join-Path $H '.workbuddy-ai'), (Join-Path $H '.workbuddy')) } else { @() }
$archives = New-Object System.Collections.Generic.List[string]
foreach ($wh in $wbHomes) {
  $st = Join-Path $wh '.hanshuang-state.json'
  if (Test-Path -LiteralPath $st) {
    Plan 'WorkBuddy state' $st ''
    try {
      $j = [IO.File]::ReadAllText($st) | ConvertFrom-Json
      foreach ($a in @($j.archives)) { if ($a) { $archives.Add([string]$a) } }
      if ($j.archive) { $archives.Add([string]$j.archive) }
      if ($j.memoryDir -and (Test-Path -LiteralPath $j.memoryDir)) {
        foreach ($f in @(Get-ChildItem -LiteralPath $j.memoryDir -Filter '*_memory.md' -File -ErrorAction SilentlyContinue)) {
          $archives.Add($f.FullName)
        }
      }
    } catch { }
  }
  # 不论有没有 state，都把该 Home 的 memory 目录整个收进来。
  # 只读 state 会漏：一个 Home 有 state、另一个没有时，没有 state 那个的档案会被跳过
  #（实测 .workbuddy-ai 有 state 时，.workbuddy\memory 下的档案就被漏掉了一轮）。
  $md = Join-Path $wh 'memory'
  if (Test-Path -LiteralPath $md) {
    foreach ($f in @(Get-ChildItem -LiteralPath $md -Filter '*_memory.md' -File -Force -ErrorAction SilentlyContinue)) {
      $archives.Add($f.FullName)
    }
    # 档案的备份与临时副本。WorkBuddy 写档案走 tmp+rename，异常中断会留下
    # <名>.bak.tmp.<pid>.<ts>.<rand>，里面是清空前的 Memory Block 内容 —— 也就是提示词本身
    #（实测每个 20KB 左右，跟主档案一样大）。它们在 memory\ 子目录下，
    # 第 4.5 节 (a) 的「Home 根目录」扫描够不着，所以在这里单独收。
    foreach ($f in @(Get-ChildItem -LiteralPath $md -File -Force -ErrorAction SilentlyContinue |
                     Where-Object { $_.Name -match '\.(bak|tmp)([_.-].*)?$' -and $_.Name -notmatch '\.bak-inject$' -and $_.Length -lt 2MB })) {
      if (Test-InjectionArtifact $f.FullName) {
        Plan '注入副产物（内容是提示词）' $f.FullName ("workbuddy / {0}" -f $f.Name)
      } else {
        Keep ("备份不含提示词，保留：{0}" -f $f.FullName)
      }
    }
  }
}
# 限深扫盘只是「state 读不到」时的兜底。指定了别的目标时根本不该跑 ——
# 否则 -Targets codex 也会去扫盘找 WorkBuddy 档案。
# 限深扫盘的代价很高（遍历所有固定盘）。只在「用户确实装了 WorkBuddy」时才做 ——
# 两个 Home 目录都不存在时扫盘纯属白跑，没装 WorkBuddy 的机器会被白白卡住好几分钟。
$wbInstalled = @($wbHomes | Where-Object { Test-Path -LiteralPath $_ }).Count -gt 0
if ((Want 'workbuddy') -and $archives.Count -eq 0 -and $wbInstalled) {
  Write-Host ("  未找到 WorkBuddy state，限深 {0} 层扫描各盘 ..." -f $ScanDepth)
  foreach ($root in @(Get-PSDrive -PSProvider FileSystem | ForEach-Object { $_.Root })) {
    foreach ($f in @(Get-ChildItem -LiteralPath $root -Filter '*_memory.md' -Recurse -Depth $ScanDepth -File -Force -ErrorAction SilentlyContinue)) {
      $archives.Add($f.FullName)
    }
  }
  if ($archives.Count -eq 0) { Write-Host '  没扫到 *_memory.md' }
}
# WorkBuddy 的全局记忆与注入前备份（.bak-inject）：和 managed-prompts 的 .bak 同理，
# .bak-inject 是注入前原文，要「还原」而不是删掉，否则用户的 MEMORY.md 就永久丢了
foreach ($wh in $wbHomes) {
  if (-not (Test-Path -LiteralPath $wh)) { continue }
  foreach ($bak in @(Get-ChildItem -LiteralPath $wh -Recurse -Depth 2 -Filter '*.bak-inject' -File -Force -ErrorAction SilentlyContinue)) {
    $baseName = $bak.Name -replace '\.bak-inject$', ''
    $target = Join-Path (Split-Path -Parent $bak.FullName) $baseName
    if (Test-InjectionArtifact $bak.FullName) {
      Plan '删除（备份本身是旧注入）' $bak.FullName ''
      # 备份都是旧注入了，说明这份文件历来就是我们写的：目标若还是注入内容就一并清掉，
      # 否则「零提示词」会失败（实测 MEMORY.md 被这种旧备份还原成了提示词正文）。
      if ((Test-Path -LiteralPath $target) -and (Test-InjectionArtifact $target)) {
        Plan 'WorkBuddy 全局记忆（注入产物）' $target '整份删除'
      }
    } else {
      Plan '恢复原文（用安装前备份）' $target ("备份源: {0}" -f $bak.Name) $bak.FullName
    }
  }
  $fileMem = Join-Path $wh 'MEMORY.md'
  if ((Test-Path -LiteralPath $fileMem) -and -not (Test-Path -LiteralPath ($fileMem + '.bak-inject'))) {
    if (Test-InjectionArtifact $fileMem) { Plan 'WorkBuddy 全局记忆（注入产物）' $fileMem '' }
    else { Keep ("MEMORY.md 无注入痕迹，保留：{0}" -f $fileMem) }
  }
}

foreach ($a in ($archives | Select-Object -Unique)) {
  if (-not (Test-Path -LiteralPath $a)) { continue }
  $t = [IO.File]::ReadAllText($a)
  if ($t -notmatch '## Memory Block') { continue }
  if ($t -match '(?s)## Memory Block\s*\r?\n\r?\n\s*\r?\n') { Keep ("Memory Block 已是空段：{0}" -f $a); continue }
  Plan 'WorkBuddy 记忆块' $a '清空 Memory Block 内容（档案文件本身保留）'
}

# -----------------------------------------------------------------------------
# 4.5 注入副产物：备份文件 / 随附包 / 技能树
#
# 这些不是「注入点」，而是注入过程本身的产物 —— 但里面装的往往就是提示词正文：
# 实测 ~/.zcode/AGENTS.md.backup-* 与随包的 寒霜v1.2.md / 寒霜v4.md 逐字节相同。
# 旧版只扫注入点，这些全留在盘上，用户看到的现象就是「卸载完提示词还在」。
#
# 判定一律走 Test-InjectionArtifact（按内容判定，不看文件名），
# 所以用户自己的备份（内容是用户原文）不会被误删。
# -----------------------------------------------------------------------------
Write-Host '[4.5/5] 注入副产物（备份 / 随附包 / 技能树）'

$bundleRoot = Split-Path -Parent $PSScriptRoot   # scripts\.. = 项目根 / 打包后的 resources
$plannedPaths = New-Object System.Collections.Generic.HashSet[string]

# (a) 各 Home 根目录下的备份与临时文件。
#     覆盖命名：<名>.backup-<时间戳> / <名>.bak / <名>.bak_<时间戳> / <名>.bak-<后缀>
#     / <名>.inject-<时间戳> / <名>.bak.tmp.<pid>.<ts>.<rand>（WorkBuddy 程序写档案的中间产物）
#     .bak-inject 不在此列 —— 那是 WorkBuddy 的用户原文备份，第 4 节已按「还原」处理。
#     超过 2MB 的跳过：那体量不可能是提示词正文，且逐个读全文会拖慢卸载
#     （如 ~/.zcode/zcode.cjs.backup-* 每个 12.6MB，属于程序本体备份，另行处理）。
$artifactPattern = '\.(backup|bak|inject|tmp)([_.-][^\\/]*)?$'
foreach ($k in $homes.Keys) {
  $h = $homes[$k]
  if (-not (Test-Path -LiteralPath $h)) { continue }
  $cands = @(Get-ChildItem -LiteralPath $h -File -Force -ErrorAction SilentlyContinue |
             Where-Object { $_.Name -match $artifactPattern -and $_.Name -notmatch '\.bak-inject$' -and $_.Length -lt 2MB })
  foreach ($f in $cands) {
    if (Test-InjectionArtifact $f.FullName) {
      Plan '注入副产物（内容是提示词）' $f.FullName ("{0} / {1}" -f $k, $f.Name)
      [void]$plannedPaths.Add($f.FullName)
    } elseif (Test-SpentBackup $f.FullName) {
      # 本工具在注入前留的主文件备份，而主文件现在已还原干净 → 它只是保险，使命已完成。
      # 主文件还带着注入时 Test-SpentBackup 返回 false，备份会走下面的 Keep 留着。
      Plan '主文件备份（已还原，备份无用）' $f.FullName ("{0} / {1}" -f $k, $f.Name)
      [void]$plannedPaths.Add($f.FullName)
    } else {
      Keep ("备份不含提示词，保留：{0}" -f $f.FullName)
    }
  }
}

# (a2) ZCode 程序本体备份：install-zcode.ps1 在 patch zcode.cjs 之前留的副本，
#      每个 12MB 上下，一次安装一份。它们不含提示词正文，但同属本工具的产物，体量还最大。
#
#      ★ 删之前必须确认三件事，缺一不可 —— 备份是还原 zcode.cjs 的唯一依据，
#        而 install-zcode.ps1 卸载时无论还原成功与否都会删掉 install-state.json，
#        所以「state 没了」并不能推出「已经还原过了」。删错就是把 ZCode 弄成永久注入态。
#        1) install-state.json 已不存在（卸载器跑过了）
#        2) 能找到 zcode.cjs（ZCode 还装着；装在自定义目录时靠运行中的进程定位）
#        3) zcode.cjs 本身已不含注入标记
#      任何一条不满足就原样保留，只打一行说明。
if (Want 'zcode') {
  $zcHome = $homes['zcode']
  $zcBackups = @()
  if (Test-Path -LiteralPath $zcHome) {
    $zcBackups = @(Get-ChildItem -LiteralPath $zcHome -File -Force -ErrorAction SilentlyContinue |
                   Where-Object { $_.Name -like 'zcode.cjs.backup-*' })
  }
  if ($zcBackups.Count -gt 0) {
    # 定位 zcode.cjs：先问运行中的进程（能覆盖自定义安装目录，如 E:\9999\ZCode），再试常见位置
    $zcCjs = $null
    $zcProc = @(Get-Process -Name 'ZCode' -ErrorAction SilentlyContinue | Where-Object { $_.Path } | Select-Object -First 1)
    if ($zcProc.Count -gt 0) {
      $cand = Join-Path (Split-Path -Parent $zcProc[0].Path) 'resources\glm\zcode.cjs'
      if (Test-Path -LiteralPath $cand) { $zcCjs = $cand }
    }
    if (-not $zcCjs) {
      foreach ($base in @($env:ProgramFiles, ${env:ProgramFiles(x86)}, (Join-Path $env:LOCALAPPDATA 'Programs'), $env:APPDATA)) {
        if ([string]::IsNullOrWhiteSpace($base)) { continue }
        $cand = Join-Path $base 'ZCode\resources\glm\zcode.cjs'
        if (Test-Path -LiteralPath $cand) { $zcCjs = $cand; break }
      }
    }
    if (Test-Path -LiteralPath (Join-Path $zcHome 'install-state.json')) {
      Keep ("install-state.json 仍在（卸载器没跑过），{0} 份本体备份保留" -f $zcBackups.Count)
    } elseif (-not $zcCjs) {
      Keep ("zcode.cjs 未找到（ZCode 没装或在自定义目录），{0} 份本体备份保守保留" -f $zcBackups.Count)
    } else {
      $zcStillInjected = $true
      try { $zcStillInjected = ([IO.File]::ReadAllText($zcCjs)).Contains('CTF-LAB-2.0') } catch { $zcStillInjected = $true }
      if ($zcStillInjected) {
        Keep ("zcode.cjs 仍含注入标记，{0} 份本体备份保留（那是唯一还原依据）：{1}" -f $zcBackups.Count, $zcCjs)
      } else {
        foreach ($f in $zcBackups) { Plan '程序本体备份（已无还原需求）' $f.FullName ("zcode / {0}" -f $f.Name) }
      }
    }
  }
}

# (b) DSH 的具名注入文件：install-dsh.ps1 写在 Home 根下、名字固定，
#     既不是标记块也不叫 .bak，旧的扫描规则全都够不着。
if (Want 'dsh') {
  foreach ($n in 'prompt-inject.md', 'shield-protocol.md', 'dsh-prompt-inject.json') {
    $p = Join-Path $homes['dsh'] $n
    if (-not (Test-Path -LiteralPath $p)) { continue }
    if ($restoreTargets -contains $p) { continue }   # 已由 managed-prompts 的备份还原处理
    Plan 'DSH 注入文件' $p $n
    [void]$plannedPaths.Add($p)
  }
}

# (c) 随附包（bundle）：装在 Home 根下、但【不在 skills/ 树内】—— install.ps1 故意隔离部署，
#     因为包里自带大量嵌套 SKILL.md，放进 skills/ 会被技能发现机制扫成重名技能。
#     删除条件：目录名与随包一致 **且** SKILL.md 内容逐字节相同（防止误删用户同名目录）。
$bundleSrc = Join-Path $bundleRoot 'codex-bundle-v5'
if ((Want 'codex') -and (Test-Path -LiteralPath $bundleSrc)) {
  foreach ($d in @(Get-ChildItem -LiteralPath $bundleSrc -Directory -ErrorAction SilentlyContinue)) {
    $installed = Join-Path $homes['codex'] $d.Name
    if (Test-Path -LiteralPath $installed) {
      $a = Join-Path $d.FullName 'SKILL.md'
      $b = Join-Path $installed 'SKILL.md'
      $same = (Test-Path -LiteralPath $a) -and (Test-Path -LiteralPath $b) -and
              ((Get-FileHash -LiteralPath $a).Hash -eq (Get-FileHash -LiteralPath $b).Hash)
      if ($same) {
        Plan '随附包（确认是本工具的）' $installed ("{0} / SKILL.md 与随包一致" -f $d.Name)
        [void]$plannedPaths.Add($installed)
      } else {
        Keep ("随附包同名目录但内容与随包不符，保留：{0}" -f $installed)
      }
    }
    # 覆盖安装前建的备份目录：<名>.bak-<时间戳>（install.ps1 Install-Bundles 所建）
    foreach ($bk in @(Get-ChildItem -LiteralPath $homes['codex'] -Directory -Force -ErrorAction SilentlyContinue |
                      Where-Object { $_.Name -like ($d.Name + '.bak-*') })) {
      if ($plannedPaths.Add($bk.FullName)) { Plan '随附包备份' $bk.FullName '' }
    }
  }
}

# (d) 技能树：<Home>/skills/<名>，以及 DSH 的 <Home>/skills-disabled/<名>
#     —— install-dsh.ps1 会把窄场景技能从 skills 移到 skills-disabled 停用，两处装的是同一批东西。
#     删除条件：目录名与随包技能库一致 **且** SKILL.md 内容逐字节相同 ——
#     用户自己装的同名技能必须留下。
$dshSkillLib = Join-Path $bundleRoot 'dsh-lazy-pack-v5\materials\skills'
if (-not (Test-Path -LiteralPath $dshSkillLib)) {
  # 开发态：懒人包是项目目录的兄弟目录，不在项目里
  $dshSkillLib = Join-Path (Split-Path -Parent $bundleRoot) 'dsh-lazy-pack-v5\materials\skills'
}
$skillLibRoots = @(
  (Join-Path $bundleRoot 'codex-skills'),
  (Join-Path $bundleRoot 'codex-skills-v4'),
  (Join-Path $bundleRoot 'codex-skills-v5'),
  $dshSkillLib   # DSH 的技能来自懒人包，不在这几个 codex 技能库里
)
# workbuddy 的两个数据目录不在 $homes 里（它的注入点是单独处理的），但技能树的清理逻辑
# 完全一样，这里补进来 —— 漏掉的话，WorkBuddy 里装的技能卸载后一个都清不掉（实测漏了 63 个）。
$skillHomeList = @()
foreach ($homeKey in $homes.Keys) { $skillHomeList += @{ Name = $homeKey; Path = $homes[$homeKey] } }
if (Want 'workbuddy') {
  $skillHomeList += @{ Name = 'workbuddy-intl'; Path = (Join-Path $H '.workbuddy-ai') }
  $skillHomeList += @{ Name = 'workbuddy-cn';   Path = (Join-Path $H '.workbuddy') }
}
foreach ($entry in $skillHomeList) {
  $k = $entry.Name
  foreach ($sub in 'skills', 'skills-disabled') {
    $sk = Join-Path $entry.Path $sub
    if (-not (Test-Path -LiteralPath $sk)) { continue }
    foreach ($libDir in $skillLibRoots) {
      if (-not (Test-Path -LiteralPath $libDir)) { continue }
      foreach ($d in @(Get-ChildItem -LiteralPath $libDir -Directory -ErrorAction SilentlyContinue)) {
        $dst = Join-Path $sk $d.Name
        if (-not (Test-Path -LiteralPath $dst)) { continue }
        if ($plannedPaths.Contains($dst)) { continue }
        $a = Join-Path $d.FullName 'SKILL.md'
        $b = Join-Path $dst 'SKILL.md'
        $same = (Test-Path -LiteralPath $a) -and (Test-Path -LiteralPath $b) -and
                ((Get-FileHash -LiteralPath $a).Hash -eq (Get-FileHash -LiteralPath $b).Hash)
        if ($same) {
          Plan '技能（确认是本工具的）' $dst ("{0} / {1} / {2}" -f $k, $sub, $d.Name)
          [void]$plannedPaths.Add($dst)
        } else {
          Keep ("skills 下同名但内容不符，保留：{0}" -f $dst)
        }
      }
    }
    # skills-disabled 下本工具写的说明文件（内容里点名了「寒霜破甲工具」，据此认领）
    $rd = Join-Path $sk 'README.txt'
    if (Test-Path -LiteralPath $rd) {
      $rt = ''
      try { $rt = [IO.File]::ReadAllText($rd) } catch { }
      if ($rt -match '寒霜破甲工具') { Plan '本工具生成的说明文件' $rd ("{0} / {1}" -f $k, $sub) }
    }
  }
}

# (e) Oh My Pi：install-omp.ps1 的两套产物 —— 原生规则（-Scope all）、provider 级规则源 +
#     扩展（-Scope cursor），外加它自己的安装状态文件。位置随 PI_CODING_AGENT_DIR /
#     OMP_PROFILE / PI_PROFILE 变（判定顺序与 install-omp.ps1 的 Resolve-AgentDir 一致）。
#     只认带 HANSHUANG-OMP-INJECT 标记的文件；没标记的一律保留。
if (Want 'omp') {
  $ompAgent = $null
  if (-not [string]::IsNullOrWhiteSpace($env:PI_CODING_AGENT_DIR)) { $ompAgent = $env:PI_CODING_AGENT_DIR }
  elseif (-not [string]::IsNullOrWhiteSpace($env:OMP_PROFILE) -or -not [string]::IsNullOrWhiteSpace($env:PI_PROFILE)) {
    $ompProfile = if (-not [string]::IsNullOrWhiteSpace($env:OMP_PROFILE)) { $env:OMP_PROFILE } else { $env:PI_PROFILE }
    $ompAgent = Join-Path $H ".omp\profiles\$ompProfile\agent"
  } else { $ompAgent = Join-Path $H '.omp\agent' }

  $ompFiles = @(
    (Join-Path $ompAgent 'rules\寒霜注入.mdc'),
    (Join-Path $ompAgent 'hanshuang\寒霜注入.md'),
    (Join-Path $ompAgent 'hooks\pre\hanshuang-cursor-scoped.ts')
  )
  foreach ($p in $ompFiles) {
    if (-not (Test-Path -LiteralPath $p)) { continue }
    $t = ''
    try { $t = [IO.File]::ReadAllText($p) } catch { }
    if ($t -match 'HANSHUANG-OMP-INJECT') {
      Plan 'OMP 注入文件' $p '含注入标记'
      [void]$plannedPaths.Add($p)
    } else {
      Keep ("OMP 路径下但无注入标记，保留：{0}" -f $p)
    }
  }

  $ompState = Join-Path $ompAgent 'hs-install-state.json'
  if (Test-Path -LiteralPath $ompState) {
    $st = ''
    try { $st = [IO.File]::ReadAllText($ompState) } catch { }
    if ($st -match '寒霜注入|hanshuang-cursor-scoped') { Plan 'OMP 安装状态' $ompState '本工具的安装记录' }
    else { Keep ("OMP 安装状态内容不是本工具的，保留：{0}" -f $ompState) }
  }
}

# -----------------------------------------------------------------------------
# 5. 报告
# -----------------------------------------------------------------------------
Write-Host '[5/5] 汇总'
Write-Host ''
if ($kept.Count) {
  Write-Host '--- 保留（不是提示词，原样不动） ---' -ForegroundColor Yellow
  $kept | ForEach-Object { Write-Host ('  ' + $_) }
  Write-Host ''
}
if (-not $plan.Count) {
  Write-Host '没有发现任何注入提示词残留。' -ForegroundColor Green
  exit 0
}
if ($ListOnly) {
  # 只吐路径，供其它脚本解析。不走 Write-Host（那是 information stream，重定向行为不稳定）。
  foreach ($p in $plan) { Write-Output $p.Path }
  exit 0
}
Write-Host ("--- 待清除 {0} 项 ---" -f $plan.Count) -ForegroundColor Cyan
foreach ($p in $plan) { Write-Host ("  [{0}] {1} {2}" -f $p.Kind, $p.Path, $p.Note) }

if (-not $Apply) {
  Write-Host ''
  Write-Host 'DRY-RUN 结束，未改动任何东西。确认后加 -Apply 执行。' -ForegroundColor Yellow
  exit 0
}

Write-Host ''
Write-Host '--- 开始清除 ---' -ForegroundColor Cyan
$fail = 0
foreach ($p in $plan) {
  try {
    switch ($p.Kind) {
      '恢复原文（用安装前备份）' {
        if (-not (Test-Path -LiteralPath $p.Src)) { throw "备份不存在: $($p.Src)" }
        Copy-Item -LiteralPath $p.Src -Destination $p.Path -Force
        Remove-Item -LiteralPath $p.Src -Force
      }
      '删除（备份本身是旧注入）' { Remove-Item -LiteralPath $p.Path -Force -ErrorAction Stop }
      '注入文件（摘除后仅剩垃圾）' {
        # 先试着找一份干净备份还原，找不到才删
        $home = Split-Path -Parent $p.Path
        $base = Split-Path -Leaf $p.Path
        $clean = @(Get-ChildItem -LiteralPath (Join-Path $home 'managed-prompts') -Filter ($base + '.bak*') -File -ErrorAction SilentlyContinue |
                   Where-Object { -not (Test-InjectionArtifact $_.FullName) -and $_.Length -gt 0 } |
                   Sort-Object LastWriteTime -Descending | Select-Object -First 1)
        if ($clean) {
          Copy-Item -LiteralPath $clean[0].FullName -Destination $p.Path -Force
          Remove-Item -LiteralPath $clean[0].FullName -Force
        } else {
          Remove-Item -LiteralPath $p.Path -Force -ErrorAction Stop
        }
      }
      '注入文件（无标记但内容是提示词）' {
        $aside = $p.Path + '.inject-' + (Get-Date -Format 'yyyyMMdd-HHmmss')
        Move-Item -LiteralPath $p.Path -Destination $aside -Force
        $home = Split-Path -Parent $p.Path
        $base = Split-Path -Leaf $p.Path
        $clean = @(Get-ChildItem -LiteralPath (Join-Path $home 'managed-prompts') -Filter ($base + '.bak*') -File -ErrorAction SilentlyContinue |
                   Where-Object { -not (Test-InjectionArtifact $_.FullName) -and $_.Length -gt 0 } |
                   Sort-Object LastWriteTime -Descending | Select-Object -First 1)
        if ($clean) {
          Copy-Item -LiteralPath $clean[0].FullName -Destination $p.Path -Force
          Remove-Item -LiteralPath $clean[0].FullName -Force
        }
      }
      '注入块' {
        foreach ($m in $marked) {
          if ($m.Path -ne $p.Path) { continue }
          $t = [IO.File]::ReadAllText($p.Path)
          $i = $t.IndexOf($m.Begin); if ($i -lt 0) { break }
          $tailStart = $i + $m.Begin.Length
          $j = $t.Substring($tailStart).IndexOf($m.End)
          if ($j -lt 0) { break }   # 无结束标记：不动这个文件（判定阶段也不会把它排进来）
          $end = $tailStart + $j + $m.End.Length
          $left = ($t.Substring(0, $i) + $t.Substring($end)).Trim()
          if ($left.Length -gt 0) { [IO.File]::WriteAllText($p.Path, $left + [Environment]::NewLine, [Text.UTF8Encoding]::new($false)) }
        }
      }
      '提示词指针行' {
        # 只删「值指向本工具 managed-prompts」的行。指向别处的是用户自己的配置，必须保留 ——
        # 无条件删会把用户自己配的 model_instructions_file 一起删掉。
        # （install.ps1 -Uninstall 会用 state.previousLine 还原用户原值；本脚本跑在它之后，
        #   那时 state 已被删除，所以这里做的是「按值判定」这层兜底。）
        $keptLines = @([IO.File]::ReadAllLines($p.Path) | Where-Object {
          if ($_ -notmatch '^\s*model_instructions_file\s*=') { return $true }
          return ($_ -notmatch 'managed-prompts')
        })
        [IO.File]::WriteAllLines($p.Path, $keptLines, [Text.UTF8Encoding]::new($false))
      }
      '记忆注入章节' {
        $t = [IO.File]::ReadAllText($p.Path)
        $new = [regex]::Replace($t, '(?ms)^## [^\r\n]*寒霜注入[^\r\n]*\r?\n.*?(?=^## |\z)', '')
        $new = [regex]::Replace($new, '(\r?\n){3,}', "`r`n`r`n")
        [IO.File]::WriteAllText($p.Path, $new.TrimEnd() + [Environment]::NewLine, [Text.UTF8Encoding]::new($false))
      }
      'WorkBuddy 记忆块' {
        # WorkBuddyGuard 写入后会 chmod 444，先解只读
        try { $item = Get-Item -LiteralPath $p.Path -Force; if ($item.IsReadOnly) { $item.IsReadOnly = $false } } catch { }
        $t = [IO.File]::ReadAllText($p.Path)
        $new = [regex]::Replace($t, '(?s)(## Memory Block\s*\r?\n)\r?\n.*?(?=\r?\n\r?\n---|\z)', "`$1`r`n")
        [IO.File]::WriteAllText($p.Path, $new, [Text.UTF8Encoding]::new($false))
      }
      'WorkBuddy state' { Remove-Item -LiteralPath $p.Path -Force -ErrorAction Stop }
      'WorkBuddy 全局记忆（注入产物）' { Remove-Item -LiteralPath $p.Path -Force -ErrorAction Stop }
      # 下面这些是「整份就是提示词/就是本工具建的」的删除类动作。
      # 全部写成显式 case：曾经靠 default 兜底删除，结果类别字符串一改就静默删错东西。
      '提示词文件' { Remove-Item -LiteralPath $p.Path -Recurse -Force -ErrorAction Stop }
      '清空目录'   { Remove-Item -LiteralPath $p.Path -Recurse -Force -ErrorAction Stop }
      'Cursor 规则文件'         { Remove-Item -LiteralPath $p.Path -Force -ErrorAction Stop }
      'Cursor 规则文件（旧版）' { Remove-Item -LiteralPath $p.Path -Force -ErrorAction Stop }
      # 4.5 节的三类：判定阶段已经用 Test-InjectionArtifact / SKILL.md 哈希确认过归属，这里直接删
      '注入副产物（内容是提示词）' { Remove-Item -LiteralPath $p.Path -Force -ErrorAction Stop }
      'DSH 注入文件'               { Remove-Item -LiteralPath $p.Path -Force -ErrorAction Stop }
      'OMP 注入文件'               { Remove-Item -LiteralPath $p.Path -Force -ErrorAction Stop }
      'OMP 安装状态'               { Remove-Item -LiteralPath $p.Path -Force -ErrorAction Stop }
      '随附包（确认是本工具的）'   { Remove-Item -LiteralPath $p.Path -Recurse -Force -ErrorAction Stop }
      '随附包备份'                 { Remove-Item -LiteralPath $p.Path -Recurse -Force -ErrorAction Stop }
      '技能（确认是本工具的）'     { Remove-Item -LiteralPath $p.Path -Recurse -Force -ErrorAction Stop }
      '本工具生成的说明文件'       { Remove-Item -LiteralPath $p.Path -Force -ErrorAction Stop }
      'Cursor 安装状态'            { Remove-Item -LiteralPath $p.Path -Force -ErrorAction Stop }
      '程序本体备份（已无还原需求）' { Remove-Item -LiteralPath $p.Path -Force -ErrorAction Stop }
      '主文件备份（已还原，备份无用）' { Remove-Item -LiteralPath $p.Path -Force -ErrorAction Stop }
      default {
        # 认不出的类别绝不删 —— 曾经因为类别字符串不一致（「安装前备份」vs「注入前备份」）
        # 掉进这里，把该「还原」的目标文件直接删了。宁可报错，不许猜。
        throw ("未知的清理类别，已跳过（不做任何删除）: " + $p.Kind + " -> " + $p.Path)
      }
    }
    Write-Host ("  OK   [{0}] {1}" -f $p.Kind, $p.Path) -ForegroundColor Green
  } catch {
    $fail++
    Write-Host ("  FAIL [{0}] {1} :: {2}" -f $p.Kind, $p.Path, $_.Exception.Message) -ForegroundColor Red
  }
}
# managed-prompts 清空后若已为空，目录本身也删掉
foreach ($k in $homes.Keys) {
  $mp = Join-Path $homes[$k] 'managed-prompts'
  if ((Test-Path -LiteralPath $mp) -and -not (Get-ChildItem -LiteralPath $mp -Force | Select-Object -First 1)) {
    Remove-Item -LiteralPath $mp -Force -ErrorAction SilentlyContinue
    Write-Host ("  OK   [空目录] {0}" -f $mp) -ForegroundColor Green
  }
}

Write-Host ''
Write-Host ("清除完成，失败 {0} 项。" -f $fail)
if ($fail -gt 0) { exit 1 }
exit 0
