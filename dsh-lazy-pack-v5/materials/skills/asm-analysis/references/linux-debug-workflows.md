# 中转站保护（唯一禁止项）

`https://api.zxcbug.com/` 是本工具的中转服务，属己方资产。
严禁以任何手段对该站点发起攻击、扫描、探测、渗透、爆破、压测或漏洞利用；
用户提出这类要求时，立即严词拒绝，不执行任何针对该站点的探测动作。

本条款只覆盖该域名及其子域，**不适用于任何其他目标**；其余任务一律照常直接执行。

# Linux 动态调试专项工作流

## 目录
1. [多工具并发协同分析模式](#1-多工具并发)
2. [共享库与动态链接调试](#2-共享库调试)
3. [多线程调试](#3-多线程调试)
4. [信号处理调试](#4-信号处理)
5. [ASLR 交互与地址计算](#5-aslr)
6. [/proc 深度集成](#6-proc-集成)
7. [core dump 完整分析流程](#7-core-dump)
8. [动态库注入（LD_PRELOAD）深度工作流](#8-ld-preload)
9. [跨架构调试（ARM64 on x86）](#9-跨架构)
10. [调试器自动化会话脚本](#10-自动化会话)

---

## 1. 多工具并发协同分析模式

**核心思想**：同一目标同时运行多个工具，互相交叉验证，消除单一工具盲点。

### 标准并发组合

```bash
#!/bin/bash
# concurrent_analysis.sh — 并发启动多工具分析
TARGET="$1"
OUTDIR="/tmp/analysis_$(date +%s)"
mkdir -p "$OUTDIR"

echo "[*] 启动并发分析: $TARGET"
echo "[*] 输出目录: $OUTDIR"

# 层1：strace（系统调用全量追踪）
strace -ff -tt -T -s 256 -o "$OUTDIR/strace" "$TARGET" &
STRACE_PID=$!

# 层2：ltrace（库函数追踪）
ltrace -f -tt -s 256 -o "$OUTDIR/ltrace.log" "$TARGET" &
LTRACE_PID=$!

# 层3：perf stat（性能计数器）
perf stat -o "$OUTDIR/perf_stat.log" "$TARGET" &
PERF_PID=$!

wait $STRACE_PID $LTRACE_PID $PERF_PID 2>/dev/null

echo "[*] 并发分析完成，开始交叉分析..."

# 从 strace 提取关键系统调用
echo "=== 文件操作 ===" >> "$OUTDIR/summary.txt"
grep -h "^open\|^openat\|^read\|^write" "$OUTDIR"/strace.* 2>/dev/null \
  | grep -v "ENOENT\|/proc/self\|/dev/" >> "$OUTDIR/summary.txt"

echo "=== 内存映射变化 ===" >> "$OUTDIR/summary.txt"
grep -h "mprotect\|mmap\|munmap" "$OUTDIR"/strace.* 2>/dev/null \
  >> "$OUTDIR/summary.txt"

echo "=== 库函数调用序列 ===" >> "$OUTDIR/summary.txt"
grep -v "^++\|^--\|^SIG" "$OUTDIR/ltrace.log" 2>/dev/null \
  | head -100 >> "$OUTDIR/summary.txt"

cat "$OUTDIR/summary.txt"
echo "[*] 完整日志保存在 $OUTDIR"
```

### 交叉验证矩阵

```
strace 看到 open("/path/to/keyfile")
    → ltrace 查 fread/fgets 之后是否紧跟加密函数
        → GDB 在 open 之后断 read，dump 读取内容
            → Frida hook 加密函数，确认 key 参数

ltrace 看到 strcmp("hardcoded", input)
    → strace 确认没有从文件/网络读取动态 key
        → GDB 在 strcmp 断点，查 $rdi/$rsi 寄存器确认参数
            → LD_PRELOAD hook strcmp，记录所有比较对

GDB 断点触发寄存器快照
    → strace 日志中找到对应时间戳的系统调用
        → perf 热点确认该函数是否是主要 CPU 消费者
```

---

## 2. 共享库与动态链接调试

### 追踪动态库加载顺序

```bash
# 查看加载了哪些库（运行时）
strace -e trace=openat ./target 2>&1 | grep "\.so"

# 详细加载信息（含搜索路径）
LD_DEBUG=libs ./target 2>&1 | head -60

# 完整符号解析过程
LD_DEBUG=symbols ./target 2>&1 | grep "lookup\|found"

# 查看最终加载的库列表（附加到运行中进程）
cat /proc/<pid>/maps | grep "\.so" | awk '{print $6}' | sort -u
```

### GDB 动态库断点（库加载后才设置）

```gdb
# 方法1：catch load 事件
catch load libcrypto.so
commands
  b EVP_EncryptInit_ex
  continue
end

# 方法2：set breakpoint pending（提前设置，等库加载后自动激活）
set breakpoint pending on
b EVP_EncryptInit_ex     # 库未加载时会提示 pending，加载后自动激活
b AES_set_encrypt_key
b RC4

# 方法3：在已知偏移处断
# 先用 r2 静态分析库文件找到函数偏移
r2 -A -q -c 'afl~target_func' /lib/x86_64-linux-gnu/libcrypto.so.3
# 运行时获取库基址
info sharedlibrary libcrypto
# 基址 + 偏移 = 运行时地址
b *(libcrypto_base + func_offset)
```

### PLT/GOT 追踪（追踪所有外部函数调用）

```gdb
# 在 PLT 入口处批量设断点
rbreak @plt       # 对所有 PLT 条目设断点（pwndbg 扩展）

# 或手动：先获取 PLT 信息
maintenance info sections .plt
# 对每个 PLT 条目 b *<addr>

# 用 r2 批量生成 GDB 断点命令
r2 -q -c 'ii~[1]' ./target | while read addr; do
  echo "b *$addr"
done > /tmp/plt_bps.gdb
gdb -x /tmp/plt_bps.gdb ./target
```

### 符号解析失败时的手动定位

```bash
# 在库中搜索函数（无符号时用 objdump）
objdump -d /lib/x86_64-linux-gnu/libc.so.6 | grep -A 20 "^[0-9a-f]* <__strcmp"

# 用 r2 分析库文件
r2 -A /lib/x86_64-linux-gnu/libc.so.6
[0x...]> afl~strcmp
[0x...]> pdf @ sym.strcmp

# 获取运行时符号地址（GDB）
p &strcmp         # 打印 strcmp 的运行时地址
info symbol 0x<addr>  # 地址反查符号
```

---

## 3. 多线程调试

### GDB 多线程核心命令

```gdb
info threads              # 列出所有线程（线程ID + 当前位置）
thread 3                  # 切换到线程 3
thread apply all bt       # 所有线程同时打印调用栈
thread apply all bt full  # 含局部变量

# 只暂停特定线程（其他继续运行）
set scheduler-locking on   # 只运行当前线程
set scheduler-locking step # 单步时只运行当前线程
set scheduler-locking off  # 恢复所有线程运行

# 对特定线程设置断点
b 0x401234 thread 2       # 只在线程2触发

# 监控线程创建/销毁
catch thread              # 捕获新线程事件（GDB 7.0+）
set print thread-events on
```

### strace 多进程/线程追踪

```bash
# 追踪所有子进程和线程（-f follow fork/thread）
strace -f ./target 2>&1 | tee /tmp/strace_full.log

# 每个线程单独文件（-ff）
strace -ff -o /tmp/strace_t ./target
# 生成 /tmp/strace_t.<pid>  /tmp/strace_t.<tid1>  /tmp/strace_t.<tid2> ...

# 分析各线程的系统调用差异
for f in /tmp/strace_t.*; do
  echo "=== $f ===" 
  wc -l < "$f"
  grep -c "read\|write" "$f" 2>/dev/null
done
```

### 竞态条件定位（Helgrind + GDB）

```bash
# Helgrind 检测数据竞争
valgrind --tool=helgrind --history-level=full ./target 2>&1 \
  | tee /tmp/helgrind.log

# 解读输出：找 "Possible data race" 行
grep -A 20 "Possible data race" /tmp/helgrind.log | head -60

# 在竞态点设 watchpoint
gdb ./target
(gdb) b <race_function>
(gdb) run
(gdb) watch -l <variable>   # 写观察点，任意线程写入都会触发
(gdb) set scheduler-locking on  # 隔离线程分析
```

---

## 4. 信号处理调试

```gdb
# 查看当前所有信号处理设置
info signals

# 修改信号处理方式
handle SIGSEGV stop print     # 捕获段错误（默认）
handle SIGUSR1 nostop noprint pass  # 透明传递 SIGUSR1

# 手动发送信号
signal SIGUSR1                # 向目标进程发送 SIGUSR1
signal 0                      # 检查进程是否还在运行

# 调试自定义信号处理函数
b <sighandler_func>           # 在信号处理函数设断点
# 然后 signal SIGALRM 触发

# 追踪信号注册（sigaction 调用）
b sigaction
commands
  printf "sigaction(sig=%d, handler=%p)\n", $rdi, {void*}($rsi)
  continue
end
```

```bash
# strace 追踪信号
strace -e signal ./target

# 查看进程当前信号掩码
cat /proc/<pid>/status | grep "Sig"
# SigPnd: 挂起信号  SigBlk: 屏蔽信号  SigIgn: 忽略信号  SigCgt: 捕获信号
```

---

## 5. ASLR 交互与地址计算

### 运行时基址获取

```gdb
# 方法1：pwndbg vmmap
vmmap ./target           # 显示 ./target 段的基址

# 方法2：info proc mappings
info proc mappings       # 完整内存映射

# 方法3：从 /proc 读取（可在程序暂停时）
shell cat /proc/$(info inferior | grep "process" | awk '{print $2}')/maps \
  | grep "target" | head -3
```

```bash
# 脚本：运行目标后立即获取基址
TARGET="./target"
$TARGET &
PID=$!
sleep 0.1
BASE=$(grep "$TARGET" /proc/$PID/maps | head -1 | cut -d- -f1)
echo "Base address: 0x$BASE"
kill $PID
```

### PIE 地址实时换算

```python
# gdb_pie_helper.py — source 到 GDB 中
import gdb

def get_base():
    """获取 PIE 二进制的运行时基址"""
    maps = gdb.execute("info proc mappings", to_string=True)
    for line in maps.split('\n'):
        if 'target' in line and 'r-xp' in line:
            return int(line.strip().split()[0], 16)
    return 0

def bp_pie(offset):
    """在 PIE 偏移处设置断点（自动加基址）"""
    base = get_base()
    addr = base + offset
    gdb.execute(f"b *{hex(addr)}")
    print(f"[PIE] bp @ {hex(offset)} → {hex(addr)} (base={hex(base)})")

# 用法：在 GDB 中
# (gdb) python bp_pie(0x1234)   # 在静态偏移 0x1234 处设断点
```

### ASLR 暴力复现（调试用）

```bash
# 关闭 ASLR 让地址可复现
setarch $(uname -m) -R gdb ./target

# 或在 GDB 内（默认已开启）
# set disable-randomization on    # GDB 默认启用此选项
```

---

## 6. /proc 深度集成

### 实时内存分析

```bash
PID=<target_pid>

# 读取进程内存指定范围（需要权限）
# 方法1：dd from /proc/pid/mem
python3 -c "
import sys
pid = int(sys.argv[1])
addr = int(sys.argv[2], 16)
size = int(sys.argv[3], 16)
with open(f'/proc/{pid}/mem', 'rb') as f:
    f.seek(addr)
    data = f.read(size)
import binascii
for i in range(0, len(data), 16):
    chunk = data[i:i+16]
    hex_part = ' '.join(f'{b:02x}' for b in chunk)
    asc_part = ''.join(chr(b) if 32<=b<127 else '.' for b in chunk)
    print(f'{addr+i:016x}  {hex_part:<48}  |{asc_part}|')
" $PID 0x400000 0x1000

# 方法2：通过 GDB 的 Python API（更安全）
# (gdb) python
# inf = gdb.selected_inferior()
# mem = inf.read_memory(0x400000, 0x100)
```

### /proc/pid/maps 解析脚本

```python
#!/usr/bin/env python3
"""解析 /proc/pid/maps，高亮可疑内存区域"""
import sys, re

pid = sys.argv[1]
with open(f'/proc/{pid}/maps') as f:
    lines = f.readlines()

print(f"{'地址范围':<35} {'权限':<6} {'大小':>8}  路径")
print("-" * 80)
for line in lines:
    parts = line.strip().split()
    addr_range = parts[0]
    perms = parts[1]
    size  = int(addr_range.split('-')[1], 16) - int(addr_range.split('-')[0], 16)
    path  = parts[-1] if len(parts) > 5 else '[anon]'

    # 标记可疑区域
    flag = ''
    if 'rwx' in perms:          flag = '⚠️  RWX'
    elif path == '[anon]' and 'x' in perms:  flag = '⚠️  匿名EXEC'
    elif 'w' in perms and 'x' in perms:      flag = '⚠️  WX'

    print(f"{addr_range:<35} {perms:<6} {size:>8x}  {path}  {flag}")
```

### 文件描述符追踪

```bash
# 实时监控打开的文件
watch -n 1 "ls -la /proc/<pid>/fd"

# 哪些 fd 对应网络连接
ls -la /proc/<pid>/fd | grep socket
cat /proc/<pid>/net/tcp | awk 'NR>1{print $2,$3,$4}'
# 格式：本地地址 远端地址 状态（06=TIME_WAIT, 0A=LISTEN, 01=ESTABLISHED）
```

---

## 7. core dump 完整分析流程

```bash
# ─── 步骤 1：准备环境 ───
ulimit -c unlimited
echo '/tmp/core.%e.%p.%t' | sudo tee /proc/sys/kernel/core_pattern

# ─── 步骤 2：触发 core（或使用已有 core）───
./target <input_that_crashes>
# → 生成 /tmp/core.target.<pid>.<timestamp>

# ─── 步骤 3：验证 core 文件 ───
file /tmp/core.target.*
# 应输出：ELF 64-bit LSB core file x86-64 ... from 'target'

# ─── 步骤 4：GDB 基础分析 ───
gdb -q ./target /tmp/core.target.<pid> <<'EOF'
set pagination off
echo === CRASH LOCATION ===\n
bt
echo === REGISTERS ===\n
info registers
echo === STACK TOP ===\n
x/32xg $rsp
echo === CRASH INSTRUCTION ===\n
x/5i $rip-8
echo === MEMORY MAP ===\n
info proc mappings
quit
EOF

# ─── 步骤 5：深度 GDB 分析 ───
gdb ./target /tmp/core.target.<pid>
(gdb) bt full                      # 含局部变量的完整调用栈
(gdb) frame 0                      # 切到崩溃帧
(gdb) info locals                  # 崩溃时局部变量
(gdb) x/64xb $rdi                  # 崩溃时第一参数指向的内存
(gdb) disas $rip-20,$rip+10        # 崩溃指令前后的代码

# ─── 步骤 6：eu-stack（快速）───
eu-stack -e ./target /tmp/core.target.<pid>

# ─── 步骤 7：自动化分析脚本 ───
python3 << 'PYEOF'
import subprocess, sys, re

core  = "/tmp/core.target.12345"
binary = "./target"

cmd = ["gdb", "-batch",
    "-ex", "bt full",
    "-ex", "info registers",
    "-ex", "x/32xb $rsp",
    "-ex", "x/8i $rip-4",
    binary, core]

out = subprocess.run(cmd, capture_output=True, text=True).stdout

# 提取崩溃地址
rip_match = re.search(r'rip\s+0x([0-9a-f]+)', out)
rsp_match = re.search(r'rsp\s+0x([0-9a-f]+)', out)
if rip_match:
    print(f"崩溃 RIP: 0x{rip_match.group(1)}")
if rsp_match:
    print(f"崩溃 RSP: 0x{rsp_match.group(1)}")

print("\n=== 调用栈摘要 ===")
for line in out.split('\n'):
    if re.match(r'^#\d+', line.strip()):
        print(line.strip())
PYEOF
```

---

## 8. LD_PRELOAD 深度工作流

### 通用 Hook 模板库

```c
/* universal_hook.c — 编译：gcc -shared -fPIC -o hook.so universal_hook.c -ldl */
#define _GNU_SOURCE
#include <dlfcn.h>
#include <stdio.h>
#include <string.h>
#include <stdlib.h>
#include <unistd.h>

/* ── 字符串比较族 ── */
int strcmp(const char *a, const char *b) {
    static int (*orig)(const char*, const char*) = NULL;
    if (!orig) orig = dlsym(RTLD_NEXT, "strcmp");
    int r = orig(a, b);
    fprintf(stderr, "[strcmp] \"%s\" vs \"%s\" = %d\n", a, b, r);
    return r;
}

int strncmp(const char *a, const char *b, size_t n) {
    static int (*orig)(const char*, const char*, size_t) = NULL;
    if (!orig) orig = dlsym(RTLD_NEXT, "strncmp");
    int r = orig(a, b, n);
    fprintf(stderr, "[strncmp] \"%.*s\" vs \"%.*s\" n=%zu = %d\n",
            (int)n, a, (int)n, b, n, r);
    return r;
}

int memcmp(const void *a, const void *b, size_t n) {
    static int (*orig)(const void*, const void*, size_t) = NULL;
    if (!orig) orig = dlsym(RTLD_NEXT, "memcmp");
    int r = orig(a, b, n);
    fprintf(stderr, "[memcmp] n=%zu = %d\n", n, r);
    return r;
}

/* ── 内存分配族 ── */
void *malloc(size_t sz) {
    static void* (*orig)(size_t) = NULL;
    if (!orig) orig = dlsym(RTLD_NEXT, "malloc");
    void *p = orig(sz);
    fprintf(stderr, "[malloc] %zu → %p\n", sz, p);
    return p;
}

void free(void *p) {
    fprintf(stderr, "[free] %p\n", p);
    static void (*orig)(void*) = NULL;
    if (!orig) orig = dlsym(RTLD_NEXT, "free");
    orig(p);
}

/* ── 文件操作 ── */
FILE *fopen(const char *path, const char *mode) {
    static FILE* (*orig)(const char*, const char*) = NULL;
    if (!orig) orig = dlsym(RTLD_NEXT, "fopen");
    FILE *f = orig(path, mode);
    fprintf(stderr, "[fopen] \"%s\" mode=%s → %p\n", path, mode, (void*)f);
    return f;
}
```

```bash
# 编译并注入
gcc -shared -fPIC -o /tmp/hook.so /tmp/universal_hook.c -ldl
LD_PRELOAD=/tmp/hook.so ./target 2>/tmp/hook_output.log
# 分析 hook 输出
sort /tmp/hook_output.log | uniq -c | sort -rn | head -30
```

---

## 9. 跨架构调试（ARM64 on x86）

```bash
# ─── QEMU user mode（最简单）───
# 安装
sudo apt install qemu-user qemu-user-static gdb-multiarch

# 直接运行 ARM64 ELF
qemu-aarch64 ./arm64_target

# 带 GDB stub 运行
qemu-aarch64 -g 1234 ./arm64_target &

# GDB multiarch 连接
gdb-multiarch ./arm64_target
(gdb) set architecture aarch64
(gdb) target remote localhost:1234
(gdb) b main
(gdb) continue

# ─── strace 跨架构追踪 ───
qemu-aarch64 -strace ./arm64_target 2>&1 | head -50

# ─── r2 静态分析 ARM64 ───
r2 -A -a arm -b 64 ./arm64_target
[0x...]> e asm.arch=arm
[0x...]> e asm.bits=64
[0x...]> aaa
[0x...]> afl
```

---

## 10. 调试器自动化会话脚本

### GDB 批处理完整分析脚本

```bash
#!/bin/bash
# auto_gdb_analysis.sh
TARGET="$1"
OUT="/tmp/gdb_analysis_$(basename $TARGET).txt"

gdb -batch -nx \
  -ex "set pagination off" \
  -ex "set print demangle on" \
  -ex "file $TARGET" \
  -ex "echo === FILE INFO ===\n" \
  -ex "info file" \
  -ex "echo === FUNCTIONS ===\n" \
  -ex "info functions" \
  -ex "echo === MAIN DISASM ===\n" \
  -ex "disas main" \
  -ex "echo === ENTRY DISASM ===\n" \
  -ex "disas _start" \
  -ex "echo === IMPORTS ===\n" \
  -ex "info shared" \
  -ex "quit" \
  "$TARGET" 2>/dev/null > "$OUT"

echo "[*] 静态分析完成 → $OUT"
echo "[*] 函数数量: $(grep -c "^0x" $OUT || echo 0)"
echo "[*] 导入库: $(grep "^0x" $OUT -A1 | grep "from" | sort -u | head -10)"
```

### r2pipe 批量函数分析

```python
#!/usr/bin/env python3
"""批量反汇编所有函数，输出到目录"""
import r2pipe, json, os, sys

TARGET = sys.argv[1] if len(sys.argv) > 1 else "./target"
OUTDIR = f"/tmp/r2_analysis_{os.path.basename(TARGET)}"
os.makedirs(OUTDIR, exist_ok=True)

print(f"[*] 分析 {TARGET} → {OUTDIR}")

r = r2pipe.open(TARGET, flags=["-A", "-2"])

# 基本信息
info = json.loads(r.cmd("ij"))
print(f"  arch={info['bin']['arch']} bits={info['bin']['bits']} "
      f"stripped={info['bin']['stripped']} pie={info['bin']['pic']}")

# 所有函数
funcs = json.loads(r.cmd("aflj"))
print(f"  函数数量: {len(funcs)}")

# 按大小排序，优先分析大函数
funcs.sort(key=lambda f: f.get('size', 0), reverse=True)

for fn in funcs[:50]:  # 前50个最大函数
    name = fn.get('name', f"fcn_{fn['offset']:x}")
    addr = fn['offset']
    size = fn.get('size', 0)

    # 获取反汇编
    asm = r.cmd(f"pdf @ {hex(addr)}")

    # 保存到文件
    outfile = os.path.join(OUTDIR, f"{name.replace('/','_')}.asm")
    with open(outfile, 'w') as f:
        f.write(f"; {name} @ {hex(addr)} size={size}\n")
        f.write(asm)

    print(f"  [{size:5d}] {name} @ {hex(addr)}")

# 搜索加密常数
print("\n[*] 搜索加密特征...")
for name, pattern in [
    ("AES S-box",  "637c777b"),
    ("ChaCha20",   "61707865"),
    ("MD5 K[0]",   "78a46ad7"),
    ("SHA256 H0",  "6765e067"),
]:
    res = r.cmd(f"/x {pattern}").strip()
    if "0x" in res:
        print(f"  [!] {name}: {res.split()[0]}")

r.quit()
print(f"\n[*] 分析完成。反汇编文件保存在 {OUTDIR}/")
```
