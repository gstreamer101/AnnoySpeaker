# 테스트 카탈로그

AnnoySpeaker의 자동화 테스트가 **무엇을** 검증하는지 정리한 문서입니다. 기능을 추가하거나 바꿀 때, 여기서 관련 테스트를 찾고 **테스트를 추가/갱신한 뒤 이 표도 함께 업데이트**해 주세요.

> ⚠️ **이 문서는 손으로 관리합니다.** 테스트 함수를 추가/이름변경/삭제하면 아래 표의 해당 행도 같이 고쳐 주세요.
>
> 🤖 **자동 가드:** `tests/test_catalog.py`가 카탈로그 대상 파일의 모든 `test_*` 함수가 이 문서에 적혀 있는지 검사합니다. 빠뜨리면 `pytest`/CI가 실패하니, 표를 갱신하면 됩니다.

## 실행

```bash
pip install pytest      # 최초 1회
pytest                  # 저장소 루트에서 (또는: gui/.venv/bin/python -m pytest)
```

- **순수 로직 테스트**는 GStreamer/AVSpeech·PySide6 없이 헤드리스로 돈다(1초 내). Linux CI에서 자동 실행.
- **플러그인/도구 테스트**는 `kb-tts-export`·`gst-inspect-1.0`가 있어야 돌고, 없으면 자동 `skip`. macOS에서 빌드 후 실행.

## 무엇이 자동화되고, 무엇이 안 되나

| 구분 | 자동화 | 이유 |
|---|---|---|
| 텍스트 전처리·읽기 문자열·offset_map·속도 곡선 | ✅ 단위 테스트 | 순수 로직(백엔드 무관) |
| 음성 목록 파싱·필터·기본 선택 | ✅ 단위 테스트 | 순수 로직 |
| m4a 내보내기, 플러그인 속성 | ✅ CLI 테스트 (있을 때) | `kb-tts-export`는 **오프라인 합성**이라 헤드리스 가능 |
| 실제 **재생·발음·일시정지·단어 하이라이트** | ❌ 수동 | AVSpeechSynthesizer 라이브 재생은 헤드리스에서 소리·콜백이 안 나옴 |

수동으로 확인해야 하는 항목은 맨 아래 [§ 수동 검증 항목](#수동-검증-항목) 참고.

---

## A. 텍스트 전처리 / 읽기 문자열 — `tests/test_textproc.py`

대상: `gui/textproc.py` (재생·내보내기 공통 텍스트 처리)

| 테스트 | 검증 대상 기능 | 정상 동작(기대) |
|---|---|---|
| `test_preprocess_empty_and_whitespace_only` | 빈/공백 입력 | 빈 문자열 `""` 반환 |
| `test_preprocess_adds_period_to_nonlast_lines_only` | 줄 끝 마침표 자동 추가 | 비마지막 줄엔 `.` 추가, **마지막 줄엔 안 붙음**(끝음절 잘림 방지) |
| `test_preprocess_keeps_existing_terminator` | 종결부호 중복 방지 | 이미 `.!?`로 끝난 줄엔 마침표 안 붙임 |
| `test_preprocess_collapses_inline_whitespace` | 공백 정리 | 연속 공백/탭 → 단일 공백 |
| `test_preprocess_blank_lines_are_paragraph_breaks` | 단락 처리 | 빈 줄은 사라지고 양쪽 줄은 보존(각 줄 끝에서 쉼) |
| `test_preprocess_neutralizes_angle_brackets` | 꺾쇠 중화 | `<기자>` → 공백 중화, 안쪽 글자 보존, `<`/`>` 미포함(발화 끊김 방지) |
| `test_build_spoken_equals_preprocess_plus_padding` | **재생/내보내기 경로 일치** | `build_spoken_text(t)[0] == preprocess(t) + TAIL_PADDING` (두 경로 발음 동일) |
| `test_build_spoken_empty_returns_empty` | 빈 입력 처리 | `("", [])` 반환 |
| `test_omap_length_matches_spoken` | offset_map 정합성 | `len(omap) == len(spoken)` |
| `test_omap_real_chars_point_to_original` | 하이라이트 매핑 | 삽입(-1)이 아닌 글자는 `spoken[i] == text[omap[i]]` |
| `test_omap_inserted_chars_are_negative` | 삽입 글자 표시 | 자동 마침표·줄 연결 공백·끝 패딩은 omap에서 `-1` |
| `test_tail_padding_has_no_comma_regression` | **회귀 #58** | `TAIL_PADDING`·읽기 문자열에 쉼표 없음(프리미엄 음성이 "쉼표"로 읽는 것 방지) |
| `test_ui_speed_to_rate_anchor_points` | 속도 곡선 | UI 0→rate 0, 1.0→0.5(default), 2.0→0.7(상한) |
| `test_ui_speed_to_rate_monotonic` | 속도 곡선 | UI 0~2 전 구간 단조 증가 |
| `test_ui_speed_to_rate_upper_segment_compressed` | 속도 곡선 | 1.0 위 구간 기울기 < 아래 구간(비선형 압축) |
| `test_map_spoken_range_roundtrip` | 범위 역매핑 | 읽기 범위 → 원본 범위 정확 매핑 |
| `test_map_spoken_range_all_inserted_returns_none` | 범위 역매핑 | 전부 삽입(-1) 구간이면 `None` |
| `test_map_spoken_range_clamps_out_of_bounds` | 범위 역매핑 | end가 길이 초과해도 예외 없이 클램프 |
| `test_long_text_does_not_crash` | 긴 텍스트 | 수천 자도 안전 처리, omap 정합 유지 |
| `test_module_constants_present` | 모듈 계약 | main.py가 기대하는 상수 노출 |

## B. 음성 목록 — `tests/test_voices.py`

대상: `gui/voices.py` (`--list-voices` 출력 파싱·필터·기본 선택)

| 테스트 | 검증 대상 기능 | 정상 동작(기대) |
|---|---|---|
| `test_parse_filters_to_downloaded_and_baseline` | 음성 필터(#42 v4 규칙) | enhanced/premium + baseline(Yuna/Samantha)만 노출, 타 언어 compact·노벨티 숨김 |
| `test_parse_ignores_malformed_lines` | 견고성 | 탭 필드 4개 미만·빈 줄 무시 |
| `test_parse_sorted_by_lang_then_name` | 정렬 | (언어, 이름 소문자) 순 — 같은 언어끼리 묶임 |
| `test_parse_empty_returns_empty` | 빈 입력 | `[]` 반환 |
| `test_pick_default_prefers_highest_quality_yuna` | 기본 선택 | 이름이 Yuna로 시작하는 음성 중 최고 품질(premium>enhanced>default) |
| `test_pick_default_falls_back_to_compact_yuna` | 기본 선택 | 프리미엄이 없으면 compact Yuna |
| `test_pick_default_none_when_no_yuna` | 기본 선택 | Yuna가 없으면 `None`(첫 항목으로 폴백) |

## C. 플러그인 / 네이티브 도구 — `tests/test_plugin_cli.py`

대상: `tools/kb-tts-export`, `plugin/` (시스템 의존 — 도구·GStreamer 없으면 `skip`)

> 🎙️ **`avspeech` 마커**: 라이브 AVSpeech 합성이 실제로 동작해야 하는 테스트. 로컬/실기기 `pytest`에선 돌지만, **헤드리스 CI 러너에선 합성 출력이 안 나와 멈추므로 2차 CI에서 `-m "not avspeech"`로 제외**된다. 즉 m4a 변환 검증은 **로컬/macOS 실기기에서** 수행된다.

| 테스트 | 검증 대상 기능 | 정상 동작(기대) |
|---|---|---|
| `test_list_voices_format` | `kb-tts-export --list-voices` | exit 0, 각 줄이 `id\tname\tlang\tquality` 4필드 이상 |
| `test_export_short_text_creates_m4a` 🎙️ | m4a 내보내기 (짧은 텍스트) | exit 0, **유효한 m4a 컨테이너**(ftyp 박스, 크기>0), stderr에 `Encoding`/`Saved:` |
| `test_export_large_text_creates_m4a` 🎙️ | m4a 내보내기 (1만 자 이상 대용량) | exit 0, 유효한 m4a 컨테이너, `Saved:`, 청크 2개 이상으로 분할 |
| `test_export_long_text_per_chunk_progress` 🎙️ | **회귀 #54** | 긴 텍스트가 여러 청크로 분할, `... i/N chunks` 진행이 **청크마다**(10개마다 아님) 출력 |
| `test_macttssink_exposes_properties` | 플러그인 속성 | `gst-inspect-1.0 macttssink`가 `rate`/`pitch`/`volume`/`voice` 노출 |

(🎙️ = `avspeech` 마커 — 헤드리스 CI 제외, 로컬/실기기에서 검증)

---

## 테스트 케이스를 추가하는 법

1. **어느 파일에?**
   - 순수 로직(백엔드 무관) → `test_textproc.py` / `test_voices.py`, 또는 새 순수 모듈이면 `test_<모듈>.py`
   - 네이티브 도구/플러그인 동작 → `test_plugin_cli.py` (반드시 도구 부재 시 `skip` 가드)
2. **테스트 작성** — 함수명은 `test_<무엇을_검증>`. 짧은/긴 텍스트는 `short_text`/`long_text` 픽스처(`conftest.py`) 사용. 테스트 데이터는 **저작권 안전한 것만**(자작 또는 퍼블릭 도메인).
3. **이 문서 갱신** — 위 표에 행 추가: 테스트 함수 / 검증 대상 기능 / 정상 동작.
4. **로컬 검증** — `pytest` + `ruff check gui/ tests/` + `ruff format --check gui/ tests/` 통과 확인 후 PR.

> 새 기능이 **재생/발음처럼 자동화 불가**라면, 자동 테스트 대신 아래 수동 검증 항목에 추가하고 PR 본문에 수동 확인 결과를 적어 주세요.

## 수동 검증 항목

AVSpeech 라이브 재생은 헤드리스 자동화가 불가능하므로, **`plugin/` 또는 재생 경로를 바꾸는 PR**은 `.app`을 빌드(`./scripts/setup-dev.sh --build-app`)해 아래를 사람이 확인합니다.

| 항목 | 확인 방법 | 정상 동작 |
|---|---|---|
| 기본 재생 | 짧은/긴 텍스트 ▶ | 끊김 없이 끝까지, 끝나면 상태바 "준비"·▶ 재활성화 |
| 일시정지/재개 (회귀 #56) | ▶↔‖ 빠르게 반복(특히 긴 텍스트 뒤쪽) | "한 단어 읽고 무한 대기" 없이 계속 재생, 멈춘 단어부터 이어짐 |
| 정지 | 재생/일시정지 중 ■ | 즉시 멈추고 idle, 다시 ▶ 누르면 처음부터 |
| 단어 하이라이트 | 재생 중 관찰 | 들리는 단어와 파란 하이라이트 일치, 재개 후에도 어긋나지 않음 |
| 끝음절·쉼표 (회귀 #58) | 마지막 줄까지 재생 | 끝음절(받침) 안 잘림, 끝에 "쉼표" 안 읽음 |
| 내보내기 진행률 (#54) | 저장 중 관찰 | 모달 진행률 바/%·텍스트 입력 잠금·취소 동작, 결과 m4a 정상 |
