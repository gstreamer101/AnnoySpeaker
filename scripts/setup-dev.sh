#!/usr/bin/env bash
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 dlgus8648
#
# AnnoySpeaker 개발 환경 자동 설정 스크립트
#
# 사전 체크 → plugin 빌드 → GUI venv + pip install → export 도구 빌드를
# 한 번에 수행합니다. BUILD.md의 절차를 그대로 코드로 옮긴 것입니다.
#
# 사용법:
#   ./scripts/setup-dev.sh                # 기본: 모두 실행
#   ./scripts/setup-dev.sh --no-gui       # GUI venv 단계 건너뜀
#   ./scripts/setup-dev.sh --no-export    # export 도구 빌드 건너뜀
#   ./scripts/setup-dev.sh --check-only   # 사전 체크만 (빌드 안 함)
#   ./scripts/setup-dev.sh --install-deps # 누락 brew 패키지 자동 설치
#   ./scripts/setup-dev.sh --build-app    # 위 단계 + PyInstaller로 .app 빌드 + /Applications 자동 설치
#   ./scripts/setup-dev.sh --build-app --no-install  # .app 빌드는 하되 /Applications 설치는 건너뜀
#   ./scripts/setup-dev.sh -h | --help    # 도움말
#
# 자세한 절차와 트러블슈팅은 BUILD.md를 참고하세요.

set -euo pipefail

# ─────────────────────────────────────────────────────────────────
# 설정 / 경로
# ─────────────────────────────────────────────────────────────────

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

GST_FRAMEWORK_DIR="/Library/Frameworks/GStreamer.framework"
GST_PKGCONFIG_DIR="$GST_FRAMEWORK_DIR/Versions/1.0/lib/pkgconfig"

PYTHON_MIN_MAJOR=3
PYTHON_MIN_MINOR=10

# ─────────────────────────────────────────────────────────────────
# 옵션 파싱
# ─────────────────────────────────────────────────────────────────

DO_GUI=1
DO_EXPORT=1
CHECK_ONLY=0
INSTALL_DEPS=0
BUILD_APP=0
INSTALL_APP=1  # --build-app일 때 /Applications에 자동 복사 (--no-install로 끔)

print_help() {
  # 파일 상단의 주석 블록 중 헤더(4~21행)만 추출해 출력. 빈 주석 줄은 빈 줄로.
  sed -n '4,21p' "$0" | sed 's/^# \{0,1\}//'
}

for arg in "$@"; do
  case "$arg" in
    --no-gui)        DO_GUI=0 ;;
    --no-export)     DO_EXPORT=0 ;;
    --check-only)    CHECK_ONLY=1 ;;
    --install-deps)  INSTALL_DEPS=1 ;;
    --build-app)     BUILD_APP=1 ;;
    --no-install)    INSTALL_APP=0 ;;
    -h|--help)       print_help; exit 0 ;;
    *)
      echo "알 수 없는 옵션: $arg" >&2
      echo "사용법은 $0 --help 참고." >&2
      exit 2
      ;;
  esac
done

# --build-app는 GUI venv가 필수 선행. 두 옵션 같이 주면 충돌.
if (( BUILD_APP && ! DO_GUI )); then
  echo "옵션 충돌: --build-app은 --no-gui와 함께 쓸 수 없습니다." >&2
  echo ".app 빌드에는 GUI venv(PyInstaller 포함)가 필요합니다." >&2
  exit 2
fi

# 단계 표시 동적 — --build-app이면 [N/5], 아니면 [N/4].
TOTAL_STEPS=4
(( BUILD_APP )) && TOTAL_STEPS=5

# ─────────────────────────────────────────────────────────────────
# 색 출력 (TTY일 때만)
# ─────────────────────────────────────────────────────────────────

if [[ -t 1 ]]; then
  C_BOLD=$'\033[1m'
  C_RED=$'\033[31m'
  C_GREEN=$'\033[32m'
  C_YELLOW=$'\033[33m'
  C_BLUE=$'\033[34m'
  C_DIM=$'\033[2m'
  C_RESET=$'\033[0m'
else
  C_BOLD=''; C_RED=''; C_GREEN=''; C_YELLOW=''; C_BLUE=''; C_DIM=''; C_RESET=''
fi

step()  { echo; echo "${C_BOLD}${C_BLUE}▸ $*${C_RESET}"; }
ok()    { echo "  ${C_GREEN}✓${C_RESET} $*"; }
warn()  { echo "  ${C_YELLOW}!${C_RESET} $*"; }
fail()  { echo "  ${C_RED}✘${C_RESET} $*" >&2; }
note()  { echo "  ${C_DIM}$*${C_RESET}"; }

# ─────────────────────────────────────────────────────────────────
# 헬퍼
# ─────────────────────────────────────────────────────────────────

has_cmd() { command -v "$1" >/dev/null 2>&1; }

# Python 버전이 PYTHON_MIN_MAJOR.PYTHON_MIN_MINOR 이상인지 확인.
python_ok() {
  local v
  v="$("$1" -c 'import sys; print(f"{sys.version_info[0]}.{sys.version_info[1]}")' 2>/dev/null)" || return 1
  local major="${v%%.*}"
  local minor="${v#*.}"
  if [[ "$major" -gt "$PYTHON_MIN_MAJOR" ]]; then return 0; fi
  if [[ "$major" -eq "$PYTHON_MIN_MAJOR" && "$minor" -ge "$PYTHON_MIN_MINOR" ]]; then return 0; fi
  return 1
}

# brew 누락 패키지를 INSTALL_DEPS=1이면 설치, 아니면 안내만.
brew_install_or_advise() {
  local pkg="$1"
  if (( INSTALL_DEPS )); then
    warn "$pkg 누락 → brew install $pkg 자동 실행"
    brew install "$pkg"
  else
    fail "$pkg 누락. 다음 명령으로 설치하세요: brew install $pkg"
    return 1
  fi
}

# ─────────────────────────────────────────────────────────────────
# 1단계: 사전 체크
# ─────────────────────────────────────────────────────────────────

MISSING=0

step "[1/${TOTAL_STEPS}] 사전 체크"

# macOS인가
if [[ "$(uname -s)" != "Darwin" ]]; then
  fail "이 스크립트는 macOS 전용입니다. (현재 OS: $(uname -s))"
  exit 1
fi
ok "macOS 확인 ($(sw_vers -productName) $(sw_vers -productVersion))"

# Xcode Command Line Tools
if ! xcode-select -p >/dev/null 2>&1; then
  fail "Xcode Command Line Tools 누락. 다음 명령으로 설치하세요: xcode-select --install"
  MISSING=$((MISSING+1))
else
  ok "Xcode Command Line Tools 설치됨 ($(xcode-select -p))"
fi

# Homebrew (brew를 빌드 도구 설치 경로로 사용)
if ! has_cmd brew; then
  fail "Homebrew 누락. https://brew.sh 에서 설치 후 다시 실행하세요."
  MISSING=$((MISSING+1))
else
  ok "Homebrew 설치됨 ($(brew --version | head -1))"
fi

# Meson
if ! has_cmd meson; then
  brew_install_or_advise meson || MISSING=$((MISSING+1))
else
  ok "Meson 설치됨 ($(meson --version))"
fi

# Ninja
if ! has_cmd ninja; then
  brew_install_or_advise ninja || MISSING=$((MISSING+1))
else
  ok "Ninja 설치됨 ($(ninja --version))"
fi

# Python 3.10+
PYTHON_BIN=""
for candidate in python3.12 python3.11 python3.10 python3; do
  if has_cmd "$candidate" && python_ok "$candidate"; then
    PYTHON_BIN="$candidate"
    break
  fi
done

if [[ -z "$PYTHON_BIN" ]]; then
  fail "Python ${PYTHON_MIN_MAJOR}.${PYTHON_MIN_MINOR}+ 누락. 다음 중 하나로 설치하세요:"
  note "  brew install python@3.12"
  note "  또는 https://www.python.org/downloads/macos/"
  MISSING=$((MISSING+1))
else
  ok "Python 설치됨 ($PYTHON_BIN $("$PYTHON_BIN" --version | awk '{print $2}'))"
fi

# GStreamer Framework
if [[ ! -d "$GST_FRAMEWORK_DIR" ]]; then
  fail "GStreamer Framework 누락 ($GST_FRAMEWORK_DIR 없음)."
  note "다음 두 .pkg를 https://gstreamer.freedesktop.org/download/ 에서 받아 더블클릭 설치하세요:"
  note "  - gstreamer-1.0-1.x.x-universal.pkg          (Runtime)"
  note "  - gstreamer-1.0-devel-1.x.x-universal.pkg    (Development)"
  note "Homebrew의 gstreamer는 사용하지 않습니다(BUILD.md §2.1 참고)."
  MISSING=$((MISSING+1))
elif [[ ! -d "$GST_PKGCONFIG_DIR" ]]; then
  fail "GStreamer Framework는 있으나 Development 패키지가 누락 ($GST_PKGCONFIG_DIR 없음)."
  note "위 두 .pkg 중 devel 패키지를 다시 설치해 주세요."
  MISSING=$((MISSING+1))
else
  GST_VER="$(PKG_CONFIG_PATH="" PKG_CONFIG_LIBDIR="$GST_PKGCONFIG_DIR" pkg-config --modversion gstreamer-1.0 2>/dev/null || echo unknown)"
  ok "GStreamer Framework 설치됨 (v$GST_VER, Runtime + Development)"
fi

if (( MISSING > 0 )); then
  echo
  fail "사전 체크에서 ${MISSING}개 항목이 누락되었습니다. 위 안내에 따라 설치 후 다시 실행하세요."
  exit 1
fi

if (( CHECK_ONLY )); then
  echo
  ok "${C_BOLD}사전 체크 모두 통과 (--check-only 모드, 빌드 건너뜀).${C_RESET}"
  exit 0
fi

# ─────────────────────────────────────────────────────────────────
# 2단계: plugin 빌드
# ─────────────────────────────────────────────────────────────────

step "[2/${TOTAL_STEPS}] plugin 빌드 (macttssink GStreamer 플러그인)"

cd "$PROJECT_ROOT/plugin"

note "PKG_CONFIG_PATH 비우고 PKG_CONFIG_LIBDIR로 Framework만 강제합니다 (BUILD.md §2.1 참고)."

PKG_CONFIG_PATH="" \
PKG_CONFIG_LIBDIR="$GST_PKGCONFIG_DIR" \
  meson setup builddir --reconfigure

ninja -C builddir

if [[ -f "$PROJECT_ROOT/plugin/builddir/gstmacttssink.dylib" ]]; then
  ok "plugin 빌드 완료: plugin/builddir/gstmacttssink.dylib"
else
  fail "plugin 빌드 결과(gstmacttssink.dylib)를 찾을 수 없습니다."
  exit 1
fi

cd "$PROJECT_ROOT"

# ─────────────────────────────────────────────────────────────────
# 3단계: GUI venv + 의존성 설치
# ─────────────────────────────────────────────────────────────────

if (( DO_GUI )); then
  step "[3/${TOTAL_STEPS}] GUI 가상환경 + 의존성 설치"

  cd "$PROJECT_ROOT/gui"

  if [[ -d .venv ]]; then
    note "기존 .venv 발견 → 그대로 사용. 클린 재설치를 원하면 'rm -rf gui/.venv' 후 다시 실행."
  else
    "$PYTHON_BIN" -m venv .venv
    ok "venv 생성됨: gui/.venv"
  fi

  # subshell로 activate (이 스크립트의 셸을 오염시키지 않음)
  (
    # shellcheck disable=SC1091
    source .venv/bin/activate
    pip install --quiet --upgrade pip
    pip install --quiet -r requirements.txt
  )

  ok "의존성 설치 완료: $(grep -v '^\s*#' requirements.txt | tr '\n' ' ')"

  cd "$PROJECT_ROOT"
else
  step "[3/${TOTAL_STEPS}] GUI 단계 건너뜀 (--no-gui)"
fi

# ─────────────────────────────────────────────────────────────────
# 4단계: export 도구 빌드
# ─────────────────────────────────────────────────────────────────

if (( DO_EXPORT )); then
  step "[4/${TOTAL_STEPS}] export 도구 빌드 (kb-tts-export)"

  cd "$PROJECT_ROOT/tools/kb-tts-export"
  make

  if [[ -x ./kb-tts-export ]]; then
    ok "export 도구 빌드 완료: tools/kb-tts-export/kb-tts-export"
  else
    fail "export 도구 빌드 결과를 찾을 수 없습니다."
    exit 1
  fi

  cd "$PROJECT_ROOT"
else
  step "[4/${TOTAL_STEPS}] export 도구 단계 건너뜀 (--no-export)"
fi

# ─────────────────────────────────────────────────────────────────
# 5단계: PyInstaller로 .app 빌드 (--build-app 시에만)
# ─────────────────────────────────────────────────────────────────

if (( BUILD_APP )); then
  step "[5/${TOTAL_STEPS}] PyInstaller로 .app 빌드"

  cd "$PROJECT_ROOT/gui"

  # subshell로 venv activate (스크립트의 셸을 오염시키지 않음)
  (
    # shellcheck disable=SC1091
    source .venv/bin/activate
    if ! command -v pyinstaller >/dev/null 2>&1; then
      echo "pyinstaller가 venv에 없습니다." >&2
      echo "requirements.txt를 다시 설치하세요: pip install -r requirements.txt" >&2
      exit 1
    fi
    note "PyInstaller 실행 중 (.app에 plugin .dylib과 export 도구를 함께 묶습니다)..."
    pyinstaller --noconfirm --log-level=WARN AnnoySpeaker.spec
  )

  APP_PATH="$PROJECT_ROOT/gui/dist/AnnoySpeaker.app"
  if [[ -d "$APP_PATH" ]]; then
    APP_SIZE="$(du -sh "$APP_PATH" | awk '{print $1}')"
    ok ".app 빌드 완료: gui/dist/AnnoySpeaker.app (${APP_SIZE})"
  else
    fail ".app 빌드 결과를 찾을 수 없습니다 ($APP_PATH)."
    exit 1
  fi

  cd "$PROJECT_ROOT"

  # /Applications에 자동 설치 (--no-install 주면 건너뜀)
  if (( INSTALL_APP )); then
    INSTALLED_APP="/Applications/AnnoySpeaker.app"

    # 기존 설치가 있으면 wipe 후 새로 복사 (cp -R 단독은 디렉토리 merge로
    # 망가질 수 있어 안전하게 rm + cp).
    if [[ -e "$INSTALLED_APP" ]]; then
      note "기존 $INSTALLED_APP 발견 → 새 빌드로 덮어씁니다."
      if ! rm -rf "$INSTALLED_APP" 2>/dev/null; then
        fail "기존 $INSTALLED_APP 제거 실패 (권한 문제일 수 있음)."
        note "다음 명령으로 직접 처리해 주세요: sudo rm -rf $INSTALLED_APP"
        note "그 후 cp -R gui/dist/AnnoySpeaker.app /Applications/"
        exit 1
      fi
    fi

    if cp -R "$APP_PATH" /Applications/ 2>/dev/null; then
      ok "/Applications/AnnoySpeaker.app 설치 완료 — Launchpad / Spotlight에서 검색 가능."
    else
      fail "/Applications 복사 실패 (권한 문제일 수 있음)."
      note "다음 명령으로 직접 처리해 주세요:"
      note "  sudo cp -R gui/dist/AnnoySpeaker.app /Applications/"
      exit 1
    fi
  else
    note "--no-install 지정 → /Applications 자동 설치 건너뜀."
  fi
fi

# ─────────────────────────────────────────────────────────────────
# 마무리 안내
# ─────────────────────────────────────────────────────────────────

echo
echo "${C_BOLD}${C_GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${C_RESET}"
echo "${C_BOLD}${C_GREEN} AnnoySpeaker 개발 환경 준비 완료${C_RESET}"
echo "${C_BOLD}${C_GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${C_RESET}"
echo
echo "다음 명령으로 빠른 동작 확인:"
echo
echo "  ${C_BOLD}# plugin 인식 확인${C_RESET}"
echo "  GST_PLUGIN_PATH=\"\$(pwd)/plugin/builddir\" gst-inspect-1.0 macttssink"
echo
echo "  ${C_BOLD}# 실제 음성 출력 확인${C_RESET}"
echo "  echo \"안녕하세요, 케이 발라볼카 입니다\" | \\"
echo "    GST_PLUGIN_PATH=\"\$(pwd)/plugin/builddir\" \\"
echo "    gst-launch-1.0 --quiet fdsrc ! 'text/x-raw,format=utf8' ! macttssink"
echo
if (( DO_GUI )); then
  echo "  ${C_BOLD}# GUI 실행 (venv 활성화 + Python)${C_RESET}"
  echo "  cd gui && source .venv/bin/activate && \\"
  echo "    GST_PLUGIN_PATH=\"\$(pwd)/../plugin/builddir\" python main.py"
  echo
fi
if (( BUILD_APP )); then
  if (( INSTALL_APP )); then
    echo "  ${C_BOLD}# Launchpad에서 'AnnoySpeaker' 검색하거나, Applications 폴더에서 더블클릭${C_RESET}"
    echo "  open -a AnnoySpeaker"
    echo
  else
    echo "  ${C_BOLD}# .app을 Applications으로 복사 (Launchpad/Spotlight에서 검색·실행)${C_RESET}"
    echo "  cp -R gui/dist/AnnoySpeaker.app /Applications/"
    echo
    echo "  ${C_BOLD}# 또는 빌드 디렉터리에서 바로 실행${C_RESET}"
    echo "  open gui/dist/AnnoySpeaker.app"
    echo
  fi
  note "venv 활성화 없이 .app 더블클릭만으로 동작합니다 (PyInstaller가 Python·PySide6를 .app에 묶음)."
  note "현재 앱 아이콘은 macOS 기본(회색)입니다. 아이콘 디자인은 별도 후속 작업."
  echo
fi
echo "자세한 옵션·트러블슈팅은 ${C_BOLD}BUILD.md${C_RESET} 참고."
