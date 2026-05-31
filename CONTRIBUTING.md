# K-Balabolka에 기여하기

K-Balabolka에 관심 가져주셔서 감사합니다. 이 문서는 외부 기여를 제출할 때 따라야 할 절차와, 기여물이 어떤 권리로 이 프로젝트에 편입되는지를 정리합니다.

---

## 1. 기여 절차 개요

1. **먼저 이슈로 논의를 시작합니다.** 작은 버그 수정이 아니라면 PR 전에 이슈를 열어 의도를 공유해 주세요. 변경 방향이 메인테이너의 생각과 어긋난 채로 큰 PR을 만드는 일이 가장 큰 시간 낭비입니다.
2. **저장소를 포크하고 브랜치를 만듭니다.** 브랜치 이름은 무엇이든 무방하지만, 변경 의도가 드러나는 이름(`fix-korean-padding`, `add-voice-selector` 등)을 권장합니다.
3. **변경 단위는 작고 의도가 명확하게.** 하나의 PR이 하나의 일을 합니다. 리팩토링과 기능 추가를 한 PR에 섞지 마세요.
4. **로컬에서 빌드와 동작 확인을 마친 뒤** PR을 제출합니다. 빌드 절차는 [BUILD.md](BUILD.md)를 참고하세요.
5. **관련 이슈를 PR 본문에서 링크**해 주세요(`Closes #123`).

---

## 2. DCO (Developer Certificate of Origin) 동의

이 프로젝트는 기여물의 권리 처리에 **DCO** 방식을 채택합니다. CLA(Contributor License Agreement)는 사용하지 않습니다. DCO는 기여자가 추가 권리 양도 없이도 "이 기여를 제출할 권리가 있음"을 증명하는 가벼운 방식입니다.

### 2.1 DCO 원문

아래 5개 문장이 DCO의 전부입니다. **이 본문은 표준 합의문이므로 임의 번역하지 않고 영문 원문 그대로 인용합니다.**

```
Developer Certificate of Origin
Version 1.1

By making a contribution to this project, I certify that:

 (a) The contribution was created in whole or in part by me and I
     have the right to submit it under the open source license
     indicated in the file; or

 (b) The contribution is based upon previous work that, to the best
     of my knowledge, is covered under an appropriate open source
     license and I have the right under that license to submit that
     work with modifications, whether created in whole or in part
     by me, under the same open source license (unless I am
     permitted to submit under a different license), as indicated
     in the file; or

 (c) The contribution was provided directly to me by some other
     person who certified (a), (b) or (c) and I have not modified
     it.

 (d) I understand and agree that this project and the contribution
     are public and that a record of the contribution (including all
     personal information I submit with it, including my sign-off) is
     maintained indefinitely and may be redistributed consistent with
     this project and the open source license(s) involved.
```

전체 원문 출처: <https://developercertificate.org/>

### 2.2 한국어 해설 (참고용)

DCO에 동의한다는 것은, 위 본문 (a)~(d) 중 적어도 하나가 자신의 기여에 해당한다는 점, 그리고 자신의 기여 기록이 영구히 공개·재배포될 수 있다는 점에 동의한다는 의미입니다. 추가적인 권리 양도는 요구되지 않습니다. 단지 "제출할 권리가 있고, 그 사실을 기록으로 남긴다"입니다.

### 2.3 DCO에 동의를 표시하는 방법: `git commit -s`

커밋을 만들 때 `-s`(`--signoff`) 플래그를 붙이면 커밋 메시지 끝에 자동으로 한 줄이 추가됩니다.

```bash
git commit -s -m "fix: 한국어 받침 음절 잘림 수정"
```

→ 커밋 메시지 끝에 다음 줄이 자동으로 추가됩니다.

```
Signed-off-by: Your Name <you@example.com>
```

이 줄을 남긴 커밋은 위 DCO 원문에 동의한 것으로 간주됩니다.

**이름과 이메일은 실명/실제 이메일이어야 합니다.** `git config user.name`과 `git config user.email`이 익명/가명으로 되어 있으면 DCO 효력에 문제가 생길 수 있습니다.

### 2.4 동의 간주 및 소급 효력

- **이 프로젝트에 PR을 제출한 시점에서, 해당 기여는 DCO에 동의한 것으로 간주됩니다.** `Signed-off-by` 줄이 없더라도 동의 의사 자체는 PR 제출 행위로 표시된 것으로 봅니다. 단, 위 2.3의 서명을 함께 남겨주시면 추적과 감사에 유리합니다.
- **향후 자동 검증 봇이 도입되어 모든 커밋에 `Signed-off-by`를 강제하게 되더라도, 그 이전 시점의 기여도 DCO에 동의한 것으로 간주합니다.** 이 소급 효력은 봇 도입 전후의 법적 공백을 차단하기 위함입니다.

자동 검증 봇 도입은 첫 외부 PR 유입 이후 별도 단계에서 활성화될 예정입니다(상위 이슈 #14 참고).

---

## 3. 코드 스타일

상세한 도구 설정(`.editorconfig`, `ruff` 설정, `.clang-format`)은 별도 작업(상위 이슈 #11)에서 추가될 예정입니다. 그전까지는 다음 방향을 따라주세요.

- **Python (`gui/`)**: PEP 8을 기본으로, 가능하면 `ruff check` / `ruff format`을 통과하는 상태를 유지합니다. 4칸 들여쓰기, 88~100자 줄 폭.
- **C / Objective-C (`plugin/`, `tools/`)**: GStreamer 코드 컨벤션을 따릅니다(2칸 들여쓰기, `lowercase_with_underscores` 함수/변수, `UpperCamelCase` 타입, `K&R` 중괄호 스타일). 기존 파일들의 스타일을 참고해 일관성을 유지해 주세요.
- 공통: 의미 있는 변수/함수 이름, 짧은 함수, 외부 동작이 변하지 않는 한 무의미한 형식 변경(re-format)은 별도 PR로 분리.

---

## 4. 디렉터리 간 코드 이동 규칙 (라이선스 무결성)

이 프로젝트는 디렉터리별로 다른 라이선스를 적용합니다. 자세한 분할 내용은 [LICENSE](LICENSE)를 참고하세요.

| 디렉터리 | 라이선스 |
|---|---|
| `plugin/` | LGPL-2.1-or-later |
| `gui/`    | MIT |
| `tools/`  | MIT |

각 소스 파일 맨 위에는 다음과 같은 SPDX 헤더가 박혀 있습니다.

```c
// SPDX-License-Identifier: LGPL-2.1-or-later
// Copyright (c) 2026 dlgus8648
```

또는

```python
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 dlgus8648
```

### 규칙

**한 디렉터리의 코드를 다른 디렉터리로 옮기는 PR에는 다음 두 가지가 반드시 함께 들어가야 합니다.**

1. **원본 파일의 SPDX 헤더를 함께 옮겨야 합니다.** 헤더 없이 본문만 옮기면, 옮겨진 디렉터리의 기본 라이선스가 사실과 달라집니다(예: LGPL 코드가 MIT 디렉터리에 표기 없이 섞임 → 라이선스 무결성 위반).
2. **옮겨진 라이선스가 대상 디렉터리의 기본 라이선스와 다른 경우, PR 본문에서 그 사실을 명시해 주세요.** 리뷰어가 이 점을 놓치지 않도록 표시하는 절차입니다. 예: "이 PR은 `plugin/`의 LGPL 코드를 `gui/`로 가져옵니다. 옮긴 파일은 SPDX 헤더로 LGPL 표기가 유지됩니다."

이 규칙이 빠지면 사람의 코드 리뷰만으로는 라이선스 오염을 잡아내기 어렵습니다. 향후 가벼운 CI(상위 이슈 #9)에서 "모든 소스에 SPDX 헤더 존재" 자동 검사가 도입될 예정이지만, 그 전까지는 기여자와 리뷰어의 주의에 의존합니다.

---

## 5. 도움이 필요할 때

- 빌드가 안 됩니다 → [BUILD.md](BUILD.md)의 "자주 만나는 문제" 절을 먼저 확인해 주세요.
- 어디서부터 시작해야 할지 모르겠습니다 → 이슈 트래커에서 `good first issue` 라벨이 붙은 이슈를 찾아보세요(라벨링은 점진적으로 진행 중입니다).
- 그 외 질문은 새 이슈를 열어 주세요.

기여해 주셔서 감사합니다.
