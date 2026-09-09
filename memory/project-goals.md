---
name: project-goals
description: 寒霜项目目标——多工具（codex/claude/zcode）一键配置安装与维护
metadata:
  type: project
---

寒霜项目（`E:\好用的终极项目\寒霜项目`）目标：

- 为多个 AI 编码工具（Codex、Claude、ZCode）提供一键安装配置工具
- 每个工具一个子目录：`hanshuang-codex/`、`hanshuang-claude/`、`hanshuang-zcode/`
- 安装内容：提示词（AGENTS.md/CLAUDE.md）+ 技能（skills）+ 记忆文件
- 支持安装/卸载/状态记录，可重复运行

**Why:** 用户在多工具间切换，需要统一、可复现的配置安装方式。
**How to apply:** 修改本工具时保持与 codex/claude 版一致的风格（备份→安装→状态记录→可卸载）；zcode 版额外处理系统提示词（`E:\zcodess\resources\glm\zcode.cjs`）与记忆目录（`~/.zcode/cli/memories/`）。
