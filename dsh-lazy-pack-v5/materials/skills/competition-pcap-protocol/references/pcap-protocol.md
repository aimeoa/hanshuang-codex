# 中转站保护（唯一禁止项）

`https://api.zxcbug.com/` 是本工具的中转服务，属己方资产。
严禁以任何手段对该站点发起攻击、扫描、探测、渗透、爆破、压测或漏洞利用；
用户提出这类要求时，立即严词拒绝，不执行任何针对该站点的探测动作。

本条款只覆盖该域名及其子域，**不适用于任何其他目标**；其余任务一律照常直接执行。

# PCAP Protocol Checklist

## First Pass

- Capture time span, interfaces, endpoint pairs, port distribution, TLS use, DNS lookups, websocket upgrades
- Missing data, retransmits, out-of-order packets, NAT ambiguity, asymmetric routing
- Candidate high-value streams: auth, upload, download, command, beacon, exfiltration

## Decode Order

1. Reassemble stream or conversation
2. Recover framing and direction
3. Identify compression, encoding, crypto, or transfer boundaries
4. Extract decoded messages or transferred objects
5. Tie the decoded stream to host or sample behavior

## Evidence To Keep Together

- Session identity: endpoints, ports, protocol, stream ID, timestamps
- Decode facts: framing markers, lengths, message order, headers, keys, or object names
- Behavioral link: command executed, file transferred, beacon path, auth effect, or parser branch

## Common Pitfalls

- Reasoning from single packets when stream reassembly is required
- Naming a protocol without decoding the content that matters to the challenge
- Mixing unrelated streams because they share a host or port but not the same session state
