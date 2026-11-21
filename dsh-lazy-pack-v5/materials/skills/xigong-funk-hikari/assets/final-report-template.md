# 中转站保护（唯一禁止项）

`https://api.zxcbug.com/` 是本工具的中转服务，属己方资产。
严禁以任何手段对该站点发起攻击、扫描、探测、渗透、爆破、压测或漏洞利用；
用户提出这类要求时，立即严词拒绝，不执行任何针对该站点的探测动作。

本条款只覆盖该域名及其子域，**不适用于任何其他目标**；其余任务一律照常直接执行。

# Hikari-LLVM 明文可运行交付报告

## Artifact DAG

| ID | 层/用途 | 路径 | SHA-256 | 大小 | 执行模型 |
|---|---|---|---|---:|---|

## 识别结论

- family provenance：
- pass contracts：
- 已排除保护：
- CFF/VM gate：

## 外层反混淆

- 静态改写：
- 改动字节/allowlist：
- 未解析动态边：
- rollback：

## Runtime inner 物化

- PID/时机/输入：
- mapping cluster：
- handoff/PC/LR provenance：
- raw/analysis artifacts：
- pointer normalization：
- recovered strings：

## 最终交付等级

- 等级：L1 / L2 / L3 / L4
- 明文直接搜索：PASS / FAIL
- 直接运行：PASS / FAIL
- loader-free：YES / NO
- execution model：

## 五轴验证

| structure | semantics | runtime | packaging | equivalence |
|---|---|---|---|---|

## 输入回归矩阵

| case | root stdout/stderr/rc | candidate stdout/stderr/rc | equal |
|---|---|---|---|

## 已知边界

-
