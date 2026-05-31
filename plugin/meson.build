# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright (c) 2026 dlgus8648

project('gst-macttssink-c', ['c', 'objc'],
  version : '0.2.0',
  default_options : [
    'warning_level=2',
    'c_std=c11',
    'buildtype=debug',
  ],
)

# Objective-C는 ARC를 명시적으로 켜야 함 (기본은 MRC)
add_project_arguments('-fobjc-arc', language : 'objc')

gst_dep      = dependency('gstreamer-1.0',      version : '>= 1.20')
gst_base_dep = dependency('gstreamer-base-1.0', version : '>= 1.20')

# macOS 네이티브 TTS API (AVSpeechSynthesizer)
apple_frameworks_dep = dependency('appleframeworks',
  modules : ['Foundation', 'AVFoundation'],
)

plugin_sources = [
  'gstmacttssink.c',
  'gstmacttssink_macos.m',
]

shared_library('gstmacttssink',
  plugin_sources,
  dependencies : [gst_dep, gst_base_dep, apple_frameworks_dep],
  install      : false,
  name_prefix  : '',
)
