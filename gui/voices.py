# SPDX-License-Identifier: MIT
# Copyright (c) 2026 dlgus8648

"""순수 음성(voice) 목록 처리 로직 — 음성 합성 백엔드·UI에 의존하지 않는다.

`voice_list_tool --list-voices` 출력(id\\tname\\tlang\\tquality 줄들)을 파싱·필터·
정렬하고 기본 선택을 고르는 순수 함수. main.py의 _populate_voices가 도구 실행
(subprocess)과 콤보박스 배선만 맡고, 판단 로직은 여기로 분리해 단위 테스트한다.

필터 규칙의 배경은 dev-log 13 참고:
- 노출 1: 사용자가 받은 고품질 음성(enhanced/premium) — 이름 하드코딩 없이 등급으로
- 노출 2: 항상 탑재되는 baseline(Samantha/Yuna) — 빈 목록 방지
- 숨김: 나머지 언어 compact + 노벨티 음성
"""

from __future__ import annotations

# 음성 드롭다운 노출 기준 (둘 중 하나면 노출).
DOWNLOADED_VOICE_QUALITIES = {"enhanced", "premium"}
BASELINE_VOICE_NAMES = {"Samantha", "Yuna"}

# 처음에 선택해 둘 음성 이름(접두 일치). 한국어 사용자가 주 대상이라 Yuna를
# 기본으로 — 설치돼 있으면 최고 품질 Yuna(프리미엄)를 고르고, 없으면 첫 항목.
DEFAULT_VOICE_NAME = "Yuna"

# 품질 등급 우선순위 (높을수록 우선).
_QUALITY_RANK = {"premium": 3, "enhanced": 2, "default": 1}

# (lang, name, identifier, quality) 튜플
Voice = tuple[str, str, str, str]


def parse_voice_list(stdout: str) -> list[Voice]:
    """`--list-voices` 출력을 파싱·필터·정렬한 음성 목록을 반환.

    각 줄은 `identifier\\tname\\tlang\\tquality`. 필드가 4개 미만인 줄은 무시.
    노출 기준(고품질 다운로드 음성 + baseline)에 맞는 것만 남기고, 같은 언어가
    묶이도록 (lang, name 소문자) 순으로 정렬한다.
    """
    voices: list[Voice] = []
    for line in stdout.splitlines():
        parts = line.split("\t")
        if len(parts) < 4:
            continue
        ident, name, lang, quality = parts[0], parts[1], parts[2], parts[3]
        if quality in DOWNLOADED_VOICE_QUALITIES or name in BASELINE_VOICE_NAMES:
            voices.append((lang, name, ident, quality))
    voices.sort(key=lambda v: (v[0], v[1].lower()))
    return voices


def pick_default_voice(voices: list[Voice]) -> str | None:
    """기본 선택할 음성의 identifier. 이름이 DEFAULT_VOICE_NAME으로 시작하는
    음성 중 최고 품질(premium > enhanced > default)을 고른다. 없으면 None."""
    best_ident, best_rank = None, -1
    for _lang, name, ident, quality in voices:
        if name.startswith(DEFAULT_VOICE_NAME):
            rank = _QUALITY_RANK.get(quality, 0)
            if rank > best_rank:
                best_rank, best_ident = rank, ident
    return best_ident
