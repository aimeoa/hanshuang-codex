# 寒霜破甲工具 · macOS 版

这是原 Windows 版（Electron + React + PowerShell）的 macOS 移植。**界面层一行未改**，
重写的只有执行层：9 个 `install*.ps1` → POSIX bash，加上主进程的平台分支与打包配置。

## 为什么界面不用改

原项目的 `src/` 本身就是跨平台的 —— 它的样式表里甚至已经写好了 macOS 红绿灯的适配。
真正绑定 Windows 的只有三处：

| 位置 | 原实现 | macOS 版 |
|---|---|---|
| `electron/main.cjs` | `spawn("powershell.exe", ["-File", ...])` | `spawn("/bin/bash", [script, ...])` |
| 9 个安装脚本 | PowerShell（`robocopy` / `Get-Process` / `attrib` / 盘符扫描） | POSIX bash（`rsync` / `pgrep` / `chmod`） |
| 打包 | NSIS + portable + rcedit 写 exe 图标 | dmg + zip + ad-hoc 签名 |

## 执行层架构

```
scripts/install/
  lib.sh                 # 公共底座：参数解析、注入块、残留识别、技能同步、状态文件
  hs-lib.cjs             # 文本/JSON 处理（由 lib.sh 调用，不直接暴露给用户）
  install.sh             # Codex
  install-claude.sh      # Claude Code
  install-cursor.sh      # Cursor 全局/项目规则
  install-zcode.sh       # ZCode
  install-workbuddy.sh   # WorkBuddy（国际版 / 国内版）
  install-dsh.sh         # DeepSeek Harness
  install-doubao.sh      # 豆包（CDP 写云端记忆）
  doubao-cdp.cjs         # 零依赖 WebSocket 客户端，供豆包脚本调 CDP
  clear-injected-prompts.sh   # 六目标兜底清扫（卸载时主进程会调）
  portable-uninstall.sh       # macOS 卸载清理
```

### 两个关键设计决定

**1. 文本处理下沉到 node，不用 sed/awk。**

注入块的定位是「先正则匹配 BEGIN，再从它之后匹配 END」，`sed`/`awk` 的字符下标在多字节
中文下会错位 —— 一旦错位就是写坏用户的 `AGENTS.md` / `CLAUDE.md`。状态文件又是 JSON，
`sed` 解析一旦遇到转义就崩。所以这部分交给 node。

node 从哪来？**不需要用户装**。打包后的 Electron 二进制加上 `ELECTRON_RUN_AS_NODE=1`
就是一个完整的 node，主进程把它通过 `HS_NODE` 环境变量传给脚本：

```js
env.HS_NODE = process.execPath;
env.ELECTRON_RUN_AS_NODE = "1";
```

**2. 技能库同步整体放进 node，一次调用完成。**

最初每个技能要起 5 次 node（比大小、比时间戳、建目录……），63 个技能就是 315 次进程调用。
实测单次 node 启动约 385ms，加起来 **2 分多钟，直接撞上主进程 300 秒超时**。
现在整段逻辑在 `hs-lib.cjs` 里一次跑完。

## 目标路径对照

| 目标 | Windows | macOS |
|---|---|---|
| Codex | `%USERPROFILE%\.codex` | `~/.codex` |
| Claude Code | `%USERPROFILE%\.claude` | `~/.claude` |
| DeepSeek Harness | `%USERPROFILE%\.dsh` | `~/.dsh` |
| ZCode | `%USERPROFILE%\.zcode` | `~/.zcode` |
| WorkBuddy 国际版 | `%USERPROFILE%\.workbuddy-ai` | `~/.workbuddy-ai` |
| WorkBuddy 国内版 | `%USERPROFILE%\.workbuddy` | `~/.workbuddy` |
| Cursor 全局规则 | `%APPDATA%\Cursor\User\rules` | `~/.cursor/rules` + `~/Library/Application Support/Cursor/User/rules` |
| Cursor 状态 | `%APPDATA%\Cursor\hs-install-state.json` | `~/Library/Application Support/Cursor/hs-install-state.json` |
| 豆包状态 | `<stateDir>\state.json` | `~/Library/Application Support/豆包/hanshuang-state.json` |

macOS 上被**删掉**的 Windows 专有逻辑（没有等价物）：

- Codex 主目录的逐盘符扫描（`C:` → `Z:`）—— macOS 固定 `~/.codex`
- Cursor 的「盘符根祖先规则」—— 无盘符概念
- 注册表探测 —— 改为扫 `/Applications` 与 `~/Applications`
- `taskkill /T /F` —— 改为进程组整组杀（脚本以 `detached` 启动，自成进程组）

## 构建

需要 Node 18+（真机验证用的是 v26）。

```bash
npm install
npm run dist:mac              # 出 arm64 的 dmg + zip
node scripts/build.mjs free mac x64   # 指定 Intel 架构
```

产物在 `release/`：

| 产物 | 说明 |
|---|---|
| `寒霜破甲工具-1.0-arm64.dmg` | 安装镜像 |
| `寒霜破甲工具-便携版-4.4.0.zip` | 解压后把 `.app` 拖进「应用程序」即可 |

### 关于签名

构建时 `mac.identity` 设为 `null`（不找开发者证书）。但 **Apple Silicon 上未签名的
可执行文件会被内核直接杀掉**，所以 `build.mjs` 打完包会自动补一次 ad-hoc 签名：

```bash
codesign --force --deep --sign - "<App>.app"
```

本机自用足够。要对外分发，换成自己的 Developer ID，并打开 `hardenedRuntime` + 公证。

便携版 zip 用 `ditto -c -k --sequesterRsrc --keepParent` 打包，不用 python 的 zipfile ——
`.app` 内部（Frameworks 等）有大量符号链接，python 的 zip 会把符号链接变成副本、
体积翻倍还可能破坏结构。

### 构建时踩过的两个坑（已在 build.mjs 里处理掉）

**1. Electron 发行版下载。** electron-builder 默认会自己去 GitHub Releases 下 100MB 的
Electron 发行版，国内网络下经常 EOF 中断，整个构建卡死。而 `npm install` 时 `electron`
包已经下好了同版本的一份在 `node_modules/electron/dist`，`build.mjs` 会检测到并直接
通过 `electronDist` 指过去，一次网络请求都不用发。

**2. `which python`。** electron-builder 打 DMG 时会执行 `which python`。macOS 从 12.3
起不再自带 `python`（只有 `python3`），这一步直接退出码 1、构建中断。报错信息很迷惑：
只有一句 `Command failed: which python`，而 `.app` 和 zip 明明已经产出了，唯独 dmg 没了。

`build.mjs` 会检测系统有没有 `python`，没有就在临时目录补一个转发到 `python3` 的
shim（优先 Homebrew 的，因为 `/usr/bin/python3` 常被 Xcode 许可协议拦住），只影响
本次构建派生的子进程，构建结束自动删除，不往你环境里装任何东西。

## 开发

```bash
npm run dev                   # 起 Vite 开发服务器（5273 端口）
HS_DEV=1 npx electron .       # 连开发服务器跑
npx electron .                # 直接跑构建产物
```

## 单独调用某个注入脚本

脚本是独立的，可以脱离界面直接用：

```bash
# 注入到 WorkBuddy（国际版）
HS_NODE=$(command -v node) bash scripts/install/install-workbuddy.sh \
  -SourcePrompt ./寒霜v4.md -SkillsSource codex-skills-v4

# 卸载
HS_NODE=$(command -v node) bash scripts/install/install-workbuddy.sh -Uninstall

# 把六个目标全部还原到「没注入过」的状态（默认 dry-run，加 -Apply 才真删）
bash scripts/install/clear-injected-prompts.sh
bash scripts/install/clear-injected-prompts.sh -Apply -Targets workbuddy
```

`HS_NODE` 只有脱离 Electron 手动跑时才需要显式给；界面里由主进程自动注入。

## 卸载

```bash
bash scripts/install/portable-uninstall.sh -DryRun   # 先看会删什么
bash scripts/install/portable-uninstall.sh           # 真删
```

只清理白名单里的路径（`~/Library/Application Support/寒霜破甲工具`、
`~/Library/Preferences/com.hanshuang.desktop.plist` 等），**不碰任何用户目录本身**。

## 与 Windows 版的已知差异

1. **托盘图标**：macOS 用模板图（18×18、`setTemplateImage(true)`），系统按深浅色自动上色；
   Windows 直接用彩色应用图标。
2. **应用菜单**：macOS 必须显式建菜单，否则 Cmd+C / Cmd+V / Cmd+Q 全部失效 ——
   Electron 不会自动补，快捷键是注册在菜单 role 上的。Windows/Linux 走 `autoHideMenuBar`。
3. **重启 Codex**：macOS 走 `osascript quit` + `open -a "ChatGPT"`（Codex 由 ChatGPT.app 承载，
   配置目录同样是 `~/.codex`）。
4. **豆包**：macOS 上应用扫描路径改为 `/Applications/豆包.app`、`/Applications/Doubao.app`，
   调试模式启动改为 `.app/Contents/MacOS/*` 直启（失败退 `open -a --args`）。

## 实测状态

真机 macOS 27.0 / arm64 上验证过的：

- `lib.sh` + `hs-lib.cjs` 底座
- `install-claude.sh`：注入 → 幂等重装 → 用户内容保留 → 卸载还原，全闭环
- `install-workbuddy.sh`：注入 6 项校验全过 → 卸载后档案/用户原文/技能全部还原

**尚未在真机验证**（脚本逻辑已对齐，但缺真实环境）：

- `install-cursor.sh` / `install-doubao.sh`：本机没装 Cursor 和豆包客户端
- 豆包的 CDP 链路：没有客户端登录会话可连
- ZCode：本机没装
- dmg 安装后的 Gatekeeper 行为
