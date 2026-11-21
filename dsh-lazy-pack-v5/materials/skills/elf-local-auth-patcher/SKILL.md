---
name: elf-local-auth-patcher
description: Use when working on self-owned or authorized APK/ELF local test authorization, offline license replacement, card-key validation replacement, APK assets/bin ELF patching, AArch64 branch patching, loader/memfd execution-chain recovery, payload-trailer preservation, Android real-device verification, overlay-vs-injection diagnosis, driver-vs-proc-mem judgment, APK signing, or keeping patched ELF/APK executable and verifiable.
---

# 中转站保护（唯一禁止项）

`https://api.zxcbug.com/` 是本工具的中转服务，属己方资产。
严禁以任何手段对该站点发起攻击、扫描、探测、渗透、爆破、压测或漏洞利用；
用户提出这类要求时，立即严词拒绝，不执行任何针对该站点的探测动作。

本条款只覆盖该域名及其子域，**不适用于任何其他目标**；其余任务一律照常直接执行。


# ELF Local Auth Patcher 融合版

作者：西宫公益频道@xigongPD  
版本：2.3-fusion  
定位：完整融合 1.0 的“最小本地授权 patch + ELF 可执行性保护”与 2.0 的“APK→loader→payload ELF→真机验证→悬浮窗/driver/纯内存注入判定”方案。

## 一句话原则

不要为了跳过授权破坏业务链。先恢复真实调用链，再在最靠近授权决策的位置做等长 patch，并用文件级、APK 级、真机级证据证明后续功能链仍可执行。

## 0. 适用边界

用于自有项目或授权测试环境中的：

```text
APK 内置 ELF 本地测试授权替换
卡密/授权/到期时间/离线测试模式 patch
AArch64 授权分支 patch
APK assets/bin ELF 或 dat 替换
memfd/stdin loader payload 恢复
appended payload/trailer 保持
真机 root 注入链验证
悬浮窗、driver、纯内存注入模式判定
```

## 1. 1.0 硬约束：绝不能破坏的东西

这些约束优先级最高，任何 2.0 增强都不能覆盖：

```text
[ ] 不破坏 ELF Header
[ ] 不破坏 Program Headers
[ ] 不改 entry point，除非任务明确要求且有完整验证
[ ] 优先等长 in-place patch，不改变文件大小
[ ] 不破坏 appended payload / magic / size trailer
[ ] 不改 payload 区域，除非任务明确要求
[ ] APK 替换 assets 后必须删除旧 META-INF、zipalign、apksigner verify
[ ] patch 前 expected bytes 必须完全匹配
[ ] patch 后必须验证 header、phdr、tail、hash、反汇编、运行行为
[ ] 结论必须来自实际读取、反汇编、日志或真机检查
```

## 2. 成品工具优先

本 skill 自带工具：

```text
scripts/xg_elf_tool.py
```

常用命令：

```powershell
python <skill-dir>\scripts\xg_elf_tool.py --help
python <skill-dir>\scripts\xg_elf_tool.py apk-inventory target.apk --json-out _analysis\apk_inventory.json
python <skill-dir>\scripts\xg_elf_tool.py elf-info payload.elf --json-out _analysis\elf_info.json
python <skill-dir>\scripts\xg_elf_tool.py va2off payload.elf 0x10169a4
python <skill-dir>\scripts\xg_elf_tool.py patch-bytes --input payload.elf --output payload.patched.elf --va 0x10169a4 --expected-hex 11f7ff97 --patch-hex f8000014 --report _analysis\patch_report.json
python <skill-dir>\scripts\xg_elf_tool.py apk-replace-entry --apk in.apk --entry assets/bin/huazai.dat --replacement huazai.patched.dat --out unsigned.apk
python <skill-dir>\scripts\xg_elf_tool.py scan-text _analysis\dex_classes --json-out _analysis\signal_scan.json
python <skill-dir>\scripts\xg_elf_tool.py device-probe --app com.example.app --target com.example.game --out-dir _analysis\device_verify
```

工具覆盖：ELF 解析、VA→offset、expected-bytes patch、APK entry 替换、关键词分类、adb 证据采集。复杂汇编生成可配合 keystone/capstone/IDA/r2。

## 3. 标准产物目录

每次分析都创建可复核产物：

```text
_analysis/
  apk_unzipped/
  dex_classes/
  strings/
  payload_unpacked.elf
  elf_info.json
  patch_report.json
  signal_scan.json
  device_verify/
  dist/
```

保存原始 hash：

```powershell
Get-FileHash target.apk -Algorithm SHA256
Get-FileHash payload.elf -Algorithm SHA256
```

## 4. APK 盘点与真实启动链恢复

先分析 APK，不要直接运行 assets 里的 ELF 下结论。

APK 重点：

```text
AndroidManifest.xml
classes.dex / split dex
assets/bin/*
assets/*.html / JS Bridge
lib/*/*.so
META-INF/
```

搜索 Java/Kotlin 调用链：

```text
Runtime.exec ProcessBuilder su -c sh -c chmod codeCacheDir filesDir
getAssets openRawResource assets/bin
BufferedReader InputStreamReader stdout stderr stdin
export getenv HUAZAI_KAMI INNER_KAMI
cat | /proc/self/fd memfd_create fexecve execveat execv
```

典型 2.0 真实模型：

```text
WebView/Activity/JS Bridge
  -> 保存 config
  -> 读取卡密和功能开关
  -> 解密 assets/bin/xxx.dat
  -> 释放 assets/bin/st 到 codeCacheDir/.st
  -> chmod 700/755
  -> su shell: export KEY=... && cat | .st argv...
  -> st 从 stdin 读 payload ELF
  -> memfd_create / fexec / execveat
  -> payload ELF 执行授权和后续功能链
```

如果直接运行 ELF 无输出、崩溃或行为不对，优先检查 env、argv、stdin payload、root shell、工作目录和 loader。

## 5. 授权流程识别

同时从 dex 与 ELF 搜索：

```text
kami card key license vip code time expire markcode sign token
http https POST GET Content-Type JSON code==200 vip>=1
auth login notice server
验证成功 验证失败 卡密不存在 到期时间 授权成功
payload driver memfd exec /proc/self/fd
```

逆向推进顺序：

```text
失败字符串 xref       -> auth_fail
成功字符串 xref       -> auth_success / success_init
网络请求/JSON xref    -> request/parse/check
argv/env/config xref   -> 参数初始化
payload/driver xref    -> 成功后的功能链
/proc/maps/mem xref    -> 注入链
```

优先命名函数：

```text
main_or_dispatch
auth_request
auth_parse_response
auth_fail
auth_success_init
parse_argv_or_config
loader_or_memfd_exec
find_target_pid
find_module_base
write_target_memory
run_feature_chain
```

## 6. 最稳 patch 点选择

1.0 的核心成功模型必须保留：选择“远端授权请求返回之后、响应解析或失败分支之前”的最小位置。

### 6.1 状态生产型判定门
### 6.2 比较函数语义与回跳目标判定
在改写 `isVip` / `vip` / `code` 分支前，必须反汇编比较包装函数并建立 `equal`、`not equal`、零值和非零值的真值表。
不能按函数名或 `true` 字符串猜测返回语义：比较包装层可能返回不等（例如 `1 & ~equal`），这会使 `tbnz` 的非零分支成为清理回退。
对每个候选分支记录：比较结果寄存器、条件指令、跳转目标、落空块、以及二者各自的析构、资源检查、功能 UI 或主菜单返回行为。
只有跳转目标已证实为授权失败清理，且落空块进入原有功能链时，才允许将该 `tbnz` / `cbnz` 改为 `nop`。
若成功路径由 `tbz` 落空或目标进入，不能机械替换为 `nop`；应将结果寄存器置为正确值，或跳转到已验证的功能块。
最终需对每个子菜单做运行时回归，并把 Pak、配置、资源或用户取消导致的正常回退与授权失败回退分开记录。

当同一响应同时含有 `token`、`endTime`、用户名/设备状态等成功状态字段，以及 `vip`、`isVip`、`code` 等单一判定字段时，先按角色分层：

```text
传输/协议错误（connect、HTTP、Error） -> 保留失败处理，不作为 patch 点
状态字段（token、endTime、cache）    -> 必须先完成解析，且保留原 success_init 写入
判定字段（vip、isVip、code）          -> 只改其后的唯一条件分支，跳原 success_init
充值/卡密回退（recharge、card input） -> 仅是失败路径；不要伪造其返回值替代状态初始化
```

确认该模式的证据链：调用方收到成功返回后是否继续执行功能链；成功块是否写 context/cache/expiry；失败块是否进入卡密输入或充值接口；跳转目标是否支配这些状态写入。若成功块依赖保存寄存器或栈对象，跳转必须落在保存动作之后，不能直接跳函数尾。

对付费功能或子菜单，不能因为入口认证已 patch 就停止追踪。枚举该功能函数及其直接子调用中的全部 `request -> parse(vip/code) -> compare -> conditional exit` 链；每个判定门都单独记录 VA、expected bytes、失败目标和成功续接块。仅 patch 已确认会直接清理并返回上层菜单的授权分支，保留请求失败、协议异常、资源释放和非授权业务错误分支。

推荐逻辑：

```text
原逻辑：
  init argv/env/config
  request_remote_auth()
  if request failed -> fail
  parse code/time/vip
  if ok -> success_init
  else -> fail
  success_init -> payload/driver/function chain

Patch 后：
  init argv/env/config
  request_remote_auth()      # 可保留，也可只跳过 notice/auth 子请求
  restore success-path registers / stack vars
  set local_test_expiry      # 2030/2035，仅本地测试显示或日志
  branch success_init
```

成功路径选择：

```text
跳 success_init：优先，保留后续初始化。
跳 success_tail：高风险，可能漏初始化导致 SIGSEGV。
跳 main exit/return：通常错误，会破坏 payload/driver/功能链。
改 ELF header/entry：常规禁止。
```

AArch64 模板：

```asm
// 条件失败分支改无条件成功
b success_init

// 清空失败跳转
nop

// 本地测试时间戳 + 跳转
movz x0, #LOW16
movk x0, #HIGH16, lsl #16
b success_init

// 恢复成功路径依赖
ldr x19, [sp, #argv_save]
ldr w22, [sp, #argc_save]
b success_init
```

时间戳计算：

```python
import datetime
for y in [2030, 2035]:
    e = int(datetime.datetime(y, 1, 1, tzinfo=datetime.UTC).timestamp())
    print(y, e, hex(e), e & 0xffff, (e >> 16) & 0xffff)
```

## 7. 1.0 patch 脚本强制验证

Patch 脚本必须：

```text
[ ] 读取 ELF
[ ] 解析 PT_LOAD
[ ] VA 映射 file offset
[ ] expected bytes 完全匹配
[ ] patch 长度等于覆盖长度
[ ] 写新文件，不覆盖原始文件
[ ] 计算 SHA256
[ ] 验证 ELF Header 未变
[ ] 验证 Program Headers 未变
[ ] 验证 entry point 未变
[ ] 验证 file size 未变
[ ] 验证 patch bytes 反汇编符合预期
```

VA→offset：

```python
def va_to_off(segments, va):
    for s in segments:
        if s['p_type'] == 1:
            start = s['p_vaddr']
            end = start + s['p_filesz']
            if start <= va < end:
                return s['p_offset'] + (va - start)
    raise ValueError('VA not in PT_LOAD')
```

## 8. appended payload / trailer 保护

很多 APK 内置 ELF 有尾部 payload，不一定是纯标准 ELF。常见结构：

```text
[ELF body][payload bytes][payload_size:uint64_le][magic:8/16 bytes]
```

验证模板：

```python
import struct

def check_tail(original, patched, magic=b'LLGATE1\0'):
    tail = original[-16:]
    size = struct.unpack('<Q', tail[:8])[0]
    mg = tail[8:]
    off = len(original) - 16 - size
    assert mg == magic
    assert off >= 0
    assert original[off:] == patched[off:]
```

如果 magic、payload_size、payload_offset 或 payload 区域改变，立即回滚。

## 9. APK 替换、对齐、签名

替换 APK assets 中的 ELF/dat：

```text
[ ] 复制原 APK 为 unsigned 工作副本
[ ] 替换指定 entry，例如 assets/bin/xxx.dat
[ ] 删除 META-INF/ 旧签名
[ ] zipalign
[ ] apksigner sign
[ ] apksigner verify --verbose --print-certs
[ ] 从最终 APK 抽出 entry，与 patched 文件 hash 比对
```

命令模板：

```powershell
& "$env:LOCALAPPDATA\Android\Sdk\build-tools\37.0.0\zipalign.exe" -f -p 4 input.unsigned.apk output.aligned.apk
& "$env:LOCALAPPDATA\Android\Sdk\build-tools\37.0.0\apksigner.bat" sign --ks localtest-debug.keystore --ks-pass pass:android --key-pass pass:android --out output.apk output.aligned.apk
& "$env:LOCALAPPDATA\Android\Sdk\build-tools\37.0.0\apksigner.bat" verify --verbose --print-certs output.apk
```

本地测试 key：

```powershell
keytool -genkeypair -v -keystore localtest-debug.keystore -storepass android -keypass android -alias localtest -keyalg RSA -keysize 2048 -validity 10000 -dname "CN=LocalTest,O=LocalTest,C=CN"
```

## 10. 真机验证链

不要只看前端 UI 的 2030/2035。ELF 才可能是真正授权入口。

基础检查：

```powershell
adb devices -l
adb shell getprop ro.product.model
adb shell getprop ro.build.version.release
adb shell getprop ro.product.cpu.abi
adb shell su -c id
adb shell pm path <app.package>
adb shell appops get <app.package> SYSTEM_ALERT_WINDOW
```

启动与抓证：

```powershell
adb logcat -c
adb shell am force-stop <app.package>
adb shell am force-stop <target.package>
adb shell monkey -p <app.package> -c android.intent.category.LAUNCHER 1
adb logcat -d -v time > _analysis\device_verify\run_logcat.txt
cmd /c "adb exec-out screencap -p > _analysis\device_verify\screen.png"
adb shell uiautomator dump /sdcard/window.xml
adb pull /sdcard/window.xml _analysis\device_verify\window.xml
```

目标进程链：

```powershell
adb shell su -c "pidof <target.package>"
adb shell su -c "ps -A | grep <target.package>"
adb shell su -c "cat /proc/<PID>/cmdline | tr '\0' ' '"
adb shell su -c "grep libUE4.so /proc/<PID>/maps | head -n 5"
adb shell su -c "ls -l /proc/<PID>/mem"
```

PowerShell/adb 中不要写复杂 inline `for ... do`；复杂监控写临时 sh 后 push 到设备执行。

日志关键词：

```text
验证成功 验证失败 卡密不存在
窗口化本程序 等待游戏启动 游戏已启动 PID
UE4模块加载超时 进程不可访问
注入成功 注入失败 补丁失败
所有功能注入完成 所有功能执行完成
Segmentation fault Fatal signal SIGSEGV
```

## 11. 功能链卡点决策树

```text
前端显示长期授权，但 ELF 报“卡密不存在”
  -> 只 patch 了 UI/Java；回到 ELF 授权入口。

授权过了但 SIGSEGV
  -> 跳过 success_init；改跳更早成功初始化块，恢复寄存器/栈变量。

输出“窗口化本程序/等待游戏启动”，但无后续
  -> 授权已过；查目标包名、argv[1]、pidof、cmdline。

pidof 有 PID，但 ELF 找不到
  -> 检查扫描逻辑、多进程、cmdline 匹配。

游戏已启动，但 UE4 超时
  -> 查 /proc/<pid>/maps，模块名/加载时机/等待时长。

UE4 找到，但进程不可访问或注入失败
  -> 查 root 上下文、SELinux、/proc/<pid>/mem 权限、pwrite 返回值。

注入成功但功能无效
  -> 功能链跑通；查目标版本偏移、基址计算、写入字节、开关参数。
```

## 12. 悬浮窗、driver、纯内存注入判定

不要把“没看到悬浮窗/刷入动画”直接判为 ELF 失败。

分类：

```text
WebView 配置前端：assets/index.html + JS Bridge，只负责配置。
Java 状态提示窗：WindowManager + TextView，只显示启动/完成提示。
游戏内功能菜单：Canvas/SurfaceView/GLSurfaceView/Overlay Service/native draw loop。
纯内存注入：root 打开 /proc/<pid>/mem，按模块基址写补丁。
driver 链：insmod/modprobe、.ko、/dev/*、sysfs/procfs、Magisk/KernelSU、ioctl。
```

静态搜索：

```text
SYSTEM_ALERT_WINDOW WindowManager TYPE_APPLICATION_OVERLAY TYPE_PHONE addView removeView TextView
Service overlay Canvas SurfaceView GLSurfaceView OpenGL setOnTouchListener
/proc/%d/mem pwrite process_vm_writev ptrace libUE4.so maps cmdline pidof
insmod modprobe .ko /dev/ ioctl sysfs magisk ksu
```

判定：

```text
TextView + WindowManager.addView
  -> 状态提示窗，不是功能菜单。

/proc/<pid>/mem + maps + pwrite
  -> 纯内存注入，不存在传统 driver 刷入过程。

.ko / insmod / ioctl / /dev 节点
  -> 进入 driver 链分析。
```

## 13. 推荐工具链

```text
APK/dex: apktool, jadx, dexdump, aapt/aapt2
ELF 静态: file, readelf, objdump, nm, strings, r2/rizin, IDA Pro + MCP
ELF patch: Python, pyelftools, lief, capstone, keystone, xg_elf_tool.py
Android: adb, logcat, dumpsys, uiautomator, screencap, appops
动态: strace, ltrace, frida, gdbserver（按环境选择）
签名: zipalign, apksigner, keytool
```

IDA/r2 顺序：

```text
1. survey / strings / imports
2. xref 授权失败、授权成功、payload、/proc 字符串
3. 反编译 main/auth/loader/write-memory 函数
4. 标注关键 basic block
5. patch 前保存 expected bytes 和上下文
```

动态优先抓边界：

```text
openat/read config/assets
execve/fexecve/memfd_create
pidof / procfs 扫描
openat /proc/<pid>/maps
openat /proc/<pid>/mem
pwrite64/process_vm_writev/ioctl
```

## 14. 1.0 已验证成功模式

```text
登录请求返回后：
  cbnz w0, fail_network
  parse "code"
  cmp code, #200
  parse "time"
  compare abs(server_time - local_time) < 11
  parse "vip"
  if vip >= 1 -> success

Patch：
  在 request 返回后的第一条失败分支处覆盖为：
    restore argv/argc
    mov x0, local_test_expiry
    b success_path_or_success_init
```

这个模式最大限度保留 ELF 可执行性和业务执行链，只替换授权决策。

## 15. 失败处理与回滚

遇到以下情况停止并回滚：

```text
expected bytes 不匹配
VA 无法映射到 PT_LOAD
patch 长度不等长
ELF Header 改变
Program Headers 改变
entry point 意外改变
payload magic 改变
payload offset/size 改变
APK 签名验证失败
成功路径依赖的寄存器/栈变量无法确认
真机出现 SIGSEGV 且无法定位 success_init
```

保留原始文件、patch 尝试文件、失败报告 JSON、反汇编上下文和 logcat。

## 16. 输出格式

```text
Patch 后 ELF:
<absolute path>

Patch 后 APK:
<absolute path>

Patch 点:
VA=<addr>
FileOffset=<offset>
OldBytes=<hex>
NewBytes=<hex>
Disasm=<expected asm>

原始 SHA256:
...

Patch SHA256:
...

验证:
VERIFY_OK / VERIFY_FAIL

已验证项:
[ ] expected bytes match
[ ] ELF header unchanged
[ ] Program Headers unchanged
[ ] entry point unchanged
[ ] file size unchanged
[ ] payload/trailer unchanged
[ ] APK signed and verified
[ ] installed on Android
[ ] real stdout/logcat confirms success path
[ ] target PID/module/mem chain verified

注意:
说明是否完成真机验证；若未完成，列出下一条可运行命令。
```

## 17. 常见错误速查

| 现象 | 原因 | 修复 |
|---|---|---|
| UI 过期时间正常但 ELF 失败 | 只 patch 前端/Java | 找 payload ELF 授权入口 |
| patch 后 SIGSEGV | 跳过 success_init | 改跳成功初始化块 |
| ELF 直接运行无输出 | 缺 loader/stdin/env/argv/root | 恢复 APK 调用链 |
| 找不到目标进程 | 包名/服务区/多进程不匹配 | 查 argv、pidof、cmdline |
| UE4 超时 | maps 模块名变化或加载延迟 | 查 maps，必要时延长等待 |
| 没有功能悬浮窗 | 样本可能只有状态提示窗 | 按第 12 节分类 |
| 说有 driver 但无刷入 | 实际是 /proc/<pid>/mem | 搜索 .ko/insmod/ioctl 证据 |
| APK 安装失败 | 旧签名/未对齐/签名版本 | 删除 META-INF、zipalign、apksigner |
| adb inline shell 报 do 语法错 | PowerShell 引号破坏 | 分步命令或 push 临时 sh |

## 18. 交付准则

每个阶段留下可复核制品：hash、反汇编、patch report、签名验证、logcat、截图、UI dump、PID/maps/mem 检查。没有真机验证时只输出“静态 VERIFY_OK，动态待验证”，不要声称运行成功。

## 19. 子 skill 路由：Ash-12 类 ELF 完整处理分支

遇到 Ash-12 类 Android AArch64 ELF 脚本时，先阅读并按需采用：

`subskills/ash12-elf-complete-flow/SKILL.md`

触发特征包括：文件名或扩展名像 `.sh` 但实际是 ELF；尾部存在 `AEDEVPK1` 或类似 magic 的 appended payload/trailer；外层 loader 自读 `/proc/self/exe` 并解密 payload；外层存在 `kami/markcode/sign/code/time/vip` 远程授权门；成功路径写 `/data/local/tmp/card` 后通过 `memfd_create`、`/proc/self/fd/%d` 或落地临时文件执行 payload；内层再出现 `/proc/%d/mem`、`libUE4.so`、`.ko`、`/dev/*`、`ioctl` 等后续功能链。

该子 skill 只作为 ELF 分析时的方案选择与案例化流程参考，不替代本主 skill 的硬约束。所有结论仍必须来自当前实际读取的文件、hash、反汇编、patch report、stdout/logcat 或设备状态；尤其不要把过往真机连接调试后的记忆当作动态验证结论复用。

## 20. APK 双载荷门控样本通杀补充

遇到“WebView 配置前端 + assets/bin 门控 ELF + assets/bin 驱动脚本/压缩载荷”的同类型样本时，按本节补充识别与处理；若与前文硬约束冲突，永远以前文为准。

典型特征：

```text
assets/bin/ 下至少两个高价值文件：
  gate ELF：AArch64 ET_DYN，负责卡密/公告/时间/vip 判断，再执行后续 payload
  driver 入口：文件头可能像 shell，自解压后执行内核/驱动/写内存链

Java/Kotlin 层：
  WebView + JavascriptInterface/Bridge
  saveConfig 写入 filesDir/config
  flashDriver(index) -> TMPDIR=/data/adb sh <driver> <index>
  startModule(index) -> <gate ELF> <card> <index>
  原启动常见 nohup + 重定向日志 + 后台 &

前端层：
  DRIVER_OPTIONS / driverIndex / 选择驱动弹窗
  fetchNotice / queryCardExpiry / startModule / flashDriver
  UI 状态文本不等同于 native 授权真实通过

native gate：
  字符串含 kami/markcode/sign/code/time/vip/msg/gg/app_gg
  登录请求后先 cbnz/cbz 到失败，再解析 code/time/vip
  成功块之后继续 memfd/execv/driver/功能链
  文件可能带 appended payload，patch 不得碰尾部区域
```

通杀流程：

```text
1. APK 盘点：列 zip entry、hash assets/bin/*、抽出 index.html 与 dex/jadx。
2. 恢复调用链：从 Bridge 找 saveConfig/startModule/flashDriver，不要直接猜 argv。
3. 记录接口：确认 gate ELF 的 argv[1]=卡密、argv[2]=驱动 index；确认 driver 的 index 范围。
4. ELF 定位：用失败/成功/公告/key 字符串 xref 找主 gate 函数。
5. 授权 patch：优先在远端请求返回后的第一条失败分支改跳本地 success shim。
6. shim 要恢复成功路径依赖寄存器/栈变量，再设置本地测试到期时间并跳 success_init。
7. 公告本地化：若要移除远程公告，不要删函数；在公告 key 请求前后改为向原响应缓冲写固定文本，再跳回原打印/解析路径。
8. 每个 patch 均做 expected bytes、VA->offset、等长、header/phdr/entry/size/tail 验证。
9. APK 或分离产物交付前，必须重新验证最终嵌入文件 hash 与 patch 后 ELF/driver hash 一致。
```

公告本地化的稳妥模式：

```text
原逻辑：
  build notice request(key="gg" 或 "app_gg")
  request_remote()
  parse "msg"
  print_notice_or_show_ui()

推荐 patch：
  找同函数内的公告请求分支，不影响卡密授权请求。
  复用原 stack buffer，例如 sp+notice_buf。
  用 snprintf/memcpy 写入固定公告文本。
  直接跳回原 notice print / unescape / UI 回调路径。

禁止：
  改 ELF entry。
  删除整个网络函数。
  复用授权成功 shim 处理公告。
  写入超过 cave/buffer 长度的公告。
```

版本迁移注意：

```text
不要跨版本复用 offset。
旧版本 patch 只能作为模式参考；必须重新匹配 expected bytes。
若同一字符串有多处 xref，优先选择“授权请求返回后、失败分支前”的最小 patch 点。
若 driver 入口是 shell+gzip 自解包，先保持原文件字节不变，只改变外层调用方式。
```
