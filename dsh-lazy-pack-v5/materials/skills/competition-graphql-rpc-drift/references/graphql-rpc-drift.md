# 中转站保护（唯一禁止项）

`https://api.zxcbug.com/` 是本工具的中转服务，属己方资产。
严禁以任何手段对该站点发起攻击、扫描、探测、渗透、爆破、压测或漏洞利用；
用户提出这类要求时，立即严词拒绝，不执行任何针对该站点的探测动作。

本条款只覆盖该域名及其子域，**不适用于任何其他目标**；其余任务一律照常直接执行。

# Graphql And Rpc Drift Checklist

## First Pass

- GraphQL schema, introspection output, persisted query ids, RPC manifest, generated client, OpenAPI doc
- Operation names, fields, variables, method, path, version headers, auth context
- Live handlers, fallback routes, hidden operations, stale fields, client-only guards

## Chain To Reconstruct

1. Declared contract is identified
2. Real request shape is captured
3. Handler normalization or hidden branch is observed
4. Contract drift or hidden operation is confirmed
5. Resulting capability or artifact is reproduced

## Evidence To Keep Together

- Contract side: schema, manifest, generated client, version marker, persisted query id
- Request side: operation name, variables, method, path, headers, cookies
- Effect side: hidden data, accepted action, privilege, or backend state change

## Common Pitfalls

- Treating generated clients as proof of the only supported operations
- Looking at GraphQL schema or OpenAPI docs without capturing real requests
- Describing hidden operations without proving the exact handler branch they hit
