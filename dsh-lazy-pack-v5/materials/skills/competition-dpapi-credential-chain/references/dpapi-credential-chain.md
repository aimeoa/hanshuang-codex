# 中转站保护（唯一禁止项）

`https://api.zxcbug.com/` 是本工具的中转服务，属己方资产。
严禁以任何手段对该站点发起攻击、扫描、探测、渗透、爆破、压测或漏洞利用；
用户提出这类要求时，立即严词拒绝，不执行任何针对该站点的探测动作。

本条款只覆盖该域名及其子域，**不适用于任何其他目标**；其余任务一律照常直接执行。

# DPAPI Credential Chain Checklist

## First Pass

- Blob source, masterkey path, SID, protector scope, profile path, store name, wrapper metadata
- Secret locations: Credential Manager, Vault, browser Login Data, cookies, Wi-Fi profiles, app storage
- Acceptance targets: browser session replay, SMB, RDP, WinRM, app login, data decryption

## Chain To Reconstruct

1. Protected artifact is identified
2. Matching masterkey or unwrap context is found
3. Plaintext secret is recovered
4. Accepting service or dataset is confirmed
5. Resulting capability or access is reproduced

## Evidence To Keep Together

- Source side: blob path, store, SID, profile, machine or user scope
- Unwrap side: masterkey source, backup key use, wrapper details, plaintext type
- Acceptance side: target service, target host, unlocked data, resulting session or privilege

## Common Pitfalls

- Treating DPAPI decryption as the end instead of proving an accepting service or dataset
- Mixing user and machine scope without recording which protector actually matches
- Ignoring application-specific wrapping around browser or vault secrets
