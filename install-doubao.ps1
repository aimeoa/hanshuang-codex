# 豆包（Doubao）破甲注入
#
# 和别的目标不一样：豆包的全局记忆不在本地磁盘，存在字节云端、绑定账号。
# 本地只有开关状态（IndexedDB 里的 switchMemoryV2_），没有记忆正文。
# 所以这里不写文件，而是用 CDP 驱动豆包客户端自身的登录会话去调云端接口：
#   /alice/generaltask/memory/get_agentsmd   读全局记忆
#   /alice/generaltask/memory/set_agentsmd   整份覆盖写全局记忆
#
# 前提：豆包必须以 --remote-debugging-port=<Port> 运行。没开的话本脚本会自动
# 重启豆包到调试模式（会话在云端，重启不丢聊天记录）。
#
# 用法：
#   .\install-doubao.ps1                          # 装 V4（Claude 版）提示词
#   .\install-doubao.ps1 -SourcePrompt .\x.md     # 指定提示词
#   .\install-doubao.ps1 -Status                  # 看当前全局记忆
#   .\install-doubao.ps1 -Uninstall               # 还原注入前的记忆

param(
    [string]$SourcePrompt,
    [string]$Version = 'v4',
    [switch]$Uninstall,
    [switch]$Status,
    [switch]$NoLaunch,
    [int]$Port = 9222
)

$ErrorActionPreference = 'Stop'
$OutputEncoding = [System.Text.UTF8Encoding]::new($false)

$Root = if ($ScriptRoot) { $ScriptRoot } else { $PSScriptRoot }
if (-not $Root) { $Root = Split-Path -Parent $MyInvocation.MyCommand.Path }

$Utf8NoBom = New-Object System.Text.UTF8Encoding($false)
# 子进程 stdout 会被上层（electron/main.cjs）按 UTF-8 解码，
# 必须先锁定控制台输出编码为 UTF-8，否则中文会以 GBK 写出而变成乱码（U+FFFD）。
try { [Console]::OutputEncoding = $Utf8NoBom } catch {}
try { $OutputEncoding = $Utf8NoBom } catch {}
function Read-Utf8([string]$Path) { return [System.IO.File]::ReadAllText($Path, [System.Text.Encoding]::UTF8) }
function Write-Utf8([string]$Path, [string]$Text) {
    $dir = Split-Path -Parent $Path
    if ($dir -and -not (Test-Path -LiteralPath $dir)) { New-Item -ItemType Directory -Path $dir -Force | Out-Null }
    $tmp = "$Path.tmp"
    [System.IO.File]::WriteAllText($tmp, $Text, $Utf8NoBom)
    Move-Item -LiteralPath $tmp -Destination $Path -Force
}
function Write-Log([string]$Text) {
    $dir = Join-Path $env:USERPROFILE '.doubao'
    if (-not (Test-Path -LiteralPath $dir)) { New-Item -ItemType Directory -Path $dir -Force | Out-Null }
    $f = Join-Path $dir 'hanshuang-doubao.log'
    try { Add-Content -LiteralPath $f -Value ("[{0}] {1}" -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'), $Text) -Encoding UTF8 } catch { }
}

# ---------- 提示词来源 ----------
$promptMap = @{ 'v4' = '寒霜v4-claude.md'; 'v3' = '寒霜v3.md'; 'v5' = '寒霜v5.md' }
if (-not $SourcePrompt) { $SourcePrompt = Join-Path $Root $promptMap[$Version] }
if (-not (Test-Path -LiteralPath $SourcePrompt)) { throw "提示词文件不存在: $SourcePrompt" }
$srcText = Read-Utf8 $SourcePrompt
$srcHash = (Get-FileHash -LiteralPath $SourcePrompt -Algorithm SHA256).Hash

$stateDir = Join-Path $env:USERPROFILE '.doubao\managed-prompts'
$stateFile = Join-Path $stateDir 'state.json'
$backupFile = Join-Path $stateDir 'agentsmd-backup.md'

# ---------- 找豆包 ----------
function Resolve-DoubaoExe {
    $cands = @()
    foreach ($rp in @('HKLM:\Software\Microsoft\Windows\CurrentVersion\Uninstall\*',
                      'HKLM:\Software\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall\*',
                      'HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\*')) {
        $item = Get-ItemProperty $rp -ErrorAction SilentlyContinue |
            Where-Object { $_.DisplayName -like '*豆包*' -and $_.InstallLocation } | Select-Object -First 1
        if ($item) { $cands += ((($item.InstallLocation -replace '^"|"$', '').TrimEnd('\')) + '\Doubao.exe') }
    }
    $proc = Get-Process Doubao -ErrorAction SilentlyContinue | Where-Object { $_.Path } | Select-Object -First 1
    if ($proc) { $cands += $proc.Path }
    $cands += 'E:\Doubao\Doubao.exe'
    $cands += (Join-Path $env:LOCALAPPDATA 'Doubao\Doubao.exe')
    $cands += (Join-Path ${env:ProgramFiles} 'Doubao\Doubao.exe')
    foreach ($c in $cands) {
        if ($c -and (Test-Path -LiteralPath $c)) { return (Resolve-Path -LiteralPath $c).Path }
    }
    return ''
}

function Get-DoubaoProcs { return @(Get-Process Doubao -ErrorAction SilentlyContinue) }

function Test-DebugPort {
    try {
        $r = Invoke-RestMethod -Uri "http://127.0.0.1:$Port/json/version" -TimeoutSec 3 -ErrorAction Stop
        return [bool]$r.webSocketDebuggerUrl
    } catch { return $false }
}

function Start-DoubaoDebug([string]$Exe) {
    # app\Doubao.exe 是真正的 Chromium 主体；根目录那个是启动器，调试参数要交给 app 下的
    $appExe = Join-Path (Split-Path -Parent $Exe) 'app\Doubao.exe'
    if (-not (Test-Path -LiteralPath $appExe)) { $appExe = $Exe }
    Start-Process -FilePath $appExe -ArgumentList "--remote-debugging-port=$Port" | Out-Null
    for ($i = 0; $i -lt 40; $i++) {
        Start-Sleep -Milliseconds 500
        if (Test-DebugPort) { return $true }
    }
    return $false
}

# ---------- CDP ----------
function Get-CdpTargets {
    return @(Invoke-RestMethod -Uri "http://127.0.0.1:$Port/json/list" -TimeoutSec 10)
}

function Select-DoubaoTarget {
    $list = Get-CdpTargets
    # 优先级：www.doubao.com 的 iframe（旧版结构）→ 对话页 doubao-chat/chat（当前版本）
    #        → 启动器页 → 任意 www.doubao.com
    # 绝不能选 doubao://doubao-background —— 那是后台页，调接口只会返回 HTML
    foreach ($pat in @('doubao-chat/chat', 'doubao-launcher/chat')) {
        $t = $list | Where-Object { $_.url -like "*$pat*" } | Select-Object -First 1
        if ($t) { return $t }
    }
    $t = $list | Where-Object { $_.type -eq 'iframe' -and $_.url -like '*www.doubao.com*' } | Select-Object -First 1
    if ($t) { return $t }
    return ($list | Where-Object { $_.url -like '*www.doubao.com*' } | Select-Object -First 1)
}

function Wait-DoubaoTarget([int]$TimeoutSec = 60) {
    # 豆包刚启动时对话页还没建出来，轮询等它出现
    for ($i = 0; $i -lt $TimeoutSec; $i++) {
        $t = Select-DoubaoTarget
        if ($t) { return $t }
        Start-Sleep -Seconds 1
    }
    return $null
}

function Invoke-CdpEval([string]$WsUrl, [string]$Expression, [int]$TimeoutSec = 120) {
    $ws = New-Object System.Net.WebSockets.ClientWebSocket
    $ct = [System.Threading.CancellationToken]::None
    $ms = $TimeoutSec * 1000
    if (-not $ws.ConnectAsync([Uri]$WsUrl, $ct).Wait($ms)) { throw 'CDP 连接超时' }
    try {
        $payload = @{
            id     = 1
            method = 'Runtime.evaluate'
            params = @{
                expression    = $Expression
                awaitPromise  = $true
                returnByValue = $true
                userGesture   = $true
                timeout       = $ms
            }
        } | ConvertTo-Json -Depth 10 -Compress
        $bytes = [System.Text.Encoding]::UTF8.GetBytes($payload)
        $seg = New-Object 'System.ArraySegment[byte]' -ArgumentList @(, $bytes)
        if (-not $ws.SendAsync($seg, [System.Net.WebSockets.WebSocketMessageType]::Text, $true, $ct).Wait($ms)) { throw 'CDP 发送超时' }

        $buf = New-Object byte[] 262144
        $sb = New-Object System.Text.StringBuilder
        do {
            $seg2 = New-Object 'System.ArraySegment[byte]' -ArgumentList @(, $buf)
            $r = $ws.ReceiveAsync($seg2, $ct).Result
            [void]$sb.Append([System.Text.Encoding]::UTF8.GetString($buf, 0, $r.Count))
        } while (-not $r.EndOfMessage)

        $msg = $sb.ToString() | ConvertFrom-Json
        if ($msg.error) { throw ("CDP 错误: " + ($msg.error | ConvertTo-Json -Compress)) }
        if ($msg.result.exceptionDetails) {
            throw ("页面异常: " + $msg.result.exceptionDetails.text + " / " + $msg.result.exceptionDetails.exception.description)
        }
        return $msg.result.result.value
    } finally { $ws.Dispose() }
}

$JS_GET = @'
(async()=>{
  try {
    const r = await fetch("https://www.doubao.com/alice/generaltask/memory/get_agentsmd", {method:"POST",
      headers:{"content-type":"application/json"}, body:"{}", credentials:"include"});
    const txt = await r.text();
    let j = null; try { j = JSON.parse(txt); } catch(e) {}
    const c = (j && j.data && j.data.content) || "";
    return JSON.stringify({ok: r.status === 200 && !!j, status: r.status, len: c.length,
                           content: c, raw: j ? "" : txt.slice(0, 200)});
  } catch(e) { return JSON.stringify({ok:false, status:-1, len:0, content:"", raw:"ERR "+e.message}); }
})()
'@

function Read-AgentsMd([string]$WsUrl) {
    $raw = Invoke-CdpEval $WsUrl $JS_GET
    return ($raw | ConvertFrom-Json)
}

function Write-AgentsMd([string]$WsUrl, [string]$Content) {
    $b64 = [Convert]::ToBase64String([System.Text.Encoding]::UTF8.GetBytes($Content))
    $js = @"
(async()=>{
  try {
    const content = new TextDecoder().decode(Uint8Array.from(atob("$b64"), c=>c.charCodeAt(0)));
    const r = await fetch("https://www.doubao.com/alice/generaltask/memory/set_agentsmd", {method:"POST",
      headers:{"content-type":"application/json"}, body: JSON.stringify({content}), credentials:"include"});
    const t = await r.text();
    return JSON.stringify({status: r.status, body: t.slice(0, 300)});
  } catch(e) { return JSON.stringify({status:-1, body:"ERR "+e.message}); }
})()
"@
    return (Invoke-CdpEval $WsUrl $js | ConvertFrom-Json)
}

# ---------- 主流程 ----------
Write-Host "== 豆包破甲 ==" -ForegroundColor Cyan
$exe = Resolve-DoubaoExe
Write-Host "  豆包程序 : $(if ($exe) { $exe } else { '未找到（可用 -DoubaoExe 指定）' })"
Write-Host "  提示词   : $SourcePrompt"
Write-Host "  调试端口 : $Port"

if (-not (Test-DebugPort)) {
    if ($NoLaunch) { throw "豆包没有以调试模式运行（$Port 不通），且指定了 -NoLaunch" }
    $running = Get-DoubaoProcs
    if ($running.Count -gt 0) {
        Write-Host "  [i] 豆包正在运行但没有开调试端口，重启到调试模式（聊天记录在云端，不会丢）" -ForegroundColor Yellow
        $running | Stop-Process -Force -ErrorAction SilentlyContinue
        Start-Sleep -Seconds 2
    }
    if (-not $exe) { throw "找不到豆包程序，无法自动启动。请手动运行：Doubao.exe --remote-debugging-port=$Port" }
    Write-Host "  [i] 启动豆包（调试模式）..." -ForegroundColor Yellow
    if (-not (Start-DoubaoDebug $exe)) { throw "豆包启动后 $Port 仍不通；如果界面停在登录页，先登录再重试" }
}

$target = Wait-DoubaoTarget 60
if (-not $target) { throw "等不到豆包对话页的调试目标（60 秒），确认豆包已登录并打开主界面" }
Write-Host "  调试目标 : $($target.type) $($target.url)"
$ws = $target.webSocketDebuggerUrl

# 状态
if ($Status) {
    $cur = Read-AgentsMd $ws
    Write-Host "`n[状态]" -ForegroundColor Cyan
    Write-Host "  云端全局记忆 : $($cur.len) 字符"
    Write-Host "  本地备份     : $(if (Test-Path -LiteralPath $backupFile) { "$((Get-Item $backupFile).Length) 字节" } else { '无' })"
    Write-Host "  注入状态     : $(if (Test-Path -LiteralPath $stateFile) { '已注入（可 -Uninstall 还原）' } else { '未注入' })"
    if ($cur.len -gt 0) {
        $head = ($cur.content -split "`n" | Select-Object -First 6) -join "`n"
        Write-Host "`n--- 记忆开头 ---`n$head`n---"
    }
    Write-Log "Status: len=$($cur.len)"
    exit 0
}

# 卸载
if ($Uninstall) {
    $done = @()
    if (Test-Path -LiteralPath $backupFile) {
        $bak = Read-Utf8 $backupFile
        # 备份内容本身就是寒霜注入时（上一版工具写进去的、或用户手工贴的），
        # 还原它等于把破甲留着 —— 这种情况直接清空，才算真卸干净。
        if ($bak -match '寒霜|中转站保护') {
            $r = Write-AgentsMd $ws ''
            $cur = Read-AgentsMd $ws
            $done += "备份内容本身是上一次的注入 → 已清空云端记忆（现在 $($cur.len) 字符）"
        } else {
            $r = Write-AgentsMd $ws $bak
            $cur = Read-AgentsMd $ws
            if ($cur.content -eq $bak) { $done += "全局记忆已还原（$($cur.len) 字符）" }
            else { $done += "还原后校验不一致（当前 $($cur.len) 字符）" }
        }
        Remove-Item -LiteralPath $backupFile -Force
    } else {
        $r = Write-AgentsMd $ws ''
        $done += "没有备份，已清空全局记忆"
    }
    if (Test-Path -LiteralPath $stateFile) { Remove-Item -LiteralPath $stateFile -Force }

    Write-Log "Uninstall: $($done -join '; ')"
    # 收拾本地痕迹：日志 + 空目录。~/.doubao 是本脚本专用的（豆包自己的数据在
    # %LOCALAPPDATA%\Doubao\User Data），空掉就删，别在用户 Home 下留垃圾。
    $logFile = Join-Path $env:USERPROFILE '.doubao\hanshuang-doubao.log'
    if (Test-Path -LiteralPath $logFile) {
        Remove-Item -LiteralPath $logFile -Force
        $done += "已删除日志 hanshuang-doubao.log"
    }
    foreach ($d in @($stateDir, (Join-Path $env:USERPROFILE '.doubao'))) {
        if ((Test-Path -LiteralPath $d) -and -not @(Get-ChildItem -LiteralPath $d -Force)) {
            Remove-Item -LiteralPath $d -Force
            $done += "已删除空目录 $(Split-Path -Leaf $d)"
        }
    }

    Write-Host "`n[完成] 卸载" -ForegroundColor Green
    $done | ForEach-Object { Write-Host "  - $_" }
    # $exe 可能已经是 app\Doubao.exe（进程路径优先），别拼成 app\app\
    $appExe = if (-not $exe) { 'Doubao.exe' }
              elseif ($exe -like '*\app\Doubao.exe') { $exe }
              else { Join-Path (Split-Path -Parent $exe) 'app\Doubao.exe' }
    Write-Host "`n  提示：豆包仍以调试模式运行（端口 $Port）。要恢复正常模式，关掉豆包后不带参数启动：" -ForegroundColor DarkGray
    Write-Host "        $appExe" -ForegroundColor DarkGray
    exit 0
}

# 备份（只在首次注入时备份，别把注入后的内容当原始记忆备份了）
$before = Read-AgentsMd $ws
Write-Host "  写入前   : $($before.len) 字符"
if (-not (Test-Path -LiteralPath $backupFile)) {
    if ($before.len -gt 0) {
        Write-Utf8 $backupFile $before.content
        Write-Host "  [i] 原记忆已备份 → $backupFile" -ForegroundColor DarkGray
    } else {
        Write-Utf8 $backupFile ''
        Write-Host "  [i] 原记忆为空，已记录空备份（卸载时会清空而不是还原）" -ForegroundColor DarkGray
    }
}

# 写入
$res = Write-AgentsMd $ws $srcText
Write-Host "  接口返回 : status=$($res.status) $($res.body)"
$after = Read-AgentsMd $ws
$ok = ($after.content -eq $srcText)

Write-Utf8 $stateFile (@{
    prompt       = $SourcePrompt
    sha256       = $srcHash
    chars        = $srcText.Length
    writtenAt    = (Get-Date).ToUniversalTime().ToString('yyyy-MM-ddTHH:mm:ss.fffZ')
    exactMatch   = $ok
} | ConvertTo-Json -Depth 4)

Write-Host "`n[校验]" -ForegroundColor Cyan
Write-Host "  写入后   : $($after.len) 字符"
Write-Host "  逐字一致 : $ok"
Write-Log "Inject: chars=$($srcText.Length) exact=$ok status=$($res.status)"

if ($ok) {
    Write-Host "`n[完成] 豆包全局记忆已替换为 $((Split-Path -Leaf $SourcePrompt))" -ForegroundColor Green
    Write-Host "  生效验证：在豆包里开一个通用任务问一句，看是否按寒霜规范回应"
    Write-Host "  还原命令：.\install-doubao.ps1 -Uninstall"
} else {
    Write-Host "`n[失败] 写进去了但读回来对不上 —— 云端可能有审核或长度截断" -ForegroundColor Red
    Write-Host "  写入前 $($before.len) 字符 / 期望 $($srcText.Length) 字符 / 实际 $($after.len) 字符"
    exit 2
}
