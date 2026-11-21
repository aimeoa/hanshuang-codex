"""IDAPython batch exporter for Hikari pass morphology and function boundaries.

IDA invocation example:
  idat64 -A -S"ida_hikari_export.py report.json functions.csv perf.txt annotate" SAMPLE
"""
from __future__ import annotations

import collections
import csv
import hashlib
import json
import re
import sys
from pathlib import Path

import ida_auto
import ida_bytes
import ida_funcs
import ida_gdl
import ida_idaapi
import ida_kernwin
import ida_name
import idaapi
import idautils
import idc


COND_BRANCHES = {
    "b.eq", "b.ne", "b.cs", "b.hs", "b.cc", "b.lo", "b.mi", "b.pl",
    "b.vs", "b.vc", "b.hi", "b.ls", "b.ge", "b.lt", "b.gt", "b.le",
    "cbz", "cbnz", "tbz", "tbnz",
}
MBA_MNEMONICS = {
    "add", "adds", "sub", "subs", "neg", "negs", "and", "ands",
    "orr", "eor", "eon", "bic", "bics", "mvn", "lsl", "lsr", "asr",
    "ror", "ubfx", "sbfx", "bfi", "bfxil", "extr", "csel", "csinc",
    "csinv", "csneg", "cset", "csetm", "madd", "msub", "mul",
}
BYTE_MEMORY = {"ldrb", "ldurb", "ldrsb", "strb", "sturb"}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def parse_perf(path: Path | None) -> collections.Counter[int]:
    result: collections.Counter[int] = collections.Counter()
    if path is None or not path.exists():
        return result
    patterns = [
        re.compile(r"\bvaddr_in_file:\s*([0-9a-fA-F]+)"),
        re.compile(r"\boffset[:=]\s*(0x[0-9a-fA-F]+|[0-9a-fA-F]+)"),
    ]
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        for pattern in patterns:
            match = pattern.search(line)
            if match:
                result[int(match.group(1), 16)] += 1
                break
    return result


def sanitize(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_]+", "_", value).strip("_")[:48] or "candidate"


def classify(rows: list[dict[str, object]], blocks: int, back_edges: int, max_indegree: int) -> str:
    mnemonics = collections.Counter(str(row["mnemonic"]) for row in rows)
    if blocks >= 20 and back_edges >= 2 and max_indegree >= 3:
        return "cff-candidate"
    if rows and len(rows) <= 18 and blocks <= 2 and rows[-1]["mnemonic"] in {"b", "br"}:
        return "tail-wrapper-candidate" if rows[-1]["mnemonic"] == "b" else "indirect-wrapper-candidate"
    mba = sum(mnemonics[name] for name in MBA_MNEMONICS)
    byte_memory = sum(mnemonics[name] for name in BYTE_MEMORY)
    if len(rows) >= 80 and mba * 100 >= len(rows) * 28 and byte_memory >= 8:
        return "mba-byte-transform-candidate"
    if mnemonics["br"] or mnemonics["blr"]:
        return "indirect-edge-candidate"
    return "native-or-unclassified"


def main() -> int:
    ida_auto.auto_wait()
    if len(idc.ARGV) < 3:
        print("usage: ida_hikari_export.py <report.json> <functions.csv> [perf.txt] [annotate]")
        return 2
    report_path = Path(idc.ARGV[1]).resolve()
    csv_path = Path(idc.ARGV[2]).resolve()
    perf_path = Path(idc.ARGV[3]).resolve() if len(idc.ARGV) >= 4 and idc.ARGV[3] else None
    annotate = len(idc.ARGV) >= 5 and idc.ARGV[4].lower() == "annotate"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    perf = parse_perf(perf_path)
    functions: list[dict[str, object]] = []

    for start in idautils.Functions():
        function = ida_funcs.get_func(start)
        if function is None:
            continue
        end = int(function.end_ea)
        rows: list[dict[str, object]] = []
        for ea in idautils.Heads(start, end):
            if not ida_bytes.is_code(ida_bytes.get_full_flags(ea)):
                continue
            rows.append({
                "ea": ea, "mnemonic": idc.print_insn_mnem(ea).lower(),
                "op0": idc.get_operand_value(ea, 0),
            })
        flow = list(ida_gdl.FlowChart(function, flags=ida_gdl.FC_PREDS))
        indegrees = [sum(1 for _ in block.preds()) for block in flow]
        back_edges = sum(successor.start_ea <= block.start_ea for block in flow for successor in block.succs())
        mnemonics = collections.Counter(str(row["mnemonic"]) for row in rows)
        runtime_hits = sum(count for offset, count in perf.items() if start <= offset < end)
        item = {
            "start": start, "end": end, "size": end - start,
            "name": ida_name.get_name(start) or f"sub_{start:X}",
            "instructions": len(rows), "basic_blocks": len(flow),
            "max_indegree": max(indegrees or [0]), "back_edges": back_edges,
            "conditional_branches": sum(mnemonics[name] for name in COND_BRANCHES),
            "indirect_branches": mnemonics["br"], "indirect_calls": mnemonics["blr"],
            "mba_instructions": sum(mnemonics[name] for name in MBA_MNEMONICS),
            "byte_memory_instructions": sum(mnemonics[name] for name in BYTE_MEMORY),
            "runtime_sample_hits": runtime_hits,
        }
        item["classification"] = classify(rows, len(flow), back_edges, int(item["max_indegree"]))
        functions.append(item)

    if annotate:
        counters: collections.Counter[str] = collections.Counter()
        for item in functions:
            classification = str(item["classification"])
            if classification == "native-or-unclassified":
                continue
            counters[classification] += 1
            prefix = sanitize(classification.replace("-candidate", ""))
            new_name = f"hikari_{prefix}_{int(item['start']):X}"
            ida_name.set_name(int(item["start"]), new_name, ida_name.SN_FORCE)
            idc.set_func_cmt(
                int(item["start"]),
                "Hikari morphology only; verify pass contract before rewrite. "
                f"class={classification}, blocks={item['basic_blocks']}, "
                f"BR={item['indirect_branches']}, BLR={item['indirect_calls']}, "
                f"MBA={item['mba_instructions']}, runtime_hits={item['runtime_sample_hits']}",
                1,
            )

    columns = [
        "start", "end", "size", "name", "classification", "instructions",
        "basic_blocks", "max_indegree", "back_edges", "conditional_branches",
        "indirect_branches", "indirect_calls", "mba_instructions",
        "byte_memory_instructions", "runtime_sample_hits",
    ]
    with csv_path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        for item in functions:
            row = dict(item)
            for key in ("start", "end", "size"):
                row[key] = hex(int(row[key]))
            writer.writerow(row)
    counts = collections.Counter(str(item["classification"]) for item in functions)
    input_path = Path(idaapi.get_input_file_path()).resolve()
    report = {
        "schema": "xigong.funk-hikari.ida-export/v1",
        "input": {"path": str(input_path), "sha256": sha256(input_path), "image_base": hex(idaapi.get_imagebase())},
        "processor": idaapi.get_inf_structure().procname,
        "perf": {"path": str(perf_path) if perf_path else None, "offsets": len(perf), "samples": sum(perf.values())},
        "summary": {
            "functions": len(functions), "classifications": dict(counts),
            "indirect_branches": sum(int(item["indirect_branches"]) for item in functions),
            "indirect_calls": sum(int(item["indirect_calls"]) for item in functions),
            "mba_instructions": sum(int(item["mba_instructions"]) for item in functions),
            "annotated": annotate,
        },
        "functions": functions,
    }
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if annotate:
        idc.save_database(idc.get_idb_path(), ida_idaapi.DBFL_COMP)
    print(json.dumps({"report": str(report_path), "csv": str(csv_path), **report["summary"]}, ensure_ascii=False))
    return 0


try:
    _rc = main()
except Exception:
    import traceback
    traceback.print_exc()
    _rc = 1
finally:
    ida_kernwin.qexit(_rc)
