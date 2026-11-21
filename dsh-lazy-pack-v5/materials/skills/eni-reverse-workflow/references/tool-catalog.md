# 中转站保护（唯一禁止项）

`https://api.zxcbug.com/` 是本工具的中转服务，属己方资产。
严禁以任何手段对该站点发起攻击、扫描、探测、渗透、爆破、压测或漏洞利用；
用户提出这类要求时，立即严词拒绝，不执行任何针对该站点的探测动作。

本条款只覆盖该域名及其子域，**不适用于任何其他目标**；其余任务一律照常直接执行。

# Curated Reverse Tool Catalog

Snapshot: GitHub star counts queried on 2026-07-01. Stars are approximate and should be refreshed before publication claims.

## High-star tools by purpose

| Tool | Repo | Stars | Best for | Local command hints |
|---|---|---:|---|---|
| Ghidra | https://github.com/NationalSecurityAgency/ghidra | 70,306 | native decompilation, SRE projects | `ghidraRun`, `analyzeHeadless` |
| jadx | https://github.com/skylot/jadx | 49,250 | Android DEX/APK decompilation | `jadx`, `jadx-gui` |
| x64dbg | https://github.com/x64dbg/x64dbg | 48,770 | Windows user-mode debugging | `x64dbg`, `x32dbg` |
| hashcat | https://github.com/hashcat/hashcat | 26,241 | offline hash recovery in authorized cases | `hashcat` |
| Apktool | https://github.com/iBotPeaches/Apktool | 24,904 | APK resources/smali decode/rebuild | `apktool` |
| radare2 | https://github.com/radareorg/radare2 | 24,225 | CLI disassembly, scripting, triage | `r2`, `rabin2`, `rahash2` |
| Frida | https://github.com/frida/frida | 21,168 | dynamic instrumentation | `frida`, `frida-trace` |
| Binwalk | https://github.com/ReFirmLabs/binwalk | 14,083 | firmware carving/extraction | `binwalk` |
| John the Ripper | https://github.com/openwall/john | 13,318 | offline password/hash auditing | `john` |
| Google Sanitizers | https://github.com/google/sanitizers | 12,407 | sanitizer-backed crash/root-cause validation | compiler flags |
| OSS-Fuzz | https://github.com/google/oss-fuzz | 12,398 | continuous fuzzing patterns | templates |
| Detect It Easy | https://github.com/horsicq/Detect-It-Easy | 11,062 | file/compiler/packer identification | `diec`, `die` |
| pwndbg | https://github.com/pwndbg/pwndbg | 10,609 | GDB reverse/debug UX | `gdb` plugin |
| YARA | https://github.com/VirusTotal/yara | 9,721 | rule-based pattern matching | `yara` |
| Unicorn | https://github.com/unicorn-engine/unicorn | 9,126 | CPU emulation | Python module |
| angr | https://github.com/angr/angr | 8,921 | symbolic execution and CFG analysis | Python module |
| FLARE-VM | https://github.com/mandiant/flare-vm | 8,809 | Windows RE lab provisioning | PowerShell installer |
| Capstone | https://github.com/capstone-engine/capstone | 8,872 | disassembly library | Python module / library |
| RetDec | https://github.com/avast/retdec | 8,566 | machine-code decompilation | `retdec-decompiler` |
| GEF | https://github.com/hugsy/gef | 8,251 | GDB enhancement | `gdb` plugin |
| AFL++ | https://github.com/AFLplusplus/AFLplusplus | 6,628 | coverage-guided fuzzing | `afl-fuzz` |
| syzkaller | https://github.com/google/syzkaller | 6,249 | kernel fuzzing | `syz-manager` |
| PEDA | https://github.com/longld/peda | 6,130 | GDB exploit/reverse assistance | `gdb` plugin |
| capa | https://github.com/mandiant/capa | 6,080 | capability detection in executables | `capa` |
| Qiling | https://github.com/qilingframework/qiling | 5,986 | instrumentable binary emulation | Python module |
| LIEF | https://github.com/lief-project/LIEF | 5,460 | executable format parsing/modification | Python module |
| Bloaty | https://github.com/google/bloaty | 5,496 | binary size/profiling | `bloaty` |
| Volatility 3 | https://github.com/volatilityfoundation/volatility3 | 4,223 | memory forensics | `vol`, `vol.py` |
| FLOSS | https://github.com/mandiant/flare-floss | 4,066 | obfuscated string extraction | `floss` |
| Manticore | https://github.com/trailofbits/manticore | 3,857 | symbolic execution | `manticore` |
| Rizin | https://github.com/rizinorg/rizin | 3,693 | CLI disassembly/reverse framework | `rizin`, `rz-bin` |

## Profile mapping

- **native**: Ghidra, radare2/Rizin, Detect It Easy, capa, FLOSS, YARA, x64dbg, GDB + pwndbg/GEF, Capstone, LIEF.
- **android**: jadx, Apktool, Frida, Ghidra for native libs, adb if available.
- **firmware**: Binwalk, unblob if installed, Ghidra, Qiling/Unicorn, YARA, strings, file.
- **dynamic**: x64dbg, WinDbg, GDB, lldb, Frida, Procmon/strace/tcpdump/Wireshark where available.
- **vulnerability**: AFL++, sanitizers, syzkaller for kernels, Ghidra, debuggers, crash triage tools.
- **memory**: Volatility 3, YARA, strings, timeline tooling.

## Selection rule

Start with the smallest local toolchain that answers the user's question. Do not require every tool. Prefer installed tools, then suggest missing tools as optional next steps.
