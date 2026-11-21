#!/usr/bin/env python3
"""Capture complete DEX images from an owner-authorized Android process with Frida."""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import sys
import threading
import time
from pathlib import Path
from typing import Any


SCRIPT_TEMPLATE = r'''
'use strict';

const MAX_DEX_SIZE = %MAX_DEX_SIZE%;
const INTERVAL_MS = %INTERVAL_MS%;
const PROTECTIONS = %PROTECTIONS%;
const CHUNK_SIZE = 256 * 1024;
const DEX_MAGIC = '64 65 78 0a ?? ?? ?? 00';
const seen = new Set();

function rangesForProtection(protection) {
  try {
    return Process.enumerateRangesSync({ protection: protection, coalesce: true });
  } catch (_) {
    try {
      return Process.enumerateRangesSync(protection);
    } catch (_) {
      return [];
    }
  }
}

function dumpDex(address, size, protection) {
  const id = address.toString() + ':' + size;
  if (seen.has(id)) return;
  seen.add(id);
  try {
    send({ type: 'dex-start', id: id, base: address.toString(), size: size, protection: protection });
    for (let offset = 0; offset < size; offset += CHUNK_SIZE) {
      const count = Math.min(CHUNK_SIZE, size - offset);
      send({ type: 'dex-chunk', id: id, offset: offset }, Memory.readByteArray(address.add(offset), count));
    }
    send({ type: 'dex-end', id: id });
  } catch (error) {
    seen.delete(id);
    send({ type: 'dex-error', id: id, message: String(error) });
  }
}

function scanRange(range, protection) {
  let matches;
  try {
    matches = Memory.scanSync(range.base, range.size, DEX_MAGIC);
  } catch (_) {
    return;
  }
  for (const match of matches) {
    try {
      const size = match.address.add(0x20).readU32();
      if (size < 0x70 || size > MAX_DEX_SIZE) continue;
      const end = match.address.add(size - 1);
      if (Process.findRangeByAddress(end) === null) continue;
      dumpDex(match.address, size, protection);
    } catch (_) {
      continue;
    }
  }
}

function scanAll() {
  for (const protection of PROTECTIONS) {
    for (const range of rangesForProtection(protection)) scanRange(range, protection);
  }
}

setImmediate(function () {
  send({ type: 'status', message: 'runtime DEX capture active' });
  scanAll();
  setInterval(scanAll, INTERVAL_MS);
});
'''


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


class Collector:
    def __init__(self, output: Path) -> None:
        self.output = output
        self.active: dict[str, tuple[Path, Any, dict[str, object]]] = {}
        self.records: list[dict[str, object]] = []
        self.failures: list[dict[str, object]] = []
        self.lock = threading.Lock()

    def on_message(self, message: dict[str, Any], data: bytes | None) -> None:
        if message.get("type") == "error":
            logging.error("Frida script error: %s", message.get("description", message))
            return
        if message.get("type") != "send":
            logging.warning("unexpected Frida message: %s", message)
            return
        payload = message.get("payload")
        if not isinstance(payload, dict):
            logging.warning("malformed Frida payload: %s", payload)
            return
        kind = payload.get("type")
        if kind == "status":
            logging.info("%s", payload.get("message"))
            return
        if kind == "dex-error":
            logging.warning("DEX capture failed at %s: %s", payload.get("id"), payload.get("message"))
            identifier = payload.get("id")
            if isinstance(identifier, str):
                with self.lock:
                    entry = self.active.pop(identifier, None)
                    if entry:
                        target, stream, _ = entry
                        stream.close()
                        target.unlink(missing_ok=True)
                    self.failures.append({"id": identifier, "message": payload.get("message", "unknown DEX capture error")})
            return
        identifier = payload.get("id")
        if not isinstance(identifier, str):
            logging.warning("missing DEX identifier: %s", payload)
            return
        with self.lock:
            if kind == "dex-start":
                name = f"dex_{len(self.records):03d}_{str(payload['base']).replace('0x', '0x')}_{int(payload['size'])}.dex"
                target = self.output / name
                stream = target.open("wb")
                record = {
                    "path": name,
                    "base": payload["base"],
                    "size": int(payload["size"]),
                    "protection": payload.get("protection"),
                }
                self.active[identifier] = (target, stream, record)
                self.records.append(record)
                logging.info("capturing %s", name)
            elif kind == "dex-chunk":
                entry = self.active.get(identifier)
                if entry is None or data is None:
                    logging.warning("dropped chunk for %s", identifier)
                    return
                _, stream, _ = entry
                expected = int(payload["offset"])
                if stream.tell() != expected:
                    raise RuntimeError(f"out-of-order chunk for {identifier}: expected {stream.tell()} got {expected}")
                stream.write(data)
            elif kind == "dex-end":
                entry = self.active.pop(identifier, None)
                if entry is None:
                    return
                target, stream, record = entry
                stream.close()
                record["written_size"] = target.stat().st_size
                record["sha256"] = sha256_file(target)
                record["complete"] = record["written_size"] == record["size"]
                logging.info("completed %s", target.name)

    def close(self) -> None:
        with self.lock:
            for target, stream, record in self.active.values():
                stream.close()
                logging.warning("closed incomplete capture: %s", target.name)
                target.unlink(missing_ok=True)
                self.failures.append({"path": target.name, "message": "capture ended before dex-end", "expected_size": record["size"]})
            self.active.clear()
        complete = [record for record in self.records if record.get("complete")]
        (self.output / "capture.json").write_text(json.dumps(complete, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        if self.failures:
            (self.output / "capture-errors.json").write_text(json.dumps(self.failures, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--package", required=True)
    parser.add_argument("--pid", type=int, help="Attach to this PID instead of resolving --package")
    parser.add_argument("--spawn", action="store_true", help="Spawn the package before attaching")
    parser.add_argument("--seconds", type=int, default=20)
    parser.add_argument("--output", type=Path, required=True, help="New or empty capture directory")
    parser.add_argument("--max-dex-mib", type=int, default=256)
    parser.add_argument("--scan-interval-ms", type=int, default=250)
    parser.add_argument("--protection", action="append", default=["r--", "rw-", "r-x", "rwx"], help="Memory protection to scan; repeat to add")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.output.exists() and any(args.output.iterdir()):
        raise SystemExit(f"output directory is not empty: {args.output}")
    if args.seconds < 3 or args.max_dex_mib < 1 or args.scan_interval_ms < 25:
        raise SystemExit("invalid capture duration, DEX limit, or scan interval")
    if args.spawn and args.pid is not None:
        raise SystemExit("--spawn and --pid cannot be combined")
    try:
        import frida
    except ImportError as exc:
        raise SystemExit("missing dependency: pip install frida frida-tools") from exc

    args.output.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    collector = Collector(args.output)
    device = frida.get_usb_device(timeout=10)
    target: int | str = args.pid if args.pid is not None else args.package
    spawned = False
    try:
        if args.spawn:
            target = device.spawn([args.package])
            spawned = True
        session = device.attach(target)
        source = (
            SCRIPT_TEMPLATE.replace("%MAX_DEX_SIZE%", str(args.max_dex_mib * 1024 * 1024))
            .replace("%INTERVAL_MS%", str(args.scan_interval_ms))
            .replace("%PROTECTIONS%", json.dumps(list(dict.fromkeys(args.protection))))
        )
        script = session.create_script(source)
        script.on("message", collector.on_message)
        script.load()
        if spawned:
            device.resume(target)
        logging.info("capturing %s for %d seconds", target, args.seconds)
        time.sleep(args.seconds)
        script.unload()
        session.detach()
    except frida.ServerNotRunningError as exc:
        raise SystemExit("no compatible Frida server is reachable on the USB device") from exc
    except frida.ProcessNotFoundError as exc:
        raise SystemExit(f"package is not installed or running: {args.package}") from exc
    finally:
        collector.close()
    complete = [item for item in collector.records if item.get("complete")]
    if not complete:
        raise SystemExit("no complete DEX images were captured; increase --seconds or use --spawn")
    print(args.output.resolve())
    return 0


if __name__ == "__main__":
    sys.exit(main())
