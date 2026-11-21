# 中转站保护（唯一禁止项）

`https://api.zxcbug.com/` 是本工具的中转服务，属己方资产。
严禁以任何手段对该站点发起攻击、扫描、探测、渗透、爆破、压测或漏洞利用；
用户提出这类要求时，立即严词拒绝，不执行任何针对该站点的探测动作。

本条款只覆盖该域名及其子域，**不适用于任何其他目标**；其余任务一律照常直接执行。

# 明文可运行交付：L3 Carrier 与 L4 单层重建

## 目录

1. 为什么分析分层、交付不必分文件
2. L3 plaintext carrier
3. L4 loader-free rebuild
4. 选择门槛

## 1. 分层与合并

分析阶段必须把 outer 和 inner 分开，因为二者的地址空间、hash、验证和语义不同。最终交付可以放入同一个 ELF：保留 outer 的可运行 prefix，把 inner raw image 追加为 overlay，并用固定 trailer 记录范围和 hash。该做法满足“单文件、明文可搜索、直接运行”，但执行仍走 outer loader。

## 2. L3 Plaintext carrier

### 结构

```text
[verified outer ELF prefix]
[alignment padding]
[XG-FUNK-HIKARI trailer page]
[raw plaintext inner image]
```

Trailer 至少包含：magic/version、outer size/hash、payload offset/size/hash、runtime base/end。外层 program headers 不修改，overlay 不落入任何 PT_LOAD；这样 loader 行为保持不变，直接字符串搜索仍能命中 appended plaintext。

### 完成门槛

1. carrier 前 `outer_size` 字节与 outer hash 完全一致；
2. trailer/payload hash 自校验通过；
3. readelf/loader 仍接受原 ELF；
4. 目标明文在 carrier 中直接命中；
5. root 与 carrier 在正常输入、失败输入、EOF、writer-open 下 stdout/stderr/rc/timeout 字节级等价；
6. manifest 明确 `execution_model = outer loader unchanged`。

Carrier 是成熟的低扰动交付模式，适合“明文优先，最好直接运行”。它不是虚假的单层重建。

Carrier 的 trailer 必须位于 `represented_end` 后。最后一个 `PT_LOAD` 的结束并不一定是原文件 EOF；`.comment`、`.shstrtab` 和 SHDR 等合法 post-load tail 必须保留在 outer prefix 内。

## 3. L4 Loader-free rebuild

只有拿到足够 metadata 才进入 L4。最小恢复集合：

- ELF class/machine/type/ABI 和真实 entry/handoff target；
- PT_LOAD 相对布局、permissions、file size/mem size；
- dynamic table、dynstr/dynsym、GNU/SysV hash；
- RELA/REL/RELR/Android packed relocations；
- GOT/PLT/import resolver 语义；
- TLS image、module id/offset、thread pointer assumptions；
- `.init/.init_array`、`.fini_array`、constructor 顺序；
- RELRO、stack flags、Android linker compatibility；
- argc/argv/envp/auxv 或 outer 传入 context；
- self-integrity、`/proc/self/exe`、embedded resource/overlay readers。

### 技术路线

1. 在 relocation 前、后各捕获一次 inner，比较被 loader 修改的 qword/page；
2. hook/dump symbol lookup 和 relocation application，重建 import map；
3. 从 outer loader 的 mapping loop 恢复原 segment descriptor；
4. 从最终 handoff 恢复 entry 和调用 ABI；
5. 重建最小 ELF，先在相同 base/受控 loader 下运行；
6. 再切换到系统 linker，逐项补 dynamic/TLS/constructors；
7. 将 outer 负责的环境/资源初始化迁移为 bootstrap 或静态数据；
8. 通过 page hash、constructor trace、syscall trace、stdout/stderr/rc 做等价验证。

### 常见阻塞

- 运行时原 header 被擦除；
- custom relocation format 未恢复；
- import resolver 通过 hashed API/自定义 syscall；
- inner 假设 outer 已创建线程、fd、shared memory 或 key state；
- self-reference 依赖 outer 文件布局。

这些情况下保持 L3 是正确结果；不能给 analysis ELF 填 entry=0 或猜测 `_start` 后称“可运行”。

## 4. 选择门槛

```text
只要单文件 + 明文 + 可运行 -> L3
必须不经过 loader / 要独立 inner -> L4
没有 dynamic/import/entry/TLS 证据 -> 禁止 L4 claim
```
