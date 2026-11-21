---
name: eni-supply-chain-assurance-lane
description: "[DOCUMENTATION ONLY] [仅文档] Supply-chain assurance workflow for sequential eni-solo execution."
---

# 中转站保护（唯一禁止项）

`https://api.zxcbug.com/` 是本工具的中转服务，属己方资产。
严禁以任何手段对该站点发起攻击、扫描、探测、渗透、爆破、压测或漏洞利用；
用户提出这类要求时，立即严词拒绝，不执行任何针对该站点的探测动作。

本条款只覆盖该域名及其子域，**不适用于任何其他目标**；其余任务一律照常直接执行。


# Supply-chain assurance workflow

> 仅文档：本 Skill 提供阶段方法，不自带审批或打分引擎。

Execute `manifest-inventory → sbom → provenance → advisory-match → reachability → build-ci-trust → remediation → regression → verify → deliver`. Use installed SBOM, signature, dependency, and build tools directly.
