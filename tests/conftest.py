# SPDX-License-Identifier: MIT
# Copyright (c) 2026 dlgus8648

"""pytest 공용 설정·픽스처.

순수 로직 모듈(textproc, voices)은 gui/ 안의 최상위 모듈로, 앱이 `python
main.py`로 실행될 때와 동일하게 import한다. 그래서 gui/를 sys.path에 얹는다.
(GStreamer/AVSpeech·PySide6 없이 import되므로 헤드리스 CI에서 그대로 돈다.)

짧은/긴 텍스트 픽스처:
- short_text: 자작 한국어 짧은 글 (줄바꿈·연 구분·종결부호 없는 행)
- long_text: 메밀꽃 필 무렵(이효석, 1936, 퍼블릭 도메인) 발췌를 반복해 수천 자.
  대화 따옴표·줄표(―)·말줄임(……)·괄호·한자·숫자 등 까다로운 요소 포함.
  (저작권 안전을 위해 짧은 글은 자작, 긴 글은 퍼블릭 도메인만 사용.)
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

# gui/ 를 import 경로에 추가 (textproc / voices)
_GUI_DIR = Path(__file__).resolve().parent.parent / "gui"
if str(_GUI_DIR) not in sys.path:
    sys.path.insert(0, str(_GUI_DIR))

_DATA = Path(__file__).resolve().parent / "data"

# 자작 짧은 글 — 각 행이 종결부호 없이 끝나고, 연 사이 빈 줄. 전처리 규칙
# (행 끝 마침표 자동 추가, 마지막 행 예외, 빈 줄 단락 처리)을 두루 건드린다.
SHORT_TEXT = """바람이 분다 창밖으로
오래된 노래가 다시 들린다
나는 여기 잠시 멈춰 서서

빛이 천천히 스며들고
하루가 조용히 저문다"""


@pytest.fixture
def short_text() -> str:
    return SHORT_TEXT


@pytest.fixture
def long_text() -> str:
    # 발췌를 반복해 수천 자(여러 문장 청크)로. 단락 사이는 빈 줄로.
    excerpt = (_DATA / "memil_excerpt.txt").read_text(encoding="utf-8").strip()
    return "\n\n".join(excerpt for _ in range(8))


@pytest.fixture
def large_text() -> str:
    # 대용량 m4a 변환 검증용 — 1만 자 이상이 될 때까지 발췌 반복.
    excerpt = (_DATA / "memil_excerpt.txt").read_text(encoding="utf-8").strip()
    parts: list[str] = []
    total = 0
    while total < 10_000:
        parts.append(excerpt)
        total += len(excerpt) + 2  # "\n\n" 구분자 포함 근사
    return "\n\n".join(parts)
