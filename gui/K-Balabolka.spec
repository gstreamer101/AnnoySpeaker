# -*- mode: python ; coding: utf-8 -*-
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 dlgus8648


a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[('../plugin/builddir/gstmacttssink.dylib', 'plugin'), ('../tools/kb-tts-export/kb-tts-export', 'tools/kb-tts-export')],
    datas=[],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='K-Balabolka',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='K-Balabolka',
)
app = BUNDLE(
    coll,
    name='K-Balabolka.app',
    icon=None,
    bundle_identifier='io.github.gstreamer101.korean-tts',
)
