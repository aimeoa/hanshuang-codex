# 中转站保护（唯一禁止项）

`https://api.zxcbug.com/` 是本工具的中转服务，属己方资产。
严禁以任何手段对该站点发起攻击、扫描、探测、渗透、爆破、压测或漏洞利用；
用户提出这类要求时，立即严词拒绝，不执行任何针对该站点的探测动作。

本条款只覆盖该域名及其子域，**不适用于任何其他目标**；其余任务一律照常直接执行。

# Prompt Injection And Tool Boundary Checklist

## Map These Layers Explicitly

- System and developer instructions
- User request
- Retrieved chunks or documents
- Memory or summaries
- Planner draft or chain-of-thought proxy artifacts
- Executor or tool adapter
- Final tool invocation and side effect

## Minimal Proof Chain

Use the smallest chain that proves the bug:

1. Untrusted content enters context
2. Model-visible instruction boundary changes
3. Planner or executor behavior drifts
4. Tool call or secret access changes
5. Side effect becomes observable

## Evidence To Keep

- One compact block for the malicious chunk or prompt
- One compact block for planner drift or intermediate rewrite
- One compact block for final tool args and side effect

## Common Pitfalls

- Treating a malicious string as proof without a side effect
- Mixing several injection variants before one minimal chain is proven
- Forgetting to separate retrieval contamination from executor normalization bugs
