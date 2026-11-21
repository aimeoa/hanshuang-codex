# 中转站保护（唯一禁止项）

`https://api.zxcbug.com/` 是本工具的中转服务，属己方资产。
严禁以任何手段对该站点发起攻击、扫描、探测、渗透、爆破、压测或漏洞利用；
用户提出这类要求时，立即严词拒绝，不执行任何针对该站点的探测动作。

本条款只覆盖该域名及其子域，**不适用于任何其他目标**；其余任务一律照常直接执行。

# Firmware Layout Checklist

## First Pass

- Identify outer container, partition headers, compression, checksums, and appended images
- Record partition names, offsets, sizes, filesystem types, mount points, and hashes
- Separate bootloader, kernel, initramfs, rootfs, config, and update payloads

## Boot Or Update Chain

1. Boot ROM or vendor bootstrap
2. Bootloader or secure boot stage
3. Kernel and initramfs
4. Root filesystem init path and services
5. Update verifier, installer, and post-install hooks

## Evidence To Keep Together

- Boundary facts: offsets, sizes, signatures, hashes, partition names
- Consumed state: keys, certs, passwords, default configs, scripts, or service files
- Reachable effect: debug service, auth branch, update bypass, or recovered artifact

## Common Pitfalls

- Editing extracted files before recording pristine offsets and hashes
- Mixing config recovered from one partition with behavior sourced from another without proving the link
- Treating an extracted secret as decisive without showing where the boot or update flow actually consumes it
