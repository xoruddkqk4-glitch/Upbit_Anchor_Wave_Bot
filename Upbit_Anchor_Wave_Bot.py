import datetime
import hashlib
import json
import os
import time
import urllib.parse
import uuid
from dotenv import load_dotenv
import jwt
import numpy as np
import pandas as pd
import requests
from telegram_alert import SendMessage

# 프로젝트 경로의 .env 명시적 로드
load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))

# ==============================================================================
# [1. 사용자 설정 및 옵션 파라미터 (Top Options)]
# ==============================================================================

# 업비트 API 키 (.env 파일 우선 적용, 없으면 기본값 사용)
UPBIT_ACCESS_KEY = os.getenv("UPBIT_ACCESS_KEY", "").strip()
UPBIT_SECRET_KEY = os.getenv("UPBIT_SECRET_KEY", "").strip()

# Google Sheets 연동 설정 (.env 파일 우선 적용)
GOOGLE_SERVICE_ACCOUNT_JSON = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON", "service_account.json").strip()
GOOGLE_SPREADSHEET_TITLE = os.getenv("GOOGLE_SPREADSHEET_TITLE", "hybrid_turtle_trade_history").strip()
GOOGLE_SPREADSHEET_ID = (
    os.getenv("GOOGLE_SPREADSHEET_ID", "").strip()
    or os.getenv("SPREADSHEET_ID", "").strip()
)
GOOGLE_DRIVE_FOLDER_ID = os.getenv("GOOGLE_DRIVE_FOLDER_ID", "").strip()

# 매매 및 실행 모드 설정 (.env의 UPBIT_PAPER_TRADING=False 인 경우 실주문 모드 전환, 기본값 False=스캔/모의 모드)
AUTO_TRADE_EXECUTE = os.getenv("AUTO_TRADE_EXECUTE", "False").lower() in [
    "true",
    "1",
]

# 감시 종목 설정 (지정된 20개 코인 감시)
TARGET_TICKERS = [
    "KRW-XRP",
    "KRW-BTC",
    "KRW-ETH",
    "KRW-SOL",
    "KRW-DOGE",
    "KRW-SUI",
    "KRW-ADA",
    "KRW-XLM",
    "KRW-LINK",
    "KRW-HBAR",
    "KRW-ALGO",
    "KRW-TRUMP",
    "KRW-ONDO",
    "KRW-WLD",
    "KRW-NEAR",
    "KRW-WAVES",
    "KRW-NEO",
    "KRW-QTUM",
    "KRW-SHIB",
    "KRW-PEPE",
]
MAX_TARGET_COUNT = 20  # 감시할 최대 코인 개수 (20개)

# 감시 및 매매 제외 종목 설정 (예: ['KRW-USDT', 'KRW-USDC'] 등 제외할 코인 지정)
EXCLUDE_TICKERS = ["KRW-USDT", "KRW-USDC", "KRW-APENFT", "KRW-EHTW", "KRW-PEPPER", "KRW-SOLO", "KRW-XCORE"]

# 슬리피지 방지 및 지정가 미체결 취소 옵션
MAX_SLIPPAGE_PCT = (
    0.005  # 허용 최대 슬리피지 비율 (0.005 = 0.5% 호가 범위 내 시장가성 지정가)
)
UNFILLED_WAIT_SEC = (
    3  # 주문 후 미체결 체결 대기 시간(초) -> 경과 후 미체결 잔량 자동 취소
)

# 차트 데이터 조회 설정
CANDLE_COUNT = 120  # 일봉 데이터 조회 개수 (최소 60~120개 권장)

# 기준봉(Reference Candle) 조건 파라미터
REF_VOL_MA_PERIOD = 20  # 거래량 평균 비교 기간 (20일)[cite: 3]
REF_VOL_MULTIPLIER = 2.0  # 거래량 급증 배수 (2.0 = 200% 이상)[cite: 3]
REF_MIN_CHANGE_PCT = (
    0.10  # 기준봉 최소 상승률 (0.10 = 10% 이상 장대양봉)[cite: 3]
)

# 매수(진입) 전략 파라미터
ENABLE_PULLBACK_ENTRY = True  # 눌림목 매수 전략 활성화 (중심가 이하 진입)[cite: 3]
ENABLE_BREAKOUT_ENTRY = True  # 돌파 매수 전략 활성화 (기준봉 고가 돌파 진입)[cite: 3]
PULLBACK_RATIO = 0.5  # 눌림목 기준 비율 (0.5 = 기준봉 중심가 이하)[cite: 3]
REQUIRE_BULLISH_REBOUND = (
    True  # 눌림목 진입 시 양봉(매수세 유입) 확인 필수 여부
)

# 3분할 매수(Scale-in) 옵션 설정
ENABLE_SCALE_IN_BUY = True  # 3분할 매수 전략 활성화 여부 (중심가~저가 구간 분할)

# 매도(익절/손절) 전략 파라미터 (대칭이론 및 5일선 복합 연동)
PREV_HIGH_LOOKBACK_DAYS = (
    60  # 전고점 매물대 저항 감시 기간 (20일, 60일, 120일 등)
)
USE_TIME_SYMMETRY_EXIT = True  # 매도 시 기간 대칭 알고리즘 반영 여부[cite: 2]
TIME_SYMMETRY_TOLERANCE_DAYS = 1  # 기간 대칭 허용 오차 (±1일)
USE_PRICE_SYMMETRY_EXIT = True  # 1차 파동 높이 기반 가격 거리 대칭 익절 활성화[cite: 2]

MIN_TAKE_PROFIT_PCT = 0.03  # 최소 보장 익절 수익률 (0.03 = +3%)

# 손절가 자동 설정
STOP_LOSS_BASE = "LOW"  # 세력 마진노선인 기준봉 저가(Low) 기반 자동 손절[cite: 3]

# 주문 금액 및 시스템 설정 (종목당 최대 매수 금액 설정)
MAX_BUY_AMOUNT_KRW = 1000000  # 종목당 최대 매수 실행 금액 (원 단위: 기본 100만원 = 1,000,000원)
ORDER_AMOUNT_KRW = MAX_BUY_AMOUNT_KRW  # 종목당 총 매수 실행 금액
API_DELAY_SEC = 0.1  # API 요청 간격 (초)

# 상태 저장용 JSON 파일 경로
STATE_FILE = "bot_state.json"


# ==============================================================================
# [JSON 파일 상태 관리 함수]
# ==============================================================================


def format_price(price: float, show_unit: bool = True) -> str:
  """가격 크기에 따라 동적으로 유효 소수점 자릿수 포맷팅 (1원 미만 밈코인은 소수점 8자리까지 표기)"""
  if price is None:
    return "0원" if show_unit else "0"
  try:
    val = float(price)
  except (ValueError, TypeError):
    return str(price)

  if val == 0:
    return "0원" if show_unit else "0"

  unit_str = "원" if show_unit else ""

  if val < 1:
    # 1원 미만 (밈코인 등 초저가 코인): 소수점 8자리까지 표기 (미세 trailing 0 제거)
    formatted = f"{val:.8f}".rstrip("0").rstrip(".")
    return f"{formatted}{unit_str}"
  elif val < 100:
    # 1원 이상 100원 미만: 소수점 4자리까지 표기
    formatted = f"{val:,.4f}".rstrip("0").rstrip(".")
    return f"{formatted}{unit_str}"
  else:
    # 100원 이상: 천단위 쉼표 + 소수점 1자리 표기
    return f"{val:,.1f}{unit_str}"


def load_state():
  """JSON 파일에서 종목별 실시간 트레이딩 상태 로드"""
  if os.path.exists(STATE_FILE):
    try:
      with open(STATE_FILE, "r", encoding="utf-8") as f:
        return json.load(f)
    except Exception as e:
      print(f"[경고] 상태 파일 로드 실패: {e}")
      return {}
  return {}


def save_state(state):
  """종목별 실시간 트레이딩 상태를 JSON 파일에 영구 저장 (유효한 기준봉 포착 종목 또는 매수 포지션 종목만 필터링하여 기록)"""
  try:
    clean_state = {
        t: st
        for t, st in state.items()
        if st.get("entry_bought", False) or st.get("active_ref_date") is not None
    }
    with open(STATE_FILE, "w", encoding="utf-8") as f:
      json.dump(clean_state, f, ensure_ascii=False, indent=4)
  except Exception as e:
    print(f"[오류] 상태 파일 저장 실패: {e}")


def get_google_sheet_doc():
  """구글 서비스 계정 인증 후 스프레드시트 개체 반환 (실패 시 None)"""
  try:
    import gspread

    json_path = GOOGLE_SERVICE_ACCOUNT_JSON
    if not os.path.isabs(json_path):
      json_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), json_path)

    if not os.path.exists(json_path):
      return None

    gc = gspread.service_account(filename=json_path)

    doc = None
    if GOOGLE_SPREADSHEET_ID:
      try:
        doc = gc.open_by_key(GOOGLE_SPREADSHEET_ID)
      except Exception:
        pass

    if doc is None and GOOGLE_SPREADSHEET_TITLE:
      try:
        doc = gc.open(GOOGLE_SPREADSHEET_TITLE)
      except Exception:
        pass

    if doc is None and GOOGLE_DRIVE_FOLDER_ID:
      try:
        doc = gc.open_by_key(GOOGLE_DRIVE_FOLDER_ID)
      except Exception:
        pass

    if doc is None and GOOGLE_SPREADSHEET_TITLE:
      try:
        if GOOGLE_DRIVE_FOLDER_ID:
          doc = gc.create(GOOGLE_SPREADSHEET_TITLE, folder_id=GOOGLE_DRIVE_FOLDER_ID)
        else:
          doc = gc.create(GOOGLE_SPREADSHEET_TITLE)
      except Exception:
        return None

    return doc
  except Exception:
    return None


def ensure_sheet_headers(ws, expected_headers):
  """시트 1행에 올바른 열이름(헤더) 제목이 위치하도록 교정 (데이터 행이 1행에 위치한 경우 헤더 삽입 후 데이터 밀어내기)"""
  try:
    all_rows = ws.get_all_values()
    if not all_rows:
      ws.append_row(expected_headers, value_input_option="USER_ENTERED")
    else:
      first_row = all_rows[0]
      if first_row != expected_headers:
        if first_row and (first_row[0].startswith("202") or first_row[0] != expected_headers[0]):
          ws.insert_row(expected_headers, index=1, value_input_option="USER_ENTERED")
        else:
          col_end = chr(64 + len(expected_headers))
          ws.update(range_name=f"A1:{col_end}1", values=[expected_headers], value_input_option="USER_ENTERED")
  except Exception as e:
    print(f"[경고] 시트 헤더 교정 중 오류: {e}")


def format_sheet_headers(doc, ws, num_cols=10):
  """각 시트의 1행 열이름(헤더)에 스타일 적용 (진한 남색 배경, 흰색 굵은 글씨, 1행 고정) 및 2행 데이터행 서식 정상화"""
  try:
    sheet_id = ws.id
    requests = [
        # 1행 헤더 스타일 적용 (진한 남색 배경, 흰색 굵은 글씨)
        {
            "repeatCell": {
                "range": {
                    "sheetId": sheet_id,
                    "startRowIndex": 0,
                    "endRowIndex": 1,
                    "startColumnIndex": 0,
                    "endColumnIndex": num_cols,
                },
                "cell": {
                    "userEnteredFormat": {
                        "backgroundColor": {
                            "red": 0.12,
                            "green": 0.28,
                            "blue": 0.49,
                        },
                        "textFormat": {
                            "foregroundColor": {
                                "red": 1.0,
                                "green": 1.0,
                                "blue": 1.0,
                            },
                            "bold": True,
                        },
                        "horizontalAlignment": "CENTER",
                    }
                },
                "fields": (
                    "userEnteredFormat(backgroundColor,textFormat,horizontalAlignment)"
                ),
            }
        },
        # 2행 이하 데이터행 스타일 보정 (흰색 배경, 검정 일반 글씨)
        {
            "repeatCell": {
                "range": {
                    "sheetId": sheet_id,
                    "startRowIndex": 1,
                    "endRowIndex": 1000,
                    "startColumnIndex": 0,
                    "endColumnIndex": num_cols,
                },
                "cell": {
                    "userEnteredFormat": {
                        "backgroundColor": {
                            "red": 1.0,
                            "green": 1.0,
                            "blue": 1.0,
                        },
                        "textFormat": {
                            "foregroundColor": {
                                "red": 0.0,
                                "green": 0.0,
                                "blue": 0.0,
                            },
                            "bold": False,
                        },
                    }
                },
                "fields": (
                    "userEnteredFormat(backgroundColor,textFormat)"
                ),
            }
        },
        {
            "updateSheetProperties": {
                "properties": {
                    "sheetId": sheet_id,
                    "gridProperties": {"frozenRowCount": 1},
                },
                "fields": "gridProperties.frozenRowCount",
            }
        },
    ]
    doc.batch_update({"requests": requests})
  except Exception:
    pass


def setup_pnl_chart_filter_ui(doc, ws_chart):
  """'손익차트' 시트에 대시보드 UI (KPI 카드 + 단일 기간 선택 드롭다운 + 동적 날짜 활성화 제어 + 차트 연동) 생성"""
  try:
    chart_sheet_id = ws_chart.id

    # 1. 시트 데이터 및 영역 초기화 후 Grid 크기 확장 (1000행 30열 확보)
    ws_chart.clear()
    try:
      ws_chart.resize(rows=1000, cols=30)
    except Exception:
      pass

    # 2. UI 구조 레이아웃 작성 (1~4행)
    ws_chart.update(
        range_name="A1:J4",
        values=[
            ["📊 실현 손익 추이 대시보드", "", "", "", "", "", "", "", "", ""],
            [
                "",
                "⚡ 기간 선택:",
                "전체",
                "",
                "📅 시작일:",
                '=IF(C2="수동 날짜 입력", "2026-09-03", "- 비활성화 -")',
                "",
                "📅 종료일:",
                '=IF(C2="수동 날짜 입력", "2026-09-12", "- 비활성화 -")',
                "",
            ],
            [
                "",
                "총 누적 실현손익",
                "",
                "전체 누적 수익률",
                "",
                "",
                "조회 기간 손익",
                "",
                "",
                "조회 기간 수익률",
            ],
            [
                "",
                '=IFERROR(TEXT(INDEX(FILTER(\'날짜별 포트폴리오 추이\'!F2:F, \'날짜별 포트폴리오 추이\'!A2:A<>""), COUNTA(FILTER(\'날짜별 포트폴리오 추이\'!A2:A, \'날짜별 포트폴리오 추이\'!A2:A<>""))), "#,##0원"), "0원")',
                "",
                '=IFERROR(TEXT(INDEX(FILTER(\'날짜별 포트폴리오 추이\'!G2:G, \'날짜별 포트폴리오 추이\'!A2:A<>""), COUNTA(FILTER(\'날짜별 포트폴리오 추이\'!A2:A, \'날짜별 포트폴리오 추이\'!A2:A<>""))), "+0.00%;-0.00%"), "0.00%")',
                "",
                "",
                '=IFERROR(TEXT(SUM(S2:S1000), "#,##0원"), "0원")',
                "",
                "",
                '=IFERROR(TEXT(SUM(S2:S1000)/10000000, "+0.00%;-0.00%"), "0.00%")',
            ],
        ],
        value_input_option="USER_ENTERED",
    )

    # 3. Hidden 헬퍼 영역 (P1:T1000) 구성 - 노출 UI 영역 외부 배치
    # P1: 시작일 헬퍼, P2: 종료일 헬퍼
    ws_chart.update(
        range_name="P1:P2",
        values=[[
            '=IF(C2="수동 날짜 입력", IF(ISDATE(F2), F2, DATE(2020,1,1)), IF(C2="최근 7일", TODAY()-7, IF(C2="최근 30일", TODAY()-30, IF(C2="최근 90일", TODAY()-90, IF(C2="최근 180일", TODAY()-180, IF(C2="올해(YTD)", DATE(YEAR(TODAY()),1,1), DATE(2020,1,1)))))))',
        ], [
            '=IF(C2="수동 날짜 입력", IF(ISDATE(I2), I2, DATE(2099,12,31)), DATE(2099,12,31))',
        ]],
        value_input_option="USER_ENTERED",
    )

    # R1:T1 (차트 헤더) 및 R2 (TO_TEXT 적용 필터링 수식)
    ws_chart.update(
        range_name="R1:T1",
        values=[["기간", "일일 실현손익(원)", "누적 실현손익(원)"]],
        value_input_option="USER_ENTERED",
    )

    filter_formula = (
        "=IFERROR(FILTER({TO_TEXT('날짜별 포트폴리오 추이'!A2:A), '날짜별 포트폴리오"
        " 추이'!E2:F}, '날짜별 포트폴리오 추이'!A2:A <> \"\", DATEVALUE('날짜별"
        " 포트폴리오 추이'!A2:A) >= P1, DATEVALUE('날짜별 포트폴리오 추이'!A2:A)"
        " <= P2), '날짜별 포트폴리오 추이'!A2:C)"
    )
    ws_chart.update(range_name="R2", values=[[filter_formula]], value_input_option="USER_ENTERED")

    # 4. 서식 및 셀 유효성 검사 (전체 초기화 후 C2 단일 드롭다운 & F2, I2 달력 팝업 설정)
    requests = [
        # 전체 1~10행 영역 유효성 검사 규칙 완전히 초기화/삭제 (B2, F1 등 잔여 드롭다운 제거)
        {
            "setDataValidation": {
                "range": {
                    "sheetId": chart_sheet_id,
                    "startRowIndex": 0,
                    "endRowIndex": 10,
                    "startColumnIndex": 0,
                    "endColumnIndex": 30,
                }
            }
        },
        # C2 기간 선택 단일 드롭다운 설정
        {
            "setDataValidation": {
                "range": {
                    "sheetId": chart_sheet_id,
                    "startRowIndex": 1,
                    "endRowIndex": 2,
                    "startColumnIndex": 2,
                    "endColumnIndex": 3,
                },
                "rule": {
                    "condition": {
                        "type": "ONE_OF_LIST",
                        "values": [
                            {"userEnteredValue": "전체"},
                            {"userEnteredValue": "최근 7일"},
                            {"userEnteredValue": "최근 30일"},
                            {"userEnteredValue": "최근 90일"},
                            {"userEnteredValue": "최근 180일"},
                            {"userEnteredValue": "올해(YTD)"},
                            {"userEnteredValue": "수동 날짜 입력"},
                        ],
                    },
                    "showCustomUi": True,
                    "strict": True,
                },
            }
        },
        # F2 시작일 달력 유효성 검사
        {
            "setDataValidation": {
                "range": {
                    "sheetId": chart_sheet_id,
                    "startRowIndex": 1,
                    "endRowIndex": 2,
                    "startColumnIndex": 5,
                    "endColumnIndex": 6,
                },
                "rule": {
                    "condition": {"type": "DATE_IS_VALID"},
                    "showCustomUi": True,
                    "strict": False,
                },
            }
        },
        # I2 종료일 달력 유효성 검사
        {
            "setDataValidation": {
                "range": {
                    "sheetId": chart_sheet_id,
                    "startRowIndex": 1,
                    "endRowIndex": 2,
                    "startColumnIndex": 8,
                    "endColumnIndex": 9,
                },
                "rule": {
                    "condition": {"type": "DATE_IS_VALID"},
                    "showCustomUi": True,
                    "strict": False,
                },
            }
        },
        # 1행 타이틀 스타일 (진한 남색 굵은 글씨)
        {
            "repeatCell": {
                "range": {
                    "sheetId": chart_sheet_id,
                    "startRowIndex": 0,
                    "endRowIndex": 1,
                    "startColumnIndex": 0,
                    "endColumnIndex": 10,
                },
                "cell": {
                    "userEnteredFormat": {
                        "textFormat": {
                            "foregroundColor": {"red": 0.12, "green": 0.28, "blue": 0.49},
                            "bold": True,
                            "fontSize": 14,
                        }
                    }
                },
                "fields": "userEnteredFormat(textFormat)",
            }
        },
        # 2행 컨트롤 바 배경 및 서식 (연한 그레이 배경)
        {
            "repeatCell": {
                "range": {
                    "sheetId": chart_sheet_id,
                    "startRowIndex": 1,
                    "endRowIndex": 2,
                    "startColumnIndex": 1,
                    "endColumnIndex": 10,
                },
                "cell": {
                    "userEnteredFormat": {
                        "backgroundColor": {"red": 0.94, "green": 0.95, "blue": 0.97},
                        "textFormat": {"bold": True, "foregroundColor": {"red": 0.12, "green": 0.28, "blue": 0.49}},
                        "horizontalAlignment": "CENTER",
                    }
                },
                "fields": "userEnteredFormat(backgroundColor,textFormat,horizontalAlignment)",
            }
        },
        # 3~4행 KPI 요약 카드 배경 및 글씨 스타일
        {
            "repeatCell": {
                "range": {
                    "sheetId": chart_sheet_id,
                    "startRowIndex": 2,
                    "endRowIndex": 4,
                    "startColumnIndex": 1,
                    "endColumnIndex": 10,
                },
                "cell": {
                    "userEnteredFormat": {
                        "backgroundColor": {"red": 0.97, "green": 0.98, "blue": 0.99},
                        "textFormat": {"bold": True},
                        "horizontalAlignment": "CENTER",
                    }
                },
                "fields": "userEnteredFormat(backgroundColor,textFormat,horizontalAlignment)",
            }
        },
    ]
    doc.batch_update({"requests": requests})
  except Exception as e:
    print(f"[경고] 손익차트 대시보드 UI 설정 중 오류: {e}")


def get_or_create_worksheets(doc):
  """'체결기록', '날짜별 포트폴리오 추이', '손익차트' 3개 시트 확보 및 열이름 헤더 보정"""
  # 1. 기존 '매매기록' 시트가 존재하면 '체결기록'으로 이름 변경
  try:
    legacy_ws = doc.worksheet("매매기록")
    legacy_ws.update_title("체결기록")
  except Exception:
    pass

  # 2. '체결기록' 시트
  try:
    ws_trades = doc.worksheet("체결기록")
  except Exception:
    try:
      ws_trades = doc.add_worksheet(title="체결기록", rows="2000", cols="15")
    except Exception:
      ws_trades = doc.get_worksheet(0)
      try:
        ws_trades.update_title("체결기록")
      except Exception:
        pass

  trade_headers = [
      "일시",
      "종목코드",
      "구분",
      "매매 전략",
      "체결가(원)",
      "체결수량",
      "거래금액(원)",
      "평단가(원)",
      "실현손익(원)",
      "수익률(%)",
      "사유/비고",
  ]
  ensure_sheet_headers(ws_trades, trade_headers)
  format_sheet_headers(doc, ws_trades, 11)

  # 3. '날짜별 포트폴리오 추이' 시트
  try:
    ws_trend = doc.worksheet("날짜별 포트폴리오 추이")
  except Exception:
    ws_trend = doc.add_worksheet(title="날짜별 포트폴리오 추이", rows="1000", cols="10")

  trend_headers = [
      "날짜",
      "원화 잔고(원)",
      "암호화폐 평가금(원)",
      "총 포트폴리오(원)",
      "일일 실현손익(원)",
      "누적 실현손익(원)",
      "누적 수익률(%)",
  ]
  ensure_sheet_headers(ws_trend, trend_headers)
  format_sheet_headers(doc, ws_trend, 7)

  # 4. '손익차트' 시트
  try:
    ws_chart = doc.worksheet("손익차트")
  except Exception:
    ws_chart = doc.add_worksheet(title="손익차트", rows="1000", cols="30")

  setup_pnl_chart_filter_ui(doc, ws_chart)

  return ws_trades, ws_trend, ws_chart


def ensure_pnl_combo_chart(doc, ws_trend, ws_chart):
  """'손익차트' 시트에 실현 손익 추이 Combo 차트 자동 생성 (기존 차트 삭제 후 재생성)"""
  try:
    metadata = doc.fetch_sheet_metadata()
    chart_sheet_id = ws_chart.id

    # 기존에 '손익차트' 시트에 남아있는 모든 차트 삭제하여 최신 스펙/제목/범례 적용 보장
    charts_to_delete = []
    for sheet in metadata.get("sheets", []):
      if sheet.get("properties", {}).get("sheetId") == chart_sheet_id:
        for chart in sheet.get("charts", []):
          charts_to_delete.append({"deleteEmbeddedObject": {"objectId": chart["chartId"]}})

    if charts_to_delete:
      doc.batch_update({"requests": charts_to_delete})

    chart_spec = {
        "title": "실현 손익 추이",
        "basicChart": {
            "chartType": "COMBO",
            "legendPosition": "TOP_LEGEND",
            "axis": [
                {"position": "BOTTOM_AXIS", "title": "기간"},
                {"position": "LEFT_AXIS", "title": "손익 (원)"},
            ],
            "domains": [
                {
                    "domain": {
                        "sourceRange": {
                            "sources": [
                                {
                                    "sheetId": chart_sheet_id,
                                    "startRowIndex": 0,
                                    "endRowIndex": 1000,
                                    "startColumnIndex": 17,  # R열 (17~18)
                                    "endColumnIndex": 18,
                                }
                            ]
                        }
                    }
                }
            ],
            "series": [
                {
                    "series": {
                        "sourceRange": {
                            "sources": [
                                {
                                    "sheetId": chart_sheet_id,
                                    "startRowIndex": 0,
                                    "endRowIndex": 1000,
                                    "startColumnIndex": 18,  # S열 (18~19)
                                    "endColumnIndex": 19,
                                }
                            ]
                        }
                    },
                    "targetAxis": "LEFT_AXIS",
                    "type": "COLUMN",
                    "colorStyle": {
                        "rgbColor": {"red": 0.35, "green": 0.65, "blue": 0.85}
                    },
                },
                {
                    "series": {
                        "sourceRange": {
                            "sources": [
                                {
                                    "sheetId": chart_sheet_id,
                                    "startRowIndex": 0,
                                    "endRowIndex": 1000,
                                    "startColumnIndex": 19,  # T열 (19~20)
                                    "endColumnIndex": 20,
                                }
                            ]
                        }
                    },
                    "targetAxis": "LEFT_AXIS",
                    "type": "LINE",
                    "colorStyle": {
                        "rgbColor": {"red": 0.85, "green": 0.15, "blue": 0.15}
                    },
                },
            ],
            "headerCount": 1,
        },
    }

    request_body = {
        "requests": [
            {
                "addChart": {
                    "chart": {
                        "spec": chart_spec,
                        "position": {
                            "overlayPosition": {
                                "anchorCell": {
                                    "sheetId": chart_sheet_id,
                                    "rowIndex": 5,
                                    "columnIndex": 1,
                                },
                                "offsetXPixels": 0,
                                "offsetYPixels": 0,
                                "widthPixels": 980,
                                "heightPixels": 550,
                            }
                        },
                    }
                }
            }
        ]
    }

    doc.batch_update(request_body)
    print(" └ [완료] '손익차트' Combo 차트 새 생성 완료")
  except Exception as e:
    print(f"[경고] 구글 시트 손익차트 생성 실패: {e}")


def update_daily_portfolio_snapshot(doc, ws_trades, ws_trend, upbit_client=None):
  """'날짜별 포트폴리오 추이' 시트에 오늘자 잔고 및 일일/누적 손익 업데이트"""
  try:
    today_str = datetime.datetime.now().strftime("%Y-%m-%d")

    # 1. 체결기록에서 오늘 일일 실현손익 합산
    all_trades = ws_trades.get_all_values()
    today_daily_pnl = 0.0
    if len(all_trades) > 1:
      for row in all_trades[1:]:
        if len(row) >= 9:
          trade_time = str(row[0])
          if trade_time.startswith(today_str):
            try:
              val_str = str(row[8]).replace(",", "").replace("원", "").strip()
              if val_str:
                today_daily_pnl += float(val_str)
            except (ValueError, TypeError):
              pass

    # 2. 누적 실현손익 계산
    all_trend = ws_trend.get_all_values()
    prev_cum_pnl = 0.0
    today_row_idx = None

    if len(all_trend) > 1:
      for idx, row in enumerate(all_trend[1:], start=2):
        if row and str(row[0]).strip() == today_str:
          today_row_idx = idx
        elif row and str(row[0]).strip() < today_str:
          try:
            val_str = str(row[5]).replace(",", "").replace("원", "").strip()
            if val_str:
              prev_cum_pnl = float(val_str)
          except (ValueError, TypeError):
            pass

    cum_pnl = prev_cum_pnl + today_daily_pnl

    # 3. 업비트 계좌 잔고 조회
    krw_balance = 0.0
    coin_eval = 0.0
    if upbit_client and hasattr(upbit_client, "access_key") and upbit_client.access_key:
      try:
        balances = upbit_client.get_balances()
        if isinstance(balances, list):
          for b in balances:
            curr = b.get("currency", "")
            bal = float(b.get("balance", 0.0)) + float(b.get("locked", 0.0))
            if curr == "KRW":
              krw_balance = bal
            else:
              avg_p = float(b.get("avg_buy_price", 0.0))
              coin_eval += bal * avg_p
      except Exception:
        pass

    total_portfolio = krw_balance + coin_eval

    # 4. 초기 자본 기반 누적 수익률 계산
    initial_capital_env = os.getenv("UPBIT_INITIAL_CAPITAL", "").strip()
    cum_return_pct = 0.0
    if initial_capital_env:
      try:
        init_cap = float(initial_capital_env)
        if init_cap > 0:
          cum_return_pct = round((cum_pnl / init_cap) * 100, 2)
      except Exception:
        pass

    row_data = [
        today_str,
        round(krw_balance),
        round(coin_eval),
        round(total_portfolio),
        round(today_daily_pnl),
        round(cum_pnl),
        cum_return_pct,
    ]

    if today_row_idx is not None:
      ws_trend.update(range_name=f"A{today_row_idx}:G{today_row_idx}", values=[row_data], value_input_option="USER_ENTERED")
    else:
      ws_trend.append_row(row_data, value_input_option="USER_ENTERED")

  except Exception as e:
    print(f"[경고] 날짜별 포트폴리오 추이 업데이트 실패: {e}")


def save_trade_to_google_sheet(
    ticker: str,
    trade_type: str,
    event_name: str,
    price: float,
    volume: float,
    amount_krw: float,
    entry_price: float = 0.0,
    realized_pnl_krw: float = 0.0,
    return_pct: float = 0.0,
    reason: str = "",
    upbit_client=None,
):
  """매매 체결 및 실현 손익 내역을 구글 스프레드시트 3개 시트에 누적 저장 및 차트 갱신"""
  try:
    doc = get_google_sheet_doc()
    if doc is None:
      json_path = GOOGLE_SERVICE_ACCOUNT_JSON
      if not os.path.isabs(json_path):
        json_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), json_path)
      if not os.path.exists(json_path):
        print(f"[경고] 구글 시트 저장 비활성화: 서비스 계정 키 파일('{GOOGLE_SERVICE_ACCOUNT_JSON}')을 찾을 수 없습니다.")
      else:
        print("[오류] 구글 시트 오픈 실패: GOOGLE_SPREADSHEET_ID 또는 GOOGLE_SPREADSHEET_TITLE 설정을 확인하세요.")
      return

    ws_trades, ws_trend, ws_chart = get_or_create_worksheets(doc)

    now = datetime.datetime.now()
    time_str = now.strftime("%Y-%m-%d %H:%M:%S")

    pnl_val = round(realized_pnl_krw) if trade_type == "매도" else 0
    ret_val = round(return_pct * 100, 2) if trade_type == "매도" else 0.0

    price_val = round(price, 8) if price < 1 else round(price, 2)
    entry_price_val = round(entry_price, 8) if entry_price < 1 else round(entry_price, 2)

    row_data = [
        time_str,
        ticker,
        trade_type,
        event_name,
        price_val,
        round(volume, 8),
        round(amount_krw),
        entry_price_val,
        pnl_val,
        ret_val,
        reason,
    ]

    # 1. '체결기록' 시트에 매매 내역 추가
    ws_trades.append_row(row_data, value_input_option="USER_ENTERED")

    # 2. '날짜별 포트폴리오 추이' 시트 갱신
    update_daily_portfolio_snapshot(doc, ws_trades, ws_trend, upbit_client=upbit_client)

    # 3. '손익차트' 시트에 Combo 차트 생성
    ensure_pnl_combo_chart(doc, ws_trend, ws_chart)

    sheet_info = doc.title
    if trade_type == "매도":
      print(
          f" └ [구글 시트 저장] '{sheet_info}' -> '체결기록' & '포트폴리오 추이' 기록 완료 (실현손익: {pnl_val:+,.0f}원"
          f" | 수익률: {ret_val:+.2f}%)"
      )
    else:
      print(
          f" └ [구글 시트 저장] '{sheet_info}' -> '체결기록' & '포트폴리오 추이' 기록 완료 (매수 금액:"
          f" {round(amount_krw):,}원)"
      )
  except Exception as e:
    print(f"[오류] 구글 시트 매매 기록 저장 실패: {e}")


def sync_google_sheet_daily_snapshot(upbit_client=None):
  """모니터링 주기 시작 시 구글 시트 3개 시트 구조 점검 및 오늘자 포트폴리오 추이 동기화"""
  try:
    doc = get_google_sheet_doc()
    if doc is None:
      return

    ws_trades, ws_trend, ws_chart = get_or_create_worksheets(doc)
    update_daily_portfolio_snapshot(doc, ws_trades, ws_trend, upbit_client=upbit_client)
    ensure_pnl_combo_chart(doc, ws_trend, ws_chart)
  except Exception:
    pass



# ==============================================================================
# [2. 업비트 REST API 연동 클래스]
# ==============================================================================


class UpbitClient:

  def __init__(self, access_key="", secret_key=""):
    self.access_key = access_key
    self.secret_key = secret_key
    self.server_url = "https://api.upbit.com/v1"

  def _get_headers(self, params=None):
    payload = {
        "access_key": self.access_key,
        "nonce": str(uuid.uuid4()),
    }
    if params:
      query_string = urllib.parse.urlencode(params)
      m = hashlib.sha512()
      m.update(query_string.encode("utf-8"))
      payload["query_hash"] = m.hexdigest()
      payload["query_hash_alg"] = "SHA512"

    jwt_token = jwt.encode(payload, self.secret_key)
    return {"Authorization": f"Bearer {jwt_token}"}

  def get_krw_tickers(self):
    """업비트 KRW 마켓 전체 종목 조회"""
    url = f"{self.server_url}/market/all"
    res = requests.get(url, timeout=5).json()
    return [item["market"] for item in res if item["market"].startswith("KRW-")]

  def get_daily_ohlcv(self, ticker, count=120):
    """업비트 일봉 데이터 조회 (09:00 KST 기준)"""
    url = f"{self.server_url}/candles/days?market={ticker}&count={count}"
    res = requests.get(url, timeout=5).json()
    if not isinstance(res, list):
      return None

    df = pd.DataFrame(res)
    df = df.iloc[::-1].reset_index(drop=True)
    df.rename(
        columns={
            "candle_date_time_kst": "Date",
            "opening_price": "open",
            "high_price": "high",
            "low_price": "low",
            "trade_price": "close",
            "candle_acc_trade_volume": "volume",
        },
        inplace=True,
    )

    df["Date"] = pd.to_datetime(df["Date"])
    df.set_index("Date", inplace=True)
    return df[["open", "high", "low", "close", "volume"]]

  def get_orderbook(self, ticker):
    """현재 호가창 조회"""
    url = f"{self.server_url}/orderbook?markets={ticker}"
    res = requests.get(url, timeout=5).json()
    if isinstance(res, list) and len(res) > 0:
      return res["orderbook_units"]
    return None

  def get_order_status(self, order_uuid):
    """주문 상태 상세 조회"""
    url = f"{self.server_url}/order"
    params = {"uuid": order_uuid}
    res = requests.get(
        url, params=params, headers=self._get_headers(params), timeout=5
    ).json()
    return res

  def cancel_order(self, order_uuid):
    """미체결 주문 취소"""
    url = f"{self.server_url}/order"
    params = {"uuid": order_uuid}
    res = requests.delete(
        url, params=params, headers=self._get_headers(params), timeout=5
    ).json()
    print(f" └ [미체결 취소] 주문번호 {order_uuid} 취소 처리 완료: {res}")
    return res

  def buy_limit_with_slippage_protection(
      self, ticker, amount_krw, max_slippage_pct=0.005, wait_sec=3
  ):
    """슬리피지 제어형 지정가 매수 + 미체결 자동 취소"""
    if not self.access_key or not self.secret_key:
      print(
          f"[알림] API Key 미설정으로 {ticker} 지정가 매수 주문 생략 (금액:"
          f" {amount_krw:,}원)"
      )
      return None

    ob = self.get_orderbook(ticker)
    if not ob:
      return None

    best_ask_price = ob["ask_price"]
    limit_price = int(best_ask_price * (1 + max_slippage_pct))
    volume = round(amount_krw / limit_price, 8)

    url = f"{self.server_url}/orders"
    params = {
        "market": ticker,
        "side": "bid",
        "volume": str(volume),
        "price": str(limit_price),
        "ord_type": "limit",
    }
    res = requests.post(
        url, json=params, headers=self._get_headers(params), timeout=5
    ).json()
    order_uuid = res.get("uuid")

    print(
        f"[매수 주문] {ticker} | 매수 상한가: {limit_price:,}원 | 수량:"
        f" {volume} | UUID: {order_uuid}"
    )

    if not order_uuid:
      return res

    if wait_sec > 0:
      time.sleep(wait_sec)
      order_info = self.get_order_status(order_uuid)
      state = order_info.get("state")
      remaining_vol = float(order_info.get("remaining_volume", 0))

      if state in ["wait", "watch"] and remaining_vol > 0:
        print(f" └ [미체결 감지] 미체결 잔량({remaining_vol}) 존재 -> 취소 진행")
        self.cancel_order(order_uuid)

    return res

  def sell_limit_with_slippage_protection(
      self, ticker, volume, max_slippage_pct=0.005, wait_sec=3
  ):
    """슬리피지 제어형 지정가 매도 + 미체결 자동 취소"""
    if not self.access_key or not self.secret_key:
      print(
          f"[알림] API Key 미설정으로 {ticker} 지정가 매도 주문 생략 (수량:"
          f" {volume})"
      )
      return None

    ob = self.get_orderbook(ticker)
    if not ob:
      return None

    best_bid_price = ob["bid_price"]
    limit_price = int(best_bid_price * (1 - max_slippage_pct))

    url = f"{self.server_url}/orders"
    params = {
        "market": ticker,
        "side": "ask",
        "volume": str(volume),
        "price": str(limit_price),
        "ord_type": "limit",
    }
    res = requests.post(
        url, json=params, headers=self._get_headers(params), timeout=5
    ).json()
    order_uuid = res.get("uuid")

    print(
        f"[매도 주문] {ticker} | 매도 하한가: {limit_price:,}원 | 수량:"
        f" {volume} | UUID: {order_uuid}"
    )

    if not order_uuid:
      return res

    if wait_sec > 0:
      time.sleep(wait_sec)
      order_info = self.get_order_status(order_uuid)
      state = order_info.get("state")
      remaining_vol = float(order_info.get("remaining_volume", 0))

      if state in ["wait", "watch"] and remaining_vol > 0:
        print(f" └ [미체결 감지] 미체결 잔량({remaining_vol}) 존재 -> 취소 진행")
        self.cancel_order(order_uuid)

    return res


# ==============================================================================
# [3. 5분 주기 모니터링 및 전략 집행 엔진 (BST 개선안 반영)]
# ==============================================================================


def detect_reference_candles(df):
  """기준봉(Reference Candle) 탐색 및 5일 이동평균선(MA5) 계산"""
  df = df.copy()
  df["Vol_MA"] = df["volume"].rolling(window=REF_VOL_MA_PERIOD).mean()
  df["High_Lookback"] = (
      df["high"].shift(1).rolling(window=REF_VOL_MA_PERIOD).max()
  )
  df["Change"] = (df["close"] - df["open"]) / df["open"]
  df["MA5"] = df["close"].rolling(window=5).mean()

  vol_cond = df["volume"] >= df["Vol_MA"] * REF_VOL_MULTIPLIER
  change_cond = df["Change"] >= REF_MIN_CHANGE_PCT
  breakout_cond = df["close"] > df["High_Lookback"]

  df["Is_Ref_Candle"] = vol_cond & change_cond & breakout_cond
  return df


def process_ticker_strategy(ticker, df, upbit_client, global_state):
  """개선된 BST 전략을 반영한 단일 종목 실시간 모니터링 및 매매 집행"""
  df = detect_reference_candles(df)

  if ticker not in global_state:
    global_state[ticker] = {
        "active_ref_date": None,
        "entry_bought": False,
        "entry_price": 0.0,
        "total_volume": 0.0,
        "remaining_ratio": 1.0,
        "symmetry_tp_executed": False,
        "scale_in_count": 0,
        "base_price": None,
        "ref_high": 0.0,
        "effective_ref_low": 0.0,
        "ref_mid": 0.0,
        "rise_duration": 0,
        "wave_height": 0.0,
    }

  state = global_state[ticker]
  signals = []
  curr_row = df.iloc[-1]
  curr_close = curr_row["close"]
  curr_open = curr_row["open"]
  curr_low = curr_row["low"]
  curr_ma5 = df["MA5"].iloc[-1]
  prev_ma5 = df["MA5"].iloc[-2] if len(df) >= 2 else curr_ma5

  # 마감 확정된 전일 일봉 (09:00 마감 완결 캔들 - 스윙/휩소 방지용)
  confirmed_row = df.iloc[-2] if len(df) >= 2 else curr_row
  confirmed_close = confirmed_row["close"]
  confirmed_open = confirmed_row["open"]
  confirmed_low = confirmed_row["low"]

  # 1. 활성 기준봉이 없는 경우: 신규 기준봉 탐색
  if not state["active_ref_date"]:
    ref_indices = df.index[df["Is_Ref_Candle"]].tolist()
    if ref_indices:
      latest_ref_idx = ref_indices[-1]
      ref_row = df.loc[latest_ref_idx]
      ref_pos = df.index.get_loc(latest_ref_idx)

      ref_high = ref_row["high"]
      ref_low = ref_row["low"]

      prev_close = (
          df["close"].iloc[ref_pos - 1] if ref_pos > 0 else ref_row["open"]
      )
      has_gap_up = ref_row["open"] > prev_close
      effective_ref_low = min(ref_low, prev_close) if has_gap_up else ref_low
      ref_mid = effective_ref_low + (ref_high - effective_ref_low) * PULLBACK_RATio

      lookback_start = max(0, ref_pos - 10)
      low_rel_pos = df["low"].iloc[lookback_start : ref_pos + 1].argmin()
      rise_duration = (ref_pos - (lookback_start + low_rel_pos)) + 1
      swing_low_price = df["low"].iloc[lookback_start : ref_pos + 1].min()
      wave_height = ref_high - swing_low_price

      state["active_ref_date"] = latest_ref_idx.strftime("%Y-%m-%d")
      state["ref_high"] = ref_high
      state["effective_ref_low"] = effective_ref_low
      state["ref_mid"] = ref_mid
      state["rise_duration"] = int(rise_duration)
      state["wave_height"] = wave_height
      print(
          f"[{ticker}] [BST] 새로운 기준봉 포착! (기준일:"
          f" {state['active_ref_date']})"
      )

  # 활성 기준봉이 있는 경우 5분 주기 실시간 모니터링 진행
  if state["active_ref_date"]:
    effective_ref_low = state["effective_ref_low"]
    ref_mid = state["ref_mid"]
    ref_high = state["ref_high"]
    wave_height = state["wave_height"]
    rise_duration = state["rise_duration"]

    # [손절 체크] 기준봉 저가(마진노선) 이탈 시 데이터 초기화
    if curr_close < effective_ref_low:
      if state["remaining_ratio"] > 0 and state["entry_bought"]:
        sell_vol = state["total_volume"] * state["remaining_ratio"]
        buy_cost = state["entry_price"] * sell_vol
        sell_amount = curr_close * sell_vol
        realized_pnl = sell_amount - buy_cost
        ret_pct = (
            (curr_close - state["entry_price"]) / state["entry_price"]
            if state["entry_price"] > 0
            else 0.0
        )

        signals.append({
            "Ticker": ticker,
            "Event": "SELL (STOP LOSS)",
            "Price": curr_close,
            "Reason": "기준봉 손절가(마진노선) 이탈 -> 기준 가격 데이터 초기화",
        })

        # 텔레그램 손절 매도 알림
        SendMessage(
            f"<b>🔴 [BST 봇] 손절 매도! (STOP LOSS)</b>\n"
            f"• <b>종목</b>: {ticker}\n"
            f"• <b>매도가</b>: {format_price(curr_close)}\n"
            f"• <b>실현손익</b>: <b>{realized_pnl:+,.0f}원 ({ret_pct*100:+.2f}%)</b>\n"
            f"• <b>사유</b>: 기준봉 저가({format_price(effective_ref_low)}) 하향 이탈 -> 전량 손절 및 상태 초기화\n"
            f"• <b>주문 모드</b>: {'실제 주문' if AUTO_TRADE_EXECUTE else '모의/스캔 모드'}"
        )

        save_trade_to_google_sheet(
            ticker=ticker,
            trade_type="매도",
            event_name="SELL (STOP LOSS)",
            price=curr_close,
            volume=sell_vol,
            amount_krw=sell_amount,
            entry_price=state["entry_price"],
            realized_pnl_krw=realized_pnl,
            return_pct=ret_pct,
            reason=f"기준봉 저가({format_price(effective_ref_low)}) 하향 이탈 전량 손절",
        )

        if AUTO_TRADE_EXECUTE and upbit_client and upbit_client.access_key:
          upbit_client.sell_limit_with_slippage_protection(
              ticker=ticker, volume=sell_vol
          )

      global_state[ticker] = {
          "active_ref_date": None,
          "entry_bought": False,
          "entry_price": 0.0,
          "total_volume": 0.0,
          "remaining_ratio": 1.0,
          "symmetry_tp_executed": False,
          "scale_in_count": 0,
          "base_price": None,
          "ref_high": 0.0,
          "effective_ref_low": 0.0,
          "ref_mid": 0.0,
          "rise_duration": 0,
          "wave_height": 0.0,
      }
      return signals

    # [재매수 체크] 5일선 꺾여 기록된 기준 가격 현재가 상향 돌파 + 5일선 상승 전환(curr_ma5 >= prev_ma5) 동시 확인 시 재매수
    if (
        state["base_price"] is not None
        and curr_close > state["base_price"]
        and curr_ma5 >= prev_ma5
        and state["remaining_ratio"] == 0
    ):
      entry_price = curr_close
      total_volume = ORDER_AMOUNT_KRW / entry_price
      state["entry_bought"] = True
      state["entry_price"] = entry_price
      state["total_volume"] = total_volume
      state["remaining_ratio"] = 1.0
      state["symmetry_tp_executed"] = False
      triggered_base_price = state["base_price"]
      state["base_price"] = None

      signals.append({
          "Ticker": ticker,
          "Event": "BUY (RE-ENTRY)",
          "Strategy": (
              f"기준가({triggered_base_price}) 현재가 상향 돌파 & 5일선 상승 전환"
              " -> 100만원 재매수"
          ),
          "Entry_Price": round(entry_price, 2),
      })

      # 텔레그램 재매수 알림
      SendMessage(
          f"<b>🚀 [BST 봇] 재매수 시그널 발생! (RE-ENTRY)</b>\n"
          f"• <b>종목</b>: {ticker}\n"
          f"• <b>전략</b>: 이전 매도 기준가({format_price(triggered_base_price)}) 현재가 상향 돌파 + 5일선 상승 전환 확인\n"
          f"• <b>체결/진입가</b>: {format_price(entry_price)}\n"
          f"• <b>매수 금액</b>: {ORDER_AMOUNT_KRW:,.0f}원 전액 재매수\n"
          f"• <b>주문 모드</b>: {'실제 주문' if AUTO_TRADE_EXECUTE else '모의/스캔 모드'}"
      )

      save_trade_to_google_sheet(
          ticker=ticker,
          trade_type="매수",
          event_name="BUY (RE-ENTRY)",
          price=entry_price,
          volume=total_volume,
          amount_krw=ORDER_AMOUNT_KRW,
          entry_price=entry_price,
          reason=(
              f"이전 매도 기준가({format_price(triggered_base_price)}) 상향 돌파"
              " & 5일선 상승 전환 재매수"
          ),
      )

      if AUTO_TRADE_EXECUTE and upbit_client and upbit_client.access_key:
        upbit_client.buy_limit_with_slippage_protection(
            ticker=ticker, amount_krw=ORDER_AMOUNT_KRW
        )

    # [진입 및 매수 체크]
    target_scale_in_steps = 3 if ENABLE_SCALE_IN_BUY else 1
    if not state["entry_bought"] or (
        ENABLE_SCALE_IN_BUY
        and state["scale_in_count"] < target_scale_in_steps
        and state["remaining_ratio"] > 0
    ):
      is_pullback = False
      if ENABLE_PULLBACK_ENTRY:
        # 마감 확정일봉(09:00 마감) 기준: 중심가 이하 저가 터치 후 확실한 양봉 마감 시 매수
        price_cond = confirmed_low <= ref_mid
        rebound_cond = (
            (confirmed_close > confirmed_open) if REQUIRE_BULLISH_REBOUND else True
        )
        is_pullback = price_cond and rebound_cond

      is_breakout = False
      if ENABLE_BREAKOUT_ENTRY:
        # 마감 확정일봉(09:00 마감) 종가가 기준봉 고가를 완벽히 상향 돌파하며 마감 시 매수 (장중 윗꼬리 휩소 차단)
        is_breakout = confirmed_close > ref_high

      # A. 신규 진입 (포지션 미보유 상태)
      if not state["entry_bought"]:
        if is_breakout:
          # 1) 돌파 매매: 3분할이 아닌 100만원 전액 즉시 매수 + 손절가를 기준봉 고가(ref_high)로 재조정
          state["entry_bought"] = True
          state["entry_price"] = curr_close
          state["total_volume"] = ORDER_AMOUNT_KRW / curr_close
          state["remaining_ratio"] = 1.0
          state["scale_in_count"] = target_scale_in_steps  # 전액 매수 완료 처리
          prev_low = state["effective_ref_low"]
          state["effective_ref_low"] = ref_high  # 손절선을 돌파가(고가)로 상향 재조정

          signals.append({
              "Ticker": ticker,
              "Event": "BUY (BREAKOUT ALL-IN)",
              "Entry_Price": round(curr_close, 2),
              "Stop_Loss_Adjusted": ref_high,
          })

          SendMessage(
              f"<b>🚀 [BST 봇] 돌파 매수 발생! (BREAKOUT ALL-IN)</b>\n"
              f"• <b>종목</b>: {ticker}\n"
              f"• <b>체결/진입가</b>: {format_price(curr_close)}\n"
              f"• <b>매수 금액</b>: {ORDER_AMOUNT_KRW:,.0f}원 (100% 전액 매수)\n"
              f"• <b>손절선 재조정</b>: {format_price(prev_low)} ➔ <b>{format_price(ref_high)}</b> (돌파가로 상향)\n"
              f"• <b>주문 모드</b>: {'실제 주문' if AUTO_TRADE_EXECUTE else '모의/스캔 모드'}"
          )

          save_trade_to_google_sheet(
              ticker=ticker,
              trade_type="매수",
              event_name="BUY (BREAKOUT ALL-IN)",
              price=curr_close,
              volume=state["total_volume"],
              amount_krw=ORDER_AMOUNT_KRW,
              entry_price=curr_close,
              reason="마감확정일봉 기준봉 고가 완벽 상향 돌파 100% 전액 매수",
          )

          if AUTO_TRADE_EXECUTE and upbit_client and upbit_client.access_key:
            upbit_client.buy_limit_with_slippage_protection(
                ticker=ticker, amount_krw=ORDER_AMOUNT_KRW
            )

        elif is_pullback:
          # 2) 눌림목 매매: 1차 분할 매수 진행 (1/3 금액)
          tranche_amount = ORDER_AMOUNT_KRW / target_scale_in_steps
          state["entry_bought"] = True
          state["entry_price"] = curr_close
          state["total_volume"] = tranche_amount / curr_close
          state["remaining_ratio"] = 1.0
          state["scale_in_count"] = 1

          signals.append({
              "Ticker": ticker,
              "Event": "BUY (PULLBACK 1/3)",
              "Entry_Price": round(curr_close, 2),
          })

          SendMessage(
              f"<b>🔵 [BST 봇] 눌림목 매수 시그널 발생! (1/{target_scale_in_steps}차 분할 매수)</b>\n"
              f"• <b>종목</b>: {ticker}\n"
              f"• <b>체결/진입가</b>: {format_price(curr_close)}\n"
              f"• <b>매수 금액</b>: {tranche_amount:,.0f}원 (1차 매수)\n"
              f"• <b>주문 모드</b>: {'실제 주문' if AUTO_TRADE_EXECUTE else '모의/스캔 모드'}"
          )

          save_trade_to_google_sheet(
              ticker=ticker,
              trade_type="매수",
              event_name=f"BUY (PULLBACK 1/{target_scale_in_steps})",
              price=curr_close,
              volume=state["total_volume"],
              amount_krw=tranche_amount,
              entry_price=curr_close,
              reason=(
                  "마감확정일봉 기준 중심가 이하 저가 터치 후 양봉 반등"
                  f" 1/{target_scale_in_steps}차 분할 매수"
              ),
          )

          if AUTO_TRADE_EXECUTE and upbit_client and upbit_client.access_key:
            upbit_client.buy_limit_with_slippage_protection(
                ticker=ticker, amount_krw=tranche_amount
            )

      # B. 눌림목 진입 후 3회차 미만에 도달해 있는 추가 매수 관리
      elif (
          state["entry_bought"]
          and state["scale_in_count"] < target_scale_in_steps
          and state["remaining_ratio"] > 0
      ):
        if is_breakout:
          # 1) 눌림목 1~2회차 진행 중 고가 돌파 시: 남은 금액을 전액(한번에) 매수하여 100만 원 채우고 손절가 상향
          remaining_steps = target_scale_in_steps - state["scale_in_count"]
          remaining_amount = (
              ORDER_AMOUNT_KRW / target_scale_in_steps
          ) * remaining_steps
          add_volume = remaining_amount / curr_close
          old_volume = state["total_volume"]

          state["entry_price"] = (
              (state["entry_price"] * old_volume) + (curr_close * add_volume)
          ) / (old_volume + add_volume)
          state["total_volume"] += add_volume
          state["scale_in_count"] = target_scale_in_steps
          prev_low = state["effective_ref_low"]
          state["effective_ref_low"] = ref_high  # 손절선을 돌파가(고가)로 상향 재조정

          signals.append({
              "Ticker": ticker,
              "Event": "BUY (BREAKOUT FULL SCALE-IN)",
              "Entry_Price": round(state["entry_price"], 2),
              "Stop_Loss_Adjusted": ref_high,
          })

          SendMessage(
              f"<b>🚀 [BST 봇] 고가 돌파 시그널! 남은 잔액 전액 매수 (BREAKOUT ALL-IN)</b>\n"
              f"• <b>종목</b>: {ticker}\n"
              f"• <b>체결가</b>: {format_price(curr_close)} (평단가: {format_price(state['entry_price'])})\n"
              f"• <b>매수 잔액</b>: {remaining_amount:,.0f}원 (남은 금액 전액 집행 ➔ 3/{target_scale_in_steps}차 완료)\n"
              f"• <b>손절선 재조정</b>: {format_price(prev_low)} ➔ <b>{format_price(ref_high)}</b> (돌파가로 상향)\n"
              f"• <b>주문 모드</b>: {'실제 주문' if AUTO_TRADE_EXECUTE else '모의/스캔 모드'}"
          )

          save_trade_to_google_sheet(
              ticker=ticker,
              trade_type="매수",
              event_name="BUY (BREAKOUT FULL SCALE-IN)",
              price=curr_close,
              volume=add_volume,
              amount_krw=remaining_amount,
              entry_price=state["entry_price"],
              reason="눌림목 진행 중 마감확정일봉 고가 돌파 잔액 전액 매수",
          )

          if AUTO_TRADE_EXECUTE and upbit_client and upbit_client.access_key:
            upbit_client.buy_limit_with_slippage_protection(
                ticker=ticker, amount_krw=remaining_amount
            )

        elif is_pullback:
          # 2) 순수 추가 눌림목 조건 만족 시: 1/3 금액만큼 다음 회차 분할 매수 진행
          tranche_amount = ORDER_AMOUNT_KRW / target_scale_in_steps
          state["scale_in_count"] += 1
          add_volume = tranche_amount / curr_close
          old_volume = state["total_volume"]

          state["entry_price"] = (
              (state["entry_price"] * old_volume) + (curr_close * add_volume)
          ) / (old_volume + add_volume)
          state["total_volume"] += add_volume

          signals.append({
              "Ticker": ticker,
              "Event": f"BUY (PULLBACK {state['scale_in_count']}/{target_scale_in_steps})",
              "Entry_Price": round(state["entry_price"], 2),
          })

          SendMessage(
              f"<b>🔵 [BST 봇] 눌림목 추가 매수 시그널! ({state['scale_in_count']}/{target_scale_in_steps}차 분할 매수)</b>\n"
              f"• <b>종목</b>: {ticker}\n"
              f"• <b>체결가</b>: {format_price(curr_close)} (평단가: {format_price(state['entry_price'])})\n"
              f"• <b>매수 금액</b>: {tranche_amount:,.0f}원\n"
              f"• <b>주문 모드</b>: {'실제 주문' if AUTO_TRADE_EXECUTE else '모의/스캔 모드'}"
          )

          save_trade_to_google_sheet(
              ticker=ticker,
              trade_type="매수",
              event_name=f"BUY (PULLBACK {state['scale_in_count']}/{target_scale_in_steps})",
              price=curr_close,
              volume=add_volume,
              amount_krw=tranche_amount,
              entry_price=state["entry_price"],
              reason=(
                  "마감확정일봉 눌림목 반등 추가"
                  f" {state['scale_in_count']}/{target_scale_in_steps}차 분할 매수"
              ),
          )

          if AUTO_TRADE_EXECUTE and upbit_client and upbit_client.access_key:
            upbit_client.buy_limit_with_slippage_protection(
                ticker=ticker, amount_krw=tranche_amount
            )

    # [매도 및 5일선 관리 체크]
    if state["entry_bought"] and state["remaining_ratio"] > 0:
      entry_price = state["entry_price"]
      current_return = (curr_close - entry_price) / entry_price

      # A. 대칭 조건 만족 시 보유량의 50% 익절
      is_time_symmetric_exit = USE_TIME_SYMMETRY_EXIT and (
          current_return >= MIN_TAKE_PROFIT_PCT
      )
      is_price_symmetric_exit = USE_PRICE_SYMMETRY_EXIT and (
          curr_close >= (entry_price + wave_height)
          and current_return >= MIN_TAKE_PROFIT_PCT
      )

      if (
          is_time_symmetric_exit or is_price_symmetric_exit
      ) and not state["symmetry_tp_executed"]:
        state["symmetry_tp_executed"] = True
        sell_vol = state["total_volume"] * 0.5
        state["remaining_ratio"] -= 0.5
        buy_cost = entry_price * sell_vol
        sell_amount = curr_close * sell_vol
        realized_pnl = sell_amount - buy_cost

        signals.append({
            "Ticker": ticker,
            "Event": "PARTIAL SELL (SYMMETRY 50%)",
            "Return(%)": round(current_return * 100, 2),
            "Reason": "대칭 조건 달성 -> 50% 익절 완료",
        })

        # 텔레그램 50% 분할 익절 알림
        SendMessage(
            f"<b>🟢 [BST 봇] 50% 분할 익절! (PARTIAL SELL)</b>\n"
            f"• <b>종목</b>: {ticker}\n"
            f"• <b>매도가</b>: {format_price(curr_close)}\n"
            f"• <b>수익률</b>: <b>{current_return * 100:+.2f}%</b>\n"
            f"• <b>실현손익</b>: <b>{realized_pnl:+,.0f}원</b>\n"
            f"• <b>사유</b>: 파동 시간/가격 대칭 목표 달성 (보유 수량 50% 익절)\n"
            f"• <b>주문 모드</b>: {'실제 주문' if AUTO_TRADE_EXECUTE else '모의/스캔 모드'}"
        )

        save_trade_to_google_sheet(
            ticker=ticker,
            trade_type="매도",
            event_name="PARTIAL SELL (SYMMETRY 50%)",
            price=curr_close,
            volume=sell_vol,
            amount_krw=sell_amount,
            entry_price=entry_price,
            realized_pnl_krw=realized_pnl,
            return_pct=current_return,
            reason="파동 시간/가격 대칭 목표 달성 (보유 수량 50% 익절)",
        )

        if AUTO_TRADE_EXECUTE and upbit_client and upbit_client.access_key:
          upbit_client.sell_limit_with_slippage_protection(
              ticker=ticker, volume=sell_vol
          )

      # B. 5일선 꺾임(하향 이탈) 체크 -> 잔여 전액 매도 후 기준 가격 기록
      if curr_ma5 < prev_ma5:
        sell_vol = state["total_volume"] * state["remaining_ratio"]
        buy_cost = entry_price * sell_vol
        sell_amount = curr_close * sell_vol
        realized_pnl = sell_amount - buy_cost
        ret_pct = (
            (curr_close - entry_price) / entry_price if entry_price > 0 else 0.0
        )

        state["remaining_ratio"] = 0.0
        state["base_price"] = curr_close

        signals.append({
            "Ticker": ticker,
            "Event": "SELL (MA5 DOWN)",
            "Price": curr_close,
            "Reason": f"5일선 꺾임 전액 매도 -> 기준 가격 기록: {curr_close}",
        })

        # 텔레그램 5일선 추세 매도 알림
        SendMessage(
            f"<b>🟡 [BST 봇] 추세 매도! (MA5 DOWN)</b>\n"
            f"• <b>종목</b>: {ticker}\n"
            f"• <b>매도가</b>: {format_price(curr_close)}\n"
            f"• <b>수익률</b>: <b>{ret_pct * 100:+.2f}%</b>\n"
            f"• <b>실현손익</b>: <b>{realized_pnl:+,.0f}원</b>\n"
            f"• <b>사유</b>: 5일선 하향 꺾임 -> 잔여 전액 매도 (기준가 {format_price(curr_close)} 기록)\n"
            f"• <b>주문 모드</b>: {'실제 주문' if AUTO_TRADE_EXECUTE else '모의/스캔 모드'}"
        )

        save_trade_to_google_sheet(
            ticker=ticker,
            trade_type="매도",
            event_name="SELL (MA5 DOWN)",
            price=curr_close,
            volume=sell_vol,
            amount_krw=sell_amount,
            entry_price=entry_price,
            realized_pnl_krw=realized_pnl,
            return_pct=ret_pct,
            reason=(
                f"5일선 하향 꺾임 잔여 전액 매도 (기준가 {format_price(curr_close)}"
                " 기록)"
            ),
        )

        if AUTO_TRADE_EXECUTE and upbit_client and upbit_client.access_key:
          upbit_client.sell_limit_with_slippage_protection(
              ticker=ticker, volume=sell_vol
          )

  return signals


# ==============================================================================
# [4. 메인 실행 함수 (5분 주기 Crontab 연동)]
# ==============================================================================


def get_upbit_warning_tickers():
  """업비트 실시간 투자 유의/위험 종목(warning=True) 목록 조회"""
  try:
    url = "https://api.upbit.com/v1/market/all?is_details=true"
    res = requests.get(url, timeout=5).json()
    warning_tickers = []
    if isinstance(res, list):
      for item in res:
        market = item.get("market", "")
        if market.startswith("KRW-"):
          market_event = item.get("market_event", {})
          if market_event.get("warning", False):
            warning_tickers.append(market)
    return warning_tickers
  except Exception as e:
    print(f"[경고] 업비트 유의 종목 조회 실패: {e}")
    return []


def run_market_scan():
  """5분마다 실행되어 09:07 스캐너(scan_ref_candles.py)가 공유한 활성 기준봉 종목만 실시간 점검"""
  global_state = load_state()
  client = UpbitClient(UPBIT_ACCESS_KEY, UPBIT_SECRET_KEY)

  sync_google_sheet_daily_snapshot(client)

  warning_tickers = get_upbit_warning_tickers()
  combined_exclude = set(EXCLUDE_TICKERS + warning_tickers)

  # 09:07 스캐너에 의해 기준봉이 포착되었거나(active_ref_date 존재) 매수 포지션이 존재하는 종목 중 제외 코인 빼고 선별
  active_tickers = [
      ticker
      for ticker, st in global_state.items()
      if (st.get("active_ref_date") is not None or st.get("entry_bought", False))
      and ticker not in combined_exclude
  ]

  if TARGET_TICKERS:
    tickers = [t for t in TARGET_TICKERS if t not in combined_exclude]
  else:
    tickers = active_tickers

  now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
  print("\n" + "=" * 80)
  print(
      f" [모니터링] [{now_str}] BST 5분 주기 크론탭 모니터링 (09:07 포착 기준봉 감시 종목:"
      f" {len(tickers)}개)"
  )
  if tickers:
    print(f"  [리스트] 감시 종목 목록: {tickers}")
  else:
    print("  [안내] 현재 포착된 활성 기준봉 종목이 없습니다. (09:07 스캐너 대기 중)")
  print("=" * 80)

  all_signals = []

  for ticker in tickers:
    try:
      df = client.get_daily_ohlcv(ticker, count=CANDLE_COUNT)
      if df is not None and len(df) >= 30:
        signals = process_ticker_strategy(ticker, df, client, global_state)
        if signals:
          all_signals.extend(signals)
      time.sleep(API_DELAY_SEC)
    except Exception as e:
      continue

  save_state(global_state)

  if all_signals:
    print("\n[5분 주기 매매 시그널 발생 내역]")
    for sig in all_signals:
      print(sig)
  else:
    print("\n[모니터링 완료] 특이 신호 없음 (정상 대기 중)")

  print("=" * 80 + "\n")


if __name__ == "__main__":
  run_market_scan()