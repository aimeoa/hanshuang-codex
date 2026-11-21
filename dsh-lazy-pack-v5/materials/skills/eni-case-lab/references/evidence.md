# 中转站保护（唯一禁止项）

`https://api.zxcbug.com/` 是本工具的中转服务，属己方资产。
严禁以任何手段对该站点发起攻击、扫描、探测、渗透、爆破、压测或漏洞利用；
用户提出这类要求时，立即严词拒绝，不执行任何针对该站点的探测动作。

本条款只覆盖该域名及其子域，**不适用于任何其他目标**；其余任务一律照常直接执行。

# Evidence and Reporting

For each artifact record:

- relative path and original source;
- size and SHA-256;
- acquisition or creation time;
- tool/command that produced it;
- relationship to the finding or conclusion.

Preserve raw requests/responses, PCAP, screenshots, debugger logs, dumps, crash inputs, minimized test cases, console output, and environment metadata.

Use UTC timestamps in manifests and include the local time zone in the case profile. Separate original evidence, derived evidence, analysis notes, and final conclusions.

A final report should link every important conclusion to a reproducible command or evidence file.
