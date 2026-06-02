# SPDX-License-Identifier: MIT
# Copyright (c) 2026 dlgus8648

"""AnnoySpeaker GUI — PySide6 frontend over pluggable TTS engines.

Layout follows the Windows Balabolka style at a high level: toolbar with
play/stop/export, an engine selector combobox, a voice selector combobox,
rate/pitch/volume sliders, a large text edit, and a status bar.

The engine combobox is backed by the ENGINES registry — selecting an entry
swaps the GStreamer sink element used for playback and the export tool used
for m4a save. Currently AVSpeechSynthesizer (macttssink) is the only engine;
the registry is structured so additional macOS TTS APIs wrapped as GStreamer
sink plugins can be added with a single entry.

The voice combobox is filled per-engine from `voice_list_tool --list-voices`
(for AVSpeech, the kb-tts-export binary). On macOS each voice is bound to a
language, so the list is sorted by language; the selected voice identifier is
passed to both playback (the sink's `voice` property) and export (`--voice`).
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QObject, QProcess, Qt, QTimer, Signal
from PySide6.QtGui import QAction, QColor, QKeySequence, QTextCharFormat, QTextCursor
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPlainTextEdit,
    QSlider,
    QStatusBar,
    QStyle,
    QTextEdit,
    QToolBar,
    QVBoxLayout,
    QWidget,
)


def _is_frozen_bundle() -> bool:
    """PyInstaller .app 번들 환경인지 여부."""
    return getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS")


if _is_frozen_bundle():
    # .app 번들: PyInstaller가 추가 리소스/바이너리를 _MEIPASS 아래에 풀어둠
    # --add-binary "src:dest" 의 dest는 폴더라서 binary는 dest 안에 들어감
    _BUNDLE_ROOT = Path(sys._MEIPASS)  # type: ignore[attr-defined]
    PLUGIN_DIR = _BUNDLE_ROOT / "plugin"
    EXPORT_TOOL = _BUNDLE_ROOT / "tools" / "kb-tts-export" / "kb-tts-export"
else:
    # 개발 모드 (python main.py)
    PROJECT_ROOT = Path(__file__).resolve().parent.parent
    PLUGIN_DIR = PROJECT_ROOT / "plugin" / "builddir"
    EXPORT_TOOL = PROJECT_ROOT / "tools" / "kb-tts-export" / "kb-tts-export"

# GStreamer Framework는 시스템 의존 (번들 안 함). 공식 .pkg 필요.
GSTREAMER_FRAMEWORK = Path("/Library/Frameworks/GStreamer.framework/Versions/1.0")


def _setup_gstreamer_env() -> None:
    """gi/Gst import 전에 framework의 typelib·dylib·plugin 경로를 환경에 주입.

    공식 framework가 번들한 PyGObject는 python3.9용이라 우리 3.12 venv에선
    별도 설치한 pygobject(3.50.0 고정)를 쓰되, typelib/dylib은 framework
    것을 가리켜야 한다. 셸 환경변수나 re-exec 없이 os.environ 설정만으로
    macOS에서 로드됨(Phase 0/4에서 실측). 자세한 내막은 dev-log 14 참고.
    """
    fw = GSTREAMER_FRAMEWORK
    os.environ.setdefault("GI_TYPELIB_PATH", str(fw / "lib" / "girepository-1.0"))
    dyld = str(fw / "lib")
    existing = os.environ.get("DYLD_FALLBACK_LIBRARY_PATH", "")
    if dyld not in existing.split(":"):
        os.environ["DYLD_FALLBACK_LIBRARY_PATH"] = dyld + (f":{existing}" if existing else "")
    os.environ["GST_PLUGIN_PATH"] = str(PLUGIN_DIR)


try:
    _setup_gstreamer_env()
    # 동적 import: PyInstaller의 gi 자동 훅이 우리 pygobject(3.50)+공식
    # framework 조합과 비호환이라 .app 빌드 시 크래시(Gst.init(None) 등)한다.
    # 모듈명을 변수로 줘서 정적 분석에 안 걸리게 우회하고, gi는 spec에서 수동
    # 수집한다. 런타임 typelib/dylib은 _setup_gstreamer_env()가 가리키는 시스템
    # framework에서 로드된다.
    import importlib

    _gi_mod = "gi"
    gi = importlib.import_module(_gi_mod)
    gi.require_version("Gst", "1.0")
    Gst = importlib.import_module(_gi_mod + ".repository.Gst")

    Gst.init([])
    GST_AVAILABLE = True
    GST_IMPORT_ERROR = ""
except Exception as gst_err:  # framework 미설치/연결 실패 등 — 재생 시 안내
    Gst = None
    GST_AVAILABLE = False
    GST_IMPORT_ERROR = str(gst_err)

# 문장 종결로 인정하는 문자 (이미 끝나있으면 마침표 중복 안 붙임)
_TERMINATORS = ".!?…。！？"
_INLINE_WHITESPACE = re.compile(r"[ \t]+")
# AVSpeech는 "<...>"를 마크업 태그로 해석해 그 지점에서 발화를 끊는다(실측).
# 예: "<기자>"가 중간에 있으면 거기서 재생이 잘림. 꺾쇠를 공백으로 중화하면
# 안쪽 글자("기자")는 정상 발음되고 잘림도 사라진다. 공백·탭과 함께 취급.
_DROP_FOR_SPEECH = " \t<>"


# ---- TTS 엔진 레지스트리 ---------------------------------------------------
#
# Balabolka가 SAPI4 / SAPI5 / MS Speech Platform을 갈아끼우듯, AnnoySpeaker도
# "엔진"을 콤보박스로 고를 수 있게 한다. 한 엔진 = (재생용 GStreamer sink
# 엘리먼트) + (m4a export 도구) 한 쌍. 콤보박스에서 엔진을 바꾸면 재생
# 파이프라인의 sink 엘리먼트와 export 도구가 통째로 교체된다.
#
# 지금은 macOS AVSpeechSynthesizer(macttssink) 하나뿐이지만, 다른 macOS TTS
# API(예: NSSpeechSynthesizer)를 GStreamer sink 플러그인 + export 경로로
# 감싸 이 리스트에 dict 하나 추가하면 콤보박스에 자동으로 나타난다.
#
# 확장 포인트: 엔진마다 지원하는 속성(rate/pitch/volume)이나 그 단위가
# 다를 수 있다. 현재는 모든 엔진이 macttssink와 동일한 rate/pitch/volume
# float 속성을 받는다고 가정한다. 엔진별 속성 매핑이 필요해지면 Engine에
# 필드를 추가한다.


@dataclass(frozen=True)
class Engine:
    """선택 가능한 TTS 엔진 하나.

    id:              내부 식별자
    display_name:    콤보박스에 보일 이름
    sink_element:    재생 파이프라인에서 쓸 GStreamer sink 엘리먼트 이름
    export_tool:     m4a export 실행 파일 경로 (None = export 미지원)
    voice_list_tool: 설치된 음성 목록을 출력하는 도구 경로
                     (`<tool> --list-voices` → "id\\tname\\tlang\\tquality" 줄들).
                     None = 보이스 열거 미지원 (드롭다운에 "시스템 기본"만).
    """

    id: str
    display_name: str
    sink_element: str
    export_tool: Path | None
    voice_list_tool: Path | None


ENGINES: list[Engine] = [
    Engine(
        id="avspeech",
        display_name="macOS AVSpeechSynthesizer",
        sink_element="macttssink",
        export_tool=EXPORT_TOOL,
        # AVSpeech 음성 열거는 export 도구의 --list-voices를 재사용
        # (같은 AVFoundation 바이너리라 .app에 이미 번들됨).
        voice_list_tool=EXPORT_TOOL,
    ),
    # 다음 엔진 예시 (구현되면 주석 해제):
    # Engine(
    #     id="nsspeech",
    #     display_name="macOS NSSpeechSynthesizer (클래식 보이스)",
    #     sink_element="macnsttssink",          # 별도 GStreamer 플러그인 필요
    #     export_tool=NS_EXPORT_TOOL,           # 별도 export 도구 필요
    #     voice_list_tool=NS_EXPORT_TOOL,
    # ),
]


# 음성 드롭다운에 노출할 음성을 고르는 두 가지 기준 (둘 중 하나면 노출).
#
# 1) DOWNLOADED_VOICE_QUALITIES — 사용자가 직접 받은 고품질 음성.
#    macOS는 모든 언어의 compact 음성(품질 "default")과 옛 노벨티 음성을
#    기본 탑재하는데(수십 개의 잡음), enhanced(고음질)/premium(프리미엄)은
#    시스템 설정에서 받아야만 생긴다. 이 등급은 "사용자가 받은 것"이라
#    이름을 몰라도 자동 노출된다 → 각자 받은 음성만 깔끔하게 보인다.
#
# 2) BASELINE_VOICE_NAMES — 항상 보여줄 기본 음성. 프리미엄을 하나도 안
#    받은 사용자도 바로 쓸 수 있도록, macOS에 항상 기본 탑재되는 한국어
#    Yuna / 영어 Samantha만 남긴다 (나머지 언어 compact·노벨티는 숨김).
#    이 둘은 모든 맥에 존재하므로 이름 하드코딩이 안전하다.
#
# 결과: "기본 Yuna·Samantha + 내가 받은 고품질 음성"만 보이고 나머진 숨김.
DOWNLOADED_VOICE_QUALITIES = {"enhanced", "premium"}
BASELINE_VOICE_NAMES = {"Samantha", "Yuna"}

# 처음에 선택해 둘 음성 이름(접두 일치). 한국어 사용자가 주 대상이라 Yuna를
# 기본으로 — 설치돼 있으면 최고 품질 Yuna(프리미엄)를 고르고, 없으면 첫 항목.
DEFAULT_VOICE_NAME = "Yuna"


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


# 한국어 끝음절 잘림 방지 패딩 (재생/내보내기 공통). 자세한 이유는 _on_play 참고.
TAIL_PADDING = " ,,"


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


class LabeledSlider(QWidget):
    """라벨 + 가로 슬라이더. 값이 바뀌면 라벨에 현재 값 표시.

    내부 값은 정수(min..max). 표시 포맷은 formatter로 커스터마이즈
    (기본은 "v%"). plugin에 넘길 float 매핑은 호출자가 따로 계산.
    """

    def __init__(
        self,
        title: str,
        lo: int,
        hi: int,
        default: int,
        formatter=None,
    ) -> None:
        super().__init__()
        self._title = title
        self._formatter = formatter or (lambda v: f"{v}%")

        self.label = QLabel()
        self.label.setStyleSheet("color: #444;")

        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.slider.setMinimum(lo)
        self.slider.setMaximum(hi)
        self.slider.setValue(default)
        self.slider.valueChanged.connect(self._on_value_changed)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)
        layout.addWidget(self.label)
        layout.addWidget(self.slider)

        self._on_value_changed(default)

    def _on_value_changed(self, v: int) -> None:
        self.label.setText(f"{self._title}: {self._formatter(v)}")

    def value(self) -> int:
        return self.slider.value()


class GstPlayer(QObject):
    """인프로세스 GStreamer 재생 컨트롤러 (PyGObject).

    파이프라인(filesrc ! capsfilter ! macttssink)을 GUI 프로세스 안에서 직접
    구동한다. 그래야 (a) macttssink가 버스에 올리는 단어 범위 메시지를
    QTimer 폴링으로 받아 실시간 하이라이트에 쓰고, (b) 일시정지/재개/정지를
    엘리먼트에 직접 보낼 수 있다 — gst-launch 서브프로세스로는 불가능. 자세한
    설계 배경은 dev-log 14 참고.

    버스는 GLib 메인루프 대신 QTimer로 폴링한다(Qt 이벤트 루프와 자연스럽게
    통합). 메시지는 스트리밍/메인 스레드에서 post되지만 폴링·시그널 방출은
    모두 GUI 스레드라 UI 접근이 안전하다.
    """

    wordSpoken = Signal(int, int)  # 읽기 문자열의 단어 범위 (start, end)
    finished = Signal()
    failed = Signal(str)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._pipeline = None
        self._sink = None
        self._timer = QTimer(self)
        self._timer.setInterval(20)
        self._timer.timeout.connect(self._poll_bus)

    def is_active(self) -> bool:
        return self._pipeline is not None

    def play(
        self,
        text_path: str,
        sink_element: str,
        rate: float,
        pitch: float,
        volume: float,
        voice: str | None,
    ) -> None:
        self.stop()
        pipeline = Gst.Pipeline.new("annoyspeaker")
        src = Gst.ElementFactory.make("filesrc", "src")
        capsf = Gst.ElementFactory.make("capsfilter", "caps")
        sink = Gst.ElementFactory.make(sink_element, "tts")
        if not (pipeline and src and capsf and sink):
            self.failed.emit(f"GStreamer 요소 생성 실패 ('{sink_element}' 플러그인 확인)")
            return

        src.set_property("location", text_path)
        src.set_property("blocksize", 104857600)  # 100MB - 어떤 길이든 한 buffer로
        capsf.set_property("caps", Gst.Caps.from_string("text/x-raw,format=utf8"))
        sink.set_property("rate", rate)
        sink.set_property("pitch", pitch)
        sink.set_property("volume", volume)
        if voice:
            sink.set_property("voice", voice)

        for el in (src, capsf, sink):
            pipeline.add(el)
        src.link(capsf)
        capsf.link(sink)

        self._pipeline = pipeline
        self._sink = sink
        pipeline.set_state(Gst.State.PLAYING)
        self._timer.start()

    def pause(self) -> None:
        if self._sink is not None:
            self._sink.emit("pause")

    def resume(self) -> None:
        if self._sink is not None:
            self._sink.emit("resume")

    def stop(self) -> None:
        self._teardown()

    def _teardown(self) -> None:
        self._timer.stop()
        if self._pipeline is not None:
            # unlock()이 블록된 render()를 깨워 즉시 NULL로 내려간다 (데드락 없음).
            self._pipeline.set_state(Gst.State.NULL)
            self._pipeline = None
            self._sink = None

    def _poll_bus(self) -> None:
        if self._pipeline is None:
            return
        bus = self._pipeline.get_bus()
        types = Gst.MessageType.ELEMENT | Gst.MessageType.ERROR | Gst.MessageType.EOS
        while True:
            msg = bus.timed_pop_filtered(0, types)
            if msg is None:
                break
            if msg.type == Gst.MessageType.ELEMENT:
                s = msg.get_structure()
                if s is None:
                    continue
                name = s.get_name()
                if name == "annoyspeaker-word":
                    self.wordSpoken.emit(s.get_value("start"), s.get_value("end"))
                elif name == "annoyspeaker-done":
                    self._teardown()
                    self.finished.emit()
                    return
            elif msg.type == Gst.MessageType.EOS:
                self._teardown()
                self.finished.emit()
                return
            elif msg.type == Gst.MessageType.ERROR:
                err, _dbg = msg.parse_error()
                self._teardown()
                self.failed.emit(str(err))
                return


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("AnnoySpeaker")
        self.resize(760, 560)

        self._export_process: QProcess | None = None
        self._tmp_text_path: str | None = None
        self._current_engine: Engine = ENGINES[0]
        self._has_voices: bool = False
        self._omap: list[int] = []  # 읽기 문자열 → 원본 위치 매핑 (현재 재생)
        self._hl_start: int | None = None  # 누적 하이라이트 시작 위치
        self._playback_state = "idle"  # idle / playing / paused

        # 인프로세스 재생 컨트롤러 (PyGObject). framework 미연결이면 None.
        self._player = GstPlayer(self) if GST_AVAILABLE else None
        if self._player is not None:
            self._player.wordSpoken.connect(self._on_word)
            self._player.finished.connect(self._on_play_finished)
            self._player.failed.connect(self._on_play_failed)

        self._build_toolbar()
        self._build_central()
        self._build_statusbar()

        self._update_char_count()
        self._on_engine_changed(0)

    # ---- UI construction ---------------------------------------------------

    def _build_toolbar(self) -> None:
        toolbar = QToolBar("Main")
        toolbar.setMovable(False)
        toolbar.setIconSize(toolbar.iconSize() * 1.1)
        self.addToolBar(toolbar)

        style = self.style()

        self.play_action = QAction(
            style.standardIcon(QStyle.StandardPixmap.SP_MediaPlay),
            "재생",
            self,
        )
        self.play_action.setShortcut(QKeySequence("Ctrl+Return"))
        self.play_action.setToolTip("재생: 처음부터 / 일시정지 중이면 이어재생 (Cmd+Enter)")
        self.play_action.triggered.connect(self._on_play)
        toolbar.addAction(self.play_action)

        # 일시정지 (재생 ▶ 와 정지 ■ 사이). 일시정지 전용 — 아이콘 안 바뀌고,
        # 일시정지하면 비활성화된다(재개는 ▶ 재생 버튼이 담당).
        self.pause_action = QAction(
            style.standardIcon(QStyle.StandardPixmap.SP_MediaPause), "일시정지", self
        )
        self.pause_action.setShortcut(QKeySequence("Ctrl+P"))
        self.pause_action.setToolTip("일시정지 (Cmd+P)")
        self.pause_action.triggered.connect(self._do_pause)
        self.pause_action.setEnabled(False)
        toolbar.addAction(self.pause_action)

        self.stop_action = QAction(
            style.standardIcon(QStyle.StandardPixmap.SP_MediaStop),
            "정지",
            self,
        )
        self.stop_action.setShortcut(QKeySequence("Ctrl+."))
        self.stop_action.setToolTip("재생 중지 (Cmd+.)")
        self.stop_action.triggered.connect(self._on_stop)
        self.stop_action.setEnabled(False)
        toolbar.addAction(self.stop_action)

        toolbar.addSeparator()

        self.export_action = QAction(
            style.standardIcon(QStyle.StandardPixmap.SP_DialogSaveButton),
            "내보내기",
            self,
        )
        self.export_action.setShortcut(QKeySequence("Ctrl+S"))
        self.export_action.setToolTip(
            "현재 텍스트와 슬라이더 설정대로 .m4a 음성 파일로 저장 (Cmd+S)"
        )
        self.export_action.triggered.connect(self._on_export)
        toolbar.addAction(self.export_action)

    def _build_central(self) -> None:
        central = QWidget()
        layout = QVBoxLayout(central)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)

        # 엔진 선택 row: "엔진:" 라벨 + 콤보박스 (Balabolka의 엔진 탭에 해당)
        engine_row = QWidget()
        engine_row_layout = QHBoxLayout(engine_row)
        engine_row_layout.setContentsMargins(4, 2, 4, 2)
        engine_row_layout.setSpacing(8)

        engine_caption = QLabel("엔진:")
        engine_caption.setStyleSheet("color: #555;")

        self.engine_combo = QComboBox()
        for engine in ENGINES:
            self.engine_combo.addItem(engine.display_name, engine.id)
        self.engine_combo.setToolTip("음성 합성에 사용할 TTS 엔진 선택")
        self.engine_combo.currentIndexChanged.connect(self._on_engine_changed)

        engine_row_layout.addWidget(engine_caption)
        engine_row_layout.addWidget(self.engine_combo, stretch=1)
        layout.addWidget(engine_row)

        # 음성 선택 row: "음성:" 라벨 + 콤보박스 (Balabolka의 voice 드롭다운에 해당)
        # 음성은 언어에 묶여 있다 — 한국어 텍스트엔 한국어 음성(Yuna), 영어엔
        # 영어 음성(Samantha 등). 선택 엔진이 바뀌면 목록을 다시 채운다.
        voice_row = QWidget()
        voice_row_layout = QHBoxLayout(voice_row)
        voice_row_layout.setContentsMargins(4, 2, 4, 2)
        voice_row_layout.setSpacing(8)

        voice_caption = QLabel("음성:")
        voice_caption.setStyleSheet("color: #555;")

        self.voice_combo = QComboBox()
        self.voice_combo.setToolTip(
            "읽을 음성 선택. 텍스트 언어에 맞는 음성을 고르세요 (예: 한국어 → Yuna)."
        )

        voice_row_layout.addWidget(voice_caption)
        voice_row_layout.addWidget(self.voice_combo, stretch=1)
        layout.addWidget(voice_row)

        # 슬라이더 row: 속도 / 음높이 / 볼륨
        # 내부 값(정수) → 표시 → plugin float 매핑:
        #   속도   0..20  → "0.0x"..."2.0x"  → rate   v/20   (0.00..1.00)
        #   음높이 50..200 → "50%"..."200%"   → pitch  v/100  (0.50..2.00)
        #   볼륨   0..100 → "0%"..."100%"    → volume v/100  (0.00..1.00)
        sliders_row = QWidget()
        sliders_layout = QHBoxLayout(sliders_row)
        sliders_layout.setContentsMargins(4, 4, 4, 4)
        sliders_layout.setSpacing(16)

        self.rate_slider = LabeledSlider("속도", 0, 20, 10, formatter=lambda v: f"{v / 10:.1f}x")
        self.pitch_slider = LabeledSlider("음높이", 50, 200, 100)
        self.volume_slider = LabeledSlider("볼륨", 0, 100, 100)

        sliders_layout.addWidget(self.rate_slider)
        sliders_layout.addWidget(self.pitch_slider)
        sliders_layout.addWidget(self.volume_slider)
        layout.addWidget(sliders_row)

        self.text_edit = QPlainTextEdit()
        self.text_edit.setPlaceholderText("여기에 읽을 텍스트를 붙여넣으세요…")
        self.text_edit.textChanged.connect(self._on_text_changed)
        layout.addWidget(self.text_edit, stretch=1)

        self.setCentralWidget(central)

    def _build_statusbar(self) -> None:
        bar = QStatusBar()
        self.setStatusBar(bar)

        self.status_label = QLabel("준비")
        self.engine_status = QLabel("macttssink")
        self.engine_status.setStyleSheet("color: #777;")
        self.char_label = QLabel("글자: 0")

        bar.addWidget(self.status_label, stretch=1)
        bar.addPermanentWidget(self.engine_status)
        bar.addPermanentWidget(QLabel("│"))
        bar.addPermanentWidget(self.char_label)

    # ---- Actions -----------------------------------------------------------

    def _update_char_count(self) -> None:
        n = len(self.text_edit.toPlainText())
        self.char_label.setText(f"글자: {n}")

    def _on_text_changed(self) -> None:
        self._update_char_count()
        # 재생/일시정지 중 사용자가 텍스트를 편집하면 문서 위치가 밀려 현재 재생의
        # 위치 매핑(omap)이 어긋나 하이라이트 싱크가 깨지고, 편집한 글자는 지금
        # 재생엔 포함도 안 된다. 그래서 편집은 "정지"와 동일하게 처리한다 —
        # 멈추고 하이라이트를 지운 뒤, 새 내용은 ▶로 처음부터 듣게 한다.
        if self._playback_state in ("playing", "paused"):
            self._on_stop()

    def _on_engine_changed(self, index: int) -> None:
        """콤보박스에서 엔진을 바꾸면 현재 엔진을 교체하고 UI를 갱신.

        재생 파이프라인의 sink 엘리먼트와 export 도구가 이 엔진을 따라간다.
        """
        if not (0 <= index < len(ENGINES)):
            return
        self._current_engine = ENGINES[index]

        # 상태바에 현재 엔진의 sink 엘리먼트 이름 표시
        self.engine_status.setText(self._current_engine.sink_element)

        # export 도구가 없는(또는 빌드 안 된) 엔진이면 내보내기 비활성화
        tool = self._current_engine.export_tool
        export_ok = tool is not None and tool.exists()
        self.export_action.setEnabled(export_ok)
        self.export_action.setToolTip(
            "현재 텍스트와 슬라이더 설정대로 .m4a 음성 파일로 저장 (Cmd+S)"
            if export_ok
            else "이 엔진은 m4a 내보내기를 지원하지 않습니다."
        )

        # 엔진별 음성 목록 갱신
        self._populate_voices()

    def _populate_voices(self) -> None:
        """선택 엔진의 설치 음성으로 음성 콤보박스를 채운다.

        `voice_list_tool --list-voices` 출력(id\\tname\\tlang\\tquality)을
        파싱하고, PREFERRED_VOICE_NAMES(자연 음성 화이트리스트)로 걸러
        언어→이름 순으로 넣는다. 화이트리스트 음성이 하나도 없으면(도구
        실패 또는 미설치) "시스템 기본"으로 폴백한다.
        """
        self.voice_combo.clear()

        tool = self._current_engine.voice_list_tool
        voices: list[tuple[str, str, str, str]] = []  # (lang, name, identifier, quality)
        if tool is not None and tool.exists():
            try:
                result = subprocess.run(
                    [str(tool), "--list-voices"],
                    capture_output=True,
                    text=True,
                    timeout=5,
                )
                for line in result.stdout.splitlines():
                    parts = line.split("\t")
                    if len(parts) >= 4:
                        ident, name, lang, quality = parts[0], parts[1], parts[2], parts[3]
                        # 받은 고품질 음성(enhanced/premium) + 기본 baseline
                        # (Yuna/Samantha)만 노출. 나머지 언어 compact·노벨티 숨김.
                        if quality in DOWNLOADED_VOICE_QUALITIES or name in BASELINE_VOICE_NAMES:
                            voices.append((lang, name, ident, quality))
            except (OSError, subprocess.SubprocessError):
                pass  # 실패해도 아래 폴백으로 계속 동작

        # 언어별로 묶여 보이도록 (lang, name) 정렬
        voices.sort(key=lambda v: (v[0], v[1].lower()))
        for lang, name, ident, _quality in voices:
            # name이 이미 "(Premium)"/"(Enhanced)"를 포함하므로 그대로 표시
            self.voice_combo.addItem(f"{name} · {lang}", ident)

        # 기본 선택: 이름이 DEFAULT_VOICE_NAME으로 시작하는 음성 중 최고 품질
        # (프리미엄 Yuna가 깔려 있으면 그것, 아니면 compact Yuna)
        quality_rank = {"premium": 3, "enhanced": 2, "default": 1}
        best_ident, best_rank = None, -1
        for _lang, name, ident, quality in voices:
            if name.startswith(DEFAULT_VOICE_NAME):
                rank = quality_rank.get(quality, 0)
                if rank > best_rank:
                    best_rank, best_ident = rank, ident

        # 음성이 하나도 없으면 시스템 기본으로 폴백
        self._has_voices = self.voice_combo.count() > 0
        if not self._has_voices:
            self.voice_combo.addItem("시스템 기본", None)
        self.voice_combo.setEnabled(self._has_voices)
        if best_ident is not None:
            idx = self.voice_combo.findData(best_ident)
            if idx >= 0:
                self.voice_combo.setCurrentIndex(idx)

    def _selected_voice(self) -> str | None:
        """현재 선택된 음성 identifier. "시스템 기본"이면 None."""
        return self.voice_combo.currentData()

    def _slider_values(self) -> tuple[float, float, float]:
        """슬라이더 정수값을 plugin이 받는 float로 매핑.

        속도는 AVSpeech의 비선형성 때문에 ui_speed_to_rate()로 압축.
        """
        ui_x = self.rate_slider.value() / 10.0  # 0.0..2.0 (사용자 표시)
        rate = ui_speed_to_rate(ui_x)  # 0.00..0.70 (압축됨)
        pitch = self.pitch_slider.value() / 100.0  # 0.50..2.00
        volume = self.volume_slider.value() / 100.0  # 0.00..1.00
        return rate, pitch, volume

    def _on_play(self) -> None:
        """재생 버튼: 일시정지 중이면 이어재생, 아니면 처음부터 재생."""
        if self._playback_state == "paused":
            self._do_resume()
        else:
            self._start_playback()

    def _start_playback(self) -> None:
        if self._player is None:
            self._fail(f"GStreamer를 불러올 수 없습니다 (framework 확인). {GST_IMPORT_ERROR}")
            return
        if self._player.is_active():
            self._player.stop()  # 만약을 위한 정리

        # 읽기 문자열 + 원본 위치 매핑. spoken은 preprocess+패딩과 바이트 동일이라
        # 오디오는 그대로고, omap으로 단어 범위를 원본에 되돌려 하이라이트한다.
        spoken, omap = build_spoken_text(self.text_edit.toPlainText())
        if not spoken:
            self.status_label.setText("입력된 텍스트가 없습니다.")
            return
        if not PLUGIN_DIR.exists():
            self._fail(f"플러그인 빌드 폴더를 찾을 수 없음: {PLUGIN_DIR}")
            return

        # 긴 텍스트도 한 buffer로 처리되도록 임시 파일 + filesrc 사용.
        try:
            tmp_fd, self._tmp_text_path = tempfile.mkstemp(suffix=".txt", prefix="kb-tts-")
            with os.fdopen(tmp_fd, "wb") as f:
                f.write(spoken.encode("utf-8"))
        except OSError as e:
            self._fail(f"임시 파일 생성 실패: {e}")
            return

        self._omap = omap
        self._clear_highlight()
        rate, pitch, volume = self._slider_values()
        self._player.play(
            self._tmp_text_path,
            self._current_engine.sink_element,
            rate,
            pitch,
            volume,
            self._selected_voice(),
        )

        self._apply_state("playing")
        ui_x = self.rate_slider.value() / 10.0
        self.status_label.setText(
            f"재생 중… (속도 {ui_x:.1f}x · rate {rate:.2f}, "
            f"음높이 {int(pitch * 100)}%, 볼륨 {int(volume * 100)}%)"
        )

    # ---- 하이라이트 ---------------------------------------------------------

    def _on_word(self, start: int, end: int) -> None:
        """macttssink가 보낸 단어 범위(읽기 문자열 기준)를 원본 위치로 되돌려
        누적 하이라이트. (범위는 UTF-16 코드유닛; BMP=한/영은 코드포인트와 1:1.)"""
        mapped = map_spoken_range(self._omap, start, end)
        if mapped is None:
            return
        lo, hi = mapped
        if self._hl_start is None:
            self._hl_start = lo
        self._apply_highlight(self._hl_start, hi)

    def _apply_highlight(self, lo: int, hi: int) -> None:
        sel = QTextEdit.ExtraSelection()
        fmt = QTextCharFormat()
        fmt.setBackground(QColor("#2d6cdf"))
        fmt.setForeground(QColor("white"))
        cursor = QTextCursor(self.text_edit.document())
        cursor.setPosition(lo)
        cursor.setPosition(hi, QTextCursor.MoveMode.KeepAnchor)
        sel.cursor = cursor
        sel.format = fmt
        self.text_edit.setExtraSelections([sel])

    def _clear_highlight(self) -> None:
        self._hl_start = None
        self.text_edit.setExtraSelections([])

    def _on_export(self) -> None:
        if self._export_process is not None:
            return  # 이미 내보내는 중

        export_tool = self._current_engine.export_tool
        if export_tool is None:
            self._fail(
                f"'{self._current_engine.display_name}' 엔진은 m4a 내보내기를 지원하지 않습니다."
            )
            return
        if not export_tool.exists():
            self._fail("export 도구가 없습니다. tools/kb-tts-export/ 에서 'make' 실행 필요.")
            return

        text = preprocess_for_speech(self.text_edit.toPlainText())
        if not text:
            self.status_label.setText("입력된 텍스트가 없습니다.")
            return
        # 라이브 재생과 동일한 한국어 안전 패딩 적용
        text = text + " ,,"

        # 파일 경로 받기
        path, _ = QFileDialog.getSaveFileName(
            self,
            "음성 파일로 저장",
            "untitled.m4a",
            "Audio (*.m4a)",
        )
        if not path:
            return  # 사용자 취소
        if not path.lower().endswith(".m4a"):
            path += ".m4a"

        rate, pitch, volume = self._slider_values()
        args = [
            "--out",
            path,
            "--rate",
            f"{rate:.2f}",
            "--pitch",
            f"{pitch:.2f}",
            "--volume",
            f"{volume:.2f}",
        ]
        voice = self._selected_voice()
        if voice:
            args += ["--voice", voice]

        proc = QProcess(self)
        proc.setProcessChannelMode(QProcess.ProcessChannelMode.MergedChannels)
        proc.finished.connect(
            lambda code, status, p=path: self._on_export_finished(p, code, status)
        )
        proc.errorOccurred.connect(self._on_error)

        self._export_process = proc
        proc.start(str(export_tool), args)
        if not proc.waitForStarted(3000):
            self._fail("kb-tts-export 시작 실패")
            self._export_process = None
            return

        proc.write(text.encode("utf-8"))
        proc.closeWriteChannel()

        self.export_action.setEnabled(False)
        self.engine_combo.setEnabled(False)
        self.voice_combo.setEnabled(False)
        self.status_label.setText(f"내보내는 중… → {path}")

    def _on_export_finished(
        self, path: str, exit_code: int, exit_status: QProcess.ExitStatus
    ) -> None:
        self._export_process = None
        self.export_action.setEnabled(True)
        self.engine_combo.setEnabled(True)
        self.voice_combo.setEnabled(self._has_voices)
        if exit_status == QProcess.ExitStatus.CrashExit:
            self.status_label.setText("내보내기 중단됨")
        elif exit_code != 0:
            self.status_label.setText(f"내보내기 실패 (exit {exit_code})")
        else:
            self.status_label.setText(f"저장됨: {path}")

    def _on_stop(self) -> None:
        if self._player is not None:
            self._player.stop()  # unlock()이 즉시 NULL로 내려 매달림 없음
        self._cleanup_tmp_text()
        self._clear_highlight()
        self._apply_state("idle")
        self.status_label.setText("정지됨")

    def _on_play_finished(self) -> None:
        # 자연 완료: 하이라이트는 남겨둠(완독 표시), 다음 재생 시 초기화.
        self._cleanup_tmp_text()
        self._apply_state("idle")
        self.status_label.setText("준비")

    def _on_play_failed(self, message: str) -> None:
        self._cleanup_tmp_text()
        self._clear_highlight()
        self._fail(message)

    # ---- 일시정지 / 재개 ----------------------------------------------------

    def _do_pause(self) -> None:
        """일시정지 버튼. 일시정지하면 이 버튼은 비활성화되고, 재개는 ▶가 맡는다."""
        if self._player is not None:
            self._player.pause()
        self._apply_state("paused")
        self.status_label.setText("일시정지됨")

    def _do_resume(self) -> None:
        """▶가 paused 상태에서 호출 → 멈춘 위치부터 이어재생."""
        if self._player is not None:
            self._player.resume()
        self._apply_state("playing")
        self.status_label.setText("재생 중…")

    def _cleanup_tmp_text(self) -> None:
        if self._tmp_text_path:
            try:
                os.unlink(self._tmp_text_path)
            except OSError:
                pass
            self._tmp_text_path = None

    def _apply_state(self, state: str) -> None:
        """재생 상태(idle/playing/paused)에 맞춰 버튼·콤보박스 활성화를 설정.

        - idle:    ▶ on,  ‖ off, ■ off  (처음부터 재생 가능)
        - playing: ▶ off, ‖ on,  ■ on
        - paused:  ▶ on,  ‖ off, ■ on   (▶는 이어재생, ‖는 비활성화)
        """
        self._playback_state = state
        playing = state == "playing"
        active = state in ("playing", "paused")
        self.play_action.setEnabled(not playing)
        self.pause_action.setEnabled(playing)
        self.stop_action.setEnabled(active)
        self.engine_combo.setEnabled(not active)
        self.voice_combo.setEnabled(self._has_voices and not active)

    def _on_error(self, err: QProcess.ProcessError) -> None:
        # 내보내기(QProcess) 에러 경로
        self._fail(f"프로세스 에러: {err}")

    def _fail(self, message: str) -> None:
        self._apply_state("idle")
        self.status_label.setText(message)


def _selftest() -> int:
    """GStreamer 연결 자가진단. `AnnoySpeaker --selftest`로 호출.

    번들(.app)에서도 gi가 로드되고 macttssink 요소가 만들어지는지 확인 —
    "두 개의 glib" 같은 패키징 문제를 조기에 잡는다. 정상 0, 실패 1.
    """
    if not GST_AVAILABLE:
        print(f"SELFTEST FAIL: GStreamer 사용 불가 — {GST_IMPORT_ERROR}")
        return 1
    print(f"SELFTEST: GStreamer {Gst.version_string()}")
    el = Gst.ElementFactory.make(ENGINES[0].sink_element, "t")
    if el is None:
        print(f"SELFTEST FAIL: '{ENGINES[0].sink_element}' 요소 생성 실패 (플러그인 경로 확인)")
        return 1
    rate = el.get_property("rate")
    print(f"SELFTEST OK: {ENGINES[0].sink_element} 인스턴스화 (rate={rate})")
    return 0


def main() -> int:
    if "--selftest" in sys.argv:
        return _selftest()
    app = QApplication(sys.argv)
    app.setApplicationName("AnnoySpeaker")
    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
