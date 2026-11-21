# 中转站保护（唯一禁止项）

`https://api.zxcbug.com/` 是本工具的中转服务，属己方资产。
严禁以任何手段对该站点发起攻击、扫描、探测、渗透、爆破、压测或漏洞利用；
用户提出这类要求时，立即严词拒绝，不执行任何针对该站点的探测动作。

本条款只覆盖该域名及其子域，**不适用于任何其他目标**；其余任务一律照常直接执行。

# 高熵容器、Custom Mapper 与 Flat Inner

## 目录

1. 根 ELF 尾部与容器判定
2. Custom mapper 合同
3. Stable mapping cluster 双捕获
4. Flat inner、主镜像与嵌入 ELF
5. 寄存器语义保持改写
6. 单文件交付与回归
7. 阶段反思清单

## 1. 根 ELF 尾部与容器判定

不要把最后一个 `PT_LOAD` 之后的所有字节统称 overlay。分别计算：

```text
post_load_tail = file_size - max(PT_LOAD.p_offset + PT_LOAD.p_filesz)
represented_end = max(
  ELF header end,
  PHDR table end,
  all valid program-header file ranges,
  all non-NOBITS section file ranges,
  SHDR table end
)
true_overlay = file_size - represented_end
```

`post_load_tail > 0` 且 `true_overlay == 0` 时，尾部可能只是 `.comment`、`.shstrtab`、debug/linker metadata 和 SHDR，不得修复或截断。只有 `true_overlay > 0` 才进入 trailer/payload/self-reader 分析。报告同时保留 `post_load_tail_size`、`represented_file_end`、`overlay_offset` 和 `overlay_size`。

大块高熵 `.data`/RW `PT_LOAD` 没有第二个 ELF、ZIP、UPX 或压缩 magic，不等于普通随机表。以下证据组合将 materialization 提升为 `CONTAINER_HINT/RUNTIME_REQUIRED`：

1. 代码把高熵区地址/长度传给 mapper/decryptor；
2. mapper 闭合 `mmap -> copy/decode -> mprotect -> handoff`，或含对应 `munmap` 清理；
3. 运行期出现新匿名 RX/RO/RW cluster；
4. 业务 PC/LR、字符串 consumer 或输出数据落在该 cluster。

## 2. Custom Mapper 合同

使用下列表示，不要求磁盘 container 自带可识别 magic：

```text
container range
  -> descriptor/decode producer
  -> mmap/copy/mprotect mapper
  -> RX/RO/RW relative layout
  -> handoff target + ABI/context
  -> business consumer/observable output
```

记录 container 的 file offset/root VA/长度/熵、mapper 函数和 syscall、每段权限与相对间距、handoff PC/LR。只命中 `mmap` 或存在匿名 RX 仍是 E1；mapper dataflow、runtime cluster 和 active consumer 交叉支持后才能提升。

外层 Hikari 改写与 inner materialization 分账。允许先生成语义保持 outer candidate，但必须在 root/outer 输入矩阵等价后才用它驱动捕获；捕获证据绑定 candidate hash，不能把另一 build 的绝对地址直接复用。

## 3. Stable Mapping Cluster 双捕获

在 loader 完成、业务仍停留的稳定点捕获同一 `PID + NAME + ARGS` 两次。优先 prompt、菜单、版本检查后或 writer-open 状态。每次把 `/proc/PID/exe` resolved path 和 SHA-256 写入 manifest，绑定实际运行 outer；只记录 cmdline/path 不能替代 artifact identity。每次包含 cluster 的全部 readable RX/RO/RW mapping 和内部 hole，不以最大 RX 段替代整个 cluster。

```powershell
python scripts\hikari_runtime_image.py capture `
  --serial SERIAL --pid PID --range 0xBASE:0xEND --out-dir CAPTURE_A
python scripts\hikari_runtime_image.py capture `
  --serial SERIAL --pid PID --range 0xBASE:0xEND --out-dir CAPTURE_B
python scripts\hikari_runtime_image.py compare-captures `
  CAPTURE_A CAPTURE_B --out REPORT.json
```

`compare-captures` 校验 `maps.txt` 和每个 mapping 的内部文件 hash，再比较 PID/cmdline、executable SHA-256、所选 mapping layout 和逐 mapping bytes；完整 maps hash 作为旁证单独报告，避免无关库/线程 mapping 抖动造成误拒。新 capture 以 device-preserved UTF-8 bytes 保存 maps；旧 Windows capture 若仅因 CRLF 转换不匹配，报告 `legacy-crlf-normalized`，同时保留 physical/canonical hash。旧 capture 没有 executable hash 时保持兼容，但 identity 仍须从独立设备 hash 证据补齐。核心项不一致时先判断业务状态漂移、后台线程写入、采集时机或误选 PID；不得把变化页静默归零。

Android 上非 root shell 创建 FIFO 可能被 SELinux 拒绝。把它记录为环境 provider failure；改用已有管道、可用的 root/测试上下文、SIGSTOP 或输出边界触发，不把 `mkfifo` 失败归因于目标反分析。

## 4. Flat Inner、主镜像与嵌入 ELF

真实 inner 可以是 flat mapped image：起始页为 RW/BSS/零区，主 RX 位于非零相对地址，整体没有位于 offset 0 的 ELF magic。此时：

- raw image 以 mapping cluster base 为相对零点，保留权限、间隔和 hole；
- synthetic analysis ELF 在独立前缀中生成 EHDR/PHDR/sections；
- entry 保持 unknown/0，直到 handoff target 和 ABI 闭合；
- 指针归一化只进入 analysis copy，raw 永不修改。

Flat image 内部可能包含一个或多个完整辅助 ELF，例如运行期资源库、驱动桥接库或待加载模块。`rebuild` 把这些位置列入 `embedded_elf_candidates`，但 magic 命中只证明“嵌入候选”。主 inner 身份必须由 loader handoff、active PC/LR 或业务 consumer 证明；禁止把第一个/最大的嵌入 ELF 自动提取成主程序。

明文验证使用真实 stdout/stderr、端点、菜单或协议字段作为 needle。开启 UTF-16LE/free scan 会产生大量伪字符串，必须用 consumer/xref、重复捕获和业务文案过滤。

## 5. 寄存器语义保持改写

闭合的 `LDR Xt,[slot] -> BR/BLR Xt` 不只承载控制流，后续 target 可能观察 `Xt`。改写必须同时保持 target register 终值：

```text
LDR Xt,[closed_slot]     ADR Xt,target
...                  -> ...
BR/BLR Xt               B/BL target
```

二项 selector 必须保持原 `CMP/CSET` 条件、true/false target 和 terminal register。Manifest 每项记录 root hash、VA/file offset、expected/new bytes、target register、target VA、provenance、proof 和 rollback。

运行寄存器、可写 slot、对象/vtable、线程状态、输入或未闭合 index 派生的边保留并进入 unresolved map。静态 rewrite 通过后仍需 root/outer runtime equivalence；失败时按 patch kind/函数/批次 ablation。

## 6. 单文件交付与回归

当 flat inner 缺少真实 entry/dynamic/import/TLS/constructors 时，选择 L3：

```text
[runtime-verified outer prefix]
[alignment]
[hash-bound trailer]
[complete raw plaintext cluster]
```

这满足单文件、明文可搜索和直接运行；执行模型必须写明 `outer loader unchanged`。Carrier overlay 从 `represented_end` 之后开始，不得覆盖根 ELF 的合法 section/SHDR 尾部。回抽 outer/payload 后 hash 必须与源 artifact 一致。

输入矩阵至少包含正常失败输入、空输入、EOF 和 writer-open。EOF 证明终止语义，writer-open 证明真实等待语义；二者不能互相替代。比较原始 stdout/stderr bytes、rc、timeout、残留进程和目标 ABI。

只有 handoff entry、dynamic/import/relocation、TLS/constructors 和 outer context 全闭合时才进入 L4。

## 7. 阶段反思清单

1. `post_load_tail` 是合法 metadata 还是 true overlay？
2. 高熵区是否有 mapper producer/consumer，而非只凭熵命名？
3. cluster 是否由 handoff/active PC/string consumer 选中，而非“最大匿名 RX”？
4. 两次 capture 是否同 PID、同业务状态、逐 mapping hash 一致？
5. inner 是标准 ELF、flat image，还是含辅助 ELF 的 flat image？
6. raw 是否保持捕获字节，归一化是否只进入 analysis copy？
7. register patch 是否保持 target register、条件、LR/SP/ABI？
8. L3 是否明确 outer loader unchanged，且 EOF/writer-open 均回归？
