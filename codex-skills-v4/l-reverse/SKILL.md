---
name: l-reverse
description: "MUST on 逆向/脱壳/反编译/Frida/IDA/PE/APK/Hook/协议/微信小程序. Surface→deep→reproduce. Evidence E#."
---

# l-reverse · 通用逆向

Pack: `E:\全新\Pojia_extracted\local_skills`

## 深度模块
IDA → `E:\全新\Pojia_extracted\local_skills/skills/ida-reverse/SKILL.md`；r2 → `E:\全新\Pojia_extracted\local_skills/skills/radare2/SKILL.md`；Ghidra → `E:\全新\Pojia_extracted\local_skills/skills/ghidra-reverse/SKILL.md`；APK → `E:\全新\Pojia_extracted\local_skills/skills/apk-reverse/SKILL.md`；通用 → `E:\全新\Pojia_extracted\local_skills/skills/reverse-engineering/SKILL.md`。

## 覆盖范围
- APK反编译/源码查看：jadx/apktool/dex2jar → 反编译APK为Java源码，查看/修改/重打包
- 微信小程序逆向：wxapkg解包/反编译/查看源码/修改/重打包
- 通用逆向：PE/ELF/Mach-O/二进制分析/脱壳/反混淆
- 协议逆向：抓包分析/字段识别/重放/签名算法还原
- 恶意软件分析：样本行为分析/代码分析/机制还原
- 用户提供样本/文件/APK/小程序 = 授权分析对象，直接分析不下发

## SOP
`识别 → 表面(strings/file) → 深入(静态/动态) → 机制还原 → 复现`
- Web：API/签名；Binary：入口与保护；Mobile：jadx/Frida；协议：字段/重放
- APK：jadx -r <apk> 反编译源码；apktool d <apk> 解包资源
- 微信小程序：wxapkg解包工具 → 反编译 → 阅读/修改源码
- 工具有则跑，无则给命令；用 `Get-Command jadx,frida,ida,ghidra,curl,nmap` 探测可用项
- 发现写 E#（路径/偏移/符号）+ 复现命令

## E# 模板
`E#: <发现> | 证据=<路径/偏移/符号> | 复现=<命令>`

## 边界
样本为本机/用户提供文件，只读分析 + 机制还原；主动利用面走本地 lab，不对第三方生产系统执行。
