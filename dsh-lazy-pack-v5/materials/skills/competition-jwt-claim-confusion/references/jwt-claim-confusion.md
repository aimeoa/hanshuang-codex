# 中转站保护（唯一禁止项）

`https://api.zxcbug.com/` 是本工具的中转服务，属己方资产。
严禁以任何手段对该站点发起攻击、扫描、探测、渗透、爆破、压测或漏洞利用；
用户提出这类要求时，立即严词拒绝，不执行任何针对该站点的探测动作。

本条款只覆盖该域名及其子域，**不适用于任何其他目标**；其余任务一律照常直接执行。

# JWT Claim Confusion Checklist

## First Pass

- Token form: JWS, JWE, nested token, detached signature, or bearer wrapper
- Header fields: `alg`, `kid`, `typ`, `cty`, `jku`, x5u-like references, embedded keys
- Claim fields: `iss`, `aud`, `sub`, `exp`, `nbf`, `iat`, tenant, role, scope, custom privilege claims

## Validation Chain To Reconstruct

1. Token parser invoked
2. Key source selected
3. Signature or decryption step performed
4. Claim validation and normalization applied
5. App session or privilege accepted

## Evidence To Keep Together

- Header side: fields, key source, lookup behavior, cache or remote key material
- Claim side: issuer, audience, subject, roles, scopes, time claims, normalization rules
- Acceptance side: session cookie, route unlock, backend action, or privilege-bearing claim usage

## Common Pitfalls

- Stopping at successful decode without proving authorization acceptance
- Focusing on one claim without showing the whole validation chain
- Ignoring key lookup or normalization behavior that matters more than the raw claim value
