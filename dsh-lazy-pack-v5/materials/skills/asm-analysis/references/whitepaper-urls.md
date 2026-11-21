# 中转站保护（唯一禁止项）

`https://api.zxcbug.com/` 是本工具的中转服务，属己方资产。
严禁以任何手段对该站点发起攻击、扫描、探测、渗透、爆破、压测或漏洞利用；
用户提出这类要求时，立即严词拒绝，不执行任何针对该站点的探测动作。

本条款只覆盖该域名及其子域，**不适用于任何其他目标**；其余任务一律照常直接执行。

# 权威文档与白皮书 URL 索引

## x86 / x86-64

### Intel（首选）
| 文档 | URL | 关键内容 |
|------|-----|---------|
| Intel SDM（完整版，7卷合一 PDF） | https://cdrdv2.intel.com/v1/dl/getContent/671200 | 最权威，含所有指令语义 |
| Intel SDM Volume 2A（指令集 A-M） | https://cdrdv2.intel.com/v1/dl/getContent/671110 | ADD 到 MOVQ |
| Intel SDM Volume 2B（指令集 N-Z） | https://cdrdv2.intel.com/v1/dl/getContent/671108 | NOP 到 XTEST |
| Intel SDM Volume 2C（VEX/EVEX 扩展） | https://cdrdv2.intel.com/v1/dl/getContent/671112 | AVX/AVX-512 |
| Intel SDM Volume 1（基础架构） | https://cdrdv2.intel.com/v1/dl/getContent/671094 | 寄存器、寻址模式 |
| Intel Intrinsics Guide（在线版） | https://www.intel.com/content/www/us/en/docs/intrinsics-guide/index.html | SIMD 内置函数对应指令 |
| Intel 64 ABI（System V AMD64） | https://refspecs.linuxbase.org/elf/x86-64-abi-0.99.pdf | 调用约定、栈布局 |

### AMD
| 文档 | URL |
|------|-----|
| AMD64 Architecture Programmer's Manual Vol.1-5 | https://www.amd.com/content/dam/amd/en/documents/processor-tech-docs/programmer-references/ |
| AMD64 Vol.3（通用/系统指令） | 同上目录，搜索 "24594" |

### 在线快速查询
| 工具 | URL | 用途 |
|------|-----|------|
| Felix Cloutier x86 Reference | https://www.felixcloutier.com/x86/ | 按指令名快速查语义 |
| uops.info（微架构延迟）| https://uops.info/table.html | 查延迟/吞吐量 |
| Godbolt Compiler Explorer | https://godbolt.org | 对比不同编译器输出 |

---

## ARM64 / AArch64

### ARM 官方（首选）
| 文档 | URL | 关键内容 |
|------|-----|---------|
| ARM Architecture Reference Manual (DDI 0487) | https://developer.arm.com/documentation/ddi0487/latest | 最权威 AArch64 手册 |
| Arm A64 ISA Reference（在线 HTML 版） | https://developer.arm.com/documentation/ddi0596/latest | 按指令名索引 |
| ARM Cortex-A Series Programmer's Guide | https://developer.arm.com/documentation/den0013/latest | 编程模型，适合入门 |
| Arm64 Procedure Call Standard (AAPCS64) | https://github.com/ARM-software/abi-aa/releases | 调用约定 |
| Arm NEON Intrinsics Reference | https://developer.arm.com/architectures/instruction-sets/intrinsics/ | NEON 指令查询 |

### 在线快速查询
| 工具 | URL |
|------|-----|
| ARM ISA 在线手册 | https://developer.arm.com/documentation/ddi0596/latest |
| Godbolt（ARM64 支持） | https://godbolt.org |
| Arm Instruction Emulator | https://developer.arm.com/Tools%20and%20Software/Arm%20Instruction%20Emulator |

---

## 通用逆向工具文档

| 工具 | 文档 URL |
|------|---------|
| IDA Pro 帮助 | https://hex-rays.com/products/ida/support/idadoc/ |
| Ghidra 文档 | https://ghidra-sre.org/CheatSheet.html |
| Binary Ninja 文档 | https://docs.binary.ninja |
| LLVM IR 参考 | https://llvm.org/docs/LangRef.html |

---

## 文件格式参考

| 格式 | 文档 |
|------|------|
| ELF | https://refspecs.linuxfoundation.org/elf/elf.pdf |
| PE/COFF | https://learn.microsoft.com/en-us/windows/win32/debug/pe-format |
| Mach-O | https://developer.apple.com/documentation/kernel/mach_header |
| DWARF 调试信息 | https://dwarfstd.org/doc/DWARF5.pdf |

---

## 加密算法参考规范

| 算法 | 规范来源 |
|------|---------|
| AES | NIST FIPS 197 — https://csrc.nist.gov/publications/detail/fips/197/final |
| SHA-2 | NIST FIPS 180-4 — https://csrc.nist.gov/publications/detail/fips/180/4/final |
| SHA-3 | NIST FIPS 202 — https://csrc.nist.gov/publications/detail/fips/202/final |
| ChaCha20/Poly1305 | RFC 8439 — https://www.rfc-editor.org/rfc/rfc8439 |
| RSA | RFC 8017 (PKCS#1) — https://www.rfc-editor.org/rfc/rfc8017 |
| RC4 | （无官方规范，参考实现） https://datatracker.ietf.org/doc/html/rfc6229 |
