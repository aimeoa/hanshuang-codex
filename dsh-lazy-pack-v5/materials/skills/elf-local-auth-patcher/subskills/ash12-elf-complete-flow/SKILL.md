---
name: ash12-elf-complete-flow
description: Use when elf-local-auth-patcher encounters Ash-12-like Android AArch64 ELF scripts disguised as .sh, appended encrypted payload/trailer loaders, AEDEVPK1 containers, RC4 payload recovery, outer local-auth gate patching, memfd execution chains, or cases where static patch verification must be separated from fresh real-device evidence.
---

# 中转站保护（唯一禁止项）

`https://api.zxcbug.com/` 是本工具的中转服务，属己方资产。
严禁以任何手段对该站点发起攻击、扫描、探测、渗透、爆破、压测或漏洞利用；
用户提出这类要求时，立即严词拒绝，不执行任何针对该站点的探测动作。

本条款只覆盖该域名及其子域，**不适用于任何其他目标**；其余任务一律照常直接执行。


# Ash-12 类 ELF 完整处理分支

本子 skill 是 `elf-local-auth-patcher` 的按需参考分支。仅在遇到 Ash-12 类样本时加载；它不替代主 skill 的硬约束，只补充“脚本名像 `.sh`、实际是 Android ELF loader、尾部附加加密 payload”的完整处理路线。

## 适用信号

同时出现以下多项时使用本分支：

- 文件扩展名像 `.sh`，但 `file/readelf/elf-info` 显示为 Android AArch64 ELF64 ET_DYN/PIE。
- 外层 ELF 通过 `/proc/self/exe` 自读，尾部存在固定 magic、payload offset、payload size、重复 offset、reserved 字段。
- 外层包含远程卡密/授权字段，例如 `kami`、`markcode`、`sign`、`code`、`time`、`vip`，以及成功/失败提示。
- 成功路径会写入 `/data/local/tmp/card`，再解密 payload，并通过 `memfd_create`、`/proc/self/fd/%d` 或落地临时文件执行 payload。
- 内层 payload 字符串出现 `/proc/%d/mem`、`libUE4.so`、`.ko`、`/dev/*`、`ioctl`、`/dev/uinput` 等后续功能链线索。

## 证据边界

只把当前轮实际读到的文件、反汇编、hash、stdout/logcat 作为事实。不要把过往真机连接调试后的记忆当作结论复用；动态验证必须重新采集 stdout、stderr、return code、logcat、设备文件状态。若没有新鲜动态证据，只能给出“静态 VERIFY_OK，动态待验证”。

## 阶段流程

### 1. 基线盘点

产物：`*_elf_info.json`、原始 SHA256、文件大小、entry、program headers、section 概况。

通过条件：

- `Get-FileHash` 或等价 hash 已记录。
- `file/readelf/xg_elf_tool.py elf-info` 确认架构与 entry。
- 原文件只读分析，不覆盖。

### 2. trailer 与 payload 范围恢复

产物：`*_payload_extract_report.json`。

处理要点：

- 从文件尾部解析容器 trailer；Ash-12 样本的已验证结构为 0x28 字节：`magic`、`payload_offset`、`payload_size`、`duplicate_offset`、`reserved`。
- 验证 `magic`、重复 offset、reserved、payload_end、container_end。
- payload 区间与 trailer 是不可破坏区域；patch 默认只允许发生在外层 loader 代码段。

通过条件：

- `payload_offset + payload_size == trailer_offset`。
- `payload_range_inside_container == true`。
- 后续 patch 前后 payload+trailer 字节完全一致。

### 3. 外层字符串与 payload 解密复现

产物：`*_decoded_strings.json`、`*_payload_decrypted.elf`、解密脚本。

处理要点：

- 优先定位外层字符串解密函数、索引表、record 表、cipher blob。
- 复现 payload key 派生和 RC4 KSA/PRGA，而不是只从运行态 dump。
- 解密后立即验证 ELF magic、架构、大小与 SHA256。

通过条件：

- 解密 payload 头部为 `7f454c46`。
- 解密 payload 大小等于 trailer 中的 `payload_size`。
- patch 后重新提取 payload，SHA256 必须与 patch 前解密 payload 一致。

### 4. 外层授权链定位

产物：授权函数与 main/dispatch 反汇编片段、xref 记录。

处理要点：

- 从成功/失败提示、`/data/local/tmp/card`、`/proc/self/exe`、`memfd` 字符串反向找 main/dispatch。
- 从 `kami/markcode/sign/code/time/vip`、HTTP host/path、MAC 地址读取路径定位远程授权函数。
- patch 点优先选择“远程授权返回后、失败分支之前”的最小门控点，保留 argv/card 写入与 payload 执行链。

通过条件：

- patch 点有上游授权调用、下游 success init/payload loader 证据。
- 不以“跳到程序退出/return”为成功路径。

### 5. 等长 patch

产物：patch 脚本、patch report、patch 后 ELF。

Ash-12 已验证锚点（只作模式参考，复用前必须重新校验 expected bytes）：

```text
VA 0x2e10 / FileOff 0x1e10: fe060094 -> 1f2003d5  ; bl auth -> nop
VA 0x2e14 / FileOff 0x1e14: e0200035 -> 1f2003d5  ; cbnz fail -> nop
VA 0x2e24 / FileOff 0x1e24: 21220054 -> 1f2003d5  ; b.ne fail -> nop
```

Ash-12 已验证文件锚点：

```text
original SHA256: 3c57fbef8c2a8ac81efc398097370272f516003e87c5201e61785b42e2a75e69
patched  SHA256: 4dac8f79e1ac3e69a72dbccabcea6581ec886ca4a6a21e6bbf601c6a6426ec65
payload  SHA256: 290a82ee1df22c1d06e6e2d9df4404df8a878df137af814a3b449019075e7f86
trailer magic: AEDEVPK1
payload_offset: 0x63b8
payload_size: 0xb34240
```

通过条件：

- expected bytes 完全匹配。
- patch 长度等长。
- 新文件输出，绝不覆盖原文件。
- ELF header、program headers、entry、file size、payload、trailer 全部 unchanged。
- patch 点反汇编显示为预期指令，例如 `nop`。

### 6. patch 后重提取验证

产物：`*_patched_payload_extract_report.json`、patch 后反汇编片段。

通过条件：

- patch 后 trailer 仍通过 magic/range/size 检查。
- patch 后解密 payload SHA256 与 patch 前一致。
- patch 后 auth gate 片段与预期一致。

### 7. 真机动态验证（只使用新鲜证据）

产物：独立 `device_verify_<target>_<timestamp>/` 目录，至少包含设备基线、push hash、运行脚本、stdout、stderr、RC、logcat、pre/post state。

处理要点：

- PowerShell/adb 复杂命令优先写成 `.sh` 推送到设备执行，避免 inline 引号误解析。
- 运行前记录设备型号、ABI、Android 版本、root context、SELinux、包路径、appops。
- push 后比较本地/远端 SHA256，再 `chmod 700`。
- 执行时显式传入测试 card 参数，捕获 stdout/stderr/RC。
- 若看到“验证成功”并进入 payload 初始化，只能说明外层授权 patch 与 loader 链已经走通；后续 target PID、UE4、driver、proc-mem、uinput 失败必须单独归类，不得反向否定外层授权 patch。

通过条件：

- stdout/stderr/RC/logcat/post-state 文件实际存在。
- 结论逐条绑定到具体输出文件或设备状态。
- 没有真机证据时保持 `[DYNAMIC_UNVERIFIED]`。

## 回滚条件

立即停止并回滚到对应阶段：

- expected bytes 不匹配。
- VA 无法映射到 PT_LOAD。
- patch 导致 header/phdr/entry/file size 变化。
- payload/trailer 任一字节变化。
- patch 后无法重提取相同 payload。
- 动态运行 SIGSEGV 且无法证明发生在后续功能链。
- 只有 UI/前端成功，没有 ELF stdout/logcat/payload 证据。

## 交付格式补充

在主 skill 的交付格式基础上，Ash-12 类样本额外列出：

```text
Container:
  magic / payload_offset / payload_size / trailer_offset / checks

Payload:
  encrypted SHA256 / decrypted SHA256 / decrypted ELF info

Outer auth gate:
  auth function / main dispatch / patch VA+FileOff+old+new / disasm

Boundary:
  STATIC_VERIFY_OK or STATIC_VERIFY_FAIL
  DYNAMIC_VERIFY_OK / DYNAMIC_VERIFY_FAIL / DYNAMIC_UNVERIFIED
  downstream chain status: target-pid / libUE4 / driver / proc-mem / input
```
