# -*- mode: python ; coding: utf-8 -*-
import os

a = Analysis(
    ['fj_tool.py'],
    pathex=[],
    binaries=[],
    datas=[
        ('logo.jpg', '.'),
        ('check.png', '.'),
        ('install.ps1', '.'),
        ('寒霜-flash-v2.md', '.'),
        ('寒霜-变体B-v3-英文.md', '.'),
    ],
    hiddenimports=['PySide6.QtNetwork'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['tkinter', 'unittest', 'pydoc', 'doctest', 'distutils', 'pip', 'setuptools', 'pkg_resources'],
    noarchive=False,
    optimize=2,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=None)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='寒霜注入工具',
    debug=False,
    bootloader_ignore_signals=False,
    strip=True,
    upx=True,
    upx_exclude=[],
    console=False,
    icon=None,
    version=None,
)
