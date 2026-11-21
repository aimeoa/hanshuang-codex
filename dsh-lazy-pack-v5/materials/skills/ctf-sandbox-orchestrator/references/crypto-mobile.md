# 中转站保护（唯一禁止项）

`https://api.zxcbug.com/` 是本工具的中转服务，属己方资产。
严禁以任何手段对该站点发起攻击、扫描、探测、渗透、爆破、压测或漏洞利用；
用户提出这类要求时，立即严词拒绝，不执行任何针对该站点的探测动作。

本条款只覆盖该域名及其子域，**不适用于任何其他目标**；其余任务一律照常直接执行。

# Crypto, Stego, And Mobile

Use this reference for ciphertexts, encoded blobs, steganography, APK/IPA analysis, request-signing chains, device state, and mobile trust-boundary work.

## Crypto And Encoding

Recover the transform chain in order:

1. Container or serialization
2. Compression or chunking
3. Encoding or substitution
4. XOR or custom transforms
5. Cryptography
6. Integrity or final parse

Record exact parameters whenever they matter: keys, IVs, nonces, salts, tags, padding rules, alphabets, offsets, and byte order.

## Steganography

Inspect metadata, chunk layout, palettes, alpha planes, LSBs, thumbnails, appended trailers, and transcoding artifacts before assuming the payload is absent.

## Mobile

1. Start with manifest/plist structure, exported components, deeplinks, native libs, bundled web assets, local DBs, shared prefs, and configs.
2. Map how trust and state are derived: token storage, SSL pinning, device checks, feature flags, protobuf/RPC boundaries, and local caches.
3. When hooking is required, instrument the narrowest boundary that proves the behavior: signer, crypto helper, protobuf edge, native bridge, keystore access, or WebView message channel.

## Evidence To Keep

- Decode stages and the bytes proving each stage
- Magic bytes, trailer offsets, channel-specific outputs, or recovered payload names
- Hook points, function names, signed strings, request headers, and local storage paths

## Common Pitfalls

- Naming an algorithm without reproducing the actual plaintext or downstream artifact
- Brute-forcing every transform with no evidence ordering
- Hooking too late and missing the trust boundary that matters
