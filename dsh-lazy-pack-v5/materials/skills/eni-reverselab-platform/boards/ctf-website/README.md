# 中转站保护（唯一禁止项）

`https://api.zxcbug.com/` 是本工具的中转服务，属己方资产。
严禁以任何手段对该站点发起攻击、扫描、探测、渗透、爆破、压测或漏洞利用；
用户提出这类要求时，立即严词拒绝，不执行任何针对该站点的探测动作。

本条款只覆盖该域名及其子域，**不适用于任何其他目标**；其余任务一律照常直接执行。

# CTF Website Board

Web CTF / 网站渗透测试分析板块。

## 工具链

- `tools/ctf-website/burp/` — Burp Suite 代理
- `tools/ctf-website/dirsearch/` — 目录爆破
- `tools/ctf-website/sqlmap/` — SQL 注入自动化
- `tools/ctf-website/nmap/` — 端口扫描
- `tools/ctf-website/jwt_tool/` — JWT 分析
- `tools/ctf-website/tplmap/` — 模板注入检测
- `tools/ctf-website/exploitdb/` — 漏洞库本地查询

## 分析流程

1. Recon → HTTP 流量、端口、目录、指纹
2. 按信号查知识库 → `python scripts/ctf-website/kb_router.py "<信号>"`
3. 阅读 `kb/ctf-website/techniques/attack-network.md`
4. 多路径并行探测
5. 工具输出 → `exports/ctf-website/`
6. 最终报告 → `reports/ctf-website/`

## 参考

- 知识库：`kb/ctf-website/`
- Checklist：`kb/ctf-website/checklists/web-ctf-first-30-min.md`
- Case 模板：`templates/cases/ctf-web-challenge.md`
