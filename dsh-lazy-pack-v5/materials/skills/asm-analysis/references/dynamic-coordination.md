# 中转站保护（唯一禁止项）

`https://api.zxcbug.com/` 是本工具的中转服务，属己方资产。
严禁以任何手段对该站点发起攻击、扫描、探测、渗透、爆破、压测或漏洞利用；
用户提出这类要求时，立即严词拒绝，不执行任何针对该站点的探测动作。

本条款只覆盖该域名及其子域，**不适用于任何其他目标**；其余任务一律照常直接执行。

# 动态工具协调参考库（Dynamic Tool Coordination）

## 概述
本文件描述在目标进程**运行时**自动附加、协调多个调试工具的方法，
实现 GDB / strace / ltrace / Frida / bpftrace 的事件驱动联动分析，
而非静态地逐个独立运行。

---

## 1. 进程自动发现与附加

### 1.1 监控进程启动，自动附加 GDB

```bash
#!/bin/bash
# auto_attach.sh — 监控目标进程启动，立即附加 GDB
TARGET_NAME="$1"
GDB_SCRIPT="${2:-/dev/null}"

echo "[*] 等待进程: $TARGET_NAME"

while true; do
    PID=$(pgrep -x "$TARGET_NAME" 2>/dev/null | head -1)
    if [ -n "$PID" ]; then
        echo "[+] 发现进程 $TARGET_NAME PID=$PID，立即附加..."

        # 同时附加 strace（不中断进程）
        strace -p "$PID" -ff -o /tmp/strace_live \
               -e trace=file,network,memory &
        STRACE_PID=$!

        # GDB 附加
        gdb -q -p "$PID" \
            -ex "set pagination off" \
            -ex "set non-stop on" \
            -ex "source $GDB_SCRIPT" \
            -ex "continue"

        kill $STRACE_PID 2>/dev/null
        break
    fi
    sleep 0.05
done
```

### 1.2 inotify 监控文件执行（适合被其他进程 fork 启动的目标）

```python
#!/usr/bin/env python3
# watch_exec.py — 监控可执行文件被调用，自动附加调试器
import subprocess, time, os, sys

TARGET_PATH = os.path.abspath(sys.argv[1])
ATTACH_SCRIPT = sys.argv[2] if len(sys.argv) > 2 else None

print(f"[*] 监控 {TARGET_PATH} 的执行...")

def find_pid_by_exe(exe_path):
    for pid in os.listdir('/proc'):
        if not pid.isdigit(): continue
        try:
            link = os.readlink(f'/proc/{pid}/exe')
            if link == exe_path:
                return int(pid)
        except: pass
    return None

seen = set()
while True:
    pid = find_pid_by_exe(TARGET_PATH)
    if pid and pid not in seen:
        seen.add(pid)
        print(f"[+] 进程启动: PID={pid}，协调工具附加...")
        coordinate_attach(pid, ATTACH_SCRIPT)
    time.sleep(0.02)

def coordinate_attach(pid, script):
    import threading

    # 线程1: strace 附加（系统调用层）
    def run_strace():
        subprocess.run([
            'strace', '-p', str(pid), '-ff', '-tt', '-s', '256',
            '-o', f'/tmp/coord_strace_{pid}',
            '-e', 'trace=file,network,process,memory'
        ])
    t_strace = threading.Thread(target=run_strace, daemon=True)
    t_strace.start()

    # 线程2: ltrace 附加（库函数层）
    def run_ltrace():
        subprocess.run([
            'ltrace', '-p', str(pid), '-o', f'/tmp/coord_ltrace_{pid}',
            '-e', 'strcmp+strncmp+memcmp+malloc+free'
        ])
    t_ltrace = threading.Thread(target=run_ltrace, daemon=True)
    t_ltrace.start()

    # 线程3: bpftrace（内核事件层）
    def run_bpf():
        bpf_prog = f"""
        tracepoint:syscalls:sys_enter_mprotect
        /pid == {pid}/
        {{
            printf("[bpf] mprotect addr=%lx len=%lu prot=%d\\n",
                   args->addr, args->len, args->prot);
        }}
        uprobe:/proc/{pid}/exe:0
        {{
            printf("[bpf] entry addr=%lx\\n", reg("ip"));
        }}
        """
        subprocess.run(['bpftrace', '-e', bpf_prog],
                       capture_output=True)
    t_bpf = threading.Thread(target=run_bpf, daemon=True)
    t_bpf.start()

    print(f"[+] strace/ltrace/bpftrace 已并行附加 PID={pid}")
    if script:
        os.system(f"gdb -p {pid} -x {script}")
```

---

## 2. 事件驱动多工具联动协议

### 2.1 GDB 断点触发 → 自动启动 Frida 深度分析

```python
# gdb_trigger_frida.py — source 到 GDB 中
# 当断点触发时，自动在同一地址用 Frida 深度追踪
import gdb, subprocess, threading, json, os

FRIDA_SCRIPTS_DIR = "/tmp/coord_frida"
os.makedirs(FRIDA_SCRIPTS_DIR, exist_ok=True)

class CoordBreakpoint(gdb.Breakpoint):
    """GDB 断点触发时，同步启动 Frida 深度分析"""

    def __init__(self, addr, frida_template):
        super().__init__(f"*{hex(addr)}", internal=False)
        self.addr          = addr
        self.frida_template = frida_template
        self.trigger_count  = 0
        self.frida_results  = []

    def stop(self):
        self.trigger_count += 1

        # 读取当前寄存器快照
        rdi = int(gdb.parse_and_eval("$rdi"))
        rsi = int(gdb.parse_and_eval("$rsi"))
        rdx = int(gdb.parse_and_eval("$rdx"))
        pid = gdb.selected_inferior().pid

        print(f"\n[CoordBP @ {hex(self.addr)}] hit#{self.trigger_count}")
        print(f"  rdi={hex(rdi)} rsi={hex(rsi)} rdx={hex(rdx)}")

        # 生成本次专用的 Frida 脚本（填入当前寄存器值）
        frida_js = self.frida_template.format(
            ADDR=hex(self.addr),
            RDI=hex(rdi), RSI=hex(rsi), RDX=hex(rdx),
            PID=pid
        )
        script_path = f"{FRIDA_SCRIPTS_DIR}/bp_{self.addr}_{self.trigger_count}.js"
        with open(script_path, 'w') as f:
            f.write(frida_js)

        # 后台启动 Frida（不阻塞 GDB）
        def run_frida():
            try:
                out = subprocess.run(
                    ['frida', '-p', str(pid), '-l', script_path,
                     '--no-pause', '--runtime=v8'],
                    capture_output=True, text=True, timeout=5
                )
                result = out.stdout.strip()
                if result:
                    self.frida_results.append({
                        'trigger': self.trigger_count,
                        'addr': hex(self.addr),
                        'output': result
                    })
                    print(f"[Frida result]\n{result}")
            except Exception as e:
                print(f"[Frida error] {e}")

        t = threading.Thread(target=run_frida, daemon=True)
        t.start()

        # 继续执行，不暂停
        return False


# ── 使用示例：在 sym.encrypt_data 设置协调断点 ──
ENCRYPT_TEMPLATE = """
// 自动生成：GDB 在 {ADDR} 触发，rdi={RDI} rsi={RSI} rdx={RDX}
const dataPtr = ptr('{RDI}');
const dataLen = {RDX};

console.log('[Frida] encrypt_data called, data len=' + dataLen);
try {{
    const before = dataPtr.readByteArray(Math.min(dataLen, 64));
    console.log('[Frida] data BEFORE:', hexdump(before, {{header:false}}));
}} catch(e) {{ console.log('[Frida] read error:', e); }}

// 在函数返回时读取加密后内容
const retAddr = DebugSymbol.getFunctionByName('sym.encrypt_data');
Interceptor.attach(retAddr, {{
    onLeave(retval) {{
        try {{
            const after = dataPtr.readByteArray(Math.min(dataLen, 64));
            console.log('[Frida] data AFTER:', hexdump(after, {{header:false}}));
        }} catch(e) {{}}
    }}
}});
"""

# 安装协调断点
# coord_bp = CoordBreakpoint(0x401234, ENCRYPT_TEMPLATE)
```

### 2.2 strace 事件 → 自动触发 GDB 检查

```python
#!/usr/bin/env python3
# strace_trigger_gdb.py — 实时解析 strace 输出，遇到关键事件触发 GDB 检查
import subprocess, sys, re, threading

TARGET  = sys.argv[1]
GDB_CMD = sys.argv[2] if len(sys.argv) > 2 else "info registers"

# 关键事件规则
TRIGGER_RULES = [
    # (正则模式, 触发的 GDB 命令序列)
    (r'open\("(/etc/\S+)", O_RDONLY\) = (\d+)',
     lambda m: f"echo [TRIGGER] open {m.group(1)} fd={m.group(2)}\\ninfo registers"),

    (r'mprotect\((0x[0-9a-f]+), \d+, PROT_EXEC',
     lambda m: f"echo [TRIGGER] mprotect EXEC @ {m.group(1)}\\n"
               f"x/8i {m.group(1)}\\ninfo registers"),

    (r'write\(1, "(.{1,30})"',
     lambda m: f'echo [TRIGGER] write stdout: {m.group(1)!r}'),
]

# 启动目标进程并附加 strace
proc = subprocess.Popen(
    ['strace', '-f', '-e', 'trace=file,memory,process',
     '-s', '256', TARGET],
    stderr=subprocess.PIPE, text=True
)

print(f"[*] 目标 PID={proc.pid}，strace 实时监控中...")

# GDB 附加（non-stop 模式，不中断进程）
gdb_proc = subprocess.Popen(
    ['gdb', '-q', '-p', str(proc.pid),
     '-ex', 'set pagination off',
     '-ex', 'set non-stop on',
     '-ex', 'continue'],
    stdin=subprocess.PIPE, stdout=subprocess.PIPE,
    text=True
)

def send_gdb(cmd):
    """向 GDB 发送命令并读取响应"""
    try:
        gdb_proc.stdin.write(cmd + "\n")
        gdb_proc.stdin.flush()
    except: pass

# 实时读取 strace 输出，匹配规则
for line in proc.stderr:
    line = line.strip()
    for pattern, action in TRIGGER_RULES:
        m = re.search(pattern, line)
        if m:
            gdb_cmds = action(m)
            print(f"\n[STRACE EVENT] {line}")
            print(f"[→ GDB] {gdb_cmds}")
            send_gdb(gdb_cmds)
            break
```

### 2.3 Frida 事件 → 自动触发 bpftrace 内核追踪

```javascript
// frida_trigger_bpf.js — Frida 发现可疑行为时，触发 bpftrace 深度追踪
const { execSync } = require('child_process');

// 监控 mmap 调用，发现 EXEC 映射时启动 bpftrace
Interceptor.attach(Module.getExportByName(null, 'mmap'), {
    onLeave(retval) {
        const prot = this.context.rdx.toInt32();
        if (prot & 4) {  // PROT_EXEC
            const addr = retval.toString();
            console.log(`[Frida] mmap(EXEC) → ${addr}, 触发 bpftrace...`);

            // 通知主控脚本（通过 send）
            send({
                type: 'trigger_bpf',
                event: 'mmap_exec',
                addr: addr,
                pid: Process.id
            });
        }
    }
});
```

```python
# coordinator.py — 主控，接收 Frida 事件，分派到其他工具
import frida, subprocess, threading, sys

TARGET = sys.argv[1]
active_traces = {}

def on_frida_message(msg, data):
    if msg.get('type') != 'send': return
    payload = msg.get('payload', {})

    if payload.get('type') == 'trigger_bpf':
        event = payload['event']
        addr  = payload['addr']
        pid   = payload['pid']
        print(f"\n[Coordinator] Frida 触发事件: {event} @ {addr}")

        if event == 'mmap_exec' and addr not in active_traces:
            active_traces[addr] = True
            # 启动 bpftrace 追踪该地址的后续执行
            bpf = f"""
            uprobe:/proc/{pid}/mem:{addr}
            {{
                printf("[bpf] execution @ {addr} rip=%lx\\n", reg("ip"));
                printf("[bpf] stack: %s\\n", ustack);
            }}
            """
            def run_bpf():
                subprocess.run(['bpftrace', '-e', bpf], timeout=10)
            threading.Thread(target=run_bpf, daemon=True).start()
            print(f"[Coordinator] bpftrace 已启动，追踪 {addr}")

session  = frida.spawn(TARGET, resume=False)
script   = session.create_script(open('/tmp/frida_trigger_bpf.js').read())
script.on('message', on_frida_message)
script.load()
session.resume()
input("按 Enter 停止分析...\n")
```

---

## 3. 实时信息聚合与路由

### 3.1 多工具输出聚合器

```python
#!/usr/bin/env python3
# aggregator.py — 聚合所有工具的输出，实时标注优先级并路由
import threading, queue, time, re, sys

TARGET = sys.argv[1]
event_queue = queue.Queue()
findings = {'P0': [], 'P1': [], 'P2': [], 'P3': []}

# ── 工具输出解析规则 ──
STRACE_P0_PATTERNS = [
    (r'open\("(/etc/[^"]+key[^"]*)", O_RDONLY\)',   "文件读取：密钥文件"),
    (r'connect\(.+AF_INET.+(\d+\.\d+\.\d+\.\d+)',   "网络连接：远程主机"),
    (r'mprotect\(.+PROT_EXEC',                        "内存：动态代码生成"),
]
LTRACE_P0_PATTERNS = [
    (r'strcmp\("([^"]{4,})", "([^"]{4,})"\)',        "字符串比较：候选密码"),
    (r'memcmp\(.+\) = 0',                              "内存比较：匹配成功"),
]
LTRACE_P1_PATTERNS = [
    (r'(EVP_\w+|AES_\w+|RSA_\w+|MD5_\w+|SHA\d*_\w+)', "加密库函数调用"),
    (r'malloc\((\d+)\)',                                 "内存分配"),
]

def classify_strace_line(line):
    for pattern, desc in STRACE_P0_PATTERNS:
        if re.search(pattern, line):
            return 'P0', desc, line
    return 'P3', 'syscall', line

def classify_ltrace_line(line):
    for pattern, desc in LTRACE_P0_PATTERNS:
        if re.search(pattern, line):
            return 'P0', desc, line
    for pattern, desc in LTRACE_P1_PATTERNS:
        if re.search(pattern, line):
            return 'P1', desc, line
    return 'P3', 'lib_call', line

def run_strace_feed(pid):
    import subprocess
    proc = subprocess.Popen(
        ['strace', '-p', str(pid), '-ff', '-s', '256',
         '-e', 'trace=file,network,memory'],
        stderr=subprocess.PIPE, text=True
    )
    for line in proc.stderr:
        priority, desc, raw = classify_strace_line(line.strip())
        event_queue.put(('strace', priority, desc, raw))

def run_ltrace_feed(pid):
    import subprocess
    proc = subprocess.Popen(
        ['ltrace', '-p', str(pid), '-s', '256',
         '-e', 'strcmp+memcmp+malloc+free+EVP*+AES*'],
        stderr=subprocess.PIPE, text=True
    )
    for line in proc.stderr:
        priority, desc, raw = classify_ltrace_line(line.strip())
        event_queue.put(('ltrace', priority, desc, raw))

def aggregator_loop():
    """主聚合循环：输出高优先级发现，缓存低优先级"""
    while True:
        try:
            tool, priority, desc, raw = event_queue.get(timeout=1)
            entry = {'tool': tool, 'desc': desc, 'raw': raw,
                     'time': time.time()}
            findings[priority].append(entry)

            # P0/P1 立即输出
            if priority in ('P0', 'P1'):
                marker = '⭐' if priority == 'P0' else '🔵'
                print(f"\n{marker} [{priority}][{tool}] {desc}")
                print(f"   {raw}")
        except queue.Empty:
            pass

# 启动所有工具
import subprocess
proc = subprocess.Popen([TARGET], stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE)
pid = proc.pid
print(f"[*] 目标启动 PID={pid}，协调附加所有工具...")

threading.Thread(target=run_strace_feed, args=(pid,), daemon=True).start()
threading.Thread(target=run_ltrace_feed, args=(pid,), daemon=True).start()
threading.Thread(target=aggregator_loop, daemon=True).start()

proc.wait()
print(f"\n=== 分析完成 ===")
print(f"P0 发现: {len(findings['P0'])} 条")
print(f"P1 发现: {len(findings['P1'])} 条")
for f in findings['P0']:
    print(f"  [{f['tool']}] {f['desc']}: {f['raw'][:120]}")
```

---

## 4. GDB non-stop 模式下的并发分析

```gdb
# gdb_nonstop.gdb — 非阻塞调试会话（目标持续运行，按需检查）
set pagination off
set non-stop on              # non-stop: 其他线程继续运行
set target-async on

# 在关键函数设断点，断后自动继续（不停整个进程）
b sym.encrypt_data
commands
  printf "[hit] encrypt_data rdi=%p rsi=%p rdx=%ld\n", $rdi, $rsi, $rdx
  # 仅暂停当前线程，其他线程继续
  x/32xb $rdi
  continue &   # 异步继续（non-stop 模式下）
end

b sym.verify_token
commands
  printf "[hit] verify_token rdi=%p\n", $rdi
  x/s $rdi
  continue &
end

# 启动目标
run &
```

---

## 5. 协调会话状态报告格式

每次动态协调会话结束后，输出标准化报告：

```
🔧 动态协调会话报告
══════════════════════════════════════════
目标 PID    : 12345 (./target)
运行时长    : 3.2 秒
══════════════════════════════════════════
工具覆盖
  strace  : ✅ 附加成功  312 条系统调用
  ltrace  : ✅ 附加成功   47 条库函数调用
  GDB     : ✅ 附加成功    8 次断点触发
  Frida   : ✅ 注入成功    3 个 hook 活跃
  bpftrace: ✅ 运行中      2 个 uprobe 探针
══════════════════════════════════════════
实时发现（按优先级）
⭐ P0  [strace]  open("/etc/app/key.bin") → 读取16字节
⭐ P0  [ltrace]  strcmp("S3cr3t", input) → 候选密码
🔵 P1  [frida]   encrypt_data: key=61 62 63...
🔵 P1  [bpf]     mprotect(EXEC) @ 0x7f...
══════════════════════════════════════════
待人工确认（STAGED，未升 COMMITTED）
  - ltrace strcmp 参数是否为真实密码（需第二工具确认）
  - mprotect(EXEC) 之后的第一条指令地址
══════════════════════════════════════════
```
