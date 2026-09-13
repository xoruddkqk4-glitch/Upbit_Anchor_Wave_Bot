# Agent Execution Rules: Upbit Anchor Wave Bot

에이전트 실행 규칙: 터미널 전용 고속 검증 (`.agents/rules/rules.md`)

## 1. Browser & Scratchpad Policy (브라우저 / 시각 검증 정책)
- **엄격 금지:** 일반적인 코드 수정 작업 중에 브라우저(Chrome, Scratchpad 등)를 구동하거나 시각 검증을 수행하지 않습니다.
- **자동 스크린샷 금지:** 코드 수정 후 스크린샷 촬영이나 시각적 확인을 절대 자동으로 수행하지 않습니다.
- 이 프로젝트는 UI가 없는 파이썬 CLI/크론탭 트레이딩 봇입니다. 브라우저 구동 및 시각 검증이 불필요합니다.
- **명시적 예외:** 오직 사용자가 `/scratchpad`, `/action scratchpad` 명령어를 입력하거나 "scratchpad로 검증해줘"라고 직접 요청한 경우에 한해 예외가 적용됩니다.

## 2. Terminal-Based Error Verification (터미널 기반 오류 검증)
- 코드 변경 후에는 브라우저 확인 대신 터미널 명령으로 빠른 정적 검증만 수행합니다.
- **이 프로젝트(파이썬) 기본 검증 명령:**
  ```bash
  python -m py_compile <수정한_파일.py>
  ```
- `py_compile`은 구문 오류만 잡고 `NameError`/`AttributeError` 같은 런타임 오류는 잡지 못합니다. 변경 범위가 특정 함수에 국한된 경우, 해당 경로를 실제로 실행하거나 최소 재현 스니펫으로 확인하는 편이 안전합니다.
- 경미한 경고는 끝없이 고치려 하지 말고 간단히 보고한 뒤 작업을 마칩니다.
- **무거운 작업 금지:** 장시간 실행되는 개발 서버, 빌드, 전체 테스트 스위트는 명시적 요청이 없으면 실행하지 않습니다.
- **실주문 절대 금지:** 검증 목적으로 `.env`의 `AUTO_TRADE_EXECUTE`를 `True`로 바꾸거나 실제 주문 API(`/v1/orders`)를 절대로 호출하지 않습니다.

## 3. Workflow Optimization (일반 수정 모드 워크플로)
- **일반적 코드 수정/오류 복구 작업 시:**
  - 코드 변경 적용 → 빠른 터미널 정적 검증(`python -m py_compile`) → 즉시 작업 종료
  - **절대로 자동으로 Git 커밋(`git commit`) 및 푸시(`git push`)를 수행하지 않습니다.**
- 사용자가 명시적으로 `/git-commit` 명령어를 입력할 때까지 커밋/푸시 없이 대기합니다.

## 4. Git 커밋 및 푸시 정책 (오직 `/git-commit` 수신 시에만 실행)
- **엄격 조건:** 오직 사용자로부터 `/action git-commit`, `/git-commit`, 또는 "README 업데이트 후 푸시"와 같은 **명시적인 커밋/푸시 명령어**를 수신했을 때만 Git 커밋 및 푸시 워크플로우를 수행합니다.
- **일반 수정 시 자동 커밋 금지:** 기능 구현, 버그 수정, 코드 리팩토링 등 일반적인 요청 시에는 코드 수정과 터미널 오류 검증만 진행하고 커밋/푸시는 절대로 자동으로 실행하지 않습니다.
- **`/git-commit` 수신 시 수행 절차:**
  1. 작업 내용 및 검증 결과를 정리하여 `README.md` 맨 하단에 누적 이력을 작성합니다.
  2. 상세한 커밋 메시지와 함께 `git add .` 및 `git commit`을 진행합니다.
  3. GitHub 원격 저장소로 `git push`를 수행하고 결과를 사용자에게 종합 보고합니다.
- **`README.md` 변경 이력 누적 기록 규칙:**
  - `README.md` 맨 하단에 **날짜 및 시간(서울 기준 KST: YYYY-MM-DD HH:mm)** 기준으로 누적 기록합니다.
  - 누적 기록에는 **날짜 및 시간(KST)**, **커밋 ID(Commit Hash)**, **수정 내용**이 반드시 포함되어야 합니다.
- 커밋 메시지는 한국어로 작성하며, `docs: update README.md and detailed commit results` 포맷을 따릅니다.
- `main` 브랜치에 직접 커밋/푸시합니다.

## 5. `/ask` 질의응답 및 계획 전용 모드 정책 (No Code Modification & No Auto-Execution)
- 사용자로부터 `/ask`, `/action ask`, 또는 `/ask`로 시작하는 질의를 받으면 프로젝트 소스 코드를 절대로 수정하지 않습니다.
- 단순 질문인 경우 대화 답변만 수행하고, 기술적/복잡한 변경 요청인 경우 `implementation_plan.md` 계획서 작성까지만 진행합니다.
- **계획서 자동 실행 금지:** `/ask` 모드로 작성된 계획서는 시스템 자동 승인(Auto-Approve/Proceed)이 전달되더라도 절대로 자동으로 코드를 변경해서는 안 되며, 사용자의 명시적인 추가 대화 명령이 있을 때까지 대기합니다.

## 6. `/scratchpad` 브라우저 검증 전용 모드 정책 (Visual Verification Explicit Exception)
- 사용자로부터 `/scratchpad`, `/action scratchpad`, 또는 "scratchpad로 검증해줘"라는 명시적인 요청을 수신하는 경우, Rule 1 정책의 명시적 예외를 적용합니다.
- Scratchpad 및 브라우저 검증 도구(`browser_subagent`)를 활용하여 대상 페이지 및 UI 인터액션 기능을 시각적으로 직접 확인하고 결과를 사용자에게 보고합니다.

## 7. `/save-djt` 세션 저장 및 재개 준비 정책 (Session Save & Resume)
- `/save-djt` 수신 시: 대화 기록을 서울 시각 파일명(`YYYYMMDDHHmm.txt`)으로 내보내고, 작업 트리(`git status`)를 점검하고, 재개 지점을 기록한 뒤 재개 안내를 제공합니다.
- 코드 수정·커밋·푸시 금지. `.gitignore`에 대화 파일 제외 패턴 추가만 허용.
