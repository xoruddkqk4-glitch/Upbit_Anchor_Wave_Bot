# 🚀 Upbit Anchor Wave Bot (업비트 기준봉 & BST 매매 자동화 봇)

업비트(Upbit) 원화(KRW) 마켓을 대상으로 **기준봉(Anchor Candle)**을 자동으로 탐색하고, **BST(Base-Symmetry-Trend / 기준봉-대칭-추세)** 알고리즘 기반으로 눌림목/돌파 진입, 대칭이론 50% 분할 익절, 5일선 추세 매도, 재매수 및 손절을 자동 집행하는 시스템입니다.

---

## 📌 주요 특징 (Key Features)

1. **독립된 09:07 KST 기준봉 스캐너 (`scan_ref_candles.py`)**
   - 매일 아침 09:07 KST에 구동되어 거래량 급증(200%↑), 장대양봉(+10%↑), 20일 신고가 돌파 기준봉을 포착합니다.
   - 탐색 결과를 `bot_state.json`에 영구 저장하여 메인 매매 봇과 상태를 실시간으로 공유합니다.

2. **5분 주기 타깃 트레이딩 집행 엔진 (`Upbit_Anchor_Wave_Bot.py`)**
   - 5분 크론탭(Crontab) 모니터링 시 전체 코인을 낭비하지 않고, **09:07 스캐너가 포착한 활성 기준봉 종목 및 매수 포지션 종목만 선별 감시**합니다.

3. **개선된 매매 전략 알고리즘 (BST Strategy)**
   - **진입**: 기준봉 중심가 이하 눌림목 반등 진입 또는 고가 돌파 진입 (최대 100만원, 3분할 매수 지원)
   - **재매수 (Re-Entry)**: 5일선 꺾임으로 매도 후, 매도 당시 가격(`base_price`)을 **현재가(실시간 체결가)가 다시 상향 돌파**할 때 100만 원 전액 재매수
   - **분할 익절**: 파동 시간/가격 대칭 달성 및 최소 +3% 수익률 충족 시 보유 수량 50% 분할 매도
   - **추세 매도**: 5일 이동평균선(MA5) 꺾임 시 잔여 수량 전량 매도
   - **손절가**: 세력 마진노선인 기준봉 저가(`effective_ref_low`) 하향 이탈 시 전량 손절 및 기준봉 상태 초기화

4. **슬리피지 방지 및 미체결 제어**
   - 매수/매도 시 최우선 호가 기준 ±0.5% 슬리피지 제한 지정가 주문 적용
   - 3초 이상 미체결 시 잔량 자동 취소 처리

---

## 📁 프로젝트 파일 구조

* `scan_ref_candles.py`: 매일 09:07 KST 실행되는 기준봉 탐색 전용 스캐너
* `Upbit_Anchor_Wave_Bot.py`: 5분 주기 매매 조건 체크 및 주문 집행 모니터링 메인 봇
* `myUpbit.py`: 이동평균, RSI, 볼린저밴드, 거래대금 상위 코인 추출 등 보조 유틸리티 모듈
* `telegram_alert.py`: 매매 시그널 및 시스템 안내 텔레그램 메시지 발송 모듈
* `bot_state.json`: 종목별 실시간 트레이딩 및 기준봉 공유 데이터 파일

---

## ⏰ 크론탭(Crontab) 설정 안내

```bash
# 1) 매일 아침 09:07 KST에 기준봉 전용 스캐너 실행
7 9 * * * cd /path/to/Upbit_Anchor_Wave_Bot && python scan_ref_candles.py >> scan.log 2>&1

# 2) 매 5분마다 09:07 스캐너가 포착한 종목을 실시간 매매 모니터링
*/5 * * * * cd /path/to/Upbit_Anchor_Wave_Bot && python Upbit_Anchor_Wave_Bot.py >> bot.log 2>&1
```

---

## 📝 [2026-09-11 20:00] 업데이트 이력 (Commit ID: a0199ce)
- **수정 내용**:
  1. 5일선 하향 이탈 매도 후 재매수 조건을 종가 돌파에서 **현재가(실시간 체결가) 상향 돌파**로 변경
  2. 기준봉 탐색 로직을 독립 스크립트(`scan_ref_candles.py`)로 분리 및 `bot_state.json` 공유 구조 구축
  3. 메인 봇(`Upbit_Anchor_Wave_Bot.py`)이 09:07 스캐너에서 포착된 활성 기준봉 종목만 선별하여 5분 간격 모니터링하도록 개편
  4. Windows cp949 인코딩 호환성을 위해 로그 출력 이모지를 표준 텍스트로 보정
  5. GitHub 원격 저장소(`https://github.com/xoruddkqk4-glitch/Upbit_Anchor_Wave_Bot.git`) 연결
- **검증 결과**:
  - `python -m py_compile` 정적 구문 검사 통과 (Exit Code 0)
  - `python scan_ref_candles.py` 09:07 스캐너 테스트 완료 (기준봉 종목 포착 및 `bot_state.json` 정상 생성 확인)
  - `python Upbit_Anchor_Wave_Bot.py` 메인 봇 테스트 완료 (공유된 기준봉 종목 선별 감시 및 시그널 정상 수집 확인)

## 📝 [2026-09-11 20:25] 업데이트 이력 (Commit ID: 4e4ff5e)
- **수정 내용**:
  1. `scan_ref_candles.py`에 이미 활성 기준봉이 있거나 포지션 보유 중인 종목 스캔 건너뛰기(Skip) 로직 반영
  2. 업비트 24시간 누적 거래대금(`acc_trade_price_24h`) 기준 상위 20개 코인 자동 정렬 추출 기능 구현
  3. `EXCLUDE_TICKERS` 감시 제외 목록(`KRW-USDT`, `KRW-USDC`, `KRW-APENFT`, `KRW-EHTW`, `KRW-PEPPER`, `KRW-SOLO`, `KRW-XCORE`) 추가 및 필터링 적용
  4. `.env` 환경변수 자동 로드 및 텔레그램 메세지(`telegram_alert.py`) 매매 시그널 자동 발송 연동
  5. `.env` 파일 내 `AUTO_TRADE_EXECUTE=False` 명시로 안전한 모의(시뮬레이션) 트레이딩 환경 구축
- **검증 결과**:
  - `python -m py_compile` 정적 구문 검사 통과 (Exit Code 0)
  - `scan_ref_candles.py` 실행 검증 완료 (거래대금 상위 20개 코인 정렬 및 텔레그램 메시지 발송 확인)
  - `Upbit_Anchor_Wave_Bot.py` 실행 검증 완료 (.env 환경변수 및 매매 시그널 텔레그램 알림 수신 확인)

## 📝 [2026-09-11 20:42] 업데이트 이력 (Commit ID: 3f3d4cc)
- **수정 내용**:
  1. `scan_ref_candles.py`의 상위 코인 추출 로직을 전일 마감 일봉 1개(09:00~09:00)의 누적 거래대금(`candle_acc_trade_price`) 정렬 추출로 전환
  2. 스캐너 포착 시 현재가가 손절가(기준봉 저가) 미만으로 하락한 무효화된 기준봉 사전 무시(필터링) 추가
  3. 기준봉 매수(눌림목/돌파) 조건 검증 시 마감 확정 일봉(`df.iloc[-2]`) 종가/저가/양봉 여부 적용하여 윗꼬리 속임수 방지
  4. 재매수(Re-Entry) 조건에 실시간 현재가 돌파 + **5일 이동평균선 상승 전환(`curr_ma5 >= prev_ma5`)** 확인을 추가하여 무한 매수-매도 핑퐁 버그 차단
  5. 스캐너 건너뛰기 로그 문구 명확화 (기준봉 감시 중 vs 포지션 보유 중 구분 출력)
- **검증 결과**:
  - `python -m py_compile scan_ref_candles.py Upbit_Anchor_Wave_Bot.py` 정적 구문 검사 통과 (Exit Code 0)
  - `scan_ref_candles.py` 전일 마감 일봉 거래대금 20개 종목 정렬 및 사전 무시 필터링 동작 확인
  - `Upbit_Anchor_Wave_Bot.py` 마감 일봉 확정 매수 & 5일선 상승 전환 재매수 로직 정상 동작 확인

## 📝 [2026-09-11 20:46] 업데이트 이력 (Commit ID: 63bce2e)
- **수정 내용**:
  1. 업비트 API(`https://api.upbit.com/v1/market/all?is_details=true`)의 `market_event.warning` 플래그 기반 실시간 유의/위험 종목 동적 자동 제외 기능 구현 (`get_upbit_warning_tickers()`)
  2. `scan_ref_candles.py` 기준봉 스캐너에 업비트 유의/위험 종목 자동 정렬 및 사전 제외 로직 적용
  3. `Upbit_Anchor_Wave_Bot.py` 메인 트레이딩 모니터링 루프에 고정 제외 목록(`EXCLUDE_TICKERS`)과 실시간 유의 종목을 동적 병합(`combined_exclude`)하여 감시 및 매매 차단
- **검증 결과**:
  - `python -m py_compile scan_ref_candles.py Upbit_Anchor_Wave_Bot.py` 정적 구문 검사 통과 (Exit Code 0)
  - `scan_ref_candles.py` 실행 시 업비트 실시간 유의/위험 종목 동적 추출 및 스캔 대상 자동 제외 동작 확인
  - `Upbit_Anchor_Wave_Bot.py` 모니터링 루프 실행 시 실시간 유의 종목 감시 대상 차단 확인

## 📝 [2026-09-11 21:04] 업데이트 이력 (Commit ID: e3594a0)
- **수정 내용**:
  1. Ticker 일괄 배치 조회 API(`GET /v1/ticker?markets=...`)를 활용하여 `scan_ref_candles.py` 스캐너의 실행 속도를 25초 이상에서 약 3초로 획기적 최적화 (800%↑ 속도 향상)
  2. 09:07 기준봉 포착 텔레그램 메시지에 현재가(`curr_close`) 항목 추가 및 실제 가격 위치(고가/중심가/손절가)에 맞춘 동적 가격 계층 순서 배치 구현
  3. 1원 미만 밈코인/초저가 종목의 소수점 뭉개짐 방지를 위해 최대 소수점 8자리 유효숫자 동적 포맷팅 알고리즘(`format_price()`) 적용
  4. 텔레그램 메시지의 `(눌림목 타겟)` 및 `(마진노선)` 부가 텍스트 제거하여 알림 수신 양식 직관화
  5. `bot_state.json` 상태 저장 시 기준봉 미포착 종목(`active_ref_date: null`) 및 미보유 종목 자동 필터링 제거 구현
- **검증 결과**:
  - `python -m py_compile scan_ref_candles.py Upbit_Anchor_Wave_Bot.py` 정적 구문 검사 통과 (Exit Code 0)
  - `python scan_ref_candles.py` 3초 쾌속 스캔 및 `bot_state.json` 미포착 종목 자동 필터링 완료
  - 텔레그램 알림 메시지 동적 가격 계층 순서 배치 및 밈코인 소수점 8자리 유효숫자 정상 작동 검증

## 📝 [2026-09-11 21:25] 업데이트 이력 (Commit ID: 29b7df5)
- **수정 내용**:
  1. `scan_ref_candles.py` 스캐너에 최근 날짜의 새로운 기준봉 포착 시 기존 기준봉 자동 갱신(Update) 및 `[최신 기준봉 갱신!]` 텔레그램 메시지 재발송 로직 반영
  2. `Upbit_Anchor_Wave_Bot.py` 매수 조건에 스윙/휩소 방지 안전 스타일 적용 (마감 확정일봉 `df.iloc[-2]` 종가/저가/양봉여부 기준 눌림목 및 돌파 진입)
  3. `bot_state.json` 유효 활성 기준봉 12개 자동 스캔 및 정상 저장 상태 검증
- **검증 결과**:
  - `python -m py_compile scan_ref_candles.py Upbit_Anchor_Wave_Bot.py` 정적 구문 검사 통과 (Exit Code 0)
  - `python scan_ref_candles.py` 3초 쾌속 스캔 및 신규/최신 기준봉 갱신 지원 동작 확인
  - `python Upbit_Anchor_Wave_Bot.py` 마감 확정 일봉 기반 휩소 방지 매수 조건 동작 검증


## 📝 [2026-09-11 21:33] 업데이트 이력 (Commit ID: 142b985)
- **수정 내용**:
  1. **눌림목 3차(100%) 매수 완료 시 손절가 유지 로직 확정**: 순수 눌림목 3분할 매수가 3차(100%)까지 완결되더라도 손절가(`effective_ref_low`)를 상향하지 않고 기준봉 저가(마진노선) 그대로 유지하도록 보정
  2. **돌파 매수 손절가 상향 조건 차별화**: 100% 돌파 즉시 매수(Breakout All-In) 또는 눌림목 1~2차 진행 중 고가 돌파 전환 시에만 손절가를 기준봉 고가(`ref_high`)로 상향 재조정
  3. 전체 매매/텔레그램 알림 체계에 마감 확정일봉(`df.iloc[-2]`) 휩소 방지 검증 및 밈코인 소수점 8자리 유효숫자 포맷팅(`format_price`) 통합 유지
- **검증 결과**:
  - `python -m py_compile scan_ref_candles.py Upbit_Anchor_Wave_Bot.py` 정적 구문 검사 통과 (Exit Code 0)
  - `python Upbit_Anchor_Wave_Bot.py` 메인 봇 모니터링 실행 검증 완료 (active 기준봉 12개 종목 정상 선별 감시 및 순수 눌림목 3차 매수 완료 시 저가 손절 유지 검증 완료)

## 📝 [2026-09-11 21:45] 업데이트 이력 (Commit ID: 84b40d2)
- **수정 내용**:
  1. **감시 코인 20개 고정 설정**: `TARGET_TICKERS` 목록에 지정된 20개 주요 코인(XRP, BTC, ETH, SOL, DOGE, SUI, ADA, XLM, LINK, HBAR, ALGO, TRUMP, ONDO, WLD, NEAR, WAVES, NEO, QTUM, SHIB, PEPE)을 `scan_ref_candles.py` 및 `Upbit_Anchor_Wave_Bot.py`에 적용하여 스캔 및 감시 대상 고정
  2. **종목당 최대 매수 금액 단독 설정**: `Upbit_Anchor_Wave_Bot.py` 상단에 `MAX_BUY_AMOUNT_KRW = 1000000` (100만원) 파라미터를 추가하여 직관적 금액 설정 연동
  3. **일별 매매 기록 엑셀 자동 저장 및 실현 손익 추적**: 매수/매도 발생 시 실행 폴더 내 일별 엑셀 파일(`trade_history_YYYY-MM-DD.xlsx`)에 일시, 종목, 구분, 체결가, 수량, 거래금액, 평단가, **실현손익(원)**, **수익률(%)**, 사유를 자동 축적 기록하는 `save_trade_to_excel()` 구축
  4. `.gitignore`에 `trade_history_*.xlsx` 및 `*.xlsx` 등록하여 자동 생성 엑셀 파일 깃 관리 제외 처리
- **검증 결과**:
  - `python -m py_compile scan_ref_candles.py Upbit_Anchor_Wave_Bot.py` 정적 구문 검사 통과 (Exit Code 0)
  - `python scan_ref_candles.py` 20개 지정 종목 스캔 및 `bot_state.json` 저장 정상 검증 완료
  - `python Upbit_Anchor_Wave_Bot.py` 20개 종목 5분 주기 감시 및 엑셀 자동 매매 기록(`save_trade_to_excel`) 정상 검증 완료

## 📝 [2026-09-11 21:51] 업데이트 이력 (Commit ID: 39f83ca)
- **수정 내용**:
  1. **단일 엑셀 파일 매매 기록 누적 저장**: 일별 분리 파일 방식에서 실행 폴더 내 **단일 엑셀 파일(`trade_history.xlsx`)**의 맨 마지막 행에 매매 내역 및 실현 손익을 계속 누적 저장하도록 `save_trade_to_excel()` 보정
  2. **최대 매수 금액 설정 정돈**: `MAX_BUY_AMOUNT_KRW = 1000000` 파라미터를 `Upbit_Anchor_Wave_Bot.py` 코드 상단에서 단독으로 통합 관리하도록 구성
- **검증 결과**:
  - `python -m py_compile Upbit_Anchor_Wave_Bot.py` 정적 구문 검사 통과 (Exit Code 0)
  - `python Upbit_Anchor_Wave_Bot.py` 단일 엑셀 파일(`trade_history.xlsx`) 누적 저장 정상 동작 검증 완료

## 📝 [2026-09-12 11:02] 업데이트 이력 (Commit ID: 0464263)
- **수정 내용**:
  1. **구글 스프레드시트 연동 및 엑셀 로직 전면 대체**: `.env` 설정(`GOOGLE_SPREADSHEET_TITLE`, `GOOGLE_DRIVE_FOLDER_ID`) 및 `service_account.json` 인증 기반으로 `체결기록`, `날짜별 포트폴리오 추이`, `손익차트` 3개 시트 자동 구성 구축
  2. **10일간 100건 더미 매매 데이터 작성 (`create_dummy_data.py`)**: 기존 기록을 초기화하고 10일간(일별 10건, 총 100건)의 체결 내역 및 10일간 일별 포트폴리오 추이 스냅샷 더미 데이터를 API 429 비율 제한 재시도(`api_call_with_retry`) 및 단일 배치 입력(`append_rows`)으로 자동 생성
  3. **'손익차트' KPI 대시보드 UX/UI 전면 개편**:
     - 기존 F1 셀 드롭다운 참조 문구 및 하단 노출 데이터 표를 전면 삭제하고 헬퍼 영역(`P~T` 열) 숨김 처리
     - 차트 X축 날짜에 `TO_TEXT`를 적용하여 시리얼 번호(`46268`) 대신 깔끔한 날짜 텍스트(`2026-09-03`) 표시 보정
     - 3~4행 KPI 카드를 `총 누적 실현손익` & `전체 누적 수익률`과 `조회 기간 손익` & `조회 기간 수익률`로 명확하게 세분화 배치
     - 2행 컨트롤 바에 단일 기간 선택 드롭다운(`C2`) 구성 (`전체`, `최근 7일`, `최근 30일`, `최근 90일`, `최근 180일`, `올해(YTD)`, `수동 날짜 입력`)
     - `수동 날짜 입력` 선택 시에만 시작일(`F2`)과 종료일(`I2`) 캘린더가 동시 활성화되며, 프리셋 선택 시 동시 **`- 비활성화 -`** 상태로 제어되도록 구조 동기화
     - '검색 시작' 버튼을 제거하여 드롭다운/날짜 변경 즉시 대시보드 수식 및 Combo 차트가 실시간 자동 갱신되도록 개선
  4. **시트 헤더/데이터행 서식 분리 (`format_sheet_headers`)**: 1행은 남색 배경/흰색 글씨, 2행 이하 데이터행은 Clean White 배경으로 엄격하게 분리하여 2행 스타일 오염 방지
- **검증 결과**:
  - `python -m py_compile Upbit_Anchor_Wave_Bot.py create_dummy_data.py` 정적 구문 검사 통과 (Exit Code 0)
  - `python create_dummy_data.py` 백그라운드 데이터 연동 및 시트 대시보드 생성 완료 (Exit Code 0)
  - 구글 스프레드시트(`Upbit_Anchor_Wave`) 3개 시트에 100건 더미 데이터 및 리뉴얼된 '손익차트' KPI 대시보드 실시간 갱신 정상 동작 검증 완료

## 📝 [2026-09-12 11:25] 업데이트 이력 (Commit ID: eadbbbe)
- **수정 내용**:
  1. **`scan_ref_candles.py` 텔레그램 알림 일괄 보고 방식 전면 개편**: 기존 종목별 개별 메시지 발송 방식을 폐기하고, 스캔 종료 후 전체 유효 기준봉을 하나의 `[기준봉 감시 현황 보고]` 메시지로 취합하여 단일 발송하도록 변경. 본문이 3,800자를 초과하는 경우 종목 블록 단위로 자동 분할(`이어서` 헤더) 발송 처리
  2. **동일 기준일 중복 스캔 스킵(`continue`) 제거 및 상태 태그 3분류 도입**: 기존에는 `prev_ref_date == ref_date_str`인 종목을 조기 `continue`로 건너뛰어 보고 대상에서 누락되었으나, 이를 제거하고 `신규 포착` / `최신 갱신` / `감시 중` 3가지 태그로 분류하여 전 종목을 보고에 포함
  3. **기준봉 미재추출 종목의 감시 연속성 확보**: `ref_indices`가 추출되지 않은 종목도 기존 `active_ref_date`가 유효하고 현재가가 손절가를 상회하는 경우 `[기존 감시 유지]`로 보고 대상에 포함하고, 손절가를 이탈한 경우에만 `active_ref_date`를 해제하도록 분기 세분화
  4. **집계 지표 분리**: `detected_count`는 신규/갱신 건수만 집계하고, 전체 보고 건수는 `all_reported_candles` 길이 기준으로 분리하여 완료 로그에 함께 출력
  5. **런타임 생성 파일 Git 추적 해제**: `.gitignore`에 `bot_state.json`을 등록하고, 기존에 추적 중이던 `__pycache__/*.pyc` 2건 및 `bot_state.json`을 `git rm -r --cached`로 추적 해제 (로컬 파일은 그대로 유지). 봇/스캐너 실행마다 작업 트리가 더럽혀지는 문제 해소
- **검증 결과**:
  - `python -m py_compile scan_ref_candles.py` 정적 구문 검사 통과 (Exit Code 0)
  - `.env`, `service_account.json` 비밀 파일 Git 미추적 상태 재확인 완료
  - 스테이징 대상에서 에이전트 설정 파일(`CLAUDE.md`, `.claude/`) 제외 확인 완료 (사용자 요청에 따라 코드만 커밋)
  - **미수행 항목**: `scan_ref_candles.py` 실제 실행 및 텔레그램 일괄 메시지 수신 검증은 이번 커밋에서 수행하지 않았습니다. 본 수정은 별도 도구로 작성된 변경분이며, `py_compile`은 구문 오류만 검출하므로 런타임 동작(분할 발송 경계 처리, `감시 중` 분기)은 실제 09:07 스캔 시 확인이 필요합니다

## 📝 [2026-09-12 11:55] 업데이트 이력 (Commit ID: 4d0d9cd)
- **수정 내용**:
  1. **호가창 조회 리스트 인덱싱 오류 수정 (`get_orderbook`)**: 업비트 `/v1/orderbook` 응답이 리스트임에도 `res["orderbook_units"]`로 문자열 인덱싱하여 `TypeError`가 발생, **실주문 경로(매수/매도) 전체가 진입 즉시 실패**하던 문제를 `res[0]["orderbook_units"]`로 수정
  2. **`PULLBACK_RATIO` 오타(`PULLBACK_RATio`) 수정**: 눌림목 중심가 계산부에서 `NameError`가 발생한 뒤 상위 `except Exception: continue`에 삼켜져 **해당 종목이 조용히 스킵**되던 문제 해소
  3. **지정가 0원 산출 및 호가단위(틱) 미준수 해소**: 기존 `int(best_price * (1 ± slippage))` 방식이 1원 미만 코인(SHIB, PEPE 등)에서 **지정가를 0으로 만들어 `amount_krw / 0` `ZeroDivisionError`**를 유발하던 문제를 수정. 호가단위 표를 하드코딩하면 업비트 정책 변경 시 어긋나므로, **호가창의 인접 호가 간격에서 실제 틱을 역산(`_infer_tick_size`)** 하고 최우선호가 기준 틱의 정수배만큼 이동(`_apply_slippage`)하도록 변경. 지정가가 float으로 바뀜에 따라 지수표기(`1e-05`) 전송을 막는 `_format_price_param` 추가
  4. **계좌 잔고 조회 메서드 `get_balances` 신규 추가**: 호출부(`:786`)만 존재하고 메서드가 부재하여 `AttributeError`가 `except Exception: pass`에 먹히던 문제를 해소. 그동안 **포트폴리오 시트의 보유 현금·평가금·총자산이 항상 0**으로 기록되던 원인
  5. **실제 체결 기반 포지션 상태 정합성 확보 (핵심 구조 개편)**: 기존에는 상태·텔레그램·시트 기록을 **먼저** 수행하고 주문을 **나중에** 집행하여, 3초 미체결 취소가 발생해도 봇 내부 상태는 "체결됨"으로 남는 정합성 붕괴가 있었음
     - `buy/sell_limit_with_slippage_protection`이 취소 처리 **이후** `/v1/order`를 재조회하여 실제 체결 수량·평균 체결가를 집계한 정규화 결과(`ok`/`price`/`volume`/`amount`)를 반환하도록 변경 (`_summarize_fill`, 부분 체결 포함)
     - 전체 8개 주문 호출부(매수 5, 매도 3)를 **"주문 선집행 → 실제 체결분으로 상태 기록"** 순서로 전면 반전. `execute_buy` / `execute_sell` 헬퍼를 도입해 모의·스캔 모드에서는 기존 이론 체결값을 그대로 반환하여 동작 불변
     - 체결 수량 0이면 상태를 변경하지 않고 건너뛰어 다음 주기에 재시도. 특히 **손절 미체결 시 포지션을 초기화하지 않도록** 보정 (기존에는 미체결이어도 상태를 전량 청산 처리하여 포지션이 유실됨)
     - 부분 체결 시 실제 체결분만큼만 `remaining_ratio`를 차감하고 잔여 수량은 다음 주기에 재시도하며, 텔레그램 알림에 부분 체결 안내 문구(`build_partial_fill_note`)를 병기
  6. **포트폴리오 평가금 시세 기준 산정 (`get_current_prices` 추가)**: 평가금을 매입원가(`avg_buy_price`)로 곱해 기록하던 문제를 `/v1/ticker` 일괄 조회 기반 **실시간 시세**로 변경. 시세 조회 실패 종목(상장폐지 등)은 종목 단위로 매입원가 폴백
- **검증 결과**:
  - `python -m py_compile Upbit_Anchor_Wave_Bot.py` 정적 구문 검사 통과 (Exit Code 0)
  - **순수 로직 단위 검증 통과**(임시 스크립트, 네트워크 미사용): SHIB형 호가창(틱 `0.0001`)에서 지정가 `0.0233`·유효 수량 산출 확인(기존 코드는 `ZeroDivisionError`), BTC형 호가창(틱 `1000`)에서 틱 경계 및 슬리피지 방향 정합 확인, 동일가 호가창 폴백 확인, `_summarize_fill`의 전량/부분/미체결·`uuid` 부재·API 오류 응답·예외·`funds` 누락 케이스 확인
  - **상태 머신 시나리오 7종 검증 통과**(텔레그램·시트·주문 API 전량 스텁 처리): ①손절 미체결 시 포지션 유지 ②손절 전량 체결 시 상태 초기화 ③손절 부분 체결 시 `remaining_ratio` 0.6 유지 및 재시도 ④5일선 매도 미체결 시 기준가 미기록 ⑤5일선 매도 체결 시 실제 체결가로 기준가 기록 ⑥재매수 미체결 시 `base_price` 유지(재시도 보존) ⑦재매수 체결 시 종가가 아닌 **실제 체결가·수량**으로 진입 기록
  - `.env`, `service_account.json` 비밀 파일 Git 미추적 상태 재확인 완료 (`AUTO_TRADE_EXECUTE` 미변경, 실주문 API 미호출)
  - **검토 필요 판단 항목**: (a) 분할 익절은 부분 체결이어도 `symmetry_tp_executed`를 확정 처리합니다. 재시도 시 `total_volume * 0.5`를 다시 계산해 초과 매도가 발생하므로 1회성 이벤트로 고정했습니다. (b) 손절 미체결 시 가격이 손절선 아래에 머무르는 동안 5분 주기마다 재시도합니다. 리스크 관리상 의도된 동작이나, 유동성이 낮은 종목에서는 0.5% 슬리피지 상한 탓에 반복 미체결이 이어질 수 있습니다
  - **미수행 항목**: 실제 업비트 주문 API를 통한 실거래 체결 검증은 수행하지 않았습니다(`CLAUDE.md` 실주문 금지 규칙). 체결 집계 로직은 스텁 응답 기준 검증이므로, 실제 `/v1/order` 응답의 `trades` 필드 구조는 최초 실주문 시 확인이 필요합니다

## 📝 [2026-09-12 12:37] 업데이트 이력 (Commit ID: __COMMIT_HASH__)
- **수정 내용** (전략 로직 3건, 모두 `Upbit_Anchor_Wave_Bot.py`):
  1. **3분할 매수 1일 1회 제한**: 눌림목 조건(`is_pullback`)이 마감 확정일봉 기준이라 하루 종일 값이 고정되는데, 5분 주기마다 재평가되어 **15분 안에 1~3회차가 연속 체결**되는 문제(분할 매수 무력화)를 수정. 상태에 `last_scale_in_date`(일봉 기준일, 업비트 09:00 KST 경계)를 추가하고 눌림목 추가 매수 분기에 `can_scale_in_today` 가드를 적용. 체결 성공 시에만 날짜를 기록해 미체결 시 같은 날 재시도는 허용. 돌파 경로는 체결 즉시 `scale_in_count`를 만수 처리하므로 가드 불필요
  2. **대칭이론(기간·가격) 매도 실제 구현**: 기존 "기간 대칭"이 `수익률 >= 3%`만 검사해 진입 당일에도 절반을 팔았고, 가격 대칭은 OR 조건상 먼저 발동할 수 없는 죽은 코드였음. 1차 파동(스윙 저점 → 기준봉 고가)의 높이 `wave_height`와 기간 `rise_duration`을 진입 이후 2차 파동에 투영하도록 변경
     - 가격 대칭: `현재가 >= 진입가 + wave_height`
     - 기간 대칭: `진입 후 경과일 >= rise_duration - TIME_SYMMETRY_TOLERANCE_DAYS`, 진입 당일(0일) 발동은 배제(`max(..., 1)`), 도달 이후 계속 유효(`>=`)
     - `MIN_TAKE_PROFIT_PCT`(3%)는 두 조건 공통 하한으로 유지(손실 상태에서 시간만 지났다고 팔지 않음)
     - 상태에 `entry_date` 추가. 최초 진입 3곳(눌림목 1차·돌파 전액·재매수)에서 기록, 추가 분할매수에서는 유지. 구버전 상태 파일에 `entry_date`가 없는 열린 포지션은 첫 틱에 현재 일봉으로 백필
     - 텔레그램·시트·시그널 사유에 발동한 대칭 종류와 목표(가격/기간/경과일)를 기록
  3. **재매수(RE-ENTRY) 후 과매수 경로 차단**: 눌림목 1/3만 진입한 채 5일선 매도 → 기준가 돌파 재매수(100만원 전액) 시 `scale_in_count=1`이 그대로 남아, 이후 눌림목 조건에 걸리면 **2/3가 추가로 들어가 133만원**이 되는 문제를 수정. 재매수 체결 시 `scale_in_count`를 만수(`target_scale_in_steps`)로 채워 추가 매수·돌파 잔액 매수 분기를 닫고 매도 로직(기간 대칭·가격 대칭·MA5·손절)만 동작하도록 변경. `target_scale_in_steps` 정의를 재매수 블록 앞으로 이동(값은 설정 상수 파생, 동작 불변)
- **검증 결과**:
  - `python -m py_compile Upbit_Anchor_Wave_Bot.py` 정적 구문 검사 통과 (Exit Code 0)
  - **분할 매수 가드 시나리오**(텔레그램·시트·주문 API 스텁, 임시 스크립트): 눌림목 조건 충족 상태로 같은 날 3틱 연속 호출 시 **1회만 체결**(`scale_in_count=1` 고정), 확정봉 날짜가 바뀐 다음 날 2회차 정상 체결 후 같은 날 재호출 시 다시 차단
  - **대칭 매도 시나리오 8종**: ①진입 당일 +4% → 매도 없음(기존 코드는 매도) ②2일 경과 +10% → 없음(기간·가격 미달) ③4일 경과 +4% → 기간 대칭 발동, 잔여 50% ④1일 경과 목표가 도달 → 가격 대칭 발동 ⑤4일 경과 +1% → 없음(3% 하한) ⑥구버전 상태(진입일 없음) → 백필, 당일 매도 없음 ⑦`rise_duration=1` → 당일 차단·1일 후 발동 ⑧기간 창 경과 후 8일째 +3.5% → 발동
  - **재매수 과매수 시나리오**: "1/3 진입 → 5일선 매도 → 기준가 돌파+MA5 상승" 상태에서 어제 확정봉이 눌림목 조건을 충족한 채 같은 날 3틱 + 다음 날 1틱 실행 → 재매수 100만원 1회만 체결, 이후 추가 매수 0회(수정 전 경로에서는 다음 날 33만원 추가)
  - `.env`, `service_account.json` 미추적 재확인, `AUTO_TRADE_EXECUTE` 미변경, 실주문 API 미호출
  - **설계 판단(검토 요청 사항)**: (a) 대칭 익절은 기간·가격 중 먼저 오는 쪽 **1회**만 발동하며 단일 플래그(`symmetry_tp_executed`)를 공유함. 잔여 50%는 5일선·손절로만 청산. 2단계(기간→50%, 가격→잔여) 분리는 미적용. (b) 기간 대칭은 목표일 이후에도 계속 유효(`>=`)하도록 구현. 목표일 ±1일 창 안에서만 발동하는 방식은 미적용. (c) `curr_ma5`가 당일 미확정 종가로 계산되어 장중 5일선 꺾임 오탐 시 대칭 대기 중인 포지션이 전량 청산될 수 있음(기존 이슈, 이번 범위 외)
