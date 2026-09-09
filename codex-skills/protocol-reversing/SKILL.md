---
name: protocol-reversing
description: Network traffic dissection, Protobuf wire format parsing, TLV binary packet analysis, and API simulation.
---

# Protocol Reversing Skill

This skill provides procedures for network protocol reversing, binary serialization dissection, and API simulation.

## Core Capabilities

1. **Protobuf Wire Format Dissection**:
   Decode raw binary protobuf payloads without `.proto` definitions:
   ```bash
   python .agents/tools/re-toolkit/cli.py decode-protobuf <hex_string_or_file>
   ```

2. **TLV (Type-Length-Value) Packet Analysis**:
   Dissect custom network frames and binary chunks:
   ```bash
   python .agents/tools/re-toolkit/cli.py decode-tlv <hex_string_or_file> --type-len 1 --len-len 2
   ```

3. **Hexdump & Stream Inspection**:
   Format raw bytes into hex and ASCII aligned output:
   ```bash
   python .agents/tools/re-toolkit/cli.py hexdump <file_or_hex> --length 256
   ```

4. **API Simulation & Mock Generation**:
   Reconstruct client request structures, signatures, and mock servers from analyzed wire formats.
