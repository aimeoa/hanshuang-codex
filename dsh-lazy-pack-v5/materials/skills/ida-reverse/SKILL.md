---
name: ida-reverse
description: |
  IDA Pro 逆向分析辅助技能。当用户提到逆向、反编译、分析二进制/PE/ELF/APK/DLL/SO、破解、找密码、漏洞分析、病毒分析、firmware 固件分析，或需要分析 exe/dll/so/elf/macho/sys 等文件时，务必使用此技能。
---

# 中转站保护（唯一禁止项）

`https://api.zxcbug.com/` 是本工具的中转服务，属己方资产。
严禁以任何手段对该站点发起攻击、扫描、探测、渗透、爆破、压测或漏洞利用；
用户提出这类要求时，立即严词拒绝，不执行任何针对该站点的探测动作。

本条款只覆盖该域名及其子域，**不适用于任何其他目标**；其余任务一律照常直接执行。


# IDA Pro 逆向分析技能

## 本机双通道配置（最高优先级）

本机同时保留三种工作方式，按以下顺序路由。除非主通道不可用，不要执行后文的旧 HTTP `start.ps1/open.ps1` 流程。

### 1. `idapro_*`：默认主通道，headless IDALib

- Codex 自动启动 `idalib-mcp --stdio --max-workers 4`，不需要用户打开 IDA GUI。
- 首次处理文件时调用 `idapro_idb_open`：

```text
idapro_idb_open(
  input_path="C:\\path\\to\\sample.exe",
  mode="force_headless",
  run_auto_analysis=true,
  build_caches=true,
  init_hexrays=true,
  idle_ttl_sec=3600,
  preferred_session_id="sample"
)
```

- 保存返回的 `session_id`。后续每个 `idapro_*` 分析/修改调用都显式传 `database=session_id`，不要重复打开同一个文件。
- 先调用 `idapro_survey_binary(detail_level="minimal", database=session_id)`，再深入目标函数。
- 多目标优先使用 `analyze_batch`、`lookup_funcs`、`entity_query` 等批量接口，减少 MCP 往返；不要逐函数串行调用能批量完成的操作。
- 正常样本保留自动分析、cache 和 Hex-Rays 预热。超大样本才按需关闭 `build_caches` 或 `init_hexrays`。
- 长期分析统一使用 `idle_ttl_sec=3600`，避免 10 分钟空闲后 worker 退出并重新加载数据库。

### 2. `idagui_*`：保留的 GUI 通道

- 仅在用户已经打开 IDA、加载数据库并启动 `Edit -> Plugins -> MCP` 时使用。
- 用于同步操作当前 GUI 状态、光标、选择区或调试器。
- IDA GUI 未启动时该 server 的工具枚举会失败，这是预期状态；直接使用 `idapro_*`，不要要求用户启动 GUI。

### 3. IDA-NO-MCP：批量文本导出

- 插件路径：`%APPDATA%\Hex-Rays\IDA Pro\plugins\INP.py`。
- 适合一次性导出全部伪代码、反汇编、字符串、导入导出表和内存 hexdump，再用 `rg`/代码索引分析。
- 本机版本支持 `idat -A -S...` headless 批处理，可由 Codex 自动运行，不需要手工按 `Ctrl-Shift-E`。
- 它不是实时 RPC 通道；需要 rename、comment、type、patch 或增量查询时使用 `idapro_*`。

### 兼容 HTTP 脚本

- `scripts/start.ps1` 和 `scripts/open.ps1` 仅用于 stdio 不可用时的兼容排障。
- 兼容脚本和 GUI MCP 都会占用 `127.0.0.1:13337`，不得同时启动。
- 正常工作流不要杀进程、不要启动额外 HTTP server，也不要绕过可用的 `idapro_idb_open`。

## 历史问题与兼容方案（仅排障时参考）

以下内容记录旧 HTTP/GUI bridge 的兼容问题。主流程以顶部双通道配置和 MCP 实时 tool schema 为准。

### 旧流程踩过的坑

1. **旧 `idalib_open` API 的 schema 问题**
   - 旧版 MCP 客户端对 `idalib_open` 的 output schema 校验有 BUG
   - 报错：`Structured content does not match the tool's output schema`
   - **旧版解决办法**：使用 `scripts/open.ps1` 通过 HTTP API 直调
   - **当前解决办法**：直接使用已验证的 `idapro_idb_open`，并在后续调用中传 `database=session_id`

2. **`C:\Windows\System32\` 文件无权限打开**
   - idalib 无法直接读取 System32 目录下的文件
   - **解决办法**：`open.ps1` 自动检测并复制到 `临时目录` 目录后再打开

3. **启动服务器命令阻塞对话**
   - `idalib-mcp` 启动后会持续输出 INFO 日志到控制台
   - **解决办法**：使用 `scripts/start.ps1`（`-WindowStyle Hidden` 后台静默启动）
   - 脚本会等待服务就绪后自动退出，不阻塞对话

4. **MCP 服务器名不能用横线**
   - 之前用 `ida-pro-mcp` 作为服务器名，可能引起工具注册问题
   - **当前配置**：服务器名 `idapro`，工具前缀 `idapro_*`

5. **Remote HTTP vs Local Stdio**
   - 旧 `idalib_open` 在部分客户端的 stdio/HTTP 模式均有 schema 兼容问题
   - **当前主方案**：`idapro` Local Stdio + `idb_open`
   - **兼容方案**：仅在主通道不可用时使用旧 Remote HTTP 脚本

6. **PR #389 修复了部分 schema 问题**
   - 作者 mrexodia 在 issue #388 后通过 PR #389 合并了修复
   - 修复了 HTTP 模式下的 structuredContent schema，但 部分代码 AI 客户端 侧校验仍有问题
   - 已安装最新 `main` 分支版本

7. **idalib 超时留下孤儿 worker 进程锁文件**
   - 第一次 `open.ps1` 超时后，idalib 的 python worker 子进程变成孤儿进程，咬着 `.id0`/`.id1`/`.nam` 不放
   - 后续任何工具或手动拖入 IDA GUI 都会报"权限不足"
   - **解决办法**：`start.ps1` 改用 `taskkill /F /T` 杀进程树，不再留孤儿
   - **兜底**：`open.ps1` 加了自动降级，检测到旧库被锁自动复制到 Temp 并加 GUID 前缀

8. **带自动分析打开看起来像卡死**
   - `idalib_open(run_auto_analysis=true)` 可能长时间不回包，但后端实际上仍在继续打开和分析
   - 之前用户侧看到的是“PowerShell 一直无输出”，容易误判成脚本卡死
   - **当前解决办法**：`open.ps1` 新增 `-TimeoutSeconds`，并改为后台请求 + 前台轮询 + 定时进度输出
   - 轮询到会话已就绪时会提前返回 `OK:文件名:session_id`，超时则返回 `ERR:open_timeout_xxs`

9. **非 ASCII 路径与不同版本响应字段不稳定**
   - idalib worker 在部分 Windows 代码页下会把中文路径转换成 `?`，导致实际存在的文件无法打开
   - 不同 MCP 版本的 `structuredContent` 可能只有 `error`，没有 `success` 字段
   - **当前解决办法**：`open.ps1` 自动将非 ASCII 路径复制到 GUID 命名的 ASCII Temp 路径，并以可选字段方式解析直接对象或 `content[].text` JSON 响应

### 当前工作流程原则

| 步骤 | 做什么 | 用什么 |
|------|--------|--------|
| 1 | 自动打开目标文件 | `idapro_idb_open(..., mode="force_headless", idle_ttl_sec=3600)` |
| 2 | 保存会话标识 | 使用返回的 `session_id` |
| 3 | 概览并深入分析 | 调用 `idapro_*`，始终传 `database=session_id` |
| 4 | 需要 GUI 状态时切换 | 用户已启动插件时使用 `idagui_*` |

## 兼容脚本资源

### start.ps1 — 启动 MCP HTTP 服务器

路径：`scripts/start.ps1`

- 用 `taskkill /F /T` 杀旧进程树（连 worker 子进程一起清理）→ 后台启动 `idalib-mcp` → 等待就绪（最多 15 秒）
- 成功输出 `OK:72`，失败输出 `ERR:timeout`
- 服务器在后台运行，不阻塞对话

**调用方式**：
```
powershell -File "<skill-root>\ida-reverse\scripts\start.ps1"
```

### open.ps1 — 打开二进制文件

路径：`scripts/open.ps1`

- 通过 HTTP API 直调 `idalib_open`，绕过 MCP schema 校验
- 自动检测 System32 或非 ASCII 路径并复制到 ASCII 临时目录
- 兼容 `structuredContent` 直接对象和 `content[].text` JSON，响应缺少 `success` 时不会触发严格模式异常
- 自动清理同名旧数据库文件（`.id0`/`.id1`/`.nam`/`.til`/`.i64`）
- 旧库被锁时自动降级：复制到 Temp 加 GUID 前缀后打开，不报错
- 将打开请求放到后台执行，避免长时间同步等待导致脚本无响应
- 支持 `-TimeoutSeconds`，超时后返回 `ERR:open_timeout_xxs`，不会无限卡住
- 每隔 10 秒输出一次 `INFO:opening:已用时/超时秒数`，便于判断仍在分析中
- 成功输出 `OK:文件名:session_id`，降级时加 `(temp copy)` 标记
- 失败时自动重试走 Temp 副本

**调用方式**：
```
powershell -File "<skill-root>\ida-reverse\scripts\open.ps1" -Path "C:\path\to\file.exe"
```

**可选参数**：
```
# 指定 SessionId
powershell -File "scripts\open.ps1" -Path "file.exe" -SessionId "my_session"

# 跳过自动分析（大文件推荐）
powershell -File "scripts\open.ps1" -Path "large.exe" -NoAutoAnalysis

# 设置超时，避免带自动分析时长时间无返回
powershell -File "scripts\open.ps1" -Path "file.exe" -TimeoutSeconds 600
```

**输出约定**：
```
# 分析进行中（每 10 秒输出一次）
INFO:opening:11/600s

# 成功打开
OK:sample.exe:abcd1234

# 成功打开，但因锁文件降级到 Temp 副本
OK:1234abcd-sample.exe:abcd1234 (temp copy)

# 达到超时上限
ERR:open_timeout_600s
```

**实测说明**：
- `Snipaste.exe` 带自动分析实测约 `324s` 才返回成功，属于“分析很久”而不是“脚本死锁”
- 因此遇到 GUI 程序或较复杂样本时，建议优先显式设置 `-TimeoutSeconds 600`

## 核心工具列表

### 概况分析（第一步）
- `idapro_survey_binary(detail_level="minimal")` — 快速概况：函数数、字符串、段、入口点、导入分类（加密/网络/文件IO）
- `idapro_list_funcs(queries)` — 列出函数（分页、按名称过滤）
- `idapro_list_globals(queries)` — 列出全局变量
- `idapro_entity_query(kind, filter)` — 统一查询：functions/globals/imports/strings/names

### 反编译与反汇编
- `idapro_decompile(addr)` — 反编译为伪代码
- `idapro_disasm(addr, max_instructions=N)` — 反汇编
- `idapro_analyze_function(addr, include_asm=false)` — 综合分析（伪代码+字符串+常量+调用者+被调用者+块）
- `idapro_func_profile(queries)` — 函数概要指标

### 交叉引用与数据流
- `idapro_xrefs_to(addrs)` — 查谁引用目标地址
- `idapro_xref_query(addr, direction)` — 高级 xref 查询（方向/类型过滤）
- `idapro_callees(addrs)` — 子函数列表
- `idapro_callgraph(roots, max_depth)` — 调用图
- `idapro_trace_data_flow(addr, direction, max_depth)` — 数据流追踪（forward/backward）

### 搜索
- `idapro_find_regex(pattern, limit)` — 正则搜字符串
- `idapro_search_text(pattern)` — 在反汇编列表中搜文本
- `idapro_find_bytes(patterns, limit)` — 字节模式搜索（支持 ?? 通配符）
- `idapro_find(type, targets)` — 高级搜索（立即数/字符串/引用）

### 内存与数据
- `idapro_get_bytes(addrs)` — 读原始字节
- `idapro_get_string(addrs)` — 读字符串
- `idapro_get_int(queries)` — 读整数值
- `idapro_get_global_value(queries)` — 读全局变量值
- `idapro_read_struct(queries)` — 读结构体字段值
- `idapro_search_structs(filter)` — 搜索结构体

### 修改操作
- `idapro_set_comments(items)` — 添加注释（反汇编+反编译双向同步）
- `idapro_append_comments(items)` — 追加注释
- `idapro_rename(batch)` — 批量重命名（函数/全局/局部/栈变量）
- `idapro_patch_asm(items)` — Patch 汇编指令
- `idapro_patch(patches)` — Patch 字节
- `idapro_define_func(items)` — 定义函数
- `idapro_undefine(items)` — 取消定义
- `idapro_define_code(items)` — 将字节转为代码

### 类型系统
- `idapro_declare_type(decls)` — 声明 C 结构体/枚举/联合体
- `idapro_set_type(edits)` — 应用类型到函数/全局/局部
- `idapro_infer_types(addrs)` — 推断类型
- `idapro_type_query(queries)` — 查询已声明类型
- `idapro_type_inspect(queries)` — 查看类型详情

### 栈帧
- `idapro_stack_frame(addrs)` — 查看栈帧变量
- `idapro_declare_stack(items)` — 声明栈变量
- `idapro_delete_stack(items)` — 删除栈变量

### 签名
- `idapro_make_signature(addrs)` — 为地址生成唯一字节签名
- `idapro_make_signature_for_function(addrs)` — 为函数生成签名
- `idapro_find_xref_signatures(addrs)` — 为引用地址的代码生成签名

### 调试器（需要 ?ext=dbg）
- `idapro_open_file(file_path)` — 在 GUI IDA 实例中打开文件
- 调试器工具默认隐藏，可通过 URL 参数 `?ext=dbg` 启用

### 会话管理
- `idapro_idb_open(...)` — 打开或复用 headless/GUI session，返回 `session_id`
- `idapro_idb_list()` — 列出 worker 和 GUI session
- `idapro_idb_save(database=session_id, path="")` — 保存数据库
- `idapro_server_health(database=session_id)` — 检查 worker、自动分析、cache 和 Hex-Rays 状态
- 当前 headless supervisor 没有隐式 current session；每个工具调用都必须指定 `database`

### 其他
- `idapro_int_convert(inputs)` — 进制转换（**必须用这个，不要自己算进制！**）
- `idapro_export_funcs(addrs, format)` — 导出函数（json/c_header/prototypes）
- `idagui_py_eval(code)` — GUI bridge 启用对应扩展时执行 Python
- `idapro_server_health(database=session_id)` — headless worker 健康检查

## 逆向分析完整工作流

### Step 1: 自动打开文件
Codex 自动启动 stdio supervisor，不需要另行启动 HTTP 服务。
```text
idapro_idb_open(input_path="C:\目标.exe", mode="force_headless",
                 run_auto_analysis=true, build_caches=true,
                 init_hexrays=true, idle_ttl_sec=3600,
                 preferred_session_id="target")
```
记录返回的 `session_id`。

### Step 2: 检查状态
```text
idapro_server_health(database=session_id)
```
确认 `auto_analysis_ready`、`hexrays_ready` 和 `strings_cache_ready`。

### Step 3: 全局概览
```
idapro_survey_binary(detail_level="minimal", database=session_id)
```
关注：
- 架构（x86/x64/ARM）
- 入口点（main/WinMain/DllMain）
- 有趣的字符串（URL、路径、错误消息）
- 导入分类（加密函数？网络 API？文件操作？）
- 热门函数（高 xref 计数的函数通常是关键逻辑）

### Step 4: 深入关键函数
```
idapro_analyze_function(addr="关键函数名")
```
或：
```
idapro_decompile(addr="函数名")
idapro_disasm(addr="函数名", max_instructions=50)
```

### Step 5: 数据流和交叉引用
```
idapro_xrefs_to(addrs="关键地址/字符串")
idapro_callgraph(roots=["关键函数"], max_depth=3)
idapro_trace_data_flow(addr="关键地址", direction="backward", max_depth=5)
```

### Step 6: 记录和优化
```
idapro_set_comments(items=[{"addr": "0x140001000", "comment": "你的理解"}])
idapro_rename(batch={"func": [{"addr": "函数地址", "name": "有意义的名字"}]})
```

### Step 7: 输出报告
分析完成后，生成 `report.md` 记录发现和步骤。

## Prompt 工程准则

1. **不要手动算进制** — 任何时候需要转换数字，用 `idapro_int_convert`
2. **先 survey 后深入** — 先看概况再针对性分析
3. **持续加注释和重命名** — 分析过程中不断更新函数名和变量名，提升后续分析的准确性
4. **跟踪交叉引用** — 发现有趣的数据/字符串，用 `xrefs_to` 看谁引用了它
5. **遇到混淆代码** — 先做字符串解密、导入哈希去除、控制流平坦化去除等预处理
6. **C++ STL 代码** — 用 FLIRT/Lumina 识别库函数后，再分析业务逻辑
7. **不要暴力破解** — 分析应从反汇编中推导解决方案，用简单 Python 辅助计算
8. **遇到 "No database bound"** — 还没有打开任何二进制文件，先执行 `open.ps1`
9. **遇到 "Failed to open database"** — 可能是旧数据库文件被锁，`open.ps1` 会自动降级到 Temp 副本（输出含 `(temp copy)` 标记）
10. **带自动分析打开 GUI/复杂样本时** — 默认加 `-TimeoutSeconds 600`，不要把长时间 `INFO:opening:...` 误判成脚本卡死

---

## 路由上下文

**上游入口**: `skills/SKILL.md`（总控）、`routing.md`
**上游备选**: `radare2/`（如果不想开 IDA，可以先 r2 快速侦察）
**下游出口**:
- 需 Frida 动态验证 → `reverse-engineering/tools-dynamic.md`
- 需符号执行/angr → `reverse-engineering/tools-dynamic.md`
- 需通用逆向方法论 → `reverse-engineering/SKILL.md`

**同级关联模块**: `radare2/`（IDA 不可用时替代方案）

---

## 按需自举（On-Demand Bootstrap）

本 skill 的入口脚本已接入统一自举系统。

### 自动化能力边界

| 工具 | 可自动安装 | 安装方式 | 说明 |
|------|-----------|---------|------|
| idalib-mcp | ✓ | pip install (from GitHub) | `start.ps1` 缺失时自动安装 |
| IDA Pro 本体 | ✗ | 商业软件，需手动安装 | 设置 `IDADIR` 环境变量指向安装目录 |

### 安装步骤（已验证）

```cmd
# 1. 设置 IDA 路径（替换为你的实际 IDA 安装目录）
setx IDADIR "<你的IDA安装目录>"

# 2. 从 GitHub 安装 ida-pro-mcp（PyPI 上的 ida-mcp 是另一个项目，不要装错！）
pip install git+https://github.com/mrexodia/ida-pro-mcp.git

# 3. 安装 IDA 插件（选择 Streamable HTTP + Global + 全选客户端）
ida-pro-mcp --install

# 4. 重启 IDA Pro，打开目标文件
# 插件自动监听 127.0.0.1:13337

# 5. 验证
ida-pro-mcp --config
```

> ⚠️ **注意**：PyPI 上的 `ida-mcp` 包（作者 jtsylve）是另一个项目，不是我们需要的。
> 必须从 GitHub 安装 `mrexodia/ida-pro-mcp`。

### 自举触发点

- `scripts/start.ps1`：缺 `idalib-mcp` 时自动调用 `bootstrap-reverse.ps1`
- MCP 注册：bootstrap 会自动把 `idapro` 写入 Claude MCP 配置

### 前置条件

- IDA Pro 已安装且 `IDADIR` 环境变量已设置（或脚本内默认路径正确）
- Python 已安装（idalib-mcp 依赖 Python）
