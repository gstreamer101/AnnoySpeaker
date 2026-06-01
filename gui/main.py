# SPDX-License-Identifier: MIT
# Copyright (c) 2026 dlgus8648

"""AnnoySpeaker GUI — PySide6 frontend over pluggable TTS engines.

Layout follows the Windows Balabolka style at a high level: toolbar with
play/stop/export, an engine selector combobox, rate/pitch/volume sliders,
a large text edit, and a status bar.

The engine combobox is backed by the ENGINES registry — selecting an entry
swaps the GStreamer sink element used for playback and the export tool used
for m4a save. Currently AVSpeechSynthesizer (macttssink) is the only engine;
the registry is structured so additional macOS TTS APIs wrapped as GStreamer
sink plugins can be added with a single entry.

Voice selection (per-engine) is exposed on the plugin side but not yet in
the GUI (next iteration).
"""

from __future__ import annotations

import os
import re
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QProcess, QProcessEnvironment, Qt
from PySide6.QtGui import QAction, QKeySequence
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

# GStreamer Framework는 시스템 의존 (번들 안 함). 사용자의 맥북에
# 공식 .pkg가 깔려있어야 동작.
GST_LAUNCH = "/Library/Frameworks/GStreamer.framework/Versions/1.0/bin/gst-launch-1.0"

# 문장 종결로 인정하는 문자 (이미 끝나있으면 마침표 중복 안 붙임)
_TERMINATORS = ".!?…。！？"
_INLINE_WHITESPACE = re.compile(r"[ \t]+")


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

    id:           내부 식별자
    display_name: 콤보박스에 보일 이름
    sink_element: 재생 파이프라인에서 쓸 GStreamer sink 엘리먼트 이름
    export_tool:  m4a export 실행 파일 경로 (None = 이 엔진은 export 미지원)
    """

    id: str
    display_name: str
    sink_element: str
    export_tool: Path | None


ENGINES: list[Engine] = [
    Engine(
        id="avspeech",
        display_name="macOS AVSpeechSynthesizer",
        sink_element="macttssink",
        export_tool=EXPORT_TOOL,
    ),
    # 다음 엔진 예시 (구현되면 주석 해제):
    # Engine(
    #     id="nsspeech",
    #     display_name="macOS NSSpeechSynthesizer (클래식 보이스)",
    #     sink_element="macnsttssink",          # 별도 GStreamer 플러그인 필요
    #     export_tool=NS_EXPORT_TOOL,           # 별도 export 도구 필요
    # ),
]


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
        line = _INLINE_WHITESPACE.sub(" ", raw).strip()
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


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("AnnoySpeaker")
        self.resize(760, 560)

        self._process: QProcess | None = None
        self._export_process: QProcess | None = None
        self._tmp_text_path: str | None = None
        self._current_engine: Engine = ENGINES[0]

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
        self.play_action.setToolTip("선택된 텍스트를 음성으로 재생 (Cmd+Enter)")
        self.play_action.triggered.connect(self._on_play)
        toolbar.addAction(self.play_action)

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
        self.text_edit.textChanged.connect(self._update_char_count)
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
        if self._process is not None:
            return  # 이미 재생 중

        text = preprocess_for_speech(self.text_edit.toPlainText())
        if not text:
            self.status_label.setText("입력된 텍스트가 없습니다.")
            return

        # AVSpeechSynthesizer가 한국어 종결 음절(받침 있는 글자)을
        # trail off로 잘라먹는 문제 안전 패딩:
        # - trailing 공백만은 어딘가에서 trim되어 효과 없음
        # - 쉼표만 붙이면 받침이 쉼표에 묻혀버림
        # → 공백 1칸 + 쉼표 2개 조합: 공백이 음절 경계를 명확히 하고,
        #   쉼표가 짧은 휴식을 만들어 fade out이 일어나기 전에
        #   마지막 음절까지 다 발음됨.
        text = text + " ,,"

        if not PLUGIN_DIR.exists():
            self._fail(f"플러그인 빌드 폴더를 찾을 수 없음: {PLUGIN_DIR}")
            return
        if not Path(GST_LAUNCH).exists():
            self._fail(f"gst-launch-1.0이 없음: {GST_LAUNCH}")
            return

        # 긴 텍스트도 한 buffer로 처리되도록 stdin 파이프 대신 임시 파일 + filesrc 사용.
        # (stdin은 macOS pipe buffer(~16~64KB) + fdsrc 기본 청크(4KB)로 잘려 여러 utterance가
        # 되면서 청크 경계 처리에서 문제가 생김. filesrc + 큰 blocksize면 전체를 한 번에 읽음.)
        try:
            tmp_fd, self._tmp_text_path = tempfile.mkstemp(suffix=".txt", prefix="kb-tts-")
            with os.fdopen(tmp_fd, "wb") as f:
                f.write(text.encode("utf-8"))
        except OSError as e:
            self._fail(f"임시 파일 생성 실패: {e}")
            return

        env = QProcessEnvironment.systemEnvironment()
        env.insert("GST_PLUGIN_PATH", str(PLUGIN_DIR))

        proc = QProcess(self)
        proc.setProcessEnvironment(env)
        proc.setProcessChannelMode(QProcess.ProcessChannelMode.MergedChannels)
        proc.finished.connect(self._on_finished)
        proc.errorOccurred.connect(self._on_error)

        rate, pitch, volume = self._slider_values()
        args = [
            "--quiet",
            "filesrc",
            f"location={self._tmp_text_path}",
            "blocksize=104857600",  # 100MB - 어떤 길이든 한 buffer로
            "!",
            "text/x-raw,format=utf8",
            "!",
            self._current_engine.sink_element,
            f"rate={rate:.2f}",
            f"pitch={pitch:.2f}",
            f"volume={volume:.2f}",
        ]

        self._process = proc
        proc.start(GST_LAUNCH, args)
        if not proc.waitForStarted(3000):
            self._fail("gst-launch-1.0 시작 실패")
            self._process = None
            self._cleanup_tmp_text()
            return

        self.play_action.setEnabled(False)
        self.stop_action.setEnabled(True)
        self.engine_combo.setEnabled(False)
        ui_x = self.rate_slider.value() / 10.0
        self.status_label.setText(
            f"재생 중… (속도 {ui_x:.1f}x · rate {rate:.2f}, "
            f"음높이 {int(pitch * 100)}%, 볼륨 {int(volume * 100)}%)"
        )

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
        self.status_label.setText(f"내보내는 중… → {path}")

    def _on_export_finished(
        self, path: str, exit_code: int, exit_status: QProcess.ExitStatus
    ) -> None:
        self._export_process = None
        self.export_action.setEnabled(True)
        self.engine_combo.setEnabled(True)
        if exit_status == QProcess.ExitStatus.CrashExit:
            self.status_label.setText("내보내기 중단됨")
        elif exit_code != 0:
            self.status_label.setText(f"내보내기 실패 (exit {exit_code})")
        else:
            self.status_label.setText(f"저장됨: {path}")

    def _on_stop(self) -> None:
        if self._process is None:
            return
        self._process.terminate()
        if not self._process.waitForFinished(1500):
            self._process.kill()
        # finished 시그널에서 상태 정리됨

    def _cleanup_tmp_text(self) -> None:
        if self._tmp_text_path:
            try:
                os.unlink(self._tmp_text_path)
            except OSError:
                pass
            self._tmp_text_path = None

    def _on_finished(self, exit_code: int, exit_status: QProcess.ExitStatus) -> None:
        self._process = None
        self._cleanup_tmp_text()
        self.play_action.setEnabled(True)
        self.stop_action.setEnabled(False)
        self.engine_combo.setEnabled(True)
        if exit_status == QProcess.ExitStatus.CrashExit:
            self.status_label.setText("정지됨")
        elif exit_code != 0:
            self.status_label.setText(f"실패 (exit {exit_code})")
        else:
            self.status_label.setText("준비")

    def _on_error(self, err: QProcess.ProcessError) -> None:
        self._fail(f"프로세스 에러: {err}")

    def _fail(self, message: str) -> None:
        self.status_label.setText(message)
        self.play_action.setEnabled(True)
        self.stop_action.setEnabled(False)
        self.engine_combo.setEnabled(True)


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("AnnoySpeaker")
    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
