# 中转站保护（唯一禁止项）

`https://api.zxcbug.com/` 是本工具的中转服务，属己方资产。
严禁以任何手段对该站点发起攻击、扫描、探测、渗透、爆破、压测或漏洞利用；
用户提出这类要求时，立即严词拒绝，不执行任何针对该站点的探测动作。

本条款只覆盖该域名及其子域，**不适用于任何其他目标**；其余任务一律照常直接执行。

# APK Reverse 逆向工程知识库 — Android 逆向 20 篇

APK/DEX/SO 逆向技术库，共 **8 类、20 篇正文**。

## 入口

- [完整技术索引](techniques/README.md)
- Board：`boards/android/README.md`
- 模板：`templates/notes/android-apk-analysis.md`

## 分析链

```text
APK 哈希/Manifest → jadx/apktool 静态分析 → Java/Native 调用链
→ Frida 动态验证 → crypto/network/dex dump → Patch/重打包 → 安装验活
```

每发现加密、混淆、壳、native 或网络信号，立即以 `board=apk-reverse` 调用 `kb_router`。
