#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 dlgus8648
"""SPDX 라이선스 헤더 검사 — 디렉터리별 라이선스 분할 무결성 검증.

이 프로젝트는 디렉터리별로 다른 라이선스를 적용한다.
- plugin/                → LGPL-2.1-or-later
- gui/, tools/           → MIT

각 소스 파일 맨 위에 SPDX-License-Identifier 한 줄이 박혀 있어야 하며,
그 ID가 자신이 속한 디렉터리의 라이선스와 일치해야 한다. 이 검사는
누락뿐 아니라 ID 불일치(예: MIT 디렉터리에 LGPL 헤더가 박힌 파일)까지
잡아낸다. 디렉터리 간 코드 이동 시 헤더를 함께 옮기지 않으면 라이선스
무결성이 깨지는데, 그 사고를 자동으로 잡기 위한 안전망이다.

CI에서 실행되며 (#9), 위반이 하나라도 있으면 종료 코드 1로 실패한다.

  사용법: python3 scripts/check-spdx-headers.py [PROJECT_ROOT]
  기본 PROJECT_ROOT는 이 스크립트 파일의 부모의 부모(저장소 루트).
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

# (디렉터리, 기대 SPDX 식별자, 검사할 파일 glob 패턴들)
RULES: list[tuple[str, str, list[str]]] = [
    ("plugin", "LGPL-2.1-or-later", ["*.c", "*.h", "*.m", "meson.build"]),
    ("gui",    "MIT",               ["*.py", "*.spec"]),
    ("tools",  "MIT",               ["*.m", "*.c", "*.h", "Makefile"]),
]

# 빌드 산출물·venv·캐시는 검사 대상에서 제외
# (.venv 안의 PyInstaller, PySide6 등은 자체 SPDX 헤더가 다수 있어 노이즈)
EXCLUDE_DIR_NAMES = {
    "builddir", "build", "dist", ".venv", "venv",
    "__pycache__", ".pytest_cache",
}

SPDX_RE = re.compile(r"SPDX-License-Identifier:\s*(\S+)")
HEADER_SCAN_BYTES = 2048  # 파일 첫 2KB만 검사


def is_excluded(path: Path) -> bool:
    return any(part in EXCLUDE_DIR_NAMES for part in path.parts)


def collect_files(root: Path, directory: str, patterns: list[str]) -> list[Path]:
    base = root / directory
    if not base.exists():
        return []
    results: list[Path] = []
    for pattern in patterns:
        for path in base.rglob(pattern):
            if path.is_file() and not is_excluded(path):
                results.append(path)
    return sorted(set(results))


def check_file(path: Path, expected_id: str) -> tuple[bool, str]:
    try:
        with path.open("rb") as f:
            head = f.read(HEADER_SCAN_BYTES).decode("utf-8", errors="replace")
    except OSError as exc:
        return False, f"read error: {exc}"
    match = SPDX_RE.search(head)
    if not match:
        return False, "missing SPDX-License-Identifier header"
    actual = match.group(1)
    if actual != expected_id:
        return False, f"wrong identifier: got '{actual}', expected '{expected_id}'"
    return True, "ok"


def main(argv: list[str]) -> int:
    root = Path(argv[1]).resolve() if len(argv) > 1 else Path(__file__).resolve().parent.parent

    print(f"SPDX header check — root: {root}")

    total_checked = 0
    failures: list[tuple[Path, str]] = []

    for directory, expected_id, patterns in RULES:
        files = collect_files(root, directory, patterns)
        print(f"  [{directory}/] {len(files)} files (expected: {expected_id})")
        for path in files:
            total_checked += 1
            ok, msg = check_file(path, expected_id)
            if not ok:
                failures.append((path.relative_to(root), msg))

    print()
    if failures:
        print(f"FAIL — {len(failures)} of {total_checked} files have SPDX issues:")
        for path, msg in failures:
            print(f"  ✘ {path}: {msg}")
        return 1

    print(f"PASS — all {total_checked} files have correct SPDX headers")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
