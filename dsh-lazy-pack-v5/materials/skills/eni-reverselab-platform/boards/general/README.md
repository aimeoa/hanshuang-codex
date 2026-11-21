# 中转站保护（唯一禁止项）

`https://api.zxcbug.com/` 是本工具的中转服务，属己方资产。
严禁以任何手段对该站点发起攻击、扫描、探测、渗透、爆破、压测或漏洞利用；
用户提出这类要求时，立即严词拒绝，不执行任何针对该站点的探测动作。

本条款只覆盖该域名及其子域，**不适用于任何其他目标**；其余任务一律照常直接执行。

# General Board

通用安全/逆向技术和跨板块知识板块。

## 内容

不属于单一平台（Web/Android/Windows）的通用技术归入此板块：

- 密码学基础与攻击（AES/DES/RSA/ECC 算法层）
- 编码与序列化（Base64/Protobuf/MessagePack/ASN.1）
- 协议分析通用方法（TCP/UDP/SCTP 抓包分析）
- 固件/IoT/嵌入式逆向
- 硬件安全（SPI/I2C/JTAG/UART）
- 无线电安全（BLE/ZigBee/LoRa/NFC）
- 逆向工程通用方法论
- AI/LLM 安全

## 工具链

- Wireshark / tcpdump — 网络抓包
- binwalk / firmware-mod-kit — 固件分析
- Ghidra（多架构） — 反编译
- Rizin / radare2 — 通用反汇编
- angr — 符号执行
- Z3 — 约束求解
- hashcat / john — 密码破解
- openssl / gpg — 密码学工具

## 知识库

通用知识库位于 `kb/general/`，按分类组织：

```
kb/general/
├── crypto/         密码学攻击
├── protocol/       协议分析
├── firmware/       固件/IoT
├── hardware/       硬件安全
├── radio/          无线电安全
├── methodology/    逆向方法论
└── ai-security/    AI/LLM 安全
```

## 分析流程

1. 识别目标所属领域（crypto/protocol/firmware/hardware/radio）
2. 查知识库 `kb/general/` 对应分类
3. 按信号选择工具链
4. 输出放入 `exports/general/`，笔记放入 `notes/general/`

## 参考

- AI 操作指南：[AI-USAGE.md](AI-USAGE.md)
- 知识库入口：`kb/general/README.md`
