# -*- mode: python ; coding: utf-8 -*-
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 dlgus8648

# PyGObject(gi)는 main.py에서 동적 import하므로 PyInstaller가 자동 감지하지
# 못한다(의도적 — 자동 gi 훅이 공식 framework와 비호환). 여기서 gi 패키지를
# 수동 수집한다. typelib/dylib은 번들하지 않고 런타임에 시스템 GStreamer
# .framework를 쓴다(main.py의 _setup_gstreamer_env가 경로 지정).
from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs, collect_submodules

gi_binaries = collect_dynamic_libs('gi')
gi_datas = collect_data_files('gi')
# gi.overrides.Gst / gi.repository.Gst를 분석 대상에서 빼면 PyInstaller의
# Gst 훅(Gst.init(None) 크래시)이 안 돈다. Gst는 main.py에서 동적 import +
# 런타임 시스템 framework로 처리. 나머지(GObject/GLib 등)는 빌드 시
# XDG_DATA_DIRS로 .gir을 찾게 해 정상 수집.
gi_hiddenimports = [m for m in collect_submodules('gi') if not m.endswith('.Gst')] + [
    'gi._gi',
    'cairo',
]

a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[
        ('../plugin/builddir/gstmacttssink.dylib', 'plugin'),
        ('../tools/kb-tts-export/kb-tts-export', 'tools/kb-tts-export'),
    ]
    + gi_binaries,
    datas=gi_datas,
    hiddenimports=gi_hiddenimports,
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
    name='AnnoySpeaker',
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
    name='AnnoySpeaker',
)
app = BUNDLE(
    coll,
    name='AnnoySpeaker.app',
    icon=None,
    bundle_identifier='io.github.gstreamer101.korean-tts',
)
