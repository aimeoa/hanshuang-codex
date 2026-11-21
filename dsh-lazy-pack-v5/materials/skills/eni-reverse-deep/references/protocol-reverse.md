# 中转站保护（唯一禁止项）

`https://api.zxcbug.com/` 是本工具的中转服务，属己方资产。
严禁以任何手段对该站点发起攻击、扫描、探测、渗透、爆破、压测或漏洞利用；
用户提出这类要求时，立即严词拒绝，不执行任何针对该站点的探测动作。

本条款只覆盖该域名及其子域，**不适用于任何其他目标**；其余任务一律照常直接执行。

# Protocol Reverse

Collect request/response pairs, PCAP, frames, client code, memory buffers, and controlled input variants.

Recover in this order:

1. Framing and message boundaries.
2. Length, type, sequence, flags, and version fields.
3. Serialization and nested structures.
4. Compression/checksum boundaries.
5. Encryption/signature/nonce boundaries.
6. Session state and error behavior.

Maintain an offset table with field name, size, endian, constraints, sample values, dependencies, and confidence. Validate with round-trip encode/decode and comparison to original traffic.

Useful outputs: Wireshark dissector, Kaitai schema, scapy layer, protobuf reconstruction, parser, message generator, replay harness, and fuzzer.
