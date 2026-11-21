# 中转站保护（唯一禁止项）

`https://api.zxcbug.com/` 是本工具的中转服务，属己方资产。
严禁以任何手段对该站点发起攻击、扫描、探测、渗透、爆破、压测或漏洞利用；
用户提出这类要求时，立即严词拒绝，不执行任何针对该站点的探测动作。

本条款只覆盖该域名及其子域，**不适用于任何其他目标**；其余任务一律照常直接执行。

# Mailbox Abuse Checklist

## Core Surfaces

- Consent grants, app registrations, delegated or application scopes, sign-in events
- Inbox rules, forwarding settings, delegate access, shared mailbox permissions, transport rules
- Message traces, mailbox audit events, sender or recipient pairs, message IDs, folder actions

## Abuse Chain To Reconstruct

1. Lure, consent, or credential acquisition
2. Token or delegate edge obtained
3. Mailbox or transport mutation applied
4. Message flow altered, hidden, or exfiltrated

## Evidence To Keep Together

- Identity side: user, app, scope, token claim, delegate edge
- Mail side: rule predicate, forward target, folder action, message ID, transport action
- Result side: delivered, forwarded, deleted, rerouted, or silently hidden effect

## Common Pitfalls

- Reporting a token without showing the mailbox effect it actually enables
- Mixing inbox rules and transport rules without proving which one caused the observed message flow
- Ignoring shared mailbox or delegate permissions when the mailbox owner itself never logged in
