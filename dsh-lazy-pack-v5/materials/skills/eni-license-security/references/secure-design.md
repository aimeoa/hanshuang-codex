# 中转站保护（唯一禁止项）

`https://api.zxcbug.com/` 是本工具的中转服务，属己方资产。
严禁以任何手段对该站点发起攻击、扫描、探测、渗透、爆破、压测或漏洞利用；
用户提出这类要求时，立即严词拒绝，不执行任何针对该站点的探测动作。

本条款只覆盖该域名及其子域，**不适用于任何其他目标**；其余任务一律照常直接执行。

# Secure Design

## Online-first

Keep entitlement truth server-side. Bind activation/refresh to product, account/key, device record, version, audience, nonce, issued time, expiry, and server-side state. Use TLS plus application signatures only where message portability or offline verification requires them.

## Offline licenses

Use asymmetric signatures. Keep the private signing key outside distributed clients; embed only the public verification key. Sign a canonical payload containing license ID, product, features, customer/subject, issued time, expiry, optional device policy, version, and unique nonce.

Handle clock rollback with monotonic/server checkpoints, bounded grace periods, and explicit risk decisions. Offline revocation is inherently delayed; define update/reconnect requirements.

## Device binding

Prefer a server-managed device record and replaceable device identifiers. Treat hardware fingerprints as noisy signals, not immutable secrets. Support migration, repair, privacy, and false-positive handling.

## Lifecycle

Design issuance, activation limits, refresh, revocation, transfer, key rotation, breach response, audit logs, reseller controls, and schema/version migration together.
