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
FILL_TOLERANCE = 1e-6  # 완전 체결로 간주할 잔량 허용 오차 (부동소수점 보정)

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
BREAKOUT_MAX_LOSS_PCT = 0.05  # 돌파 진입 손절선 상한: 직전 확정봉 저가가 이보다 멀면 진입가 -5%로 제한 (전액 포지션 단일 최대 손실 통제)

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
          holdings = []
          for b in balances:
            curr = b.get("currency", "")
            bal = float(b.get("balance", 0.0)) + float(b.get("locked", 0.0))
            if curr == "KRW":
              krw_balance = bal
            elif bal > 0:
              holdings.append((curr, bal, float(b.get("avg_buy_price", 0.0))))

          # 평가금은 매입원가가 아닌 실시간 시세 기준으로 산정
          prices = upbit_client.get_current_prices(
              [f"KRW-{curr}" for curr, _, _ in holdings]
          )
          for curr, bal, avg_p in holdings:
            # 시세 조회 실패 종목(상장폐지 등)은 매입원가로 폴백
            coin_eval += bal * prices.get(f"KRW-{curr}", avg_p)
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

  def get_balances(self):
    """전체 계좌 잔고 조회"""
    url = f"{self.server_url}/accounts"
    res = requests.get(url, headers=self._get_headers(), timeout=5).json()
    return res if isinstance(res, list) else []

  def get_current_prices(self, markets):
    """복수 마켓 현재가 일괄 조회 -> {market: trade_price}"""
    markets = [m for m in markets if m]
    if not markets:
      return {}
    url = f"{self.server_url}/ticker"
    res = requests.get(
        url, params={"markets": ",".join(markets)}, timeout=5
    ).json()
    if not isinstance(res, list):
      return {}
    return {
        item["market"]: float(item["trade_price"])
        for item in res
        if item.get("market") and item.get("trade_price") is not None
    }

  def get_orderbook(self, ticker):
    """현재 호가창 조회"""
    url = f"{self.server_url}/orderbook?markets={ticker}"
    res = requests.get(url, timeout=5).json()
    if isinstance(res, list) and len(res) > 0:
      return res[0]["orderbook_units"]
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

  @staticmethod
  def _infer_tick_size(units):
    """호가창의 인접 호가 간격에서 실제 호가단위(틱)를 역산

    호가단위 표를 하드코딩하면 업비트 정책 변경 시 어긋나므로, 항상 유효한
    틱 배수인 호가창 가격들의 최소 간격에서 틱을 역산한다.
    """
    prices = sorted({
        float(u[k])
        for u in units
        for k in ("bid_price", "ask_price")
        if u.get(k) is not None
    })
    gaps = [round(b - a, 10) for a, b in zip(prices, prices[1:]) if b > a]
    return min(gaps) if gaps else None

  @staticmethod
  def _format_price_param(price):
    """1원 미만 코인까지 지수표기 없이 주문 파라미터 문자열로 변환"""
    return f"{price:.8f}".rstrip("0").rstrip(".")

  def _apply_slippage(self, units, key, slippage_pct, is_buy):
    """최우선호가 기준 틱의 정수배만큼 이동한 유효 지정가 산출"""
    best_price = float(units[0][key])
    tick = self._infer_tick_size(units)
    if not tick:
      return best_price
    steps = int((best_price * slippage_pct) // tick)
    offset = steps * tick if is_buy else -steps * tick
    return round(best_price + offset, 8)

  def _summarize_fill(self, order_uuid, fallback_price):
    """주문 UUID 기준 실제 체결 수량 / 평균 체결가 집계"""
    empty = {
        "ok": False,
        "price": fallback_price,
        "volume": 0.0,
        "amount": 0.0,
        "uuid": order_uuid,
    }
    if not order_uuid:
      return empty

    try:
      info = self.get_order_status(order_uuid)
    except Exception as e:
      print(f"[오류] 체결 내역 조회 실패 ({order_uuid}): {e}")
      return empty

    if not isinstance(info, dict):
      return empty

    executed = float(info.get("executed_volume", 0.0) or 0.0)
    if executed <= 0:
      return empty

    funds = 0.0
    for t in info.get("trades") or []:
      trade_funds = t.get("funds")
      if trade_funds is None:
        trade_funds = float(t.get("price", 0.0) or 0.0) * float(
            t.get("volume", 0.0) or 0.0
        )
      funds += float(trade_funds or 0.0)

    avg_price = funds / executed if funds > 0 else fallback_price
    return {
        "ok": True,
        "price": avg_price,
        "volume": executed,
        "amount": funds if funds > 0 else avg_price * executed,
        "uuid": order_uuid,
    }

  def buy_limit_with_slippage_protection(
      self, ticker, amount_krw, max_slippage_pct=0.005, wait_sec=3
  ):
    """슬리피지 제어형 지정가 매수 + 미체결 자동 취소 (실제 체결 결과 반환)"""
    if not self.access_key or not self.secret_key:
      print(
          f"[알림] API Key 미설정으로 {ticker} 지정가 매수 주문 생략 (금액:"
          f" {amount_krw:,}원)"
      )
      return None

    ob = self.get_orderbook(ticker)
    if not ob:
      return None

    limit_price = self._apply_slippage(ob, "ask_price", max_slippage_pct, True)
    if limit_price <= 0:
      print(f"[오류] {ticker} 유효하지 않은 지정가({limit_price}) 산출 -> 주문 생략")
      return None
    volume = round(amount_krw / limit_price, 8)

    url = f"{self.server_url}/orders"
    params = {
        "market": ticker,
        "side": "bid",
        "volume": str(volume),
        "price": self._format_price_param(limit_price),
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
      return self._summarize_fill(None, limit_price)

    if wait_sec > 0:
      time.sleep(wait_sec)
      order_info = self.get_order_status(order_uuid)
      state = order_info.get("state")
      remaining_vol = float(order_info.get("remaining_volume", 0) or 0)

      if state in ["wait", "watch"] and remaining_vol > 0:
        print(f" └ [미체결 감지] 미체결 잔량({remaining_vol}) 존재 -> 취소 진행")
        self.cancel_order(order_uuid)

    # 취소 반영 후 실제 체결분만 집계 (부분 체결 포함)
    return self._summarize_fill(order_uuid, limit_price)

  def sell_limit_with_slippage_protection(
      self, ticker, volume, max_slippage_pct=0.005, wait_sec=3
  ):
    """슬리피지 제어형 지정가 매도 + 미체결 자동 취소 (실제 체결 결과 반환)"""
    if not self.access_key or not self.secret_key:
      print(
          f"[알림] API Key 미설정으로 {ticker} 지정가 매도 주문 생략 (수량:"
          f" {volume})"
      )
      return None

    ob = self.get_orderbook(ticker)
    if not ob:
      return None

    limit_price = self._apply_slippage(ob, "bid_price", max_slippage_pct, False)
    if limit_price <= 0:
      print(f"[오류] {ticker} 유효하지 않은 지정가({limit_price}) 산출 -> 주문 생략")
      return None

    url = f"{self.server_url}/orders"
    params = {
        "market": ticker,
        "side": "ask",
        "volume": str(volume),
        "price": self._format_price_param(limit_price),
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
      return self._summarize_fill(None, limit_price)

    if wait_sec > 0:
      time.sleep(wait_sec)
      order_info = self.get_order_status(order_uuid)
      state = order_info.get("state")
      remaining_vol = float(order_info.get("remaining_volume", 0) or 0)

      if state in ["wait", "watch"] and remaining_vol > 0:
        print(f" └ [미체결 감지] 미체결 잔량({remaining_vol}) 존재 -> 취소 진행")
        self.cancel_order(order_uuid)

    # 취소 반영 후 실제 체결분만 집계 (부분 체결 포함)
    return self._summarize_fill(order_uuid, limit_price)


def execute_buy(upbit_client, ticker, amount_krw, fallback_price):
  """매수 집행 후 실제 체결 결과 반환 (모의/스캔 모드면 이론 체결값)

  ok=False는 '체결 0'을 뜻하므로, 호출부는 상태를 변경하지 않고 건너뛴다.
  """
  if not (AUTO_TRADE_EXECUTE and upbit_client and upbit_client.access_key):
    return {
        "ok": True,
        "price": fallback_price,
        "volume": amount_krw / fallback_price,
        "amount": amount_krw,
    }

  fill = upbit_client.buy_limit_with_slippage_protection(
      ticker=ticker, amount_krw=amount_krw
  )
  if not fill or not fill.get("ok"):
    print(f"[미체결] {ticker} 매수 체결 수량 0 -> 포지션 상태 변경 생략")
    return {"ok": False, "price": fallback_price, "volume": 0.0, "amount": 0.0}
  return fill


def execute_sell(upbit_client, ticker, volume, fallback_price):
  """매도 집행 후 실제 체결 결과 반환 (모의/스캔 모드면 이론 체결값)"""
  if not (AUTO_TRADE_EXECUTE and upbit_client and upbit_client.access_key):
    return {
        "ok": True,
        "price": fallback_price,
        "volume": volume,
        "amount": fallback_price * volume,
    }

  fill = upbit_client.sell_limit_with_slippage_protection(
      ticker=ticker, volume=volume
  )
  if not fill or not fill.get("ok"):
    print(f"[미체결] {ticker} 매도 체결 수량 0 -> 포지션 상태 변경 생략")
    return {"ok": False, "price": fallback_price, "volume": 0.0, "amount": 0.0}
  return fill


def calc_breakout_stop(confirmed_low, entry_price, current_stop):
  """돌파 진입 손절선 산출 -> (손절가, 산출 근거)

  기본은 직전 확정봉(돌파를 확정한 마감 일봉) 저가. 아래서 치고 올라온 장대 돌파봉은
  저가가 지나치게 멀 수 있어 진입가 대비 BREAKOUT_MAX_LOSS_PCT를 상한으로 둔다.
  손절선은 위로만 이동하므로 기존 손절선보다 낮아지지는 않는다.
  """
  cap = entry_price * (1 - BREAKOUT_MAX_LOSS_PCT)
  if cap > confirmed_low:
    stop, basis = cap, f"진입가 -{BREAKOUT_MAX_LOSS_PCT:.0%} 상한 적용"
  else:
    stop, basis = confirmed_low, "직전 확정봉 저가"
  if current_stop > stop:
    stop, basis = current_stop, "기존 손절선 유지"
  return stop, basis


def build_partial_fill_note(target_volume, filled_volume):
  """부분 체결 시 알림 메시지에 덧붙일 안내 문구 (완전 체결이면 빈 문자열)"""
  if filled_volume >= target_volume * (1 - FILL_TOLERANCE):
    return ""
  return (
      f"\n• <b>부분 체결</b>: 목표 {target_volume:.8f} 중 {filled_volume:.8f}"
      " 체결 (잔여 수량은 다음 주기 재시도)"
  )


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


def process_ticker_strategy(ticker, df, upbit_client, global_state, allow_entry=True):
  """개선된 BST 전략을 반영한 단일 종목 실시간 모니터링 및 매매 집행

  allow_entry=False면 신규 진입·분할 추가·재매수 등 모든 매수 분기를 건너뛰고
  손절·대칭 익절·5일선 매도 등 매도 감시만 수행한다 (유의종목 등 제외 종목의 보유 포지션용).
  """
  df = detect_reference_candles(df)

  if ticker not in global_state:
    global_state[ticker] = {
        "active_ref_date": None,
        "entry_bought": False,
        "entry_date": None,
        "entry_price": 0.0,
        "total_volume": 0.0,
        "remaining_ratio": 1.0,
        "symmetry_tp_executed": False,
        "scale_in_count": 0,
        "last_scale_in_date": None,
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
  # 진행 중인 일봉의 기준일(업비트 09:00 KST 마감 기준). 분할 매수 1일 1회 제한에 사용
  curr_candle_date = curr_row.name.strftime("%Y-%m-%d")

  # 마감 확정된 전일 일봉 (09:00 마감 완결 캔들 - 스윙/휩소 방지용)
  confirmed_row = df.iloc[-2] if len(df) >= 2 else curr_row
  confirmed_close = confirmed_row["close"]
  confirmed_open = confirmed_row["open"]
  confirmed_low = confirmed_row["low"]
  confirmed_candle_date = confirmed_row.name.strftime("%Y-%m-%d")

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
      ref_mid = effective_ref_low + (ref_high - effective_ref_low) * PULLBACK_RATIO

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
        target_vol = state["total_volume"] * state["remaining_ratio"]
        fill = execute_sell(upbit_client, ticker, target_vol, curr_close)
        if not fill["ok"]:
          # 체결 0 -> 포지션을 그대로 유지한 채 다음 주기에 손절 재시도
          return signals

        sell_vol = fill["volume"]
        sell_price = fill["price"]
        sell_amount = fill["amount"]
        buy_cost = state["entry_price"] * sell_vol
        realized_pnl = sell_amount - buy_cost
        ret_pct = (
            (sell_price - state["entry_price"]) / state["entry_price"]
            if state["entry_price"] > 0
            else 0.0
        )
        fill_note = build_partial_fill_note(target_vol, sell_vol)

        signals.append({
            "Ticker": ticker,
            "Event": "SELL (STOP LOSS)",
            "Price": sell_price,
            "Reason": "기준봉 손절가(마진노선) 이탈 -> 기준 가격 데이터 초기화",
        })

        # 텔레그램 손절 매도 알림
        SendMessage(
            f"<b>🔴 [BST 봇] 손절 매도! (STOP LOSS)</b>\n"
            f"• <b>종목</b>: {ticker}\n"
            f"• <b>매도가</b>: {format_price(sell_price)}\n"
            f"• <b>실현손익</b>: <b>{realized_pnl:+,.0f}원 ({ret_pct*100:+.2f}%)</b>\n"
            f"• <b>사유</b>: 기준봉 저가({format_price(effective_ref_low)}) 하향 이탈 -> 전량 손절 및 상태 초기화"
            f"{fill_note}\n"
            f"• <b>주문 모드</b>: {'실제 주문' if AUTO_TRADE_EXECUTE else '모의/스캔 모드'}"
        )

        save_trade_to_google_sheet(
            ticker=ticker,
            trade_type="매도",
            event_name="SELL (STOP LOSS)",
            price=sell_price,
            volume=sell_vol,
            amount_krw=sell_amount,
            entry_price=state["entry_price"],
            realized_pnl_krw=realized_pnl,
            return_pct=ret_pct,
            reason=f"기준봉 저가({format_price(effective_ref_low)}) 하향 이탈 전량 손절",
        )

        if fill_note:
          # 부분 체결 -> 잔여 수량만 남기고 다음 주기에 손절 재시도 (상태 초기화 금지)
          state["remaining_ratio"] = (
              max(target_vol - sell_vol, 0.0) / state["total_volume"]
          )
          return signals

      global_state[ticker] = {
          "active_ref_date": None,
          "entry_bought": False,
          "entry_date": None,
          "entry_price": 0.0,
          "total_volume": 0.0,
          "remaining_ratio": 1.0,
          "symmetry_tp_executed": False,
          "scale_in_count": 0,
          "last_scale_in_date": None,
          "base_price": None,
          "ref_high": 0.0,
          "effective_ref_low": 0.0,
          "ref_mid": 0.0,
          "rise_duration": 0,
          "wave_height": 0.0,
      }
      return signals

    target_scale_in_steps = 3 if ENABLE_SCALE_IN_BUY else 1

    # [재매수 체크] 5일선 꺾여 기록된 기준 가격 현재가 상향 돌파 + 5일선 상승 전환(curr_ma5 >= prev_ma5) 동시 확인 시 재매수
    if (
        allow_entry
        and state["base_price"] is not None
        and curr_close > state["base_price"]
        and curr_ma5 >= prev_ma5
        and state["remaining_ratio"] == 0
    ):
      fill = execute_buy(upbit_client, ticker, ORDER_AMOUNT_KRW, curr_close)
      # 체결 0이면 기준가(base_price)를 유지해 다음 주기에 재매수 재시도
      if fill["ok"]:
        entry_price = fill["price"]
        total_volume = fill["volume"]
        state["entry_bought"] = True
        state["entry_price"] = entry_price
        state["total_volume"] = total_volume
        state["remaining_ratio"] = 1.0
        state["symmetry_tp_executed"] = False
        state["entry_date"] = curr_candle_date  # 2차 파동 기점 (기간 대칭 기준일)
        # 최대 금액 전액 재매수이므로 분할 매수 회차를 만수로 채워 추가 매수 분기를 닫는다.
        # (이전 사이클이 1/3만 진입한 채 5일선에 팔린 경우, 재매수 후 눌림목 조건에 걸리면
        #  2/3가 더 들어가 133만원이 되는 과매수 경로 차단). 이후는 매도 로직만 동작.
        state["scale_in_count"] = target_scale_in_steps
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
            f"• <b>매수 금액</b>: {fill['amount']:,.0f}원 재매수\n"
            f"• <b>주문 모드</b>: {'실제 주문' if AUTO_TRADE_EXECUTE else '모의/스캔 모드'}"
        )

        save_trade_to_google_sheet(
            ticker=ticker,
            trade_type="매수",
            event_name="BUY (RE-ENTRY)",
            price=entry_price,
            volume=total_volume,
            amount_krw=fill["amount"],
            entry_price=entry_price,
            reason=(
                f"이전 매도 기준가({format_price(triggered_base_price)}) 상향 돌파"
                " & 5일선 상승 전환 재매수"
            ),
        )

    # [진입 및 매수 체크] (allow_entry=False면 매도 감시만 수행하므로 전체 건너뜀)
    if allow_entry and (
        not state["entry_bought"]
        or (
            ENABLE_SCALE_IN_BUY
            and state["scale_in_count"] < target_scale_in_steps
            and state["remaining_ratio"] > 0
        )
    ):
      is_pullback = False
      if ENABLE_PULLBACK_ENTRY:
        # 마감 확정일봉(09:00 마감) 기준: 중심가 이하 저가 터치 후 확실한 양봉 마감 시 매수
        price_cond = confirmed_low <= ref_mid
        rebound_cond = (
            (confirmed_close > confirmed_open) if REQUIRE_BULLISH_REBOUND else True
        )
        # 확정봉이 기준봉 자신이면(기준일 다음 날) 저가<=중심가·양봉 조건이 항상 성립하므로,
        # 기준봉 '이후'에 마감한 봉만 눌림목 후보로 인정한다 (기준일 당일 자기 일치 차단)
        after_ref_cond = confirmed_candle_date > state["active_ref_date"]
        is_pullback = price_cond and rebound_cond and after_ref_cond

      # 눌림목 조건은 마감 확정일봉 기준이라 하루 종일 값이 고정된다.
      # 가드가 없으면 5분 주기마다 재평가되어 같은 날 3회차까지 연속 체결되므로,
      # 분할 매수는 일봉 기준일당 1회로 제한한다 (체결 성공 시에만 날짜 기록).
      can_scale_in_today = state.get("last_scale_in_date") != curr_candle_date

      is_breakout = False
      if ENABLE_BREAKOUT_ENTRY:
        # 마감 확정일봉(09:00 마감) 종가가 기준봉 고가를 완벽히 상향 돌파하며 마감 시 매수 (장중 윗꼬리 휩소 차단)
        # + 현재가도 고가 위에 있어야 함: 어제 돌파했어도 오늘 갭하락으로 반납했으면 이미 실패한 돌파이며,
        #   진입가가 새 손절선 아래에 놓여 매수 직후 손절되는 경로를 차단
        is_breakout = confirmed_close > ref_high and curr_close > ref_high

      # A. 신규 진입 (포지션 미보유 상태)
      if not state["entry_bought"]:
        if is_breakout:
          # 1) 돌파 매매: 3분할이 아닌 100만원 전액 즉시 매수 + 손절가를 직전 확정봉 저가(상한 적용)로 상향 재조정
          fill = execute_buy(upbit_client, ticker, ORDER_AMOUNT_KRW, curr_close)
          if fill["ok"]:
            state["entry_bought"] = True
            state["entry_price"] = fill["price"]
            state["total_volume"] = fill["volume"]
            state["remaining_ratio"] = 1.0
            state["scale_in_count"] = target_scale_in_steps  # 전액 매수 완료 처리
            state["entry_date"] = curr_candle_date  # 2차 파동 기점 (기간 대칭 기준일)
            prev_low = state["effective_ref_low"]
            new_stop, stop_basis = calc_breakout_stop(
                confirmed_low, fill["price"], prev_low
            )
            state["effective_ref_low"] = new_stop

            signals.append({
                "Ticker": ticker,
                "Event": "BUY (BREAKOUT ALL-IN)",
                "Entry_Price": round(fill["price"], 2),
                "Stop_Loss_Adjusted": new_stop,
            })

            SendMessage(
                f"<b>🚀 [BST 봇] 돌파 매수 발생! (BREAKOUT ALL-IN)</b>\n"
                f"• <b>종목</b>: {ticker}\n"
                f"• <b>체결/진입가</b>: {format_price(fill['price'])}\n"
                f"• <b>매수 금액</b>: {fill['amount']:,.0f}원 (100% 전액 매수)\n"
                f"• <b>손절선 재조정</b>: {format_price(prev_low)} ➔ <b>{format_price(new_stop)}</b> ({stop_basis})\n"
                f"• <b>주문 모드</b>: {'실제 주문' if AUTO_TRADE_EXECUTE else '모의/스캔 모드'}"
            )

            save_trade_to_google_sheet(
                ticker=ticker,
                trade_type="매수",
                event_name="BUY (BREAKOUT ALL-IN)",
                price=fill["price"],
                volume=fill["volume"],
                amount_krw=fill["amount"],
                entry_price=fill["price"],
                reason="마감확정일봉 기준봉 고가 완벽 상향 돌파 100% 전액 매수",
            )

        elif is_pullback:
          # 2) 눌림목 매매: 1차 분할 매수 진행 (1/3 금액)
          tranche_amount = ORDER_AMOUNT_KRW / target_scale_in_steps
          fill = execute_buy(upbit_client, ticker, tranche_amount, curr_close)
          if fill["ok"]:
            state["entry_bought"] = True
            state["entry_price"] = fill["price"]
            state["total_volume"] = fill["volume"]
            state["remaining_ratio"] = 1.0
            state["scale_in_count"] = 1
            state["last_scale_in_date"] = curr_candle_date  # 1일 1회 분할 매수 제한
            state["entry_date"] = curr_candle_date  # 2차 파동 기점 (기간 대칭 기준일, 추가 매수 시 유지)

            signals.append({
                "Ticker": ticker,
                "Event": "BUY (PULLBACK 1/3)",
                "Entry_Price": round(fill["price"], 2),
            })

            SendMessage(
                f"<b>🔵 [BST 봇] 눌림목 매수 시그널 발생! (1/{target_scale_in_steps}차 분할 매수)</b>\n"
                f"• <b>종목</b>: {ticker}\n"
                f"• <b>체결/진입가</b>: {format_price(fill['price'])}\n"
                f"• <b>매수 금액</b>: {fill['amount']:,.0f}원 (1차 매수)\n"
                f"• <b>주문 모드</b>: {'실제 주문' if AUTO_TRADE_EXECUTE else '모의/스캔 모드'}"
            )

            save_trade_to_google_sheet(
                ticker=ticker,
                trade_type="매수",
                event_name=f"BUY (PULLBACK 1/{target_scale_in_steps})",
                price=fill["price"],
                volume=fill["volume"],
                amount_krw=fill["amount"],
                entry_price=fill["price"],
                reason=(
                    "마감확정일봉 기준 중심가 이하 저가 터치 후 양봉 반등"
                    f" 1/{target_scale_in_steps}차 분할 매수"
                ),
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
          fill = execute_buy(upbit_client, ticker, remaining_amount, curr_close)
          if fill["ok"]:
            add_volume = fill["volume"]
            old_volume = state["total_volume"]

            state["entry_price"] = (
                (state["entry_price"] * old_volume)
                + (fill["price"] * add_volume)
            ) / (old_volume + add_volume)
            state["total_volume"] += add_volume
            state["scale_in_count"] = target_scale_in_steps
            prev_low = state["effective_ref_low"]
            # 손실 상한은 잔액 매수 반영 후의 평단가 기준으로 산출 (포지션 전체에 적용되는 손절선)
            new_stop, stop_basis = calc_breakout_stop(
                confirmed_low, state["entry_price"], prev_low
            )
            state["effective_ref_low"] = new_stop

            signals.append({
                "Ticker": ticker,
                "Event": "BUY (BREAKOUT FULL SCALE-IN)",
                "Entry_Price": round(state["entry_price"], 2),
                "Stop_Loss_Adjusted": new_stop,
            })

            SendMessage(
                f"<b>🚀 [BST 봇] 고가 돌파 시그널! 남은 잔액 전액 매수 (BREAKOUT ALL-IN)</b>\n"
                f"• <b>종목</b>: {ticker}\n"
                f"• <b>체결가</b>: {format_price(fill['price'])} (평단가: {format_price(state['entry_price'])})\n"
                f"• <b>매수 잔액</b>: {fill['amount']:,.0f}원 (남은 금액 집행 ➔ 3/{target_scale_in_steps}차 완료)\n"
                f"• <b>손절선 재조정</b>: {format_price(prev_low)} ➔ <b>{format_price(new_stop)}</b> ({stop_basis})\n"
                f"• <b>주문 모드</b>: {'실제 주문' if AUTO_TRADE_EXECUTE else '모의/스캔 모드'}"
            )

            save_trade_to_google_sheet(
                ticker=ticker,
                trade_type="매수",
                event_name="BUY (BREAKOUT FULL SCALE-IN)",
                price=fill["price"],
                volume=add_volume,
                amount_krw=fill["amount"],
                entry_price=state["entry_price"],
                reason="눌림목 진행 중 마감확정일봉 고가 돌파 잔액 전액 매수",
            )

        elif is_pullback and can_scale_in_today:
          # 2) 순수 추가 눌림목 조건 만족 시: 1/3 금액만큼 다음 회차 분할 매수 진행
          # (같은 확정봉 기준으로 하루 내내 조건이 유지되므로, 1일 1회로 제한해
          #  5분 주기마다 연속 체결되는 것을 방지)
          tranche_amount = ORDER_AMOUNT_KRW / target_scale_in_steps
          fill = execute_buy(upbit_client, ticker, tranche_amount, curr_close)
          if fill["ok"]:
            state["scale_in_count"] += 1
            state["last_scale_in_date"] = curr_candle_date
            add_volume = fill["volume"]
            old_volume = state["total_volume"]

            state["entry_price"] = (
                (state["entry_price"] * old_volume)
                + (fill["price"] * add_volume)
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
                f"• <b>체결가</b>: {format_price(fill['price'])} (평단가: {format_price(state['entry_price'])})\n"
                f"• <b>매수 금액</b>: {fill['amount']:,.0f}원\n"
                f"• <b>주문 모드</b>: {'실제 주문' if AUTO_TRADE_EXECUTE else '모의/스캔 모드'}"
            )

            save_trade_to_google_sheet(
                ticker=ticker,
                trade_type="매수",
                event_name=f"BUY (PULLBACK {state['scale_in_count']}/{target_scale_in_steps})",
                price=fill["price"],
                volume=add_volume,
                amount_krw=fill["amount"],
                entry_price=state["entry_price"],
                reason=(
                    "마감확정일봉 눌림목 반등 추가"
                    f" {state['scale_in_count']}/{target_scale_in_steps}차 분할 매수"
                ),
            )

    # [매도 및 5일선 관리 체크]
    if state["entry_bought"] and state["remaining_ratio"] > 0:
      entry_price = state["entry_price"]
      current_return = (curr_close - entry_price) / entry_price

      # A. 대칭이론 조건 만족 시 보유량의 50% 익절
      #    1차 파동(스윙 저점 -> 기준봉 고가)의 높이(wave_height)와 기간(rise_duration)을
      #    2차 파동(진입 이후)에 그대로 투영한다. 둘 중 먼저 도달하는 조건에서 익절하며,
      #    MIN_TAKE_PROFIT_PCT는 공통 하한(손실 상태에서 시간만 지났다고 팔지 않도록).
      if not state.get("entry_date"):
        # 구버전 상태 파일 호환: 진입일 미기록 포지션은 현재 일봉부터 기간 카운트 시작
        state["entry_date"] = curr_candle_date
      days_since_entry = (
          pd.Timestamp(curr_candle_date) - pd.Timestamp(state["entry_date"])
      ).days
      # 허용오차만큼 앞당겨 발동 가능하되, 진입 당일(0일) 발동은 배제
      time_target_days = max(rise_duration - TIME_SYMMETRY_TOLERANCE_DAYS, 1)
      price_target = entry_price + wave_height

      is_time_symmetric_exit = (
          USE_TIME_SYMMETRY_EXIT
          and days_since_entry >= time_target_days
          and current_return >= MIN_TAKE_PROFIT_PCT
      )
      is_price_symmetric_exit = (
          USE_PRICE_SYMMETRY_EXIT
          and curr_close >= price_target
          and current_return >= MIN_TAKE_PROFIT_PCT
      )
      if is_price_symmetric_exit:
        symmetry_reason = (
            f"가격 대칭 달성: 1차 파동 높이 {format_price(wave_height)} 투영 목표가"
            f" {format_price(price_target)} 도달"
        )
      elif is_time_symmetric_exit:
        symmetry_reason = (
            f"기간 대칭 달성: 1차 파동 {rise_duration}일 대비 진입 후"
            f" {days_since_entry}일 경과 (허용오차 ±{TIME_SYMMETRY_TOLERANCE_DAYS}일)"
        )
      else:
        symmetry_reason = ""

      if (
          is_time_symmetric_exit or is_price_symmetric_exit
      ) and not state["symmetry_tp_executed"]:
        target_vol = state["total_volume"] * 0.5
        fill = execute_sell(upbit_client, ticker, target_vol, curr_close)
        if fill["ok"]:
          # 부분 체결이어도 익절 이벤트는 1회로 확정 (재진입 시 초과 매도 방지)
          state["symmetry_tp_executed"] = True
          sell_vol = fill["volume"]
          sell_price = fill["price"]
          sell_amount = fill["amount"]
          held_vol = state["total_volume"] * state["remaining_ratio"]
          state["remaining_ratio"] = (
              max(held_vol - sell_vol, 0.0) / state["total_volume"]
          )
          buy_cost = entry_price * sell_vol
          realized_pnl = sell_amount - buy_cost
          realized_return = (
              (sell_price - entry_price) / entry_price if entry_price > 0 else 0.0
          )
          fill_note = build_partial_fill_note(target_vol, sell_vol)

          signals.append({
              "Ticker": ticker,
              "Event": "PARTIAL SELL (SYMMETRY 50%)",
              "Return(%)": round(realized_return * 100, 2),
              "Reason": f"{symmetry_reason} -> 50% 익절 완료",
          })

          # 텔레그램 50% 분할 익절 알림
          SendMessage(
              f"<b>🟢 [BST 봇] 50% 분할 익절! (PARTIAL SELL)</b>\n"
              f"• <b>종목</b>: {ticker}\n"
              f"• <b>매도가</b>: {format_price(sell_price)}\n"
              f"• <b>수익률</b>: <b>{realized_return * 100:+.2f}%</b>\n"
              f"• <b>실현손익</b>: <b>{realized_pnl:+,.0f}원</b>\n"
              f"• <b>사유</b>: {symmetry_reason} (보유 수량 50% 익절)\n"
              f"• <b>대칭 목표</b>: 가격 {format_price(price_target)} / 기간 {rise_duration}일 (진입 후 {days_since_entry}일 경과)"
              f"{fill_note}\n"
              f"• <b>주문 모드</b>: {'실제 주문' if AUTO_TRADE_EXECUTE else '모의/스캔 모드'}"
          )

          save_trade_to_google_sheet(
              ticker=ticker,
              trade_type="매도",
              event_name="PARTIAL SELL (SYMMETRY 50%)",
              price=sell_price,
              volume=sell_vol,
              amount_krw=sell_amount,
              entry_price=entry_price,
              realized_pnl_krw=realized_pnl,
              return_pct=realized_return,
              reason=f"{symmetry_reason} (보유 수량 50% 익절)",
          )

      # B. 5일선 꺾임(하향 이탈) 체크 -> 잔여 전액 매도 후 기준 가격 기록
      if curr_ma5 < prev_ma5:
        target_vol = state["total_volume"] * state["remaining_ratio"]
        fill = execute_sell(upbit_client, ticker, target_vol, curr_close)
        if fill["ok"]:
          sell_vol = fill["volume"]
          sell_price = fill["price"]
          sell_amount = fill["amount"]
          buy_cost = entry_price * sell_vol
          realized_pnl = sell_amount - buy_cost
          ret_pct = (
              (sell_price - entry_price) / entry_price if entry_price > 0 else 0.0
          )
          fill_note = build_partial_fill_note(target_vol, sell_vol)

          state["remaining_ratio"] = (
              max(target_vol - sell_vol, 0.0) / state["total_volume"]
              if state["total_volume"] > 0
              else 0.0
          )
          # 완전 청산된 경우에만 재매수 기준가를 확정 기록
          if not fill_note:
            state["base_price"] = sell_price

          signals.append({
              "Ticker": ticker,
              "Event": "SELL (MA5 DOWN)",
              "Price": sell_price,
              "Reason": f"5일선 꺾임 전액 매도 -> 기준 가격 기록: {sell_price}",
          })

          # 텔레그램 5일선 추세 매도 알림
          SendMessage(
              f"<b>🟡 [BST 봇] 추세 매도! (MA5 DOWN)</b>\n"
              f"• <b>종목</b>: {ticker}\n"
              f"• <b>매도가</b>: {format_price(sell_price)}\n"
              f"• <b>수익률</b>: <b>{ret_pct * 100:+.2f}%</b>\n"
              f"• <b>실현손익</b>: <b>{realized_pnl:+,.0f}원</b>\n"
              f"• <b>사유</b>: 5일선 하향 꺾임 -> 잔여 전액 매도 (기준가 {format_price(sell_price)} 기록)"
              f"{fill_note}\n"
              f"• <b>주문 모드</b>: {'실제 주문' if AUTO_TRADE_EXECUTE else '모의/스캔 모드'}"
          )

          save_trade_to_google_sheet(
              ticker=ticker,
              trade_type="매도",
              event_name="SELL (MA5 DOWN)",
              price=sell_price,
              volume=sell_vol,
              amount_krw=sell_amount,
              entry_price=entry_price,
              realized_pnl_krw=realized_pnl,
              return_pct=ret_pct,
              reason=(
                  f"5일선 하향 꺾임 잔여 전액 매도 (기준가 {format_price(sell_price)}"
                  " 기록)"
              ),
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


def select_monitor_tickers(global_state, combined_exclude):
  """감시 대상 선별 -> (감시 종목 목록, 매도 감시만 수행할 보유 제외 종목 목록)

  제외 종목(유의종목·EXCLUDE_TICKERS)은 신규 진입 대상에서 빼되, 이미 보유 중인 포지션은
  손절·대칭·5일선 매도 감시가 끊기지 않도록 목록에 유지한다. 유의종목 지정은 보통 급등락
  직후라, 이때 감시가 멈추면 가장 위험한 순간에 포지션이 방치된다.
  (매수 분기는 호출부에서 allow_entry=False로 차단)
  """
  held_excluded = [
      t
      for t, st in global_state.items()
      if st.get("entry_bought", False)
      and st.get("remaining_ratio", 0) > 0
      and t in combined_exclude
  ]
  if TARGET_TICKERS:
    base = [t for t in TARGET_TICKERS if t not in combined_exclude]
  else:
    base = [
        t
        for t, st in global_state.items()
        if (st.get("active_ref_date") is not None or st.get("entry_bought", False))
        and t not in combined_exclude
    ]
  tickers = base + [t for t in held_excluded if t not in base]
  return tickers, held_excluded


def run_market_scan():
  """5분마다 실행되어 09:07 스캐너(scan_ref_candles.py)가 공유한 활성 기준봉 종목만 실시간 점검"""
  global_state = load_state()
  client = UpbitClient(UPBIT_ACCESS_KEY, UPBIT_SECRET_KEY)

  sync_google_sheet_daily_snapshot(client)

  warning_tickers = get_upbit_warning_tickers()
  combined_exclude = set(EXCLUDE_TICKERS + warning_tickers)

  # 09:07 스캐너에 의해 기준봉이 포착되었거나(active_ref_date 존재) 매수 포지션이 존재하는 종목 중 제외 코인 빼고 선별
  tickers, held_excluded = select_monitor_tickers(global_state, combined_exclude)

  now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
  print("\n" + "=" * 80)
  print(
      f" [모니터링] [{now_str}] BST 5분 주기 크론탭 모니터링 (09:07 포착 기준봉 감시 종목:"
      f" {len(tickers)}개)"
  )
  if tickers:
    print(f"  [리스트] 감시 종목 목록: {tickers}")
    if held_excluded:
      print(
          "  [매도 감시만] 제외/유의 종목 보유 중 -> 신규·추가·재매수 차단, 매도만 감시:"
          f" {held_excluded}"
      )
  else:
    print("  [안내] 현재 포착된 활성 기준봉 종목이 없습니다. (09:07 스캐너 대기 중)")
  print("=" * 80)

  all_signals = []

  for ticker in tickers:
    try:
      df = client.get_daily_ohlcv(ticker, count=CANDLE_COUNT)
      if df is not None and len(df) >= 30:
        signals = process_ticker_strategy(
            ticker,
            df,
            client,
            global_state,
            allow_entry=ticker not in combined_exclude,
        )
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