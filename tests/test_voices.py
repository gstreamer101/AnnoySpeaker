# SPDX-License-Identifier: MIT
# Copyright (c) 2026 dlgus8648

"""순수 음성 목록 처리 로직(gui/voices.py) 단위 테스트.

`--list-voices` 출력의 파싱·필터(다운로드 고품질 + baseline)·정렬·기본 선택을
백엔드 없이 검증. 필터 규칙 배경은 dev-log 13.
"""

from __future__ import annotations

from voices import parse_voice_list, pick_default_voice

# id\tname\tlang\tquality 형식의 가상 --list-voices 출력.
# 포함돼야: Yuna(baseline), Yuna (Premium)(premium), Samantha(baseline), Ava(enhanced)
# 제외돼야: Kyoko(다른 언어 compact), Bad News(노벨티/compact), 형식 깨진 줄
SAMPLE = "\n".join(
    [
        "com.apple.voice.compact.ko-KR.Yuna\tYuna\tko-KR\tdefault",
        "com.apple.voice.premium.ko-KR.Yuna\tYuna (Premium)\tko-KR\tpremium",
        "com.apple.voice.compact.en-US.Samantha\tSamantha\ten-US\tdefault",
        "com.apple.voice.enhanced.en-US.Ava\tAva (Enhanced)\ten-US\tenhanced",
        "com.apple.voice.compact.ja-JP.Kyoko\tKyoko\tja-JP\tdefault",
        "com.apple.speech.synthesis.voice.BadNews\tBad News\ten-US\tdefault",
        "형식이 깨진 줄 — 탭 없음",
        "",
    ]
)


def _names(voices):
    return [name for _lang, name, _ident, _q in voices]


def test_parse_filters_to_downloaded_and_baseline():
    voices = parse_voice_list(SAMPLE)
    names = _names(voices)
    assert "Yuna" in names  # baseline
    assert "Yuna (Premium)" in names  # premium
    assert "Samantha" in names  # baseline
    assert "Ava (Enhanced)" in names  # enhanced
    # 다른 언어 compact·노벨티는 숨김
    assert "Kyoko" not in names
    assert "Bad News" not in names


def test_parse_ignores_malformed_lines():
    voices = parse_voice_list(SAMPLE)
    # 깨진 줄/빈 줄이 섞여도 정상 항목만 4개
    assert len(voices) == 4


def test_parse_sorted_by_lang_then_name():
    voices = parse_voice_list(SAMPLE)
    langs = [lang for lang, _n, _i, _q in voices]
    # en-US 가 ko-KR 앞에 묶여 나온다
    assert langs == sorted(langs)
    # 같은 언어 내 이름순(소문자 비교): en-US 는 Ava, Samantha 순
    en = [n for lang, n, _i, _q in voices if lang == "en-US"]
    assert en == ["Ava (Enhanced)", "Samantha"]


def test_parse_empty_returns_empty():
    assert parse_voice_list("") == []


def test_pick_default_prefers_highest_quality_yuna():
    voices = parse_voice_list(SAMPLE)
    ident = pick_default_voice(voices)
    # 프리미엄 Yuna가 있으면 그것을 고른다 (premium > default)
    assert ident == "com.apple.voice.premium.ko-KR.Yuna"


def test_pick_default_falls_back_to_compact_yuna():
    only_compact = "com.apple.voice.compact.ko-KR.Yuna\tYuna\tko-KR\tdefault"
    voices = parse_voice_list(only_compact)
    assert pick_default_voice(voices) == "com.apple.voice.compact.ko-KR.Yuna"


def test_pick_default_none_when_no_yuna():
    no_yuna = "com.apple.voice.compact.en-US.Samantha\tSamantha\ten-US\tdefault"
    voices = parse_voice_list(no_yuna)
    assert pick_default_voice(voices) is None
