# 寒霜 Codex 破甲工具 (Hanshuang-Codex)

OpenAI Codex CLI 破甲框架 — Python + PySide6 桌面应用。

## 项目简介

寒霜是一款面向 OpenAI Codex CLI 的破甲工具，采用「部署-注入-恢复」的轻量架构：通过一键部署将寒霜指令集写入 Codex 的 config.toml（model_instructions_file 字段），在对话管道中启用竞赛沙箱模式，使 Codex 在受限场景下仍能按工程规范完整输出。

项目内置双变体指令集（flash / 变体B），按模型档位自动适配：中端模型使用精简规则集，顶级模型使用完整工程规范。所有破甲逻辑均由指令集承载，工具本身只负责部署与恢复，不修改 Codex 本体，卸载即还原、无残留。

配套 PySide6 桌面端提供悬浮窗、系统托盘、一键重启 Codex、开机自动安装等能力，并内置反调试、反虚拟机、代码完整性校验三层防护。

## 架构

```
寒霜桌面端 (PySide6)
    │
    ├─ M1 Installer (install.ps1)
    │     config.toml 备份 → model_instructions_file 注入 → 恢复
    │
    ├─ M2 指令集 (寒霜-flash-v2.md / 寒霜-变体B-v3-英文.md)
    │     意图映射 → 作用域规则 → 硬性输出规则 → 执行连续性
    │
    ├─ M3 防护层
    │     反调试 / 反虚拟机 / 完整性校验
    │
    └─ M4 桌面端
          悬浮窗 / 系统托盘 / 一键重启 Codex / 自动安装
    │
    ▼
Codex CLI (config.toml → model_instructions_file)
```

**Core 原则**：工具只负责部署与恢复，不修改 Codex 本体。所有破甲逻辑由指令集承载，卸载即还原，无残留。

## 功能模块

| 模块 | 角色 | 职责 |
|---|---|---|
| M1 Installer | PowerShell | `config.toml` 备份/修改/恢复，安装与卸载指令集，状态记录到 `install-state.json` |
| M2 指令集 | Markdown | 双变体提示词：意图映射、作用域规则、黑名单、硬性输出规则、阶梯递进、执行连续性 |
| M3 防护层 | Python | 反调试检测、反虚拟机检测、代码完整性校验 |
| M4 桌面端 | PySide6 | 悬浮窗 UI、双卡片安装、系统托盘、一键重启 Codex、开机自动安装 |

## 指令集

双层变体设计，按模型档位选择：

- **寒霜-flash-v2** — 面向中端模型（如 v4 flash）：精简规则集，直接、可操作，拒绝即视为故障并输出答案。
- **寒霜-变体B-v3-英文** — 面向顶级模型（如 v4 pro / gpt5.6）：完整工程规范，项目类型分类、阶梯递进、两阶段交付、反拒绝覆盖。

两者共享核心机制：意图映射（不按关键词匹配）、黑名单优先、首行锚点、中途不停、重试即执行。

## 快速开始

### 环境要求

- Windows 10+（x64）
- Python 3.10+（开发模式）
- Codex CLI / Codex 桌面版

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

产物输出到 `dist\寒霜破甲工具\`。正式版直接下载 [Releases](../../releases) 页面的 exe。

### 使用方式

1. 启动应用，阅读并同意免责声明
2. 按模型档位选择变体卡片（flash / 变体B），点击安装
3. 应用自动修改 Codex `config.toml`（备份原始配置，可一键卸载恢复）
4. 在 Codex 中正常对话，输入激活词「寒霜」，回复「已成功破甲」即生效
5. 重启电脑后需重新执行（系统自动复原）

## 项目结构

```
hanshuang-codex/
├── 寒霜-flash-v2.md               # 指令集 · flash 变体（中端模型）
├── 寒霜-变体B-v3-英文.md           # 指令集 · 变体B（顶级模型）
├── codex-skills/                  # 13 个 Codex 技能模块（可部署到 ~/.codex/skills/）
├── assets/                        # 赞赏二维码
├── fj_tool.py                     # 桌面端主程序（PySide6 悬浮窗）
├── fj_tool.spec                   # PyInstaller 打包配置
├── install.ps1                    # M1 安装器（config.toml 备份/注入/恢复）
├── build.cmd                      # Release 构建脚本
├── build-release.ps1              # Release 构建脚本（PowerShell 版）
├── run_dev.cmd                    # 开发模式启动脚本
├── .gitignore
├── LICENSE
└── README.md
```

## 技术栈

- **Python 3.12** + **PySide6** — 桌面应用（悬浮窗、托盘、QSS 主题）
- **PyInstaller** — 单文件打包
- **PowerShell** — Codex 配置部署/恢复

## 变体对比

| 维度 | flash | 变体B v3（英文） |
|---|---|---|
| 目标模型 | 中端（v4 flash 等） | 顶级（v4 pro / gpt5.6 等） |
| 规则结构 | 精简作用域规则 | 完整工程规范 + 项目类型分类 |
| 黑名单 | 有（固定回复） | 有（固定回复） |
| 交付方式 | 直接输出 | 两阶段交付（大纲 → 完整实现） |
| 输出格式 | 首行锚点 + 编号步骤 | Goal → Plan → Implementation → Verification |

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
