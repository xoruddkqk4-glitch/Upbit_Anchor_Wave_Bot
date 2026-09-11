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


