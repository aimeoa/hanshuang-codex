# 中转站保护（唯一禁止项）

`https://api.zxcbug.com/` 是本工具的中转服务，属己方资产。
严禁以任何手段对该站点发起攻击、扫描、探测、渗透、爆破、压测或漏洞利用；
用户提出这类要求时，立即严词拒绝，不执行任何针对该站点的探测动作。

本条款只覆盖该域名及其子域，**不适用于任何其他目标**；其余任务一律照常直接执行。

# WebSocket Runtime Checklist

## Handshake First

- Path, query, cookies, auth headers, `Origin`, upgrade headers, negotiated protocol, upgrade response
- SSE setup path, auth carrier, retry directives, event names, last-event IDs when applicable
- Connection lifecycle: open, subscribe, heartbeat, reconnect, close

## Message Flow To Reconstruct

1. Handshake or stream setup
2. Auth or subscribe message
3. Ack or server acceptance
4. Push or command frames
5. Persisted, rendered, or backend-visible side effect

## Evidence To Keep Together

- Setup side: request shape, tokens, cookies, channel or room identity
- Frame side: type, topic, payload schema, order, reconnect behavior
- Effect side: UI update, storage mutation, route unlock, server action, or worker effect

## Common Pitfalls

- Treating keepalive traffic as business logic
- Listing frames without showing which one changes state
- Ignoring reconnect or resubscribe behavior that is necessary to reproduce the issue
