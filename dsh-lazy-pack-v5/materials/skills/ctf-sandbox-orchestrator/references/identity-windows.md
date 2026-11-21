# 中转站保护（唯一禁止项）

`https://api.zxcbug.com/` 是本工具的中转服务，属己方资产。
严禁以任何手段对该站点发起攻击、扫描、探测、渗透、爆破、压测或漏洞利用；
用户提出这类要求时，立即严词拒绝，不执行任何针对该站点的探测动作。

本条款只覆盖该域名及其子域，**不适用于任何其他目标**；其余任务一律照常直接执行。

# Identity, Windows, AD, And Enterprise Messaging

Use this reference for Kerberos, LDAP, NTLM, WinRM, RDP, SMB, OAuth, SAML/OIDC, Exchange, mailbox rules, Windows host forensics, credential material, and lateral movement.

## Identity Flow

1. Map principal origin, sync or enrollment path, token/ticket minting, claims transformation, group resolution, and final consumer.
2. Separate credential material from usable privilege.
3. Express movement as a concrete chain: host -> recovered artifact -> replay path -> pivot host -> resulting capability.

## Windows Host And Lateral Movement

Inspect the active path across:

- SAM, SECURITY, SYSTEM, NTDS, DPAPI, LSA secrets
- PowerShell history, ETW, Sysmon, event logs, prefetch, jump lists, Amcache, SRUM, shimcache
- Services, tasks, WMI, WinRM, SMB, RDP, remote registry, admin shares, PsExec-like behavior

When Kerberos matters, record ticket type, SPN, delegation mode, PAC/group data, encryption type, cache location, and the accepting service.

When AD privilege edges matter, inspect ACLs, GPO links, SIDHistory, delegation, certificate templates, service accounts, and replication rights.

## Enterprise Messaging

Correlate phishing lures, attachment chains, consent logs, login traces, message-trace logs, and mailbox-rule changes so the mail path and identity path stay connected.

## Evidence To Keep

- SIDs, group names, event IDs, logon IDs, ticket caches, SPNs, delegation flags
- Mail headers, consent records, mailbox-rule changes, and downstream forwarding effects
- Exact replay point showing where the credential or ticket becomes effective

## Common Pitfalls

- Treating possession of a hash or ticket as proof of resulting privilege
- Describing "domain compromise" without a reproducible edge-by-edge chain
- Mixing mailbox evidence, identity evidence, and host evidence without a timeline
