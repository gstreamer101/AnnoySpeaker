# K-Balabolka 빌드 가이드

이 문서는 K-Balabolka의 세 컴포넌트(`plugin/`, `gui/`, `tools/`)를 macOS에서 처음부터 빌드하고 실행하는 절차를 정리한 문서입니다. 외부 기여자가 깨끗한 환경에서 이 문서만 보고 따라 해도 빌드가 재현되는 것이 목표입니다.

> **요점만 먼저:** GStreamer는 공식 `.pkg` Framework로 설치하고, plugin을 빌드할 때는 반드시 `PKG_CONFIG_PATH=""` + `PKG_CONFIG_LIBDIR=/Library/Frameworks/GStreamer.framework/Versions/1.0/lib/pkgconfig` 환경에서 Meson을 실행하세요. 이걸 안 하면 plugin이 빌드는 성공하지만 로드 시점에 `GObject NODE_REFCOUNT` 어설션으로 크래시합니다. 자세한 이유는 [§2.1](#21-왜-pkg_config-우회가-필요한가)에 있습니다.

---

## 1. 사전 요구 사항

| 항목 | 용도 | 설치 방법 |
|---|---|---|
| **Xcode Command Line Tools** | `clang`, `make` (plugin C/Objective-C, tools/Makefile) | `xcode-select --install` |
| **GStreamer 1.x Framework — Runtime + Development** | plugin이 동적 링크 | <https://gstreamer.freedesktop.org/download/> 에서 macOS용 `.pkg` 두 개 (`gstreamer-1.0-1.x.x-universal.pkg` + `gstreamer-1.0-devel-1.x.x-universal.pkg`) 다운로드 후 더블클릭 설치 |
| **Meson** | plugin 빌드 시스템 | `brew install meson` |
| **Ninja** | Meson이 호출하는 빌더 | `brew install ninja` |
| **Python 3.10 이상** | GUI 실행 | `brew install python@3.12` 또는 <https://www.python.org/downloads/macos/> |

빌드 도구(Meson/Ninja)에 Homebrew를 써도 무방합니다 — 이들은 우리 산출물에 링크되지 않는 빌드 시점 도구일 뿐입니다. 충돌 위험이 있는 건 GStreamer 자체뿐입니다.

### 1.1 검증된 버전

다음 조합에서 동작이 확인되었습니다. 다른 버전이어도 호환되면 동작할 가능성이 높지만, 처음 빌드하는 경우 가능하면 이 조합 또는 그 이상으로 맞추는 것을 권장합니다.

| 항목 | 검증된 버전 |
|---|---|
| macOS | 26.4 (Tahoe) |
| GStreamer | 1.28.2 |
| Python | 3.14.4 |
| Meson | 1.11.0 |
| Ninja | 1.13.2 |
| Apple clang | 21.0.0 (Xcode CLT) |

GStreamer는 1.20 이상이면 우리 plugin이 사용하는 API가 모두 존재합니다. macOS는 AVSpeechSynthesizer가 안정적으로 동작하는 12 (Monterey) 이상을 권장합니다.

---

## 2. `plugin/` 빌드 — `macttssink` GStreamer 플러그인

### 2.1 왜 PKG_CONFIG 우회가 필요한가

이 부분이 가장 자주 막히는 지점입니다. 본질을 짚고 갑니다.

- 시스템 셸의 `PKG_CONFIG_PATH`에 **Homebrew와 GStreamer Framework의 pkgconfig 경로가 함께 들어있는 경우가 많습니다** (예: macOS 개발 환경 셋업 시 자동으로 `/opt/homebrew/lib/pkgconfig`가 추가됨).
- 이 상태에서 Meson이 `pkg-config --cflags gstreamer-1.0`를 호출하면 한쪽(Framework)의 GStreamer를 보면서, 동시에 다른 쪽(Homebrew)의 GLib 헤더를 끌어옵니다.
- 빌드 자체는 경고 없이 성공합니다. 그러나 `gst-inspect-1.0 macttssink` 또는 `gst-launch-1.0`으로 plugin을 로드하는 순간, Homebrew GLib과 Framework GLib에서 같은 GObject 심볼이 두 번 등록되며 다음 어설션으로 크래시합니다.

  ```
  GObject: g_object_unref: assertion 'NODE_REFCOUNT(object) > 0' failed
  ```

- 원인이 빌드 시점에 드러나지 않기 때문에 모르고 시작하면 디버깅이 매우 어렵습니다. 그래서 **빌드 명령에서 `PKG_CONFIG_PATH`를 명시적으로 비우고 `PKG_CONFIG_LIBDIR`로 Framework만 단일 출처로 강제**합니다.

### 2.2 빌드 명령

```bash
cd plugin
PKG_CONFIG_PATH="" \
PKG_CONFIG_LIBDIR=/Library/Frameworks/GStreamer.framework/Versions/1.0/lib/pkgconfig \
meson setup builddir --reconfigure
ninja -C builddir
```

성공하면 `plugin/builddir/libgstmacttssink.dylib` 가 생성됩니다.

이미 한 번 `meson setup`을 끝낸 디렉터리에서 재빌드만 하려면 `ninja -C builddir`만 다시 돌리면 됩니다(환경변수 재지정 불필요 — Meson이 이미 캐시).

### 2.3 다른 GStreamer 설치를 쓰는 경우 (검증되지 않음)

Homebrew GStreamer 또는 직접 소스 빌드한 GStreamer를 쓰고 싶다면, `PKG_CONFIG_LIBDIR`를 그 출처의 `pkgconfig` 디렉터리로 바꿔 동일한 명령을 실행하면 됩니다. 다만 다음 사항을 주의하세요.

- macttssink는 macOS Framework 빌드(1.24 ~ 1.28)에서만 동작이 검증되었습니다.
- Homebrew GStreamer는 plugin 셋이 다르고 AVFoundation 통합 방식이 다를 수 있어, 빌드가 실패하거나 런타임 동작이 다를 수 있습니다.
- 두 출처를 동시에 보이게 한 채 빌드하면 [§2.1](#21-왜-pkg_config-우회가-필요한가)의 GLib 충돌 크래시가 재발합니다. **반드시 한 출처만 노출**시키세요.

---

## 3. `gui/` 실행 — PySide6 데스크톱 앱

### 3.1 가상환경과 의존성 설치

```bash
cd gui
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

`requirements.txt`는 PySide6 ≥ 6.8, PyInstaller ≥ 6.0 으로 최소 버전만 고정합니다. pip이 그 시점의 호환 최신 버전을 가져갑니다. 최종 빌드된 `.app`에 묶이는 정확한 PySide6/Qt 버전은 PyInstaller 빌드 로그 또는 번들 내부의 `PySide6/__init__.py`에서 확인할 수 있습니다.

### 3.2 plugin 경로 환경변수

GUI는 `macttssink` plugin을 동적으로 로드합니다. 시스템 GStreamer plugin 디렉터리에 설치하지 않고 빌드 디렉터리에서 그대로 쓰려면 다음 환경변수를 지정하세요.

```bash
export GST_PLUGIN_PATH="$(pwd)/../plugin/builddir"
```

### 3.3 실행

```bash
python main.py
```

K-Balabolka 윈도우가 뜨고, 텍스트박스에 한국어/영어 텍스트를 입력해 "재생" 버튼을 누르면 음성이 출력됩니다.

---

## 4. `tools/kb-tts-export` 빌드 — m4a 내보내기 CLI

```bash
cd tools/kb-tts-export
make
```

→ `kb-tts-export` 바이너리 생성.

별도의 외부 의존성이 없습니다(`Foundation` / `AVFoundation` 시스템 프레임워크만 사용). Xcode Command Line Tools만 설치되어 있으면 빌드됩니다.

---

## 5. 동작 확인

빌드한 결과물이 실제로 동작하는지 빠르게 확인하는 최소 명령들입니다.

### 5.1 plugin이 로드되는지

```bash
GST_PLUGIN_PATH="$(pwd)/plugin/builddir" \
gst-inspect-1.0 macttssink
```

`Element Properties: rate, pitch, volume, voice` 등이 출력되면 OK. 출력이 비어 있거나 "No such element"가 나오면 plugin이 인식되지 않은 것 — [§6.2](#62-plugin이-인식-안-됨)를 참고하세요.

> 시스템 GStreamer 환경에서 실행할 때 [§2.1](#21-왜-pkg_config-우회가-필요한가)에 설명한 GLib 어설션 크래시가 다시 발생할 수 있습니다. 그런 경우 `PKG_CONFIG` 환경을 같이 정리해서 실행하세요.

### 5.2 음성이 실제로 나오는지

```bash
echo "안녕하세요, 케이 발라볼카 입니다" | \
  GST_PLUGIN_PATH="$(pwd)/plugin/builddir" \
  gst-launch-1.0 --quiet fdsrc ! 'text/x-raw,format=utf8' ! macttssink
```

스피커에서 음성이 들리면 plugin과 AVSpeechSynthesizer 연결까지 정상입니다.

### 5.3 m4a 파일이 생성되는지

```bash
echo "테스트 텍스트" | tools/kb-tts-export/kb-tts-export -o /tmp/test.m4a
afplay /tmp/test.m4a
```

`/tmp/test.m4a`가 생성되고 재생되면 export 도구 정상.

---

## 6. 자주 만나는 문제

### 6.1 GObject NODE_REFCOUNT 어설션 크래시

```
GObject: g_object_unref: assertion 'NODE_REFCOUNT(object) > 0' failed
```

**원인:** Homebrew GLib과 Framework GLib이 동시에 링크됨.
**해결:** [§2.2](#22-빌드-명령)의 명령처럼 `PKG_CONFIG_PATH=""`로 비우고 `PKG_CONFIG_LIBDIR`로 Framework만 명시한 다음 **`meson setup builddir --reconfigure`로 재구성**한 뒤 다시 빌드하세요. 캐시가 남아 있으면 같은 증상이 반복됩니다.

### 6.2 plugin이 인식 안 됨

`gst-inspect-1.0 macttssink` 가 "No such element or plugin 'macttssink'"를 반환합니다.

**원인:** `GST_PLUGIN_PATH`가 설정되지 않았거나, 빌드 디렉터리를 잘못 가리킴.
**해결:** 절대 경로로 `$(pwd)/plugin/builddir`를 지정. `ls plugin/builddir/libgstmacttssink.dylib` 로 dylib가 실제 존재하는지 먼저 확인하세요.

### 6.3 한국어 음성이 영어 발음으로 들림

**원인:** macOS가 한국어 voice를 선택하지 못해 영어 기본 음성으로 fallback함.
**해결:** GUI의 voice 선택 드롭다운에서 한국어 음성(예: `com.apple.voice.compact.ko-KR.Yuna`)을 명시적으로 선택. CLI로 직접 테스트할 때는 `voice` 속성을 지정하세요.

```bash
gst-launch-1.0 ... ! macttssink voice=com.apple.voice.compact.ko-KR.Yuna
```

### 6.4 PyInstaller로 빌드한 `.app`이 실행이 안 됨

원인이 다양합니다(코드 서명, plugin .dylib 미동봉, GStreamer Framework 미동봉 등). 개발일지 `docs/dev-log/07-Stage7-App패키징.md`에 우리가 실제로 만난 케이스가 정리되어 있습니다(현 시점에서는 개인 문서, 외부 공개 X).

---

## 7. 다음 단계

빌드와 실행이 검증되면, 변경을 제출하기 위한 기여 절차는 `CONTRIBUTING.md`를 참고하세요(DCO 서명 안내 포함).
