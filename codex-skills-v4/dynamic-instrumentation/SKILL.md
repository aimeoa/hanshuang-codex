---
name: dynamic-instrumentation
description: Frida dynamic hooking, memory patching, API parameter tracing, and anti-debug bypass script generation.
---

# Dynamic Instrumentation Skill

This skill provides procedures for dynamic binary instrumentation, API hooking with Frida, and runtime memory inspection.

## Core Capabilities

1. **Function Hook Generator**:
   Generate Frida Interceptor scripts for specific functions with argument logging and return value rewriting:
   ```bash
   python .agents/tools/re-toolkit/cli.py gen-hook --symbol <function_name> --module <module_name> --args-count 4 --output hook.js
   ```

2. **Anti-Debug Bypass Generation**:
   Generate ready-to-use Frida bypasses for `IsDebuggerPresent`, `CheckRemoteDebuggerPresent`, and `NtQueryInformationProcess`:
   ```bash
   python -c "from frida_bridge import FridaScriptGenerator; print(FridaScriptGenerator.generate_anti_debug_bypass())"
   ```

3. **Memory Byte Patching**:
   Generate in-memory runtime patches:
   ```bash
   python -c "from frida_bridge import FridaScriptGenerator; print(FridaScriptGenerator.generate_memory_patch('target.exe', '0x1000', '9090C3'))"
   ```
