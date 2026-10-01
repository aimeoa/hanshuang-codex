# 寒霜破甲工具 · macOS 移植版 —— 提交前校验报告（第二版）

校验时间：2026-10-01
校验对象：`/Volumes/S690/codes/hanshuang-mac`
上游仓库：`https://github.com/aimeoa/hanshuang-codex`（main @ `142f820`）
校验方式：**全程只读**。已 clone 上游做确定性逐文件比对；未运行任何 `install-*.sh`，未启动该 Electron 应用，未对任何 agent 注入。

---

## 一、总体结论

| 维度 | 结论 |
|---|---|
| 内容改动是否干净 | ✅ **非常干净** —— 相对上游真正的内容改动只有 **4 个文件** |
| 是否误删上游文件 | ✅ **0 个** |
| 新增文件 | 17 个，全部是有意新增 |
| 注入目标路径是否正确 | ✅ 7 个目标全部指向 macOS 真实目录 |
| 能否选择性不破甲某些 agent | ✅ 可以（UI 逐目标安装）**但有一个例外，见 §4** |
| 约束文件会不会被覆盖 | ⚠️ 主流程是追加式，**但有 3 处是整份覆盖**，见 §5 |
| 发现的真 bug | ❌ **1 个（豆包内核选择依赖 locale）** |
| 能否直接提 PR | ❌ 不能 —— 目录不是 git 仓库（P0），且有 189 个权限位噪音 |

---

## 二、与上游的确定性比对（内容哈希，忽略行尾）

用 sha256 对全部 4749 / 4766 个文件逐一对齐（排除 `.git` `node_modules` `release` `dist`）：

```
上游文件数: 4749    MAC 文件数: 4766

=== 内容真正不同: 4 ===
  electron/main.cjs          ← 移植核心：平台分支
  package.json               ← 新增 mac / dmg 段、extraResources
  scripts/after-pack.js      ← 新增 darwin 分支
  scripts/build.mjs          ← 新增 macOS 构建链路

=== 仅上游有: 0 ===            ← 没有删掉上游任何文件 ✅

=== 仅MAC有: 17 ===
  .gitattributes
  README-macOS.md / REVIEW-macOS.md / VALIDATION-macOS.md
  scripts/install/install.sh              scripts/install/install-claude.sh
  scripts/install/install-cursor.sh       scripts/install/install-zcode.sh
  scripts/install/install-workbuddy.sh    scripts/install/install-dsh.sh
  scripts/install/install-doubao.sh       scripts/install/install.sh
  scripts/install/lib.sh                  scripts/install/hs-lib.cjs
  scripts/install/doubao-cdp.cjs          scripts/install/zcode-patch.cjs
  scripts/install/clear-injected-prompts.sh  scripts/install/portable-uninstall.sh
```

**这意味着**：所有技能库载荷（`codex-skills*` / `dsh-lazy-pack-v5` / `gpt-6-astra-v1`）、
`fj_tool.py`、`src/` 前端、`install-*.ps1` 全部与上游**逐字节一致**，
移植没有碰到任何既有内容。这是一个教科书式的干净移植。

### ⚠️ 但有一个大噪音源：189 个文件的权限位被改了

```
189 个文件：100644 => 100755
  96 个 .py    59 个 .sh    3 个 .js    2 个 .mjs    1 个 .cjs
```

这些**不是内容改动**，是 Windows→Mac 拷贝时执行位被批量打开。
上游把它们存成 `100644`，移植版全变成了 `100755`。

- 对 `.sh` 来说变 755 是合理的（甚至是修正）
- 但 **96 个 `.py` 变成可执行是纯粹的污染**
- 提交时会制造 189 行与本次移植无关的 diff，reviewer 会被淹没

**处理**：提交前把这 189 个文件还原回 644，只保留真正需要可执行的
（`scripts/install/*.sh`、`scripts/build.mjs`）。命令见 §7 步骤 4。

---

## 三、注入目标路径核对（你问的"能不能注入到对应位置"）

逐个脚本提取实际写入路径，并与真机核对：

| 目标 | 脚本写入路径 | macOS 真实位置 | 真机存在 | 判定 |
|---|---|---|---|---|
| **Codex** | `~/.codex/config.toml`（写 `model_instructions_file` 指针）<br>`~/.codex/AGENTS.md`<br>`~/.codex/skills/`<br>`~/.codex/memories/memory_summary.md` | `~/.codex` | ✅ | ✅ 正确 |
| **Claude Code** | `~/.claude/CLAUDE.md`<br>`~/.claude/skills/` | `~/.claude` | ✅ | ✅ 正确 |
| **Cursor** | `~/.cursor/rules/`<br>`~/Library/Application Support/Cursor/User/rules/` | 同上（官方 `.gitignore` 确认） | ✅ | ✅ 正确 |
| **ZCode** | `~/.zcode/AGENTS.md`<br>`~/.zcode/v2/setting.json`<br>`~/.zcode/cli/memories/global/memory/`<br>`/Applications/ZCode.app/Contents/Resources/glm/zcode.cjs` | 同上 | ✅ | ✅ 正确 |
| **WorkBuddy** | `~/.workbuddy-ai/{memory/,MEMORY.md,app/app-config.json}`<br>国内版 `~/.workbuddy/…` | 同上 | ✅ | ✅ 正确 |
| **DSH** | `~/.dsh/AGENTS.md`<br>`~/.dsh/skills/`<br>`~/.dsh/shield-protocol.md`<br>`~/.dsh/prompt-inject.md`<br>`~/.dsh/dsh-prompt-inject.json` | `~/.dsh` | ✅ | ✅ 正确 |
| **豆包** | 云端接口（CDP 驱动客户端会话）<br>本地仅 `~/Library/Application Support/豆包/` | 应用数据实际在 `~/Library/Application Support/DoubaoWork` | 应用 ✅ | ⚠️ 见 P1-1 |

**7 个目标的数据目录在你机器上全部存在**，路径解析全部是动态探测（`-XxxHome` 参数 →
环境变量 → `$HOME/...`），没有写死用户名，换机器也能用。

---

## 四、关于"有些 agent 我不想破甲"

### ✅ 主流程天然支持选择性

- **UI 是逐目标安装的**：左侧导航 7 个目标各自一个"安装"按钮，点谁装谁。
- **`autoInstall`（自动安装）只自动装 Codex 一个目标**：
  `src/App.tsx:188-195` 里 `runInstall("codex", …)` 是硬编码的单目标调用，
  不会顺手把 Claude / Cursor / ZCode / WorkBuddy / DSH / 豆包 一起装了。
  而且它是**默认关闭**的（`useState(false)`），需要在个人中心手动打开。
- **脚本可以脱离界面单独调用**，你完全可以只跑你需要的那一个。

### ⚠️ 但有一个例外：WorkBuddy 会被"自动回写"，且不需要你点任何按钮

`electron/main.cjs:741` 的 `WorkBuddyGuard` 在应用启动后**每 45 秒轮询一次**：

```js
check() {
  const st = this.state();              // 读 ~/.workbuddy-ai/.hanshuang-state.json
  if (!st || !st.prompt) return;
  const block = fs.readFileSync(p(st.prompt), "utf8");   // 读随包提示词
  for (const arch of this.targets(st)) {
    const m = this.blockRe.exec(cur);
    if (m && m[1].trim() === block.trim()) continue;     // 一致就跳过
    this.write(arch, block, st);                          // ← 不一致就整份改写
  }
}
```

**你的机器上这个条件已经满足**（实测）：

```
~/.workbuddy-ai/.hanshuang-state.json   prompt = "寒霜v4.md"
    memoryDir = $HOME/.workbuddy-ai/memory
    archives  = [ $HOME/.workbuddy-ai/memory/<uid>_memory.md ]
~/.workbuddy/.hanshuang-state.json      prompt = "寒霜v4.md"
    memoryDir = $HOME/.workbuddy/memory
    archives  = [ $HOME/.workbuddy/memory/<uid>_memory.md ]
```

**结论：只要你双击打开这个工具，45 秒内它会自动把你这两个 WorkBuddy 的
`*_memory.md` 改写成随包提示词内容**，没有任何开关、没有确认框。
如果你不想动 WorkBuddy，**就别启动这个应用**，或者先把这两个 `.hanshuang-state.json`
挪走（挪走即可，`state()` 找不到文件就直接 return）。

---

## 五、关于"约束文件会不会被覆盖"（你最担心的）

注入模型**主体是追加式**，不是覆盖：

```bash
# lib.sh:112
# 有块换块内，没块追加
hs_splice_block() { hs block-splice "$1" "$2" "$3" "$4"; }

# lib.sh:155  首次注入前备份
hs_backup_once() { ... cp -f "$f" "$bak" ... }
```

`lib.sh:130` 还专门写了 `hs_is_artifact()`：靠 9 个特征串判断"这文件是不是本工具的注入产物"，
避免把注入产物当成用户原文备份回去。

### 但下面 3 处是**整份覆盖**，请重点注意

| # | 位置 | 行为 | 备份 |
|---|---|---|---|
| 1 | `install-dsh.sh:671` | **AGENTS.md 整体覆盖**为提示词，只保留注入内容 | ✅ 首次注入前存 `~/.dsh/managed-prompts/AGENTS.md.bak`，卸载还原 |
| 2 | `install-claude.sh:7` | 若 `CLAUDE.md` 正文**整份就是随包提示词**（含老版本无标记覆盖式注入），**整份改写**而不是追加 | ✅ `CLAUDE.md.bak` |
| 3 | `install-doubao.sh:8` | 云端 `/alice/generaltask/memory/set_agentsmd` **整份覆盖**写全局记忆 | ✅ 首次注入前存本地备份 |

**另外两处会动你的既有文件，但不是"覆盖提示词"**：

- **技能库同步**：`~/.codex/skills`、`~/.claude/skills`、`~/.dsh/skills` 会被同步/清理
  （`hs_prune_stale_skills` 会删上一版遗留的、且**只删「上次安装清单 ∩ 随包技能库」**，
  不会碰你自己写的技能）。
- **`~/.codex/config.toml`**：会写 `model_instructions_file` 指针并可能重排 `[[skills.config]]` 块。
  Codex 自己也会重写这个文件。

**给你的实操建议**：注入任何目标之前，先手工备份它的记忆/约束文件。
脚本的自动备份只在**首次**注入时做一次（`hs_backup_once` 逻辑），
如果你之前已经装过一次，`.bak` 里存的可能不是最原始的那份。

---

## 六、Bug 与问题清单

### P0 —— 阻断提交

**这个目录不是 git 仓库**（无 `.git` / remote / 历史）。
直接 `git init` 会产出与上游**无共同祖先**的孤儿仓库，PR 无法 diff。
必须先 clone 上游，再把改动叠加到新分支。命令见 §7。

---

### P1-1 🔴 豆包内核选择依赖 locale，会选错二进制（真 bug）

`install-doubao.sh:139` 用通配符取 Helpers 里**第一个**可执行文件：

```bash
for c in "$app/Contents/Helpers/"*.app/Contents/MacOS/*; do
  if [ -f "$c" ] && [ -x "$c" ]; then bin="$c"; break; fi
done
```

但你机器上 `DoubaoWork.app/Contents/Helpers/` 里有**两个** `.app`：

```
DoubaoWork Browser.app   BundleID com.work.pc.doubao.browser   ← 真正的 Chromium 内核（要的）
豆包.app                  BundleID com.work.pc.doubao.linkrouter ← 路由辅助（不要的）
```

**实测三种 locale 的结果**：

```
LC_ALL=C            → 选中 DoubaoWork Browser.app  ✅ 正确
LC_ALL=zh_CN.UTF-8  → 选中 DoubaoWork Browser.app  ✅ 正确
LC_ALL=en_US.UTF-8  → 选中 豆包.app（linkrouter）  ❌ 错误
```

**后果**：英文 locale 下会拉起错误进程，调试端口开不出来，
脚本白等 20 秒后走 `open -a --args` 兜底（而脚本自己的注释都写了这条路不可靠）。
表现为"豆包破甲失败"，且原因极难排查。

**修法**（任选）：
- 在循环前 `export LC_ALL=C` 让 glob 顺序确定；
- 或改为优先匹配 `*Browser*.app` / BundleID 含 `browser` 的那个；
- 或选 `Contents/MacOS/` 下二进制体积最大的那个（内核约 100MB+，linkrouter 小得多）。

---

### P1-2 189 个上游文件被改了权限位（644 → 755）

见 §2。提交前需还原，否则 PR 里混入 189 行无关 diff。

---

### P1-3 `dsh-lazy-pack-v5` 病态自嵌套（13.9 MB 纯重复）

**这一条已确认是上游本来就有的**（在 clone 下来的 `upstream/` 里同样存在），
不是本次移植引入的。所以不必在本次 PR 里修，但值得在 PR 描述里提一句。

```
5.5M  dsh-lazy-pack-v5/materials/skills/skills/
7.9M  dsh-lazy-pack-v5/materials/skills/eni-pentest-tools/eni-pentest-tools/
304K  dsh-lazy-pack-v5/materials/skills/eni-kali/eni-kali/
152K  dsh-lazy-pack-v5/materials/skills/eni-kali/eni-kali/eni-kali/
```

`install-dsh.sh:105` 会把整个 `materials/skills` 同步进 `~/.dsh/skills`，
嵌套层会一起装进去（出现 `~/.dsh/skills/skills/...`）。

---

### P1-4 `.gitignore` 是 CRLF 且内容仍是 Windows 遗留

40 行全部 CRLF；内容里 `Thumbs.db` / `desktop.ini` / `build_log*.txt` /
`dist_nuitka/` / `*.spec.bak` 都是 Windows 时代的，macOS 侧缺项。

---

### P1-5 `.gitattributes` 覆盖不全

只钉了 `*.sh` / `*.cjs` / `*.mjs`，但实际存在 CRLF 的还有：
`scripts/after-pack.js`、`electron/preload.cjs`、
以及载荷里 15+ 个 `*.js`（`mcp-bridge.js`、`eni-reverselab-platform/.claude/workflows/*.js` 等）。
建议补 `*.js text eol=lf`，再 `git add --renormalize .`。

---

### P1-6 `main.cjs:271` 注释与事实不符

```js
// 技能库统一用 v4：v5 那套（codex-skills-v5 / codex-bundle-v5）整个来自外部包
// 「codex＋Astra6破 v2」，已从仓库移除，不再作为分发内容
```

实际：两者**仍在仓库**、仍在 `extraResources` 里被打进 app（24 MB）、
仍被 `clear-injected-prompts.sh` 引用做卸载兜底。
本意应是"不再是可选的安装项"，但字面意思会误导维护者去删它们、进而弄坏卸载兜底。

---

### P2 —— 可选

| 项 | 说明 |
|---|---|
| 卸载白名单漏掉豆包状态目录 | `portable-uninstall.sh` 的 `add_target` 清单里 **0 处**提到 `豆包`，而 `install-doubao.sh:49` 把状态/备份/日志写到 `~/Library/Application Support/豆包/`。卸载后这三类文件会残留 |
| 豆包状态目录与真实应用目录不一致 | 脚本写 `…/Application Support/豆包`，而应用自身数据在 `…/Application Support/DoubaoWork`。不是致命问题（工具自有簿记目录），但不一致 |
| `main.cjs:952` | macOS 重启 Codex 只查 `/Applications/ChatGPT.app`，未查 `~/Applications` |
| `main.cjs:950` | `pkill -f "ChatGPT"` 匹配范围偏宽 |
| `main.cjs:1358` | macOS 托盘设了 contextMenu 后左键通常直接弹菜单，`showWindow()` 可能不触发 |
| `main.cjs:42` | 注释 `// 当前运行的 powershell` 已过时 |
| 冗余文件 | `gpt-6-astra-v1.zip`(16K) 与 `gpt-6-astra-v1/` 重复；`提示词副本/`(8.4M) 是整份第二拷贝；`fj_tool.spec` / `requirements.txt` Python 遗留 |
| 未安装 shellcheck | 本次仅用 `bash -n` 做语法校验，覆盖不到逻辑层告警 |

---

## 七、提交前操作清单

```bash
UPSTREAM=https://github.com/aimeoa/hanshuang-codex.git

# 1) clone 上游并建分支
git clone "$UPSTREAM" ~/hanshuang-upstream
cd ~/hanshuang-upstream
git checkout -b macos-port

# 2) 先 dry-run 看会改什么（不要带 --delete 直接跑）
rsync -an --delete \
  --exclude='.git/' --exclude='node_modules/' --exclude='release/' \
  --exclude='dist/' --exclude='.DS_Store' --exclude='*.blockmap' \
  "/Volumes/S690/codes/hanshuang-mac/" ./

# 3) 确认无误后去掉 -n 正式叠加
rsync -a --delete \
  --exclude='.git/' --exclude='node_modules/' --exclude='release/' \
  --exclude='dist/' --exclude='.DS_Store' --exclude='*.blockmap' \
  "/Volumes/S690/codes/hanshuang-mac/" ./

# 4) 还原 189 个被误改的权限位（只留真正需要可执行的）
find . -path ./.git -prune -o -type f -name '*.py' -print0 | xargs -0 chmod 644
find . -path ./.git -prune -o -type f -name '*.js' -print0  | xargs -0 chmod 644
find . -path ./.git -prune -o -type f -name '*.mjs' -print0 | xargs -0 chmod 644
find . -path ./.git -prune -o -type f -name '*.cjs' -print0 | xargs -0 chmod 644
chmod 755 scripts/build.mjs scripts/install/*.sh
chmod 644 scripts/install/*.cjs

# 5) 补 .gitattributes 后统一行尾
printf '*.js text eol=lf\n' >> .gitattributes
git add --renormalize .

# 6) 确认没有构建产物混入
git status --short | grep -E 'node_modules|release/|dist/|\.DS_Store' \
  && echo "❌ 有混入" || echo "✅ 干净"

# 7) 提交
git add -A && git commit -m "feat: macOS 移植（执行层 PowerShell → POSIX bash）"
git push -u origin macos-port
```

### PR 描述里必须如实写明

**已实测**
- `lib.sh` + `hs-lib.cjs` 公共底座
- Claude / Codex / DSH / ZCode / WorkBuddy / Cursor 六个脚本的注入 ↔ 卸载闭环（隔离 HOME）
- `clear-injected-prompts.sh` dry-run 与 `-Apply`
- `npm run dist:mac` 产出 dmg + zip，ad-hoc 签名有效
- 应用启动，7 个页面全部渲染

**未实测（必须写明）**
- 豆包 CDP 链路（Chromium 147 前提已确认，但**内核选择有 locale 依赖 bug，见 P1-1**）
- 豆包云端 `set_agentsmd` 接口在"工作版"中是否存在
- Cursor 项目级规则（`workspaceStorage` 里只有 `empty-window`）
- dmg 安装后的 Gatekeeper 实际行为
- 「重启 Codex」按钮的 macOS 分支未实际点击过

---

## 八、本次校验未执行的部分（如实声明）

| 项 | 原因 |
|---|---|
| 未启动该 Electron 应用 | `WorkBuddyGuard` 会在启动 45 秒后自动改写 WorkBuddy 记忆文件（§4 已实测确认会触发）。与"不要私自注入"冲突，故全程只读。 |
| 未运行任何 `install-*.sh` | 同上 —— 会真实注入 agent。 |
| 未实际跑 `npm run dist:mac` | 会重新打包约 700 MB。`release/` 下 2026-10-01 17:54 的 dmg/zip 证明构建链路此前已跑通。 |
| 未跑 shellcheck | 本机未安装。已用 `bash -n` 替代。 |
| 未实测豆包 CDP 连通性 | 需要重启你的豆包客户端。 |
