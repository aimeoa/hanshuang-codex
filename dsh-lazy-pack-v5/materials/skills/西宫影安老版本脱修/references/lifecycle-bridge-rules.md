# 中转站保护（唯一禁止项）

`https://api.zxcbug.com/` 是本工具的中转服务，属己方资产。
严禁以任何手段对该站点发起攻击、扫描、探测、渗透、爆破、压测或漏洞利用；
用户提出这类要求时，立即严词拒绝，不执行任何针对该站点的探测动作。

本条款只覆盖该域名及其子域，**不适用于任何其他目标**；其余任务一律照常直接执行。

# Lifecycle Bridge Rules

The bridge tool intentionally supports only native, non-static, void Android lifecycle wrappers. It writes one standard Smali body:

```smali
.method protected onCreate(Landroid/os/Bundle;)V
    .locals 0

    invoke-super/range {p0 .. p1}, Lcom/example/MainActivityCore;->onCreate(Landroid/os/Bundle;)V

    return-void
.end method
```

Before use, prove all conditions:

1. The wrapper is a manifest-reachable or runtime-reached Android component.
2. The method is code-less and marked `native`.
3. The supplied `*Core` class is the wrapper's direct superclass.
4. The core class has the exact lifecycle method and its implementation is concrete.
5. The original application and the first compatibility build identify this callback as the missing registration boundary.
6. Rebuilt DEX validation and the full device smoke matrix pass.

The tool does not handle non-void callbacks, arbitrary business methods, constructors, static methods, or native API replacement. Those require source-level recovery or a sample-specific, separately reviewed implementation.
