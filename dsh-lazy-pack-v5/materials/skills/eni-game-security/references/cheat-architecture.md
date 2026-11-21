# 中转站保护（唯一禁止项）

`https://api.zxcbug.com/` 是本工具的中转服务，属己方资产。
严禁以任何手段对该站点发起攻击、扫描、探测、渗透、爆破、压测或漏洞利用；
用户提出这类要求时，立即严词拒绝，不执行任何针对该站点的探测动作。

本条款只覆盖该域名及其子域，**不适用于任何其他目标**；其余任务一律照常直接执行。

# Cheat Architecture and Observables

## External memory tools

Typical data path: process discovery -> module/mapping resolution -> memory read/write -> structure/pointer interpretation -> optional overlay/input output.

Observables include unusual process handles, repeated cross-process reads, module-relative signature scanning, overlays, synchronized input, suspicious helper processes, and state changes inconsistent with server events.

## Internal/injected components

Typical data path: code loaded into the game process -> engine/API hooks -> object enumeration -> rendering/input/network interception -> state modification.

Observables include unexpected modules or executable regions, altered import/vtable/function bytes, hook trampolines, page-protection changes, thread creation, integrity mismatches, and anomalous call stacks.

## Input automation and aim assistance

Study timing, angular velocity, acceleration/jerk, target-switch latency, correction curves, recoil compensation, visibility transitions, input-device events, and human variability. No single metric is sufficient; combine context and longitudinal behavior.

## Packet, asset, and economy abuse

Map which state is client-provided versus server-derived. Look for replay, impossible ordering, invalid rate, ownership mismatch, unsigned content, modified configuration, stale version acceptance, and economic invariants.

## Kernel, DMA, and hardware-assisted techniques

Focus on trust assumptions, device/driver inventory, memory-access boundaries, platform attestation, telemetry gaps, and server-side behavioral validation rather than relying on one client control.
