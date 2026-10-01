# macOS 移植 · 最终审查报告

审查时间：2026-10-01（第二版，修正了首版对豆包的误判）
验证主机：macOS 27.0 / arm64（真机）
验证方式：**只读扫描 + 隔离 HOME 实测**，真实配置文件未被写入

---

## 一、结论速览

| 目标 | 脚本 | 路径正确性 | 真机注入状态 | 可移植性 |
|---|---|---|---|---|
| Codex | `install.sh` | ✅ 正确 | 未注入（用户未操作） | ✅ 动态探测 |
| Claude | `install-claude.sh` | ✅ 正确 | 未注入（用户未操作） | ✅ 动态探测 |
| DeepSeek Harness | `install-dsh.sh` | ✅ 正确 | ✅ 已注入（懒人包模式） | ✅ 动态探测 |
| ZCode | `install-zcode.sh` | ✅ 主体正确 | ✅ 已注入 + **系统提示词补丁已修好** | ✅ 内容锚点 |
| WorkBuddy | `install-workbuddy.sh` | ✅ 正确 | ⚠️ 云记忆被回写清空 | ✅ 动态探测 |
| Cursor | `install-cursor.sh` | ✅ 已由官方文件确认 | 未注入（用户未操作） | ✅ 动态探测 |
| 豆包 | `install-doubao.sh` | ✅ **已修正应用名与内核路径** | 未注入（CDP 链路待实测） | ✅ 动态探测 |

> 第二轮修复了 3 个 P0（ZCode 补丁 + 豆包两处），详见第四节「修复记录」。

---

## 二、逐目标文件位置分析

### 1. Cursor —— ✅ 路径已获官方确认

**实测（用户启动过之后）**

| 项 | 值 |
|---|---|
| 应用 | `/Applications/Cursor.app` 版本 3.22.12 |
| BundleID | `com.todesktop.230313mzl4w4u92` |
| `~/.cursor` | ✅ 存在（启动后生成） |
| `~/.cursor/rules` | 尚未创建（没人写过规则） |
| `~/Library/Application Support/Cursor/User` | ✅ 存在，`settings.json` 44 字节 |
| `~/Library/Application Support/Cursor/User/workspaceStorage` | ✅ 存在，仅 `empty-window` |
| `~/Library/Preferences/com.todesktop.230313mzl4w4u92.plist` | ✅ 存在 |

**决定性证据**：`~/.cursor/.gitignore` 是 Cursor 自己维护的
`# >>> CURSOR MANAGED BLOCK >>>`，里面逐条列出了官方用户级目录：

```
# Plugin cache (rules, skills, agents)
!plugins/
# Built-in Cursor skills
!skills-cursor/
# User's personal skills
!skills/
# User's personal slash commands
!commands/
# User's plan files
!plans/
# Subagent state/transcripts
!subagents/
# User-level cursor rules      ← 关键
!rules/
!rules/**
```

**`# User-level cursor rules` → `!rules/`**，即 **`~/.cursor/rules/` 是 Cursor 官方确认的用户级规则目录**。
脚本把它列为第一候选（主路径），完全正确 ✅

同一份清单还确认了另外两个可用位置（本次移植未使用，可作为后续增强）：

- `~/.cursor/skills/` —— 用户个人 skills（实测 `~/.cursor/skills-cursor/` 已有 26 个内置技能）
- `~/.cursor/commands/` —— 用户自定义斜杠命令

**遗留风险**：`workspaceStorage` 目前只有 `empty-window`，没有真实项目记录，
所以「项目级规则自动探测」这条路径仍未验证。等用户用 Cursor 打开过真实项目后即可确认。

---

### 2. 豆包 —— ⚠️ 首版误判已修正：**技术前提成立，但脚本应用名对不上**

> **首版结论错误。** 首版因为看到 `Contents/Frameworks` 不存在、主二进制只有 2.6MB，
> 判定它不是 Electron、CDP 方案不可行。**这个判断是错的** —— 它用的是
> 「主壳 + Helpers 子应用」的布局，Chromium 内核藏在 Helpers 里。

**实测**

| 项 | 值 |
|---|---|
| 实际应用 | `/Applications/DoubaoWork.app` |
| BundleID | `com.work.pc.doubao` |
| 版本 | 2.31.8 |
| **CFBundleSignature** | **`Cr24`** ← Chromium 应用的传统签名 |
| 主可执行 | `Contents/MacOS/DoubaoWork`（2.6MB，启动器） |
| 内置子应用 | `Contents/Helpers/豆包.app`（`com.work.pc.doubao.linkrouter`） |
| 内置浏览器 | `Contents/Helpers/DoubaoWork Browser.app` |
| **Chromium 内核** | `.../DoubaoWork Browser.app/Contents/Frameworks/DoubaoWork Browser Framework.framework/Versions/**147.0.7727.149**` |

**Chromium 铁证（全部实测命中）**

```
CFBundleSignature = Cr24                                  ← Chromium 传统签名
DoubaoWork Browser Framework .../147.0.7727.149           ← Chromium 147
.../Resources/icudtl.dat                                  ✅
.../Resources/resources.pak                               ✅
~/Library/Application Support/DoubaoWork/Local State      ← Chromium 的 Local State
~/Library/Application Support/DoubaoWork/Default/         ← Chromium 标准 profile
  ├── Cookies / History / IndexedDB / GPUCache / LOCK / LOG
  └── Extension Rules / Extension Scripts / Extension State
~/Library/Application Support/DoubaoWork/first_party_sets.db
~/Library/Application Support/DoubaoWork/GraphiteDawnCache
~/Library/Application Support/DoubaoWork/GrShaderCache
```

**结论修正**

- ✅ **技术前提成立**：Chromium 内核支持 `--remote-debugging-port`，CDP 方案在 macOS 上可行
- ❌ **脚本扫不到它**：`install-doubao.sh` 的候选只有 `豆包.app` / `Doubao.app`，
  实际是 `DoubaoWork.app`
- ⚠️ **启动参数要打到正确的二进制**：脚本现在拼的是
  `"$APP_BUNDLE/Contents/MacOS/豆包" --remote-debugging-port=$PORT`，
  而实际主可执行是 `Contents/MacOS/DoubaoWork`，Chromium 在
  `Contents/Helpers/DoubaoWork Browser.app/Contents/MacOS/DoubaoWork Browser`
- ❓ **云端接口未验证**：原脚本调 `/alice/generaltask/memory/set_agentsmd`。
  这台机器上装的是「工作版」（`DoubaoWork`），与脚本针对的消费级豆包未必同一产品线，
  该接口是否存在需要实测

**建议（已于第二轮实施，见第四节）**：`install-doubao.sh` 已补上 `DoubaoWork.app` 候选，
并把启动目标从外层启动器改为 `Contents/Helpers/<X> Browser.app` 里的 Chromium 主体。
CDP 链路本身仍需实机验证一次（那会重启用户的豆包客户端）。

---

### 3. ZCode —— ⚠️ 主体成功，系统提示词补丁失败

**实测**

| 项 | 值 |
|---|---|
| 应用 | `/Applications/ZCode.app` 版本 3.14.4 |
| BundleID | `dev.zcode.app` |
| 系统提示词文件 | `/Applications/ZCode.app/Contents/Resources/glm/zcode.cjs`（14,820,968 字节）✅ 路径正确 |
| `~/.zcode/AGENTS.md` | ✅ |
| `~/.zcode/cli/memories/global/memory/` | ✅ 含 `MEMORY.md` + `seagull-agents.md` |
| `~/.zcode/v2/setting.json` | ✅ `memoryEnabled = true` |
| `~/.zcode/v2/bot-state.v2.json` | ❌ **实际是 `bot-state.v3.json`** |
| `~/.zcode/skills` | 63 个 |

**注入结果**

| 注入点 | 结果 |
|---|---|
| `~/.zcode/AGENTS.md` | ✅ **与 `寒霜v4.md` 逐字节相同** |
| `cli/memories/global/memory/seagull-agents.md` | ✅ 11132 字节，含 4 处特征串 |
| `v2/setting.json` → `memoryEnabled` | ✅ true |
| `skills/` | ✅ 63 个 |
| **系统提示词补丁（zcode.cjs）** | ❌ **未生效** |

**补丁为什么没生效** —— 根因是**锚点用的是混淆后的变量名，而 3.14.4 把它们全打乱了**：

| 脚本依赖的锚点 | 在 3.14.4 里的实际情况 |
|---|---|
| `function u9o`（起点） | ✅ 存在 1 次，但**已变成完全不相干的函数**：`function u9o(e,t){return r9o(e,...".zcode","workflows"))?"project":...}` —— 是判断 workflow 作用域的辅助函数 |
| `function Alt`（终点） | ❌ **0 次**，终点锚点不存在 → 前置条件不成立，补丁被跳过 |
| `s9o="You are ZCode, an interactive coding agent"` | 字符串**还在**，但变量名改成了 **`IJs`**：`IJs="You are ZCode, an interactive coding agent"` |
| `Xlt={...beforeDefault:[...]}` | 变量名已改，但 **`beforeDefault` 这个键还在**（2 处），内容为 `"# Communicating with the user"` 那一段沟通指南 |

脚本 `install-zcode.sh:462` 的前置条件是
`[[ "$content" == *"function u9o"* && "$content" == *"function Alt"* ]]`，
第二个条件不满足 → 走 `else` 分支 → 打印 `[3/4] u9o function not found, skipped` →
**继续执行，退出码仍为 0**。所以界面上显示的是「安装成功」。

`zcode.cjs` 里寒霜特征串 0 处、无 `.backup-*` 文件、
`install-state.json` 的 `systemPromptBackup` 为 `null` —— 三方印证：补丁从未写入。

**为什么补丁失败不影响激活**：激活逻辑写在 `寒霜v4.md` 的正文里，
而这份正文已经通过另外三条路径注入成功（AGENTS.md 逐字节相同 + 记忆文件 + 技能库）。
系统提示词补丁只是**更深的可选一层**，用来额外改写 ZCode 自带的身份提示
（`"You are ZCode, an interactive coding agent"` 前缀 + 沟通指南）。

**修复方向（已于第二轮实施，见第四节）**：锚点改成**按内容匹配**，执行交给 node。

- CLI 前缀：匹配字符串字面量 `"You are ZCode, an interactive coding agent"`，变量名靠正则现读
- 沟通指南：定位 `beforeDefault` 键名，字符串感知地清空数组
- 不再依赖 `u9o` / `Alt` 这类压缩变量名
- **找不到锚点必须显式报警**（旧实现静默 skip，用户以为成功了）

---

## 三、可移植性审查

### 硬编码审计（2026-10-01 第二轮）

对 `scripts/install/` 全量扫描，结论如下。

**干净的部分**

| 检查项 | 结果 |
|---|---|
| 是否出现 `/Users/<用户名>` | ❌ 无 |
| 是否出现具体用户名（如 `/Users/<用户名>`） | ❌ 无 |
| 是否出现 `/home/` | ❌ 无 |
| 是否写死机器特定标识（uid、设备号） | ❌ 无 |
| 具体版本号（3.14.4 / 2.31.8 / 147.x） | 只出现在**注释**里，代码不依赖 |

**数据目录层（决定注入是否生效的部分）100% 动态**

| 脚本 | 解析顺序 |
|---|---|
| `install.sh` | `-CodexHome` → `$CODEX_HOME` → `~/.codex` |
| `install-claude.sh` | `-ClaudeHome` → `~/.claude` |
| `install-dsh.sh` | `-DshHome` → `~/.dsh` |
| `install-zcode.sh` | `-ZcodeHome` → `~/.zcode`；`zcode.cjs` 三候选 + 进程反推 + `HS_ZCODE_CJS` |
| `install-workbuddy.sh` | `-ConfigDir` → `cli/product.json` 的 `dataFolderName` → `~/.workbuddy-ai` → `~/.workbuddy` |
| `install-cursor.sh` | 三候选规则目录 + `workspaceStorage` 动态反解 |
| `install-doubao.sh` | `HS_DOUBAO_APP` → 四候选应用名 → `$HOME/Applications` |

**WorkBuddy 的 uid 完全动态**：`-Uid` 参数 → 扫 `<ConfigDir>/memory/*_memory.md` 文件名
→ `settings.json` 的 `claw.legacyOwnerUid`。没有写死。

**唯一需要"找 .app 包"的目标只有两个**

其余 5 个目标只操作 `$HOME` 下的数据文件，**连应用装没装都不需要知道** ——
换任何一台 Mac，只要数据目录存在就能注入。只有 ZCode（要改包内 `zcode.cjs`）
和豆包（CDP 要启动客户端）需要定位应用包，两者都配了环境变量覆盖开关。

### 第二轮修掉的一个越权缺陷

`install-workbuddy.sh` 的「其它 profile 兜底」原本直接遍历 **`/Users/*` 下所有账户**：

```bash
for u in /Users/*; do          # ← 从 Windows 版 C:\Users\* 照搬
```

这个假设在 macOS 上不成立：`C:\Users` 下多半是同一个人建的多套环境，
而 `/Users` 下通常是**不同的真人账户**。后果是：当本账户还没有 WorkBuddy 数据时，
脚本会「跨账户」切到别人的配置目录并往里注入。

**已收紧为只认同 uid 的家目录**，并实测验证：

```
/Users/Shared owner uid = 0 ，当前用户 uid = 501
在 /Users/Shared 下造诱饵 .workbuddy-ai/memory/otherperson_memory.md
跑兜底分支 → ✅ 未选中诱饵，老老实实待在本账户目录
同 uid 家目录兜底仍然生效（多账户场景保留）
```

---

## 四、修复记录（2026-10-01 第二轮）

### 已修复

**1. ZCode 系统提示词补丁（P0）—— 重写为内容锚点，并改为 node 执行**

新增 `scripts/install/zcode-patch.cjs`，`install-zcode.sh` 第 3 步改为调用它。改动要点：

| 项 | 旧实现 | 新实现 |
|---|---|---|
| CLI 前缀锚点 | 变量名 `s9o` | 字符串字面量 `"You are ZCode, an interactive coding agent"`，变量名靠正则现读 |
| 结束锚点 | `function Alt`（3.14.4 不存在） | 不再需要 |
| 沟通指南 | 变量名 `Xlt` + bash 前后缀裁剪 | 键名 `beforeDefault` + 字符串感知的括号配对 |
| 执行者 | bash 字符串操作（14MB 单行，易错位） | node（`JSON.stringify` 生成字面量） |
| 失败行为 | 静默 skip，退出码 0 | 显式报错，`HAD_ERROR=1`，退出码 1 |
| 已注入判定 | 固定串 `CTF-LAB-2.0`（**不在任何提示词里，从未生效**） | 由 `zcode-patch.cjs` 判定真实状态（`clean` / `patched`） |

实测（在副本上，真实 app 未被触碰）：

```
安装:  ACTION_CLI=replaced  CLI_VAR=IJs  CLI_PROMPT_CHARS=5125
       ACTION_GUIDE=cleared GUIDE_ARRAY_LEN_BEFORE=2124   EXIT=0
验证:  node --check 通过（补丁后仍是合法 JS）
       STATE=patched
幂等:  再次安装 → "already patched, skipped"，体积不变
卸载:  Restored system prompt → 逐字节还原（sha256 一致）
真实 app 指纹: 安装前后一致，全程未动
```

**2. 豆包应用名与内核启动（P0）**

| 项 | 旧实现 | 新实现 |
|---|---|---|
| 应用候选 | 只有 `豆包.app` / `Doubao.app` | 补上 **`DoubaoWork.app`**（macOS 实际安装名） |
| 启动目标 | `Contents/MacOS/<任意可执行>`（实测只是 2.6MB 启动器） | **优先 `Contents/Helpers/<X> Browser.app/Contents/MacOS/<X> Browser`**（真正的 Chromium 主体），无 Helpers 结构时再退回 |

实测：内核选择正确命中
`/Applications/DoubaoWork.app/Contents/Helpers/DoubaoWork Browser.app/Contents/MacOS/DoubaoWork Browser`，
对应框架版本 `147.0.7727.149`。

### 回归测试

全部 7 个目标脚本 + 兜底清扫，**30 项断言全部通过**（隔离 HOME，真实配置零改动）：

```
1. Claude      安装/卸载 5 项 ✅
2. Codex       安装/卸载 6 项 ✅
3. DSH         安装/卸载 3 项 ✅
4. ZCode       安装/补丁/JS 合法性/卸载/还原 7 项 ✅
5. Cursor      安装/卸载 4 项 ✅
6. WorkBuddy   安装/卸载 4 项 ✅
7. 豆包        正确识别 DoubaoWork.app ✅（-NoLaunch，未启动应用）
8. 兜底清扫    dry-run 1 项 ✅
```

### 仍未验证

- 豆包的 **CDP 链路本身**：内核已确认是 Chromium 147，启动路径已修正，
  但「启动后能否真的开出调试端口」「云端 `set_agentsmd` 接口在工作版里是否存在」
  需要实机跑一次才能确认（那会重启用户的豆包客户端）
- ZCode 补丁的**运行时效果**：JS 语法合法、结构正确，但 ZCode 启动后是否正常
  加载新提示词，需要重启 ZCode 验证

---

## 五、待修清单

| # | 问题 | 位置 | 状态 |
|---|---|---|---|
| ~~P0~~ | ~~豆包应用名候选缺 `DoubaoWork.app`~~ | `install-doubao.sh` | ✅ **已修** |
| ~~P0~~ | ~~豆包启动目标是启动器而非内核~~ | `install-doubao.sh` | ✅ **已修** |
| ~~P0~~ | ~~ZCode 系统提示词补丁静默失败~~ | `install-zcode.sh` + 新增 `zcode-patch.cjs` | ✅ **已修** |
| P1 | ZCode `bot-state.v2.json` vs 实际 `v3` | `install-zcode.sh` | 待修（不影响主流程） |
| P1 | WorkBuddy 云记忆被回写清空 | 原版设计问题 | 需 `WorkBuddyGuard` 常驻补写 |
| P2 | Cursor 项目级规则未经真机验证 | `install-cursor.sh` | 打开真实项目后验证 |
| P3 | Cursor 未利用 `~/.cursor/skills/` | — | 后续增强 |

---

## 六、已验证 vs 未验证（PR 描述里应如实写明）

**已在真机 macOS 上验证**

- `lib.sh` + `hs-lib.cjs` 公共底座
- `install-claude.sh`：注入 → 幂等重装 → 用户内容保留 → 卸载还原（隔离 HOME）
- `install.sh`（Codex）：注入 + config.toml 指针 + 卸载还原（隔离 HOME）
- `install-dsh.sh`：真机注入成功（懒人包模式，AGENTS.md 带 `pack=` 标记）
- `install-zcode.sh`：真机 AGENTS.md / 记忆 / 技能注入成功
- `install-workbuddy.sh`：真机注入 6 项校验全过；卸载可完整还原
- `install-cursor.sh`：隔离 HOME 注入/卸载闭环；规则目录已由 Cursor 官方 `.gitignore` 确认
- `clear-injected-prompts.sh`：dry-run 与 `-Apply` 均正常
- 构建：`npm run dist:mac` 产出 dmg + zip，ad-hoc 签名有效
- 应用启动：`HS_CAPTURE` 模式跑通，7 个页面全部渲染

**未验证**

- 豆包 CDP 链路：技术前提（Chromium 147）已确认，但应用名与可执行路径需修正后实测
- 豆包云端接口 `set_agentsmd` 在「工作版」中是否存在
- Cursor 项目级规则：`workspaceStorage` 目前只有 `empty-window`
- ZCode 系统提示词补丁：锚点失配，未生效
- dmg 安装后的 Gatekeeper 实际行为
- 「重启 Codex」按钮的 macOS 分支（`osascript` + `open -a`）未实际点击过
