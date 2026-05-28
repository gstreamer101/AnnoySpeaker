"""K-Balabolka GUI — PySide6 frontend over macttssink.

Layout follows the Windows Balabolka style at a high level: toolbar with
play/stop, an engine info label, rate/pitch/volume sliders, a large text
edit, and a status bar.

Stage 3 added the rate/pitch/volume sliders; voice selection is exposed
on the plugin side but not yet in the GUI (next iteration).
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

from PySide6.QtCore import QProcess, QProcessEnvironment, Qt
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import (
    QApplication,
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


PROJECT_ROOT = Path(__file__).resolve().parent.parent
PLUGIN_DIR = PROJECT_ROOT / "plugin" / "builddir"
GST_LAUNCH = "/Library/Frameworks/GStreamer.framework/Versions/1.0/bin/gst-launch-1.0"
EXPORT_TOOL = PROJECT_ROOT / "tools" / "kb-tts-export" / "kb-tts-export"

# 문장 종결로 인정하는 문자 (이미 끝나있으면 마침표 중복 안 붙임)
_TERMINATORS = ".!?…。！？"
_INLINE_WHITESPACE = re.compile(r"[ \t]+")


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
        self.setWindowTitle("K-Balabolka")
        self.resize(760, 560)

        self._process: QProcess | None = None
        self._export_process: QProcess | None = None

        self._build_toolbar()
        self._build_central()
        self._build_statusbar()

        self._update_char_count()

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

        engine_label = QLabel("엔진: macOS AVSpeechSynthesizer (macttssink)")
        engine_label.setStyleSheet("color: #555; padding: 2px 4px;")
        layout.addWidget(engine_label)

        # 슬라이더 row: 속도 / 음높이 / 볼륨
        # 내부 값(정수) → 표시 → plugin float 매핑:
        #   속도   0..20  → "0.0x"..."2.0x"  → rate   v/20   (0.00..1.00)
        #   음높이 50..200 → "50%"..."200%"   → pitch  v/100  (0.50..2.00)
        #   볼륨   0..100 → "0%"..."100%"    → volume v/100  (0.00..1.00)
        sliders_row = QWidget()
        sliders_layout = QHBoxLayout(sliders_row)
        sliders_layout.setContentsMargins(4, 4, 4, 4)
        sliders_layout.setSpacing(16)

        self.rate_slider = LabeledSlider(
            "속도", 0, 20, 10, formatter=lambda v: f"{v/10:.1f}x"
        )
        self.pitch_slider  = LabeledSlider("음높이", 50, 200, 100)
        self.volume_slider = LabeledSlider("볼륨",   0, 100, 100)

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

    def _slider_values(self) -> tuple[float, float, float]:
        """슬라이더 정수값을 plugin이 받는 float로 매핑.

        속도는 AVSpeech의 비선형성 때문에 ui_speed_to_rate()로 압축.
        """
        ui_x   = self.rate_slider.value() / 10.0      # 0.0..2.0 (사용자 표시)
        rate   = ui_speed_to_rate(ui_x)               # 0.00..0.70 (압축됨)
        pitch  = self.pitch_slider.value()  / 100.0   # 0.50..2.00
        volume = self.volume_slider.value() / 100.0   # 0.00..1.00
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
            "fdsrc",
            "!",
            "text/x-raw,format=utf8",
            "!",
            "macttssink",
            f"rate={rate:.2f}",
            f"pitch={pitch:.2f}",
            f"volume={volume:.2f}",
        ]

        self._process = proc
        proc.start(GST_LAUNCH, args)
        if not proc.waitForStarted(3000):
            self._fail("gst-launch-1.0 시작 실패")
            self._process = None
            return

        proc.write(text.encode("utf-8"))
        proc.closeWriteChannel()

        self.play_action.setEnabled(False)
        self.stop_action.setEnabled(True)
        ui_x = self.rate_slider.value() / 10.0
        self.status_label.setText(
            f"재생 중… (속도 {ui_x:.1f}x · rate {rate:.2f}, "
            f"음높이 {int(pitch * 100)}%, 볼륨 {int(volume * 100)}%)"
        )

    def _on_export(self) -> None:
        if self._export_process is not None:
            return  # 이미 내보내는 중

        if not EXPORT_TOOL.exists():
            self._fail(
                f"export 도구가 없습니다. tools/kb-tts-export/ 에서 'make' 실행 필요."
            )
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
            "--out", path,
            "--rate", f"{rate:.2f}",
            "--pitch", f"{pitch:.2f}",
            "--volume", f"{volume:.2f}",
        ]

        proc = QProcess(self)
        proc.setProcessChannelMode(QProcess.ProcessChannelMode.MergedChannels)
        proc.finished.connect(
            lambda code, status, p=path: self._on_export_finished(p, code, status)
        )
        proc.errorOccurred.connect(self._on_error)

        self._export_process = proc
        proc.start(str(EXPORT_TOOL), args)
        if not proc.waitForStarted(3000):
            self._fail("kb-tts-export 시작 실패")
            self._export_process = None
            return

        proc.write(text.encode("utf-8"))
        proc.closeWriteChannel()

        self.export_action.setEnabled(False)
        self.status_label.setText(f"내보내는 중… → {path}")

    def _on_export_finished(
        self, path: str, exit_code: int, exit_status: QProcess.ExitStatus
    ) -> None:
        self._export_process = None
        self.export_action.setEnabled(True)
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

    def _on_finished(self, exit_code: int, exit_status: QProcess.ExitStatus) -> None:
        self._process = None
        self.play_action.setEnabled(True)
        self.stop_action.setEnabled(False)
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


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("K-Balabolka")
    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
