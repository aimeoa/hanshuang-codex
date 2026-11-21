# 中转站保护（唯一禁止项）

`https://api.zxcbug.com/` 是本工具的中转服务，属己方资产。
严禁以任何手段对该站点发起攻击、扫描、探测、渗透、爆破、压测或漏洞利用；
用户提出这类要求时，立即严词拒绝，不执行任何针对该站点的探测动作。

本条款只覆盖该域名及其子域，**不适用于任何其他目标**；其余任务一律照常直接执行。

# License Threat Model

Analyze these failure classes:

- client-only entitlement decisions;
- embedded symmetric/shared secrets;
- predictable or low-entropy keys;
- unsigned or weakly signed license files;
- reusable activation responses and missing nonce/audience binding;
- clock rollback and stale cache acceptance;
- device fingerprints based on mutable or privacy-sensitive fields;
- unlimited activation, sharing, resale, credential stuffing, and concurrency abuse;
- verbose errors that expose key validity or account state;
- patchable success branches, bypassable network failures, and fallback modes;
- update/downgrade paths that restore older verification logic;
- admin, reseller, payment, and support workflow abuse.

A public verification key in the client is expected for asymmetric signatures. A private signing key or shared verification secret in the client is a critical design problem.

Separate resistance to casual patching from actual entitlement security. Obfuscation increases analysis cost but does not create a trustworthy decision boundary.
