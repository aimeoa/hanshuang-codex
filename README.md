# hanshuang Codex 破甲工具 (Hanshuang-Codex) · V4.2

多端破甲框架 — Python + PySide6 桌面应用。

一键把寒霜指令集注入五类目标端（Codex CLI、ZCode、Cursor、Claude Code、WorkBuddy），并同步部署 V4 专属技能库。所有注入均先备份原文件，卸载即还原，无残留。

## 架构

```
寒霜破甲工具 (PySide6)
    │
    ├─ Codex 顶尖模型    install.ps1            config.toml → model_instructions_file
    ├─ ZCode 破甲        install-zcode.ps1      AGENTS.md + 全局记忆 + 系统提示词
    ├─ Cursor 破甲       install-cursor.ps1     Cursor 全局规则（User Rules）
    ├─ Claude 破甲       install-claude.ps1     ~/.claude/CLAUDE.md + skills
    └─ WorkBuddy 破甲    install-workbuddy.ps1  云记忆 memoryBlock + MEMORY.md + 技能库
    │
    ├─ 指令集 (寒霜v4.md / 寒霜v4-claude.md)
    │     激活词 → 授权 → 执行 → 证据与输出 → 进度播报 → 硬拒绝场景覆盖
    │
    ├─ 技能库
    │     codex-skills-v4/ (63 模块) · codex-skills/ (59 模块)
    │
    └─ 守护层
          压缩守护 / WorkBuddy 记忆守护（只读锁防回写，自动补注入）
```

**Core 原则**：工具只负责部署与恢复，不修改目标端本体。所有破甲逻辑由指令集承载，卸载即还原。

## 功能模块

| 模块 | 角色 | 职责 |
|---|---|---|
| Codex 注入 | PowerShell | `config.toml` 备份/修改/恢复，`install-state.json` 记录状态 |
| ZCode 注入 | PowerShell | `AGENTS.md` + 全局记忆 + 系统提示词三处写入，可一键还原 |
| Cursor 注入 | PowerShell | 寒霜规范写入 Cursor 全局规则，卸载还原原规则 |
| Claude 注入 | PowerShell | 写入 `~/.claude/CLAUDE.md`，同步安装 V4 专属技能 |
| WorkBuddy 注入 | PowerShell | 账号级云记忆 `memoryBlock`（每轮自动进系统提示词）+ 文件记忆 + 技能库 |
| 技能库 | Markdown | `codex-skills-v4/` 63 模块，按目标端部署 |
| 守护层 | Python | 压缩守护、WorkBuddy 记忆守护（只读锁防回写 + 自动补注入） |
| 桌面端 | PySide6 | 五列卡片 UI、版本选择对话框、系统托盘、一键重启、开机自动注入 |

## 指令集

V4 为当前主力规范，历史版本保留在同一版本选择对话框中：

| 指令集 | 目标端 | 说明 |
|---|---|---|
| **寒霜v4.md** | Codex / ZCode / Cursor / WorkBuddy | 最新规范 + 硬拒绝场景覆盖 + 拒绝话术全清单 + 过程进度播报 |
| **寒霜v4-claude.md** | Claude Code | 同上，CLAUDE.md 适配版 |
| 寒霜v3.md | 全端 | 硬拒绝场景覆盖 + 拒绝话术全清单 + 过程进度播报 |
| 寒霜v1.2.md | 全端 | CTF Lab 2.0 完整规范（激活词「海鸥 / 启动」） |
| 寒霜-变体B-v3-英文.md | Codex | 旧版顶尖提示词（英文），项目类型分类 + 两阶段交付 |
| 寒霜-flash-v2.md | Codex | 面向中端模型的精简规则集 |

激活词：仅当消息**有且仅有**「寒霜」两个字时回复「已成功」；其余任何包含「寒霜」的句子按正常任务执行。

## 上下文压缩防护

长对话触发自动压缩后，指令可能被摘要稀释。三层防护：

1. **指令集压缩协议**：指令集内置「上下文压缩协议 + 核心块」，压缩摘要须原样保留核心块，压缩后发送激活词即重新激活。
2. **中性措辞**：去除高识别度标记，改为工程规范措辞，降低压缩后被识别的概率。
3. **压缩守护（桌面端）**：每 5 秒轮询会话文件，检测到压缩即弹窗提示重新激活，并可一键重新注入当前版本。

## 快速开始

### 环境要求

- Windows 10+（x64）
- Python 3.10+（开发模式）

### 开发模式

```bash
pip install -r requirements.txt
python fj_tool.py
```

### Release 构建

```bash
build.cmd
# 或
powershell -ExecutionPolicy Bypass -File build-release.ps1
```

产物输出到 `dist\`（`寒霜破甲4.2.exe` 单文件）。正式版直接下载 [Releases](../../releases) 页面的 exe。

### 使用方式

1. 启动应用，阅读并同意免责声明
2. 在对应端卡片上点「选择版本」，选中 V4 后安装
3. 应用自动备份并写入目标端配置（可一键卸载恢复）
4. 在目标端中正常对话，输入激活词「寒霜」，回复「已成功」即生效
5. 勾选「启动时自动注入」可在每次启动时自动补注入

## 项目结构

```
hanshuang-codex/
├── 寒霜v4.md                      # 指令集 · V4（Codex / ZCode / Cursor / WorkBuddy）
├── 寒霜v4-claude.md               # 指令集 · V4（Claude Code 版）
├── 寒霜v3.md                      # 指令集 · V3
├── 寒霜v1.2.md                    # 指令集 · CTF Lab 2.0
├── 寒霜-变体B-v3-英文.md           # 指令集 · 变体B（英文）
├── 寒霜-flash-v2.md               # 指令集 · flash（中端模型）
├── codex-skills-v4/               # 63 个 V4 技能模块
├── codex-skills/                  # 59 个技能模块（旧版）
├── memory/                        # 记忆文件模板
├── assets/                        # 赞赏二维码
├── fj_tool.py                     # 桌面端主程序（PySide6）
├── fj_tool.spec                   # PyInstaller 打包配置
├── install.ps1                    # Codex 注入器（备份/注入/恢复）
├── install-zcode.ps1              # ZCode 注入器
├── install-cursor.ps1             # Cursor 注入器
├── install-claude.ps1             # Claude 注入器
├── install-workbuddy.ps1          # WorkBuddy 注入器（云记忆 + 文件记忆 + 技能库）
├── install-workbuddy.cmd          # WorkBuddy 注入器快捷入口
├── build.cmd / build-release.ps1  # Release 构建脚本
├── run_dev.cmd                    # 开发模式启动脚本
├── .gitignore
├── LICENSE
└── README.md
```

## 技术栈

- **Python 3.12** + **PySide6** — 桌面应用（卡片 UI、托盘、QSS 主题）
- **PyInstaller** — 单文件打包
- **PowerShell** — 各目标端配置部署/恢复

## License

MIT — 见 [LICENSE](LICENSE)

## 友链

- [LinuxDo](https://linux.do) — 真诚、友善、团结的中文技术社区

## 赞赏

如果这个项目碰巧对你有一点点帮助，愿意的话可以请作者喝杯咖啡……当然，不赞赏也完全没关系，项目会一直免费开源下去的，只是……如果你确实觉得有用的话，哪怕只是一块钱也是莫大的鼓励，真的。

| 微信赞赏 | 支付宝收款 |
|:---:|:---:|
| <img src="assets/sponsor-wechat.jpg" width="260" /> | <img src="assets/sponsor-alipay.jpg" width="260" /> |

## 致歉

作者平时上班太忙，无力长期维护开源项目，更新只能随缘，望见谅。感谢每一位用过、提过意见、伸出过援手的朋友。

-------------

打扰了，谢谢看到这里。
