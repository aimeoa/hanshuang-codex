# SLO-PROTECTED-WRAPPER-V1
from __future__ import annotations
import hashlib as _slo_hashlib
from pathlib import Path as _SloPath
import subprocess as _slo_subprocess
import sys as _slo_sys

_SLO_DEPTH = 6
_SLO_ASSET_ID = 'f4af934a381e6536dfd5bd8c3f50273c'
_SLO_ENTRY = 'tools/skills/mcp/ReverseLabToolsMCP/reverselab_mcp/tools/python_re_tools.py'
_SLO_ENGINE_RELATIVE = '.slo-protected/engine/slo-engine.exe'
_SLO_ENGINE_SHA256 = 'bf0788a71e67588e480567d6fa555173bfdb1edb80e5881ff05590ed74dad9e9'
_SLO_DEVICE_STORE = 'C:\\Users\\Administrator\\AppData\\Local\\SLO Offline Delivery\\device-key-v2.json'

def _slo_run() -> int:
    root = _SloPath(__file__).resolve().parents[_SLO_DEPTH]
    engine = root.joinpath(*_SLO_ENGINE_RELATIVE.split('/'))
    if not engine.is_file():
        raise RuntimeError('SLO protected engine is missing')
    digest = _slo_hashlib.sha256(engine.read_bytes()).hexdigest()
    if digest != _SLO_ENGINE_SHA256:
        raise RuntimeError('SLO protected engine integrity check failed')
    command = [str(engine)]
    if engine.suffix.casefold() in {'.py', '.pyw'}:
        command = [_slo_sys.executable, str(engine)]
    command.extend([
        'protected-engine',
        '--skill-root', str(root),
        '--asset-id', _SLO_ASSET_ID,
        '--entry', _SLO_ENTRY,
        '--device-store', _SLO_DEVICE_STORE,
        '--',
        *_slo_sys.argv[1:],
    ])
    return _slo_subprocess.run(command, check=False).returncode

if __name__ == '__main__':
    raise SystemExit(_slo_run())
