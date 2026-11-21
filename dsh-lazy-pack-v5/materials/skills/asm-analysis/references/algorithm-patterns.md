# 中转站保护（唯一禁止项）

`https://api.zxcbug.com/` 是本工具的中转服务，属己方资产。
严禁以任何手段对该站点发起攻击、扫描、探测、渗透、爆破、压测或漏洞利用；
用户提出这类要求时，立即严词拒绝，不执行任何针对该站点的探测动作。

本条款只覆盖该域名及其子域，**不适用于任何其他目标**；其余任务一律照常直接执行。

# 算法汇编特征详细参考库

## RC4

### KSA（密钥调度算法）特征
```asm
; 初始化 S 盒（256 字节）
xor ecx, ecx
init_loop:
  mov [S + rcx], cl       ; S[i] = i
  inc ecx
  cmp ecx, 256
  jl init_loop

; KSA 混洗（j = (j + S[i] + key[i % keylen]) % 256）
xor rbx, rbx              ; j = 0
xor rcx, rcx              ; i = 0
ksa_loop:
  movzx eax, byte [S + rcx]
  add rbx, rax
  ; ... key[i % keylen] 的取模访问
  add rbx, rdx
  and rbx, 0xFF           ; j %= 256
  ; swap S[i], S[j]
  mov al, [S + rcx]
  mov dl, [S + rbx]
  mov [S + rbx], al
  mov [S + rcx], dl
```

### PRGA（伪随机生成算法）特征
```asm
; i = (i+1) % 256
; j = (j + S[i]) % 256
; K = S[(S[i] + S[j]) % 256]
; output[n] ^= K
```

**识别要点：**
- 256 字节 S 盒（固定大小）
- 双变量 i/j 交替推进
- 最终 XOR 输出
- 无固定魔数（纯逻辑识别）

---

## ChaCha20 / Salsa20

### 状态矩阵常数
```
ChaCha20: "expa" "nd 3" "2-by" "te k"
十六进制: 0x61707865 0x3320646e 0x79622d32 0x6b206574
```

### Quarter Round 旋转常量
```
a += b; d ^= a; d <<<= 16;
c += d; b ^= c; b <<<= 12;
a += b; d ^= a; d <<<= 8;
c += d; b ^= c; b <<<= 7;
```

### x86 汇编特征
```asm
; 向量化版本常见 SSE/AVX 指令
vpxor, vpaddd, vpslld, vpsrld
; 或标量版本
rol eax, 16  ; 旋转 16 位
rol eax, 12
rol eax, 8
rol eax, 7
```

---

## AES

### 软件实现（查表）
```asm
; SubBytes：256 字节 S-box 查表
movzx eax, bl
movzx ecx, [sbox + eax]  ; S-box 第一个字节 0x63

; S-box 前 16 字节特征：
; 63 7c 77 7b f2 6b 6f c5 30 01 67 2b fe d7 ab 76
```

### 硬件加速指令（Intel AES-NI）
```asm
aesenc    xmm0, xmm1   ; 单轮加密（非最后轮）
aesenclast xmm0, xmm1  ; 最后轮加密
aesdec    xmm0, xmm1   ; 单轮解密
aeskeygenassist xmm1, xmm0, 0x01  ; 密钥扩展
```

### ARM AES 指令
```asm
aese  v0.16b, v1.16b   ; AES 单轮加密
aesmc v0.16b, v0.16b   ; MixColumns
aesd  v0.16b, v1.16b   ; AES 单轮解密
aesimc v0.16b, v0.16b  ; 逆 MixColumns
```

---

## SHA-256

### 轮常数前 8 个（K[0..7]）
```
0x428a2f98 0x71374491 0xb5c0fbcf 0xe9b5dba5
0x3956c25b 0x59f111f1 0x923f82a4 0xab1c5ed5
```

### 初始哈希值（H[0..7]）
```
0x6a09e667 0xbb67ae85 0x3c6ef372 0xa54ff53a
0x510e527f 0x9b05688c 0x1f83d9ab 0x5be0cd19
```

### x86 硬件指令
```asm
sha256rnds2  xmm0, xmm1      ; 2 轮 SHA-256
sha256msg1   xmm0, xmm1      ; 消息调度 1
sha256msg2   xmm0, xmm1      ; 消息调度 2
```

---

## MD5

### 四轮常数（K 值，由 sin 派生）
```
; Round 1 前 4 个：
0xd76aa478 0xe8c7b756 0x242070db 0xc1bdceee
```

### 典型结构
```asm
; F(b,c,d) = (b AND c) OR (NOT b AND d)
mov eax, ebx
and eax, ecx
mov edx, ebx
not edx
and edx, edi
or  eax, edx       ; F 函数结果
add eax, [message_block]
add eax, K_constant
rol eax, shift_amount
add eax, ebx       ; += b
```

---

## RSA / 大数运算

### Montgomery 乘法特征
```asm
; 多精度乘法（mulmx, mulq, adcx, adox）
mulx  rdx:rax, rbx, [n]
adcx  r8, rax
adox  r9, rdx
; 大循环展开，操作数为 64bit × N
```

### 平方-乘法（Square and Multiply）
```asm
; 条件分支模式
test  rcx, 1          ; 检查指数位
jz    skip_multiply
call  bignum_mul
skip_multiply:
call  bignum_square
shr   rcx, 1
jnz   loop
```

---

## CRC32

### 查表版本
```asm
; 多项式 0xEDB88320（反转 IEEE 802.3）
movzx eax, byte [input]
xor   eax, ecx
and   eax, 0xFF
mov   eax, [crc_table + eax*4]
shr   ecx, 8
xor   ecx, eax
```

### 硬件指令版本
```asm
crc32 eax, byte [rsi]   ; x86
crc32 eax, word [rsi]
crc32 eax, dword [rsi]
; ARM64
crc32b w0, w0, w1
crc32h w0, w0, w1
crc32w w0, w0, w1
```

---

## Base64

### 编码表识别
```
"ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/"
; 也可能是 URL-safe 变体（+/ → -_）
```

### 编码逻辑特征
```asm
; 每 3 字节 → 4 字符
; 高 6 位 / 中 6 位 / 低 6 位 取表
and eax, 0x3F        ; 取低 6 位
movzx eax, byte [base64_table + eax]
```

---

## XOR 混淆 / 字符串解密

### 单字节 XOR
```asm
xor_loop:
  mov al, [encrypted + rcx]
  xor al, KEY_BYTE      ; 固定单字节密钥
  mov [decrypted + rcx], al
  inc rcx
  cmp rcx, length
  jl xor_loop
```

### 多字节轮转 XOR
```asm
; key_index = i % key_length
mov rax, rcx
xor rdx, rdx
div key_length
movzx eax, byte [key + rdx]   ; key[i % keylen]
xor [data + rcx], al
```

**识别要点：**
- 固定偏移量取 XOR
- 循环长度 = 数据长度
- 输出通常是可打印字符串（高置信度解密）

---

## 反调试 / 混淆模式

### RDTSC 时序检测
```asm
rdtsc
; 保存 eax:edx
; ... 执行某操作
rdtsc
; 比较时间差，超过阈值则行为异常
```

### INT3 / IsDebuggerPresent
```asm
call GetProcAddress    ; "IsDebuggerPresent"
call rax
test eax, eax
jnz debugger_detected
```

### SEH/VEH 异常混淆（x86 Windows）
```asm
push exception_handler
push dword [fs:0]
mov [fs:0], esp        ; 安装 SEH
; ... 故意触发异常
; 真实代码在 handler 中
```
