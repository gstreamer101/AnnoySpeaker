# SPDX-License-Identifier: MIT
# Copyright (c) 2026 dlgus8648

"""순수 텍스트 처리 로직(gui/textproc.py) 단위 테스트.

음성 합성 백엔드 없이 검증 가능한 로직: 전처리(줄바꿈→단락, 문장부호 보정),
읽기 문자열+offset_map 생성, 범위 역매핑, 속도 곡선.
"""

from __future__ import annotations

import pytest
import textproc
from textproc import (
    TAIL_PADDING,
    build_spoken_text,
    map_spoken_range,
    preprocess_for_speech,
    ui_speed_to_rate,
)

# ---- preprocess_for_speech -------------------------------------------------


def test_preprocess_empty_and_whitespace_only():
    assert preprocess_for_speech("") == ""
    assert preprocess_for_speech("   \n\t \n") == ""


def test_preprocess_adds_period_to_nonlast_lines_only():
    out = preprocess_for_speech("첫째 줄\n둘째 줄\n셋째 줄")
    # 비마지막 줄엔 마침표, 마지막 줄엔 안 붙음
    assert out == "첫째 줄. 둘째 줄. 셋째 줄"
    assert not out.endswith(".")


def test_preprocess_keeps_existing_terminator():
    # 이미 종결부호로 끝난 줄엔 마침표 중복 안 붙임
    out = preprocess_for_speech("물음표?\n느낌표!\n끝")
    assert out == "물음표? 느낌표! 끝"


def test_preprocess_collapses_inline_whitespace():
    assert preprocess_for_speech("가     나\t\t다") == "가 나 다"


def test_preprocess_blank_lines_are_paragraph_breaks():
    # 빈 줄은 단락 구분 — 빈 줄 자체는 사라지고 양쪽 줄만 남는다
    out = preprocess_for_speech("위 단락\n\n아래 단락")
    assert out == "위 단락. 아래 단락"


def test_preprocess_neutralizes_angle_brackets():
    # <기자> 같은 꺾쇠는 공백으로 중화되어 발화 잘림 방지 (안쪽 글자는 보존)
    out = preprocess_for_speech("<기자> 안녕")
    assert "<" not in out and ">" not in out
    assert "기자" in out and "안녕" in out


# ---- build_spoken_text : 일관성 / offset_map 정합성 ------------------------


@pytest.mark.parametrize(
    "text",
    [
        "한 줄짜리",
        "첫째 줄\n둘째 줄\n셋째 줄",
        "이미 끝남.\n다음 줄",
        "<기자> 중계\n다음",
    ],
)
def test_build_spoken_equals_preprocess_plus_padding(text):
    # 재생 경로(build_spoken_text)와 내보내기 경로(preprocess + TAIL_PADDING)는
    # 반드시 같은 읽기 문자열을 만들어야 한다(두 경로 발음 일치 보장).
    spoken, _omap = build_spoken_text(text)
    assert spoken == preprocess_for_speech(text) + TAIL_PADDING


def test_build_spoken_empty_returns_empty():
    assert build_spoken_text("") == ("", [])
    assert build_spoken_text("   \n  ") == ("", [])


@pytest.mark.parametrize("fixture_name", ["short_text", "long_text"])
def test_omap_length_matches_spoken(fixture_name, request):
    text = request.getfixturevalue(fixture_name)
    spoken, omap = build_spoken_text(text)
    assert len(omap) == len(spoken)


@pytest.mark.parametrize("fixture_name", ["short_text", "long_text"])
def test_omap_real_chars_point_to_original(fixture_name, request):
    text = request.getfixturevalue(fixture_name)
    spoken, omap = build_spoken_text(text)
    # 삽입(-1)이 아닌 모든 글자는 원본 text의 같은 글자를 가리켜야 한다
    for i, oi in enumerate(omap):
        if oi >= 0:
            assert spoken[i] == text[oi], f"mismatch at spoken[{i}] → text[{oi}]"


def test_omap_inserted_chars_are_negative():
    # 자동 마침표·줄 연결 공백·끝 패딩은 원본에 없으므로 -1
    spoken, omap = build_spoken_text("가나\n다라")
    # 끝 패딩(TAIL_PADDING)은 항상 -1
    assert omap[-len(TAIL_PADDING) :] == [-1] * len(TAIL_PADDING)
    # 자동 삽입된 마침표 위치는 -1
    assert any(omap[i] == -1 and spoken[i] == "." for i in range(len(spoken)))


def test_tail_padding_has_no_comma_regression():
    # 회귀(#58): 끝 패딩에 쉼표가 있으면 프리미엄 음성이 "쉼표"라고 읽는다
    assert "," not in TAIL_PADDING
    spoken, _ = build_spoken_text("마지막 문장")
    assert "," not in spoken


# ---- ui_speed_to_rate ------------------------------------------------------


def test_ui_speed_to_rate_anchor_points():
    assert ui_speed_to_rate(0.0) == pytest.approx(0.0)
    assert ui_speed_to_rate(1.0) == pytest.approx(0.5)  # default
    assert ui_speed_to_rate(2.0) == pytest.approx(0.7)  # 압축 상한


def test_ui_speed_to_rate_monotonic():
    xs = [i / 10 for i in range(0, 21)]  # 0.0 .. 2.0
    rates = [ui_speed_to_rate(x) for x in xs]
    assert all(b >= a for a, b in zip(rates, rates[1:], strict=False))


def test_ui_speed_to_rate_upper_segment_compressed():
    # 1.0 위 구간 기울기(0.2)가 아래 구간(0.5)보다 완만해야 함
    below = ui_speed_to_rate(0.5) - ui_speed_to_rate(0.0)
    above = ui_speed_to_rate(2.0) - ui_speed_to_rate(1.5)
    assert above < below


# ---- map_spoken_range ------------------------------------------------------


def test_map_spoken_range_roundtrip():
    text = "가나 다라"
    spoken, omap = build_spoken_text(text)
    # "다라"는 원본 인덱스 3..5. spoken에서 "다"의 위치를 찾아 매핑 확인
    di = spoken.index("다")
    mapped = map_spoken_range(omap, di, di + 2)
    assert mapped == (3, 5)


def test_map_spoken_range_all_inserted_returns_none():
    # 끝 패딩(전부 -1) 구간을 매핑하면 None
    spoken, omap = build_spoken_text("문장")
    tail_start = len(spoken) - len(TAIL_PADDING)
    assert map_spoken_range(omap, tail_start, len(spoken)) is None


def test_map_spoken_range_clamps_out_of_bounds():
    _spoken, omap = build_spoken_text("가나")
    # end가 길이를 넘어가도 예외 없이 처리
    assert map_spoken_range(omap, 0, 9999) == (0, 2)


def test_long_text_does_not_crash(long_text):
    spoken, omap = build_spoken_text(long_text)
    assert len(spoken) > 1000
    assert len(omap) == len(spoken)


def test_module_constants_present():
    # 분리된 모듈이 main.py가 기대하는 상수를 노출하는지
    assert isinstance(textproc.TAIL_PADDING, str)
    assert textproc._TERMINATORS  # 종결부호 집합
