---
name: save-djt
description: Triggered strictly by '/save-djt'. Saves the current session for a break — exports the conversation to a KST-timestamped txt (YYYYMMDDHHmm.txt), verifies the git working tree, records the resume point in memory, and reports the exact resume command. Never modifies source code and never commits.
---

# 세션 저장 & 재개 준비 스킬 (`save-djt`)

사용자가 잠시 자리를 비울 때 `/save-djt`로 호출합니다. 대화 기록을 서울 시각 파일명으로 남기고, 작업 트리를 점검하고, 재개 지점을 기록해 바로 이어갈 수 있게 합니다.

## 핵심 원칙

1. **코드 수정 금지, 커밋/푸시 금지.** 미커밋 변경이 있으면 목록만 기록하고 그대로 둡니다 (커밋은 `/git-commit` 정책에 따름). 예외적으로 `.gitignore`에 대화 파일 제외 패턴 1줄을 추가하는 것만 허용합니다.
2. `/export`는 CLI 내장 명령이라 스킬이 직접 호출할 수 없습니다. 대신 `export_chat.py`가 세션 기록을 읽어 같은 목적의 txt를 만듭니다.
3. 답변은 한국어로 합니다.

## 수행 절차

### 1. 파일명 산출 (서울 시각)
```bash
date '+%Y%m%d%H%M'
```
(또는 파이썬 스크립트 실행 시각 기준) 결과에 `.txt`를 붙여 파일명으로 씁니다. 예: `202609132155.txt`

### 2. 대화 txt 생성
```bash
python .agents/skills/save-djt/export_chat.py <파일명>.txt
```
- 출력의 `SESSION_ID=...` 값을 보고에 사용합니다.
- **종료 코드 2(세션 기록을 찾지 못함)** 이면 실패를 숨기지 말고, 사용자에게 알립니다.

### 3. `.gitignore` 점검
생성한 파일이 실제로 무시되는지 확인합니다 (패턴 문자열이 아니라 결과로 판정):
```bash
git check-ignore -q <파일명>.txt && echo IGNORED || echo NOT_IGNORED
```
`NOT_IGNORED`면 아래 두 줄을 `.gitignore` 끝에 추가합니다:
```
# 대화 내보내기 파일 (YYYYMMDDHHmm.txt)
/20??????????.txt
```

### 4. 작업 트리 점검 (읽기 전용)
```bash
git status -sb          # 브랜치·원격 동기화 상태
git status --short      # 미커밋/미추적 파일
git log -1 --format="%h | %ad | %s" --date=format-local:"%Y-%m-%d %H:%M"
```
- 미커밋 코드 변경이 있으면 **어느 파일이 어떤 작업분인지** 대화 맥락에서 정리해 기록합니다.
- `.env`, `service_account.json`이 추적되지 않는지도 재확인합니다.

### 5. 재개 지점 보고
- 생성한 대화 파일명과 위치
- 작업 트리 상태 요약 (깨끗함 / 미커밋 N개 파일)
- 직전 작업 내역 및 재개 지점 요약 (다음에 무엇부터 할지)
- 실패하거나 건너뛴 단계가 있으면 명시
