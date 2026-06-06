# SPDX-License-Identifier: MIT
# Copyright (c) 2026 dlgus8648

"""플러그인/네이티브 도구 동작 테스트 (시스템 의존 — 가능한 환경에서만 실행).

- kb-tts-export 는 오프라인 합성(writeUtterance 버퍼 콜백)이라 오디오 장치
  없이도 동작한다 → 헤드리스에서도 m4a 생성·청크 진행이 검증된다.
- macttssink 속성은 gst-inspect-1.0 로 확인 (GStreamer framework 필요).

도구/프레임워크가 없는 환경(예: Linux CI)에서는 skip 한다. 이 테스트들은
macOS 2차 CI(#13)에서 의미가 있다.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parent.parent
_EXPORT_TOOL = _ROOT / "tools" / "kb-tts-export" / "kb-tts-export"
_PLUGIN_DYLIB = _ROOT / "plugin" / "builddir" / "gstmacttssink.dylib"

requires_export_tool = pytest.mark.skipif(
    not _EXPORT_TOOL.exists(),
    reason="kb-tts-export 미빌드 (tools/kb-tts-export/ 에서 make 필요)",
)
requires_gst_inspect = pytest.mark.skipif(
    shutil.which("gst-inspect-1.0") is None or not _PLUGIN_DYLIB.exists(),
    reason="gst-inspect-1.0 또는 macttssink.dylib 없음 (GStreamer framework + 플러그인 빌드 필요)",
)


def _assert_valid_m4a(path: Path) -> int:
    """생성된 파일이 비어있지 않고 유효한 m4a(MP4) 컨테이너인지 확인하고 크기 반환.

    MP4/m4a는 'ftyp' 박스로 시작한다(보통 4~8바이트 위치). 0바이트/깨진 파일을
    "생성됨"으로 착각하지 않도록 컨테이너 매직까지 본다.
    """
    assert path.exists(), "m4a 파일이 생성되지 않음"
    size = path.stat().st_size
    assert size > 0, "m4a 파일이 비어 있음"
    with path.open("rb") as f:
        head = f.read(16)
    assert b"ftyp" in head, f"유효한 m4a(ftyp) 컨테이너가 아님 (head={head!r})"
    return size


# ---- kb-tts-export ---------------------------------------------------------


@requires_export_tool
def test_list_voices_format():
    """--list-voices 가 id\\tname\\tlang\\tquality 형식을 낸다."""
    res = subprocess.run(
        [str(_EXPORT_TOOL), "--list-voices"],
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert res.returncode == 0, res.stderr
    rows = [ln for ln in res.stdout.splitlines() if ln.strip()]
    assert rows, "음성이 하나도 출력되지 않음"
    # 모든 줄이 최소 4개 탭 필드
    assert all(len(r.split("\t")) >= 4 for r in rows)


@pytest.mark.avspeech
@requires_export_tool
def test_export_short_text_creates_m4a(tmp_path, short_text):
    """(1) 짧은 텍스트가 유효한 m4a로 잘 생성되는지."""
    out = tmp_path / "short.m4a"
    res = subprocess.run(
        [str(_EXPORT_TOOL), "--out", str(out), "--rate", "0.55"],
        input=short_text,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert res.returncode == 0, res.stderr
    _assert_valid_m4a(out)
    assert "Encoding" in res.stderr and "Saved:" in res.stderr


@pytest.mark.avspeech
@requires_export_tool
def test_export_large_text_creates_m4a(tmp_path, large_text):
    """(2) 1만 자 이상 대용량 텍스트도 유효한 m4a로 잘 생성되는지."""
    assert len(large_text) >= 10_000, "대용량 픽스처가 1만 자 미만"
    out = tmp_path / "large.m4a"
    res = subprocess.run(
        [str(_EXPORT_TOOL), "--out", str(out), "--rate", "0.6"],
        input=large_text,
        capture_output=True,
        text=True,
        timeout=600,
    )
    assert res.returncode == 0, res.stderr
    _assert_valid_m4a(out)
    assert "Saved:" in res.stderr
    # 대용량이므로 청크가 여럿이어야 한다
    m = re.search(r"Encoding (\d+) chunk", res.stderr)
    assert m and int(m.group(1)) > 1, f"청크 분할이 안 됨:\n{res.stderr}"


@pytest.mark.avspeech
@requires_export_tool
def test_export_long_text_per_chunk_progress(tmp_path, long_text):
    """긴 텍스트는 여러 청크로 나뉘고, 청크마다 진행률이 출력된다(회귀 #54)."""
    out = tmp_path / "long.m4a"
    res = subprocess.run(
        [str(_EXPORT_TOOL), "--out", str(out), "--rate", "0.55"],
        input=long_text,
        capture_output=True,
        text=True,
        timeout=180,
    )
    assert res.returncode == 0, res.stderr
    assert out.exists() and out.stat().st_size > 0

    m = re.search(r"Encoding (\d+) chunk", res.stderr)
    assert m, f"'Encoding N chunk' 없음:\n{res.stderr}"
    total = int(m.group(1))
    assert total > 1, "긴 텍스트인데 청크가 1개뿐"

    # 청크마다 '... i/total chunks' 한 줄씩 (10개마다가 아니라 매번 — #54)
    progress = re.findall(r"\.\.\. (\d+)/(\d+) chunks", res.stderr)
    assert len(progress) == total, f"진행 출력 {len(progress)}줄 ≠ 청크 {total}개"
    assert progress[-1] == (str(total), str(total))


# ---- macttssink 속성 (gst-inspect) ----------------------------------------


@requires_gst_inspect
def test_macttssink_exposes_properties():
    env = {"GST_PLUGIN_PATH": str(_PLUGIN_DYLIB.parent)}
    res = subprocess.run(
        ["gst-inspect-1.0", "macttssink"],
        capture_output=True,
        text=True,
        timeout=30,
        env={**__import__("os").environ, **env},
    )
    assert res.returncode == 0, res.stderr
    for prop in ("rate", "pitch", "volume", "voice"):
        assert prop in res.stdout, f"속성 '{prop}' 미노출"
