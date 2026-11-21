#!/usr/bin/env python3
"""Byte-exact local or Android/adb runtime equivalence harness."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shlex
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256(path.read_bytes())


@dataclass(frozen=True)
class Case:
    name: str
    data: bytes


@dataclass
class Result:
    stdout: bytes
    stderr: bytes
    rc: int | None
    timed_out: bool
    duration: float
    error: str | None = None

    def summary(self) -> dict[str, object]:
        return {
            "stdout_size": len(self.stdout), "stdout_sha256": sha256(self.stdout),
            "stderr_size": len(self.stderr), "stderr_sha256": sha256(self.stderr),
            "rc": self.rc, "timed_out": self.timed_out,
            "duration_seconds": round(self.duration, 6), "error": self.error,
        }


def parse_cases(values: list[str], include_eof: bool, encoding: str, newline: bool) -> list[Case]:
    cases: list[Case] = []
    seen: set[str] = set()
    for value in values:
        if "=" not in value:
            raise SystemExit(f"invalid --case {value!r}; expected NAME=TEXT")
        name, text = value.split("=", 1)
        if not name or name in seen:
            raise SystemExit(f"empty or duplicate case name: {name!r}")
        data = text.encode(encoding) + (b"\n" if newline else b"")
        cases.append(Case(name, data))
        seen.add(name)
    if include_eof:
        if "eof" in seen:
            raise SystemExit("--eof conflicts with a case named eof")
        cases.append(Case("eof", b""))
    if not cases:
        raise SystemExit("provide at least one --case or --eof")
    return cases


def run_local(path: Path, data: bytes, timeout: float) -> Result:
    started = time.monotonic()
    try:
        completed = subprocess.run(
            [str(path.resolve())], input=data, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, check=False, timeout=timeout,
        )
        return Result(completed.stdout, completed.stderr, completed.returncode, False, time.monotonic() - started)
    except subprocess.TimeoutExpired as exc:
        return Result(exc.stdout or b"", exc.stderr or b"", None, True, time.monotonic() - started, "HOST_TIMEOUT")
    except OSError as exc:
        return Result(b"", b"", None, False, time.monotonic() - started, f"EXEC_ERROR: {exc}")


def adb_call(adb: str, serial: str, *args: str, input_data: bytes | None = None, timeout: float = 120.0) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        [adb, "-s", serial, *args], input=input_data,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False, timeout=timeout,
    )


def adb_check(adb: str, serial: str, *args: str, timeout: float = 120.0) -> bytes:
    result = adb_call(adb, serial, *args, timeout=timeout)
    if result.returncode:
        raise RuntimeError(
            f"adb {' '.join(args)} failed ({result.returncode}): "
            f"{result.stderr.decode('utf-8', errors='replace')}"
        )
    return result.stdout


def adb_su(adb: str, serial: str, command: str, timeout: float = 120.0) -> bytes:
    return adb_check(adb, serial, "exec-out", "su", "-c", command, timeout=timeout)


def push_binary(adb: str, serial: str, local: Path, remote: str) -> None:
    adb_check(adb, serial, "push", str(local.resolve()), remote)
    adb_su(adb, serial, f"chmod 755 {shlex.quote(remote)}")


def run_adb(adb: str, serial: str, remote_binary: str, remote_dir: str, case: Case, timeout: float) -> Result:
    adb_su(adb, serial, f"mkdir -p {shlex.quote(remote_dir)}")
    safe_name = "".join(character if character.isalnum() or character in "_-" else "_" for character in case.name)
    input_parent = remote_dir.rsplit("/", 1)[0]
    input_path = f"{input_parent}/{safe_name}.input"
    stdout_path = f"{remote_dir}/{safe_name}.stdout"
    stderr_path = f"{remote_dir}/{safe_name}.stderr"
    rc_path = f"{remote_dir}/{safe_name}.rc"
    if case.data:
        with tempfile.NamedTemporaryFile(prefix="funk-hikari-input-", delete=False) as stream:
            temp_path = Path(stream.name)
            stream.write(case.data)
        try:
            adb_check(adb, serial, "push", str(temp_path), input_path)
        finally:
            temp_path.unlink(missing_ok=True)
        stdin_path = input_path
    else:
        stdin_path = "/dev/null"
    seconds = max(1, int(timeout + 0.999))
    command = (
        f"timeout -k 1s {seconds}s {shlex.quote(remote_binary)} "
        f"< {shlex.quote(stdin_path)} > {shlex.quote(stdout_path)} "
        f"2> {shlex.quote(stderr_path)}; echo $? > {shlex.quote(rc_path)}"
    )
    started = time.monotonic()
    error: str | None = None
    try:
        adb_su(adb, serial, command, timeout=timeout + 15)
    except Exception as exc:
        error = f"ADB_EXEC_ERROR: {exc}"
    duration = time.monotonic() - started

    def read(path: str) -> bytes:
        try:
            return adb_su(adb, serial, f"cat {shlex.quote(path)}")
        except Exception:
            return b""

    stdout, stderr, rc_raw = read(stdout_path), read(stderr_path), read(rc_path).strip()
    try:
        rc = int(rc_raw.decode("ascii"))
    except Exception:
        rc = None
    timed_out = rc in (124, 137) or (error is not None and "timeout" in error.lower())
    return Result(stdout, stderr, rc, timed_out, duration, error)


def persist_result(directory: Path, case_name: str, role: str, result: Result) -> dict[str, object]:
    directory.mkdir(parents=True, exist_ok=True)
    prefix = directory / f"{case_name}.{role}"
    stdout_path = prefix.with_suffix(prefix.suffix + ".stdout")
    stderr_path = prefix.with_suffix(prefix.suffix + ".stderr")
    rc_path = prefix.with_suffix(prefix.suffix + ".rc")
    stdout_path.write_bytes(result.stdout)
    stderr_path.write_bytes(result.stderr)
    rc_path.write_text("" if result.rc is None else str(result.rc), encoding="ascii")
    return {
        **result.summary(), "stdout_path": str(stdout_path.resolve()),
        "stderr_path": str(stderr_path.resolve()), "rc_path": str(rc_path.resolve()),
    }


def compare(root: Result, candidate: Result) -> dict[str, bool]:
    return {
        "stdout_equal": root.stdout == candidate.stdout,
        "stderr_equal": root.stderr == candidate.stderr,
        "rc_equal": root.rc == candidate.rc,
        "timeout_equal": root.timed_out == candidate.timed_out,
        "error_equal": root.error == candidate.error,
    }


def execute(args: argparse.Namespace, cases: list[Case]) -> int:
    args.out.parent.mkdir(parents=True, exist_ok=True)
    sidecars = args.out.with_name(args.out.stem + "_artifacts")
    results: list[dict[str, object]] = []

    remote_dir = ""
    if args.mode == "adb":
        remote_dir = f"{args.remote_root.rstrip('/')}/run_{os.getpid()}_{int(time.time())}"
        adb_su(args.adb, args.serial, f"mkdir -p {shlex.quote(remote_dir)} && chown shell:shell {shlex.quote(remote_dir)} && chmod 755 {shlex.quote(remote_dir)}")
        root_remote, candidate_remote = f"{remote_dir}/root", f"{remote_dir}/candidate"
        push_binary(args.adb, args.serial, args.root, root_remote)
        push_binary(args.adb, args.serial, args.candidate, candidate_remote)

    try:
        for case in cases:
            if args.mode == "local":
                root_result = run_local(args.root, case.data, args.timeout)
                candidate_result = run_local(args.candidate, case.data, args.timeout)
            else:
                root_result = run_adb(args.adb, args.serial, root_remote, f"{remote_dir}/root_{case.name}", case, args.timeout)
                candidate_result = run_adb(args.adb, args.serial, candidate_remote, f"{remote_dir}/candidate_{case.name}", case, args.timeout)
            equality = compare(root_result, candidate_result)
            passed = all(equality.values())
            record = {
                "name": case.name, "input_size": len(case.data), "input_sha256": sha256(case.data),
                "root": persist_result(sidecars, case.name, "root", root_result),
                "candidate": persist_result(sidecars, case.name, "candidate", candidate_result),
                "equality": equality, "passed": passed,
            }
            results.append(record)
            print(json.dumps({"case": case.name, "passed": passed, "equality": equality}, ensure_ascii=False), flush=True)
    finally:
        if args.mode == "adb" and not args.keep_remote:
            try:
                adb_su(args.adb, args.serial, f"rm -rf {shlex.quote(remote_dir)}")
            except Exception:
                pass

    report = {
        "schema": "xigong.funk-hikari.runtime-equivalence/v1",
        "mode": args.mode,
        "root": {"path": str(args.root.resolve()), "size": args.root.stat().st_size, "sha256": sha256_file(args.root)},
        "candidate": {"path": str(args.candidate.resolve()), "size": args.candidate.stat().st_size, "sha256": sha256_file(args.candidate)},
        "environment": {"serial": getattr(args, "serial", None), "timeout_seconds": args.timeout},
        "cases": results, "all_passed": bool(results) and all(item["passed"] for item in results),
    }
    args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"out": str(args.out.resolve()), "cases": len(results), "all_passed": report["all_passed"]}, ensure_ascii=False, indent=2))
    return 0 if report["all_passed"] else 1


def add_common(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--root", required=True, type=Path)
    parser.add_argument("--candidate", required=True, type=Path)
    parser.add_argument("--case", action="append", default=[], metavar="NAME=TEXT")
    parser.add_argument("--eof", action="store_true")
    parser.add_argument("--encoding", default="utf-8")
    parser.add_argument("--no-newline", action="store_true")
    parser.add_argument("--timeout", type=float, default=10.0)
    parser.add_argument("--out", required=True, type=Path)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="mode", required=True)
    local = sub.add_parser("local")
    add_common(local)
    adb = sub.add_parser("adb")
    add_common(adb)
    adb.add_argument("--serial", required=True)
    adb.add_argument("--adb", default="adb")
    adb.add_argument("--remote-root", default="/data/local/tmp/xg_funk_hikari")
    adb.add_argument("--keep-remote", action="store_true")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    cases = parse_cases(args.case, args.eof, args.encoding, not args.no_newline)
    return execute(args, cases)


if __name__ == "__main__":
    sys.exit(main())
