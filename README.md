# AnnoySpeaker

macOS용 텍스트 음성 변환 리더. macOS 시스템 음성 합성(AVSpeechSynthesizer)을 GStreamer 파이프라인 위에서 활용하는 데스크톱 애플리케이션입니다. Windows용 [Balabolka](https://www.cross-plus-a.com/balabolka.htm)에서 영감을 받았습니다.

> **⚠️ 원작과의 관계 (비제휴 고지)**
> 본 프로젝트는 Windows용 텍스트 음성 변환 리더 Balabolka에서 영감을 받은 독립 프로젝트이며, 원작 및 그 저작자(Ilya Morozov)와 **제휴하거나 승인받은 관계가 아닙니다.** 코드는 처음부터 독립적으로 작성되었습니다. 원작은 <https://www.cross-plus-a.com/balabolka.htm> 에서 확인할 수 있습니다.
>
> **명칭의 유래:** "Балаболка"(Balabolka)는 러시아어로 "쉴 새 없이 떠드는 사람 / 수다쟁이"라는 뜻입니다. **AnnoySpeaker**라는 이름은 그 어원의 자조적 뉘앙스를 영어로 옮긴 오마주입니다 — 원작에 대한 존중을 의미로 유지하면서도, 명칭 자체는 독립적입니다.

---

## 설치 · 빌드 · 실행

아래 명령어를 위에서부터 차례로 복사-붙여넣기만 하면 **clone → 빌드 → 실행**까지 한 번에 됩니다. macOS 12 이상이 필요합니다.

### 1) 사전 도구 설치

```bash
# Xcode Command Line Tools (clang, make)
xcode-select --install

# Meson, Ninja, Python (Homebrew 사용)
brew install meson ninja python@3.12
```

그리고 **GStreamer 1.x Framework**를 공식 사이트에서 받아 설치하세요(`.pkg` 두 개를 더블클릭):
<https://gstreamer.freedesktop.org/download/> 에서

- `gstreamer-1.0-1.x.x-universal.pkg` (Runtime)
- `gstreamer-1.0-devel-1.x.x-universal.pkg` (Development)

> Homebrew의 `gstreamer`가 아니라 공식 `.pkg` Framework여야 합니다. 이유는 [BUILD.md](BUILD.md)에 자세히 있습니다.

### 2) 저장소 가져오기

```bash
git clone https://github.com/gstreamer101/AnnoySpeaker.git
cd AnnoySpeaker
```

### 3) `macttssink` GStreamer 플러그인 빌드

```bash
cd plugin
PKG_CONFIG_PATH="" \
PKG_CONFIG_LIBDIR=/Library/Frameworks/GStreamer.framework/Versions/1.0/lib/pkgconfig \
meson setup builddir --reconfigure
ninja -C builddir
cd ..
```

→ `plugin/builddir/gstmacttssink.dylib` 가 생성됩니다.

### 4) GUI 실행

```bash
cd gui
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
GST_PLUGIN_PATH="$(pwd)/../plugin/builddir" python main.py
```

AnnoySpeaker 윈도우가 뜨면 텍스트박스에 한국어/영어를 입력하고 "재생"을 눌러보세요.

### 5) (옵션) m4a 내보내기 도구 빌드

GUI에서 m4a 내보내기를 쓰려면 export 도구를 함께 빌드하세요.

```bash
cd tools/kb-tts-export
make
cd ../..
```

### 6) 동작 확인 (CLI)

GUI 없이 plugin이 잘 동작하는지 빠르게 검증:

```bash
echo "안녕하세요, 케이 발라볼카 입니다" | \
  GST_PLUGIN_PATH="$(pwd)/plugin/builddir" \
  gst-launch-1.0 --quiet fdsrc ! 'text/x-raw,format=utf8' ! macttssink
```

스피커에서 음성이 들리면 OK.

### 7) (옵션) `.app`으로 패키징해서 venv 없이 더블클릭 실행

매번 `source .venv/bin/activate && python main.py` 하기 번거롭다면, PyInstaller로 `.app` 번들을 만들어 두면 됩니다 — Python 인터프리터와 PySide6를 `.app` 안에 묶기 때문에 venv 활성화 없이 더블클릭만으로 실행됩니다.

위 1)~5)를 마친 상태에서 한 명령으로:

```bash
./scripts/setup-dev.sh --build-app
```

또는 수동으로:

```bash
cd gui && source .venv/bin/activate && pyinstaller --noconfirm AnnoySpeaker.spec && cd ..
```

→ `gui/dist/AnnoySpeaker.app` 생성. `/Applications`으로 복사하면 Launchpad / Spotlight에서 검색 가능:

```bash
cp -R gui/dist/AnnoySpeaker.app /Applications/
```

또는 빌드 직후 바로 실행:

```bash
open gui/dist/AnnoySpeaker.app
```

> **참고:** 현재 앱 아이콘이 macOS 기본(회색)으로 표시됩니다. 아이콘 디자인은 별도 후속 작업입니다.

---

## 막혔을 때

- 빌드/실행 중 `GObject: NODE_REFCOUNT` 같은 크래시나 "plugin이 인식 안 됨"이 나오면 → **[BUILD.md "자주 만나는 문제"](BUILD.md#6-자주-만나는-문제)** 절을 먼저 보세요.
- 위 명령어가 왜 이렇게 되어 있는지(특히 `PKG_CONFIG_PATH=""` 우회) 궁금하면 → **[BUILD.md § 2.1](BUILD.md#21-왜-pkg_config-우회가-필요한가)** 에 원리가 정리되어 있습니다.
- Homebrew GStreamer나 직접 소스 빌드한 GStreamer를 쓰고 싶다면 → **[BUILD.md § 2.3](BUILD.md#23-다른-gstreamer-설치를-쓰는-경우-검증되지-않음)** 의 fallback 안내를 참고하세요(검증되지 않은 경로).

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
