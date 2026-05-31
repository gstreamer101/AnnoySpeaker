# AnnoySpeaker

macOS용 텍스트 음성 변환 리더. macOS 시스템 음성 합성(AVSpeechSynthesizer)을 GStreamer 파이프라인 위에서 활용하는 데스크톱 애플리케이션입니다. Windows용 [Balabolka](https://www.cross-plus-a.com/balabolka.htm)에서 영감을 받았습니다.

> **⚠️ 원작과의 관계 (비제휴 고지)**
> 본 프로젝트는 Windows용 텍스트 음성 변환 리더 Balabolka에서 영감을 받은 독립 프로젝트이며, 원작 및 그 저작자(Ilya Morozov)와 **제휴하거나 승인받은 관계가 아닙니다.** 코드는 처음부터 독립적으로 작성되었습니다. 원작은 <https://www.cross-plus-a.com/balabolka.htm> 에서 확인할 수 있습니다.
>
> **명칭의 유래:** "Балаболка"(Balabolka)는 러시아어로 "쉴 새 없이 떠드는 사람 / 수다쟁이"라는 뜻입니다. **AnnoySpeaker**라는 이름은 그 어원의 자조적 뉘앙스를 영어로 옮긴 오마주입니다 — 원작에 대한 존중을 의미로 유지하면서도, 명칭 자체는 독립적입니다.

---

## 설치 · 실행

macOS 12 이상에서 **3단계로 끝**납니다. 한 명령으로 빌드 + 설치까지 자동.

### 1) 사전 도구 설치

```bash
# Xcode Command Line Tools (clang, make)
xcode-select --install

# Meson, Ninja, Python (Homebrew)
brew install meson ninja python@3.12
```

그리고 **GStreamer 1.x Framework**를 공식 사이트에서 받아 설치 (`.pkg` 두 개 더블클릭):

<https://gstreamer.freedesktop.org/download/> 에서

- `gstreamer-1.0-1.x.x-universal.pkg` (Runtime)
- `gstreamer-1.0-devel-1.x.x-universal.pkg` (Development)

> Homebrew의 `gstreamer`가 아니라 공식 `.pkg` Framework가 필요합니다. 이유는 [BUILD.md § 2.1](BUILD.md#21-왜-pkg_config-우회가-필요한가)에 있습니다.

### 2) 저장소 가져오기

```bash
git clone https://github.com/gstreamer101/AnnoySpeaker.git
cd AnnoySpeaker
```

### 3) 한 명령으로 빌드 + 설치

```bash
./scripts/setup-dev.sh --build-app
```

이 한 명령이:

- 사전 도구 점검
- `macttssink` GStreamer 플러그인 빌드 (`plugin/builddir/gstmacttssink.dylib`)
- GUI 가상환경 + PySide6/PyInstaller 설치
- m4a 내보내기 도구 빌드 (`tools/kb-tts-export`)
- PyInstaller로 `.app` 빌드 (Python 인터프리터·PySide6·plugin .dylib·export 도구 모두 `.app` 안에 묶음, ≈ 103MB)
- **`/Applications/AnnoySpeaker.app` 자동 설치** (기존 설치는 새 빌드로 덮어씀)

까지 자동으로 수행합니다. 몇 분 소요.

완료되면 **Launchpad에서 "AnnoySpeaker" 검색하거나 Applications 폴더에서 더블클릭**으로 실행하세요.

> **옵션:** `/Applications`에 자동 설치하지 않고 `gui/dist/AnnoySpeaker.app`만 만들고 싶으면 `--no-install`을 추가하세요.
>
> **참고:** 현재 앱 아이콘이 macOS 기본(회색)으로 표시됩니다. 아이콘 디자인은 별도 후속 작업입니다.

---

## 막혔을 때 / 더 자세히

- **빌드/실행 중 에러** (예: `GObject: NODE_REFCOUNT` 크래시, "plugin 인식 안 됨", 한국어 음성이 영어로 나옴 등) → [BUILD.md "자주 만나는 문제"](BUILD.md#6-자주-만나는-문제)
- **수동으로 단계별 빌드하고 싶거나 코드를 수정해 venv에서 직접 실행하려면** → [BUILD.md](BUILD.md)에 plugin 빌드(§2)·GUI venv 실행(§3)·동작 확인 CLI(§5) 전체 절차가 있습니다.
- **다른 GStreamer 출처**(Homebrew, 직접 소스 빌드 등)를 쓰고 싶으면 → [BUILD.md § 2.3](BUILD.md#23-다른-gstreamer-설치를-쓰는-경우-검증되지-않음) (검증되지 않은 경로)

---

## 아키텍처

```
┌──────────────────────────────────┐      ┌────────────────────────┐
│       PySide6 GUI (Python)       │      │  tools/kb-tts-export   │
│            gui/main.py           │      │   (Objective-C CLI)    │
└─────────────────┬────────────────┘      └───────────┬────────────┘
                  │                                   │
                  ▼                                   ▼
┌──────────────────────────────────┐      ┌────────────────────────┐
│      GStreamer 1.x pipeline      │      │  AVSpeechSynthesizer   │
│  fdsrc/filesrc ! macttssink ...  │      │   + AVAssetWriter      │
└─────────────────┬────────────────┘      │   → .m4a (AAC)         │
                  │                       └────────────────────────┘
                  ▼
┌──────────────────────────────────┐
│  macttssink (C + Objective-C)    │
│   plugin/gstmacttssink*.{c,m}    │
└─────────────────┬────────────────┘
                  ▼
       AVSpeechSynthesizer (macOS)
```

- **재생 경로**: GUI → GStreamer pipeline → `macttssink` plugin → AVSpeechSynthesizer → 시스템 스피커.
- **Export 경로**: GUI 또는 직접 CLI → `kb-tts-export`(독립 도구) → AVAssetWriter → `.m4a` 파일.

---

## 컴포넌트 / 라이선스

이 프로젝트는 **디렉터리별로 다른 라이선스**를 적용합니다. 자세한 라이선스 전문과 분할 근거는 [LICENSE](LICENSE) 파일을 참고하세요.

| 디렉터리 | 내용 | 라이선스 |
|---|---|---|
| [`plugin/`](plugin/) | GStreamer 커스텀 sink 플러그인 (`macttssink`) — C + Objective-C | **LGPL-2.1-or-later** |
| [`gui/`](gui/) | PySide6 데스크톱 애플리케이션, PyInstaller로 `.app` 패키징 | **MIT** |
| [`tools/`](tools/) | 음성 파일(m4a) 내보내기 네이티브 도구 — Objective-C | **MIT** |

`plugin/`이 LGPL인 이유는 GStreamer(LGPL) 런타임에 동적 링크되기 때문이고, `gui/`와 `tools/`가 MIT인 이유는 최종 애플리케이션 산출물이라 LGPL의 재링크 조항이 배포에 마찰을 주기 때문입니다.

배포 산출물(`.app` 번들)에 동봉되는 제3자 컴포넌트(GStreamer, PySide6/Qt 등)의 라이선스와 소스 입수 경로는 **[NOTICE](NOTICE)** 에 정리되어 있습니다.

---

## 기여하기

외부 기여를 환영합니다. PR 제출 전 **[CONTRIBUTING.md](CONTRIBUTING.md)** 를 읽어주세요. 핵심 사항:

- 이 프로젝트는 기여물의 권리 처리에 **DCO**(Developer Certificate of Origin)를 채택합니다. 커밋에 `git commit -s`로 `Signed-off-by` 줄을 남겨주세요.
- 디렉터리별로 라이선스가 다르므로, 한 디렉터리의 코드를 다른 디렉터리로 옮길 때는 SPDX 헤더를 함께 옮겨야 합니다.

---

## 라이선스 / 고지 / 기여 문서 모음

- 우리 자체 소스 코드 → [LICENSE](LICENSE) (`plugin/` LGPL-2.1-or-later, `gui/` + `tools/` MIT)
- 제3자 컴포넌트 고지 → [NOTICE](NOTICE)
- 기여 절차와 DCO → [CONTRIBUTING.md](CONTRIBUTING.md)
- 빌드 상세와 트러블슈팅 → [BUILD.md](BUILD.md)

---

## 참고 / 감사

- **원작**: [Balabolka](https://www.cross-plus-a.com/balabolka.htm) by Ilya Morozov (Windows).
- **설계 참고**: [avstack/gst-ttssink](https://github.com/avstack/gst-ttssink) — Rust 기반 cross-platform GStreamer TTS sink. AnnoySpeaker는 이 프로젝트를 학습한 뒤 C/Objective-C로 처음부터 독립 구현했으며 코드를 복사하지 않았습니다(자세한 내용은 [NOTICE § 4](NOTICE) 참고).
- **GStreamer**: <https://gstreamer.freedesktop.org/>
