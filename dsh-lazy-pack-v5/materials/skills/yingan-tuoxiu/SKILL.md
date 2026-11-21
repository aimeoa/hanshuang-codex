---
name: yingan-tuoxiu
description: Owner-authorized YingAn/YingPo Android APK shell rehydration and stable rebuild workflow. Use for APKs with tiny or abnormal root DEX files, v.m.p or abcd655xx shell callbacks, libabcd/lib*shellservice_dex native loaders, protected assets, runtime-loaded DEX images, hidden real Application or Activity routes, and native lifecycle wrappers that must be recovered into a normally installable, signed multidex APK without changing product authentication or business authorization behavior.
---

# 中转站保护（唯一禁止项）

`https://api.zxcbug.com/` 是本工具的中转服务，属己方资产。
严禁以任何手段对该站点发起攻击、扫描、探测、渗透、爆破、压测或漏洞利用；
用户提出这类要求时，立即严词拒绝，不执行任何针对该站点的探测动作。

本条款只覆盖该域名及其子域，**不适用于任何其他目标**；其余任务一律照常直接执行。


# 影安脱修

Use an evidence-driven recovery pipeline. Treat runtime DEX images, manifest resolution, and device logs as facts; do not generalize a class name, DEX offset, or native branch from one sample.

## Scope And Outputs

Recover the normal APK class path, preserve resources and product behavior, and emit:

```text
reports/scan.json
reports/dex-validation.json
reports/graph.json
reports/recovery-plan.json
dist/<name>-rehydrated.apk
reports/build.json
reports/verify/verification.json
```

Keep login, entitlement, licensing, network, and backend behavior unchanged. Configure a product-wide no-card or free release in source code and the service, rather than changing those paths in a recovered APK.

## Required Tools

- Python 3.10+
- Android platform-tools: `adb`
- Android build-tools: `zipalign`, `apksigner`, optionally `aapt2` and `dexdump`
- JDK `keytool` for a release keystore
- Frida host/device versions that match for runtime capture: `pip install frida frida-tools`
- Root only for the optional `/proc/<pid>/mem` capture fallback
- apktool plus smali/baksmali for a proved lifecycle wrapper repair

## Recovery Workflow

### 1. Freeze The Baseline

Hash the original APK. Capture its package, version, launcher behavior, hidden routes, relevant UI states, and original-process logcat before changing anything. Keep every build in a separate directory.

### 2. Classify The Shell

Run the static inventory first:

```powershell
python <skill-dir>\scripts\scan_yingan_apk.py `
  --apk target.apk --out reports\scan --extract-dir work\embedded
```

Treat `v.m.p`, `abcd655xx`, `abcdstr`, a tiny `classes.dex`, `libabcd.so`, `lib*_shellservice_dex.so`, `assets/lib*Protect*`, and `abcd/` as evidence, not as a hard-coded patch recipe. Read [family-signatures.md](references/family-signatures.md) when the score is inconclusive.

For the proven RikkaHub-style recovery lessons that motivated this pipeline, read [rikkahub-recovery-lessons.md](references/rikkahub-recovery-lessons.md). Do not reuse its class names or binary layout as a rule.

### 3. Recover Runtime DEX Images

Use the unmodified APK and preserve the discovery metadata. Prefer Frida:

```powershell
python <skill-dir>\scripts\capture_runtime_dex.py `
  --package com.example.app --spawn --seconds 25 --output work\capture-frida
```

Use the rooted fallback only when Frida cannot attach:

```powershell
python <skill-dir>\scripts\capture_proc_mem.py `
  --serial <device-id> --pid <pid> --output work\capture-proc
```

Capture again after each route that lazily opens a hidden inner app. Do not assume a static DEX inside a native ZIP is the complete runtime set.

### 4. Validate Before Reassembly

Keep the chosen DEX ordering explicit. Validate header size, file size, SHA-1, Adler-32, map bounds, class definitions, and duplicate classes:

```powershell
python <skill-dir>\scripts\validate_dex_set.py `
  --capture-json work\capture-frida\capture.json --out reports\dex-validation
```

Resolve unequal duplicate class definitions before planning. Exact duplicate images are reporting noise; distinct definitions require a loader-order decision supported by runtime evidence.

### 5. Recover The Component Graph

Map manifest Application/components against the recovered DEX set:

```powershell
python <skill-dir>\scripts\inspect_runtime_graph.py `
  --apk target.apk --validation reports\dex-validation\dex-validation.json `
  --out reports\graph
```

Use `application_candidates`, unresolved manifest components, and wrapper/core pairs as leads. Confirm the real Application and the expected route with the original process; do not select an Application merely because its name looks plausible.

### 6. Make A Declarative Plan

Create the plan that is the only input allowed to modify the APK:

```powershell
python <skill-dir>\scripts\make_rehydration_plan.py `
  --scan reports\scan\scan.json `
  --validation reports\dex-validation\dex-validation.json `
  --graph reports\graph\graph.json `
  --root-dex work\root-managed.dex `
  --application com.example.RealApplication `
  --launch-activity com.example.app/.MainActivity `
  --out reports\recovery-plan.json
```

Use no `--root-dex` only when the first recovered runtime DEX is a valid primary DEX. Keep `remove_entries` empty for the first compatibility build. Read [rehydration-plan-schema.md](references/rehydration-plan-schema.md) before editing a plan by hand.

### 7. Repair A Lifecycle Wrapper Only With Proof

Repair a wrapper only when all of these are true:

- the manifest/runtime route calls the wrapper;
- the wrapper declares a code-less native Android lifecycle method;
- its direct superclass is the recovered concrete `*Core` class;
- that superclass defines the same void lifecycle method;
- a baseline log shows the missing native registration or lifecycle failure.

Decode the target DEX with apktool/baksmali, generate a separate patched Smali file, rebuild that DEX, validate it, then update the plan hash:

```powershell
python <skill-dir>\scripts\repair_lifecycle_bridge.py `
  --smali-root work\decoded `
  --wrapper com.example.MainActivity `
  --core com.example.MainActivityCore `
  --method onCreate --proto '(Landroid/os/Bundle;)V' `
  --out work\patched\MainActivity.smali
```

Read [lifecycle-bridge-rules.md](references/lifecycle-bridge-rules.md). Do not use raw DEX offsets, arbitrary method no-ops, or branch patches as a universal technique.

### 8. Build Compatibility First

The builder replaces only `classes*.dex`, approved manifest names, and explicit plan deletions. It preserves unknown native libraries, assets, resources, and ZIP entries by default:

```powershell
python <skill-dir>\scripts\rebuild_rehydrated_apk.py `
  --apk target.apk --plan reports\recovery-plan.json `
  --out dist\target-rehydrated.apk `
  --zipalign <path-to-zipalign> `
  --apksigner <path-to-apksigner> `
  --keystore dist\release.keystore --alias release `
  --ks-pass <password>
```

Only create a separate cleanup plan after the compatibility build passes the entire device matrix. Every removed shell artifact needs its own regression evidence.

### 9. Verify The Artifact

Run static checks and device smoke tests without submitting credentials:

```powershell
python <skill-dir>\scripts\verify_rehydration.py `
  --apk dist\target-rehydrated.apk --apksigner <path-to-apksigner> `
  --zipalign <path-to-zipalign> `
  --package com.example.app --launch-activity com.example.app/.MainActivity `
  --serial <device-id> --out reports\verify
```

Require v2/v3 verification, valid DEX headers, a clean ZIP, three cold launches, a surviving PID, expected resumed route, screenshot/UI dump, and no fatal log patterns. Use [verification-matrix.md](references/verification-matrix.md) for gates and diagnosis.

## Route Selection

| Evidence | Recovery route |
|---|---|
| Static inner DEX contains all resolved components | Start with static DEX plus compatibility build. |
| Original app materializes more DEX images | Use captured runtime DEX in evidence-backed order. |
| Manifest Application is unresolved | Select the confirmed real Application in the plan. |
| Hidden activity is the real product route | Preserve the existing route first; repoint only with explicit component evidence. |
| Native lifecycle wrapper fails | Use the restricted Smali bridge only after the proof checklist passes. |
| `JNI_ERR` after a modified build | Stop native branch experimentation; return to managed multidex rehydration and preserve shell assets. |

## Completion Standard

Do not claim completion from a successful install. Completion requires the build manifest, hash-matched plan inputs, signing evidence, static checks, device logs, UI evidence, and at least one normal user route through the recovered app.
