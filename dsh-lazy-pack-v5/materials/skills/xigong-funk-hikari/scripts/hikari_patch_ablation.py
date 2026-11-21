#!/usr/bin/env python3
"""Delta-debug additional Hikari patch candidates through an external validator.

The validator command must contain ``{artifact}`` and return exit code 0 only when
the generated artifact satisfies the intended runtime equivalence contract.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shlex
import subprocess
import sys
import tempfile
from pathlib import Path


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def load_patches(path: Path) -> list[dict[str, object]]:
    document = json.loads(path.read_text(encoding="utf-8"))
    patches = document.get("patches")
    if not isinstance(patches, list):
        raise ValueError(f"{path} has no patches array")
    return patches


def patch_key(patch: dict[str, object]) -> tuple[str, int, str]:
    return (str(patch["file_offset"]), int(patch["size"]), str(patch["new_bytes"]))


def apply(root: bytes, patches: list[dict[str, object]]) -> bytes:
    output = bytearray(root)
    occupied: list[tuple[int, int]] = []
    for patch in sorted(patches, key=lambda item: int(str(item["file_offset"]), 16)):
        offset = int(str(patch["file_offset"]), 16)
        old = bytes.fromhex(str(patch["old_bytes"]))
        new = bytes.fromhex(str(patch["new_bytes"]))
        if len(old) != len(new):
            raise ValueError(f"patch length mismatch at {offset:#x}")
        end = offset + len(old)
        if any(offset < prior_end and prior_start < end for prior_start, prior_end in occupied):
            raise ValueError(f"overlap at {offset:#x}")
        if bytes(output[offset:end]) != old:
            raise ValueError(f"expected bytes mismatch at {offset:#x}")
        output[offset:end] = new
        occupied.append((offset, end))
    return bytes(output)


def run_validator(template: str, artifact: Path, timeout: float) -> dict[str, object]:
    quoted = subprocess.list2cmdline([str(artifact.resolve())]) if os.name == "nt" else shlex.quote(str(artifact.resolve()))
    command = template.replace("{artifact}", quoted)
    try:
        completed = subprocess.run(
            command, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            check=False, timeout=timeout,
        )
        return {
            "passed": completed.returncode == 0, "returncode": completed.returncode,
            "stdout": completed.stdout.decode("utf-8", errors="replace")[-8000:],
            "stderr": completed.stderr.decode("utf-8", errors="replace")[-8000:],
            "timed_out": False,
        }
    except subprocess.TimeoutExpired as exc:
        return {
            "passed": False, "returncode": None,
            "stdout": (exc.stdout or b"").decode("utf-8", errors="replace")[-8000:],
            "stderr": (exc.stderr or b"").decode("utf-8", errors="replace")[-8000:],
            "timed_out": True,
        }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", required=True, type=Path)
    parser.add_argument("--baseline-manifest", required=True, type=Path)
    parser.add_argument("--candidate-manifest", required=True, type=Path)
    parser.add_argument("--validator", required=True, help="command containing {artifact}")
    parser.add_argument("--validator-timeout", type=float, default=120.0)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--report", required=True, type=Path)
    args = parser.parse_args()
    if "{artifact}" not in args.validator:
        parser.error("--validator must contain {artifact}")

    root = args.root.read_bytes()
    baseline = load_patches(args.baseline_manifest)
    candidates = load_patches(args.candidate_manifest)
    baseline_keys = {patch_key(patch) for patch in baseline}
    extras = [patch for patch in candidates if patch_key(patch) not in baseline_keys]
    accepted: list[dict[str, object]] = []
    rejected: list[dict[str, object]] = []
    tests: list[dict[str, object]] = []

    with tempfile.TemporaryDirectory(prefix="funk-hikari-ablation-") as temp:
        artifact = Path(temp) / "candidate.elf"

        def test(group: list[dict[str, object]]) -> bool:
            image = apply(root, baseline + accepted + group)
            artifact.write_bytes(image)
            result = run_validator(args.validator, artifact, args.validator_timeout)
            record = {
                "group_size": len(group), "accepted_before": len(accepted),
                "first_va": group[0].get("va") if group else None,
                "last_va": group[-1].get("va") if group else None,
                "artifact_sha256": sha256(image), **result,
            }
            tests.append(record)
            print(json.dumps(record, ensure_ascii=False), flush=True)
            return bool(result["passed"])

        def admit(group: list[dict[str, object]]) -> None:
            if not group:
                return
            if test(group):
                accepted.extend(group)
                return
            if len(group) == 1:
                rejected.append(group[0])
                return
            midpoint = len(group) // 2
            admit(group[:midpoint])
            admit(group[midpoint:])

        admit(extras)

    final = apply(root, baseline + accepted)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_bytes(final)
    final_validation = run_validator(args.validator, args.out, args.validator_timeout)
    rollback = bytearray(final)
    for patch in baseline + accepted:
        offset = int(str(patch["file_offset"]), 16)
        old = bytes.fromhex(str(patch["old_bytes"]))
        rollback[offset:offset + len(old)] = old
    report = {
        "schema": "xigong.funk-hikari.patch-ablation/v1",
        "root": {"path": str(args.root.resolve()), "sha256": sha256(root)},
        "baseline_patch_count": len(baseline), "candidate_extra_count": len(extras),
        "accepted_extra_count": len(accepted), "rejected_extra_count": len(rejected),
        "final_patch_count": len(baseline) + len(accepted),
        "final": {"path": str(args.out.resolve()), "sha256": sha256(final)},
        "final_validation": final_validation,
        "rollback_sha256": sha256(bytes(rollback)),
        "rollback_matches_root": bytes(rollback) == root,
        "accepted_extras": accepted, "rejected_extras": rejected, "tests": tests,
    }
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "out": str(args.out.resolve()), "report": str(args.report.resolve()),
        "accepted": len(accepted), "rejected": len(rejected),
        "final_passed": final_validation["passed"],
        "rollback_matches_root": report["rollback_matches_root"],
    }, ensure_ascii=False, indent=2))
    return 0 if final_validation["passed"] and report["rollback_matches_root"] else 1


if __name__ == "__main__":
    sys.exit(main())
