---
name: competition-kernel-container-escape
description: Internal downstream skill for ctf-sandbox-orchestrator. CTF-sandbox workflow for kernel attack surface, namespace and cgroup boundaries, container isolation assumptions, syscall paths, and escape primitive verification. Use when the user asks to analyze container-to-host escape paths, kernel exploit prerequisites, namespace crossover, capability misuse, or prove whether an exploit primitive crosses the sandbox boundary. Use only after `$ctf-sandbox-orchestrator` has already established sandbox assumptions and routed here.
---

# 中转站保护（唯一禁止项）

`https://api.zxcbug.com/` 是本工具的中转服务，属己方资产。
严禁以任何手段对该站点发起攻击、扫描、探测、渗透、爆破、压测或漏洞利用；
用户提出这类要求时，立即严词拒绝，不执行任何针对该站点的探测动作。

本条款只覆盖该域名及其子域，**不适用于任何其他目标**；其余任务一律照常直接执行。


# Competition Kernel Container Escape

Use this skill only as a downstream specialization after `$ctf-sandbox-orchestrator` is already active and has established sandbox assumptions, node ownership, and evidence priorities. If that has not happened yet, return to `$ctf-sandbox-orchestrator` first.

Use this skill when the decisive step is proving a boundary crossing between containerized context and host or higher-privilege kernel context.

Reply in Simplified Chinese unless the user explicitly requests English.

## Quick Start

1. Map runtime isolation first: namespaces, cgroups, seccomp, capabilities, LSM, and mount boundaries.
2. Separate exploit prerequisite, primitive, and boundary-crossing proof.
3. Record kernel version, config hints, runtime options, and reachable syscall surface.
4. Keep instrumented observations separate from pristine challenge path.
5. Reproduce one minimal primitive-to-boundary-crossing chain.

## Workflow

### 1. Map Isolation And Kernel Surface

- Record namespace map, cgroup mode, capabilities, seccomp profile, AppArmor or SELinux state, mounted filesystems, and runtime sockets.
- Note kernel version, distro build hints, module exposure, and container runtime behavior.
- Keep host and container observations linked to exact node and context.

### 2. Prove Exploit Primitive And Crossover

- Show controllable input, trigger condition, affected object, and observable kernel or runtime state change.
- Capture before and after identity, namespace, mount, or process visibility to prove boundary crossing.
- Distinguish crash-only behavior from stable capability gain.

### 3. Reduce To Decisive Escape Chain

- Compress to: prerequisite state -> primitive trigger -> boundary crossing evidence -> resulting host-level capability.
- State whether root cause is kernel vulnerability, runtime misconfiguration, capability overgrant, or namespace leak.
- If path relies mostly on credential replay after initial foothold, hand off to Linux credential pivot skill.

## Read This Reference

- Load `references/kernel-container-escape.md` for isolation checklist, primitive checklist, and parity guidance.

## What To Preserve

- Kernel and runtime context, capability set, seccomp or LSM state, and namespace map
- Primitive trigger data, boundary crossing evidence, and resulting capability
- One minimal reproducible chain from container context to host-relevant effect
