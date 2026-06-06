# SPDX-License-Identifier: MIT
# Copyright (c) 2026 dlgus8648

"""순수 텍스트 처리 로직 — 음성 합성 백엔드(GStreamer/AVSpeech)·UI(PySide6)에
의존하지 않는다. 그래서 헤드리스 CI에서 단위 테스트로 검증 가능하다.

main.py가 재생/내보내기 경로에서 이 함수들을 쓴다:
- preprocess_for_speech: 줄바꿈→단락, 문장부호 보정 (내보내기 경로)
- build_spoken_text: 위와 동일한 읽기 문자열 + 원본 위치 매핑(offset_map) (재생 경로,
  실시간 단어 하이라이트용)
- map_spoken_range: 읽기 문자열 범위 → 원본 범위 역매핑
- ui_speed_to_rate: UI 속도 배율 → AVSpeech rate 비선형 압축
"""

from __future__ import annotations

import re

# 문장 종결로 인정하는 문자 (이미 끝나있으면 마침표 중복 안 붙임)
_TERMINATORS = ".!?…。！？"
_INLINE_WHITESPACE = re.compile(r"[ \t]+")
# AVSpeech는 "<...>"를 마크업 태그로 해석해 그 지점에서 발화를 끊는다(실측).
# 예: "<기자>"가 중간에 있으면 거기서 재생이 잘림. 꺾쇠를 공백으로 중화하면
# 안쪽 글자("기자")는 정상 발음되고 잘림도 사라진다. 공백·탭과 함께 취급.
_DROP_FOR_SPEECH = " \t<>"

# 한국어 끝음절 잘림 방지용 꼬리 패딩 (재생/내보내기 공통).
# 끝음절(받침) 잘림은 plugin의 postUtteranceDelay(마지막 청크 포함)가 막아주므로
# 발화되는 문자는 붙이지 않는다. 예전엔 " ,,"(쉼표)를 썼으나 프리미엄 음성
# (예: Yuna Premium)이 쉼표를 "쉼표"라고 읽어버려 무음 공백으로 교체.
TAIL_PADDING = "  "


def ui_speed_to_rate(ui_x: float) -> float:
    """UI multiplier(0.0~2.0)를 AVSpeech rate(0.0~1.0)로 압축 매핑.

    AVSpeech의 rate 0.5~1.0 구간이 비선형(매우 급격)이라 단순 선형으로
    매핑하면 UI 1.5x가 체감 3배 가까이 빨라진다. UI 1.0x = default(0.5)는
    그대로 두고, 그 위 구간만 좁게 압축해 사용자 직관에 가깝게 만든다.

    - UI 0.0..1.0 → rate 0.00..0.50 (선형, default까지)
    - UI 1.0..2.0 → rate 0.50..0.70 (압축, default 위로 천천히)
    """
    if ui_x <= 1.0:
        return ui_x * 0.5
    return 0.5 + (ui_x - 1.0) * 0.2


def preprocess_for_speech(text: str) -> str:
    """모든 줄바꿈을 단락 구분으로 취급해 줄 사이마다 자연 휴식을 만든다.

    - 빈 줄과 단순 Enter를 동일하게 단락으로 처리
    - 줄 내부의 연속 공백/탭은 단일 공백으로 정리
    - 종결 부호(.!?…)로 끝나지 않는 줄엔 마침표를 추가해 휴식 유도
    - **단, 마지막 줄에는 자동 마침표를 붙이지 않음** — 마침표가 trail
      off의 trigger가 되어 마지막 음절(특히 한국어 받침)을 잘라먹기 때문.
      대신 호출자가 trailing 공백 패딩으로 마무리 처리.
    - 줄들을 공백 하나로 이어 한 utterance로
    """
    lines = []
    for raw in text.splitlines():
        # 꺾쇠(<>)를 공백으로 중화 후 공백/탭 정리 (AVSpeech 마크업 끊김 방지)
        cleaned = "".join(" " if c in "<>" else c for c in raw)
        line = _INLINE_WHITESPACE.sub(" ", cleaned).strip()
        if line:
            lines.append(line)
    if not lines:
        return ""

    processed = []
    for i, line in enumerate(lines):
        is_last = i == len(lines) - 1
        if not is_last and line[-1] not in _TERMINATORS:
            line = line + "."
        processed.append(line)
    return " ".join(processed)


def build_spoken_text(text: str) -> tuple[str, list[int]]:
    """preprocess_for_speech(text) + TAIL_PADDING 와 **동일한** 읽기 문자열을
    만들되, 읽기 문자열의 각 글자가 원본 text의 몇 번째 코드포인트인지
    매핑(offset_map)을 함께 반환한다. 삽입 글자(자동 마침표·줄 연결 공백·끝
    패딩)는 -1.

    인프로세스 재생에서 이 문자열을 합성기로 보내고, macttssink가 돌려주는
    단어 범위(읽기 문자열 기준)를 offset_map으로 원본 위치에 되돌려
    실시간 하이라이트에 쓴다.

    범위/매핑은 코드포인트 기준. BMP(한국어·영어·CJK)는 UTF-16과 1:1이라
    macttssink가 주는 UTF-16 범위와 그대로 맞는다. BMP 밖(이모지 등)은
    수신 측(Phase 4)에서 UTF-16↔코드포인트 보정 필요 — 현재는 BMP 가정.
    """
    # 1) 줄 분리 + 각 줄의 원본 시작 오프셋 (\n, \r, \r\n 처리)
    raw_lines: list[tuple[int, str]] = []
    start = 0
    i = 0
    n = len(text)
    while i <= n:
        if i == n or text[i] in "\n\r":
            raw_lines.append((start, text[start:i]))
            if i < n and text[i : i + 2] == "\r\n":
                i += 1
            start = i + 1
        i += 1

    # 2) 각 줄: 연속 공백/탭 → 단일 공백, 양끝 strip. 글자별 원본 인덱스 추적.
    cleaned: list[list[tuple[str, int]]] = []
    for off, raw in raw_lines:
        buf: list[tuple[str, int]] = []
        prev_space = False
        for j, ch in enumerate(raw):
            if ch in _DROP_FOR_SPEECH:  # 공백·탭·꺾쇠(<>)는 공백으로 (하이라이트 -1)
                if not prev_space:
                    buf.append((" ", -1))
                prev_space = True
            else:
                buf.append((ch, off + j))
                prev_space = False
        while buf and buf[0][0] == " ":
            buf.pop(0)
        while buf and buf[-1][0] == " ":
            buf.pop()
        if buf:
            cleaned.append(buf)

    if not cleaned:
        return "", []

    # 3) 마침표(비마지막) + 줄 연결 공백 + 끝 패딩
    chars: list[str] = []
    omap: list[int] = []
    for idx, buf in enumerate(cleaned):
        for ch, oi in buf:
            chars.append(ch)
            omap.append(oi)
        if idx != len(cleaned) - 1:
            if buf[-1][0] not in _TERMINATORS:
                chars.append(".")
                omap.append(-1)
            chars.append(" ")
            omap.append(-1)
    for ch in TAIL_PADDING:
        chars.append(ch)
        omap.append(-1)

    return "".join(chars), omap


def map_spoken_range(omap: list[int], start: int, end: int) -> tuple[int, int] | None:
    """읽기 문자열의 [start, end) 범위를 원본 코드포인트 [lo, hi) 범위로 매핑.
    범위 안에 원본 글자가 하나도 없으면(삽입 글자뿐) None."""
    origs = [omap[i] for i in range(start, min(end, len(omap))) if i >= 0 and omap[i] >= 0]
    if not origs:
        return None
    return min(origs), max(origs) + 1
