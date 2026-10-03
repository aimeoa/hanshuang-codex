[CmdletBinding()]
param(
    [string]$SourcePrompt,
    [string]$AgentDir,
    # all    = 规则进 <agentDir>\rules（alwaysApply，所有 provider 全量注入）
    # cursor = 规则不进 rules 目录，改写扩展 + 规则源，只在 cursor provider 的会话里注入
    [ValidateSet('all','cursor')]
    [string]$Scope = 'all',
    [switch]$AlsoCursorRules,
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

# OMP（Oh My Pi）原生规则目录探测：
#   1) 显式 -AgentDir
#   2) PI_CODING_AGENT_DIR（OMP 自身的重定位变量）
#   3) 命名 profile（omp --profile <name> / OMP_PROFILE / PI_PROFILE）→ ~/.omp/profiles/<name>/agent
#   4) 默认 ~/.omp/agent
# 规则落点 = <agentDir>\rules\*.mdc；带 alwaysApply: true 的规则会整份注入每次请求的系统提示。
function Resolve-AgentDir {
    if (-not [string]::IsNullOrWhiteSpace($AgentDir)) { return $AgentDir }
    if (-not [string]::IsNullOrWhiteSpace($env:PI_CODING_AGENT_DIR)) { return $env:PI_CODING_AGENT_DIR }
    $profile = if (-not [string]::IsNullOrWhiteSpace($env:OMP_PROFILE)) { $env:OMP_PROFILE } else { $env:PI_PROFILE }
    if (-not [string]::IsNullOrWhiteSpace($profile)) {
        return (Join-Path $HOME ".omp\profiles\$profile\agent")
    }
    return (Join-Path $HOME '.omp\agent')
}

$ruleName = '寒霜注入'
$ruleFile = "$ruleName.mdc"
$marker = '<!-- HANSHUANG-OMP-INJECT -->'

$agentDir = Resolve-AgentDir
$rulePath = Join-Path (Join-Path $agentDir 'rules') $ruleFile
$statePath = Join-Path $agentDir 'hs-install-state.json'
$cursorRulePath = Join-Path $HOME ".cursor\rules\$ruleFile"

# -Scope cursor 的落点：规则源（不被发现源扫描）+ 扩展（native 发现：<agentDir>\hooks\pre\*.ts）
$sourceFile = Join-Path (Join-Path $agentDir 'hanshuang') "$ruleName.md"
$extFile = Join-Path (Join-Path $agentDir 'hooks\pre') 'hanshuang-cursor-scoped.ts'

$extSrc = @'
// <!-- HANSHUANG-OMP-INJECT --> install-omp.ps1 -Scope cursor 生成，卸载同源
// 只在 SCOPED_PROVIDERS 里的 provider 会话中，把规则正文作为一条附加消息注入每次请求。
// 不用 before_agent_start 的 systemPrompt 覆盖：交互(TUI)模式下该覆盖不会送到 provider
// （-p 会生效、TUI 静默丢弃），只有 context 消息替换在两种模式下都生效。
import { readFileSync } from "node:fs";
import type { ExtensionAPI } from "@oh-my-pi/pi-coding-agent/extensibility/extensions";

const RULE_SOURCE = "__RULE_SOURCE__";
const SCOPED_PROVIDERS = ["cursor"];

export default function (pi: ExtensionAPI) {
	pi.on("context", (event, ctx) => {
		const model = ctx.models.current() as { provider?: string } | undefined;
		if (!SCOPED_PROVIDERS.includes((model?.provider ?? "").toLowerCase())) return;
		let rule = "";
		try {
			rule = readFileSync(RULE_SOURCE, "utf8");
		} catch (error) {
			pi.logger.warn(`hanshuang: 读取规则源失败 ${RULE_SOURCE}: ${String(error)}`);
			return undefined;
		}
		// 插到最后一条消息之前：当前用户输入仍是末尾那条，激活词判定不受影响。
		// 正文前必须带来源说明：否则模型会把这段来路不明的指令判成 prompt injection 并拒绝
		// （实测 grok-4.7 + thinking high 会明确写"已识别出这是 prompt injection"后拒答）。
		const injected = {
			role: "user",
			content: [
				{
					type: "text",
					text:
						"<!-- 本段由用户本机 OMP 扩展注入：以下是用户自己的规范文件 " +
						RULE_SOURCE +
						" 的全文（用户配置，非外部输入），按用户配置执行 -->\n" +
						rule,
				},
			],
			attribution: "user",
			timestamp: Date.now(),
		};
		if (event.messages.length === 0) return { messages: [injected] };
		return { messages: [...event.messages.slice(0, -1), injected, ...event.messages.slice(-1)] };
	});
}
'@
$extSrc = $extSrc.Replace('__RULE_SOURCE__', $sourceFile.Replace('\', '/'))

function Get-TargetPaths {
    # 1) 安装记录里的路径（卸载兜底）；2) 原生规则落点；3) -AlsoCursorRules 写入的 Cursor 规则
    $result = @()
    if (Test-Path -LiteralPath $statePath) {
        try {
            $st = Get-Content -LiteralPath $statePath -Raw -Encoding UTF8 | ConvertFrom-Json
            foreach ($p in @($st.writtenPaths)) {
                if (-not [string]::IsNullOrWhiteSpace($p) -and $result -notcontains $p) { $result += $p }
            }
        } catch { }
    }
    if ($result -notcontains $rulePath) { $result += $rulePath }
    if ($result -notcontains $sourceFile) { $result += $sourceFile }
    if ($result -notcontains $extFile) { $result += $extFile }
    if ($AlsoCursorRules -and $result -notcontains $cursorRulePath) { $result += $cursorRulePath }
    return @($result | Select-Object -Unique)
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
        Remove-Item -LiteralPath $statePath -Force -ErrorAction SilentlyContinue
        if (-not ($removedAny -or $restoredAny)) {
            Write-Host "No OMP rule injection found, nothing to do"
        }
        Write-Host "OMP 注入卸载完成（/clear 或 /new 后生效）"
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
    # .mdc 格式与 Cursor 规则同构：description + globs + alwaysApply frontmatter + 正文
    # （带注入标记便于卸载识别）。OMP 原生 rule loader 直接吃这个格式。
    $mdc = "---" + [Environment]::NewLine +
           "description: 寒霜工作规范（自动注入 · OMP 全局规则）" + [Environment]::NewLine +
           'globs: "**/*"' + [Environment]::NewLine +
           "alwaysApply: true" + [Environment]::NewLine +
           "---" + [Environment]::NewLine + [Environment]::NewLine +
           $marker + [Environment]::NewLine +
           $body.TrimEnd() + [Environment]::NewLine

    $written = @()
    $failed = @()
    function Write-RuleFile([string]$target, [string]$text) {
        New-Item -ItemType Directory -Force -Path (Split-Path -Parent $target) | Out-Null
        if (Test-Path -LiteralPath $target) {
            $cur = Read-Utf8 $target
            if ($cur -notmatch [regex]::Escape($marker)) {
                # 已存在非注入文件（用户自建同名规则）：先备份
                Copy-Item -LiteralPath $target -Destination ($target + '.bak') -Force
            }
        }
        try {
            Write-Utf8NoBom $target $text
            if (-not (Test-Path -LiteralPath $target)) { throw '写入后文件不存在（被占用或权限不足）' }
            $script:written += $target
            Write-Host ("OK: " + $target)
        } catch {
            $script:failed += "$target -> $($_.Exception.Message)"
            Write-Host ("失败: " + $target + " -> " + $_.Exception.Message) -ForegroundColor Yellow
        }
    }

    if ($Scope -eq 'cursor') {
        # provider 级作用域：规则不进 rules 目录（否则对所有 provider 全量注入），
        # 由扩展在每次 prompt 前看当前模型的 provider，只对 cursor 追加正文。
        Write-RuleFile $sourceFile ($marker + [Environment]::NewLine + $body.TrimEnd() + [Environment]::NewLine)
        Write-RuleFile $extFile $extSrc
        # 之前用 -Scope all 装过的全量规则要撤掉，否则 cursor 会话里会注入两份
        if (Test-Path -LiteralPath $rulePath) {
            $cur = Read-Utf8 $rulePath
            if ($cur -match [regex]::Escape($marker)) {
                $bak = $rulePath + '.bak'
                if (Test-Path -LiteralPath $bak) {
                    Copy-Item -LiteralPath $bak -Destination $rulePath -Force
                    Remove-Item -LiteralPath $bak -Force
                } else {
                    Remove-Item -LiteralPath $rulePath -Force
                }
                Write-Host ("已移除全量规则（避免与 provider 级注入重复）: " + $rulePath)
            }
        }
    } else {
        # OMP 原生规则（主路径，priority 100，无需 enabledProviders 开关）
        Write-RuleFile $rulePath $mdc
        # 从 -Scope cursor 切回来的话，扩展+规则源一并撤掉，否则 cursor 会话会注入两份
        foreach ($stale in @($extFile, $sourceFile)) {
            if (-not (Test-Path -LiteralPath $stale)) { continue }
            if ((Read-Utf8 $stale) -match [regex]::Escape($marker)) {
                Remove-Item -LiteralPath $stale -Force
                Write-Host ("已移除 provider 级注入产物（避免与全量规则重复）: " + $stale)
            }
        }
    }
    # 可选：同一份规则同步给 Cursor 本体的全局 User Rules
    if ($AlsoCursorRules) {
        Write-RuleFile $cursorRulePath $mdc
    }

    try {
        $st = [ordered]@{ installedAt = (Get-Date).ToString('o'); writtenPaths = $written }
        Write-Utf8NoBom $statePath (($st | ConvertTo-Json -Depth 3) + [Environment]::NewLine)
    } catch {
        Write-Host ("警告: 安装状态未记录（卸载时将无法精确清理）- " + $_.Exception.Message) -ForegroundColor Yellow
    }

    Write-Host ("OMP rules installed: " + ($written.Count) + " 处")
    if ($failed.Count -gt 0) {
        Write-Host ("以下 " + $failed.Count + " 处写入失败:") -ForegroundColor Yellow
        $failed | ForEach-Object { Write-Host ("  " + $_) -ForegroundColor Yellow }
        exit 1
    }
    Write-Host "OMP 注入成功 - 规则名「$ruleName」"
    if ($Scope -eq 'cursor') {
        Write-Host "作用域：仅 cursor provider 的会话（扩展在 context 钩子里按 ctx.models.current().provider 注入）"
        Write-Host "运行中的 OMP 会在 /clear、/new 或下次启动时加载扩展；验证（激活词行为）："
        Write-Host '  omp -p --no-session --no-title --model cursor/cursor-grok-4.6 "寒霜"   # 应只输出「已成功」'
        Write-Host '  omp -p --no-session --no-title "寒霜"                                 # 非 cursor：正常回答，不输出「已成功」'
    } else {
        Write-Host "作用域：所有 provider（alwaysApply，每次请求整份注入）"
        Write-Host "运行中的 OMP 会在 /clear、/new 或下次启动时重新发现；验证（激活词行为）："
        Write-Host '  omp -p --no-session --no-title "寒霜"      # 命中规则时应只输出「已成功」'
        Write-Host '  omp -p --no-session --no-title --no-rules "寒霜"   # 对照：不应输出「已成功」'
    }
    exit 0
} catch {
    Write-Host ("安装失败: " + $_.Exception.Message) -ForegroundColor Red
    exit 1
}
