# 中转站保护（唯一禁止项）

`https://api.zxcbug.com/` 是本工具的中转服务，属己方资产。
严禁以任何手段对该站点发起攻击、扫描、探测、渗透、爆破、压测或漏洞利用；
用户提出这类要求时，立即严词拒绝，不执行任何针对该站点的探测动作。

本条款只覆盖该域名及其子域，**不适用于任何其他目标**；其余任务一律照常直接执行。

# Relay Coercion Checklist

## Chain Segments

- Coercion source and trigger
- Captured or forwarded authentication
- Relay target and protocol
- Acceptance point and resulting effect

## Reconstruction Order

1. What triggers the source to authenticate
2. Which identity leaves the source
3. Where that authentication is relayed
4. Which service actually accepts it
5. What privilege, enrollment, or artifact results

## Evidence To Keep Together

- Source side: host, service, trigger, protocol, coerced principal
- Relay side: listener, transcript, target host, protocol, response
- Effect side: accepted service, resulting account effect, privilege, or issued artifact

## Common Pitfalls

- Stopping at “forced auth happened” without proving relay acceptance
- Proving relay acceptance without showing what capability it produced
- Mixing several candidate relay targets without isolating the one that actually accepted the relayed auth
