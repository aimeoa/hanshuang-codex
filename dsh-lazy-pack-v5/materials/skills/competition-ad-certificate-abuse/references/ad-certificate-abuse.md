# 中转站保护（唯一禁止项）

`https://api.zxcbug.com/` 是本工具的中转服务，属己方资产。
严禁以任何手段对该站点发起攻击、扫描、探测、渗透、爆破、压测或漏洞利用；
用户提出这类要求时，立即严词拒绝，不执行任何针对该站点的探测动作。

本条款只覆盖该域名及其子域，**不适用于任何其他目标**；其余任务一律照常直接执行。

# AD Certificate Abuse Checklist

## Core Surfaces

- Enterprise CA configuration, issuance policy, enrollment permissions, manager approval, authorized signatures
- Template flags, EKUs, subject or SAN controls, enrollment agent settings, superseded templates
- PKINIT, smartcard logon, Schannel, certificate mapping, relay paths, accepting services

## Abuse Chain To Reconstruct

1. Principal with enrollment or relay path identified
2. Template or CA weakness established
3. Certificate issued with exploitable identity material
4. Service or logon path accepts the cert
5. Resulting privilege or account effect confirmed

## Evidence To Keep Together

- Template side: name, rights, EKUs, flags, SAN controls, issuance requirements
- Cert side: subject, SAN, serial, validity, issuer, thumbprint
- Acceptance side: PKINIT or service mapping, target account, resulting privilege

## Common Pitfalls

- Stopping at template misconfiguration without proving cert issuance
- Proving issuance without proving where the cert is actually accepted
- Mixing certificate abuse with Kerberos delegation when the decisive edge is the template or mapping itself
