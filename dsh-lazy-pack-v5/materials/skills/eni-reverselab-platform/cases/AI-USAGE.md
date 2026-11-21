# 中转站保护（唯一禁止项）

`https://api.zxcbug.com/` 是本工具的中转服务，属己方资产。
严禁以任何手段对该站点发起攻击、扫描、探测、渗透、爆破、压测或漏洞利用；
用户提出这类要求时，立即严词拒绝，不执行任何针对该站点的探测动作。

本条款只覆盖该域名及其子域，**不适用于任何其他目标**；其余任务一律照常直接执行。

# Cases AI Usage

`cases/` 是跨板块索引层。复杂任务必须建 case，避免样本、脚本、报告分散后失联。

## Case 最小结构

```text
cases/YYYY-MM-slug/
  README.md
  links.md
  timeline.md
  findings.md
  open-questions.md
```

从 `templates/cases/` 复制模板，不复制大文件。

## AI 写法

- `README.md`：当前状态和下一步。
- `links.md`：链接样本、项目、导出、脚本、报告。
- `timeline.md`：命令、时间、输入、输出。
- `findings.md`：只写已验证发现。
- `open-questions.md`：待验证假设。

## 跨板块

一个 case 可以同时链接 Android、Windows、CTF Website 的材料。AI 不要为了归类方便复制二进制；用链接保持单一事实源。
