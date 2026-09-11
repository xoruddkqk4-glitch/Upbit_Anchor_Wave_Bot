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

# 매매 및 실행 모드 설정 (.env의 UPBIT_PAPER_TRADING=False 인 경우 실주문 모드 전환, 기본값 False=스캔/모의 모드)
AUTO_TRADE_EXECUTE = os.getenv("AUTO_TRADE_EXECUTE", "False").lower() in [
    "true",
    "1",
]

# 감시 종목 설정 (None: 업비트 원화 마켓 전체, 또는 특정 종목 지정 ['KRW-BTC', 'KRW-ETH'])
TARGET_TICKERS = None
MAX_TARGET_COUNT = 20  # 업비트 전체 대상일 때 감시할 최대 코인 개수 제한 (20개)

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

# 주문 금액 및 시스템 설정 (최대 매수 금액 100만원)
ORDER_AMOUNT_KRW = 1000000  # 종목당 총 매수 실행 금액 (100만원)
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
            f"• <b>사유</b>: 기준봉 저가({format_price(effective_ref_low)}) 하향 이탈 -> 전량 손절 및 상태 초기화\n"
            f"• <b>주문 모드</b>: {'실제 주문' if AUTO_TRADE_EXECUTE else '모의/스캔 모드'}"
        )

        if AUTO_TRADE_EXECUTE and upbit_client and upbit_client.access_key:
          sell_vol = state["total_volume"] * state["remaining_ratio"]
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

      if AUTO_TRADE_EXECUTE and upbit_client and upbit_client.access_key:
        upbit_client.buy_limit_with_slippage_protection(
            ticker=ticker, amount_krw=ORDER_AMOUNT_KRW
        )

    # [진입 및 3분할 매수 체크]
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

      if is_pullback or is_breakout:
        if not state["entry_bought"]:
          state["entry_bought"] = True
          state["entry_price"] = curr_close
          state["total_volume"] = ORDER_AMOUNT_KRW / curr_close
          state["remaining_ratio"] = 1.0
          state["scale_in_count"] = 1
        else:
          state["scale_in_count"] += 1
          add_volume = (ORDER_AMOUNT_KRW / target_scale_in_steps) / curr_close
          state["total_volume"] += add_volume
          state["entry_price"] = (
              (state["entry_price"] * (state["total_volume"] - add_volume))
              + (curr_close * add_volume)
          ) / state["total_volume"]

        event_name = (
            "BUY (SCALE-IN)" if state["scale_in_count"] > 1 else "BUY"
        )
        signals.append({
            "Ticker": ticker,
            "Event": event_name,
            "Entry_Price": round(state["entry_price"], 2),
        })

        # 텔레그램 매수 알림
        SendMessage(
            f"<b>🔵 [BST 봇] 매수 시그널 발생! ({'분할 매수' if state['scale_in_count'] > 1 else '신규 매수'})</b>\n"
            f"• <b>종목</b>: {ticker}\n"
            f"• <b>체결/진입가</b>: {format_price(curr_close)} (평단가: {format_price(state['entry_price'])})\n"
            f"• <b>매수 단계</b>: {state['scale_in_count']}/{target_scale_in_steps}차 분할 매수\n"
            f"• <b>주문 모드</b>: {'실제 주문' if AUTO_TRADE_EXECUTE else '모의/스캔 모드'}"
        )

        if AUTO_TRADE_EXECUTE and upbit_client and upbit_client.access_key:
          tranche_amount = ORDER_AMOUNT_KRW / target_scale_in_steps
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
            f"• <b>사유</b>: 파동 시간/가격 대칭 목표 달성 (보유 수량 50% 익절)\n"
            f"• <b>주문 모드</b>: {'실제 주문' if AUTO_TRADE_EXECUTE else '모의/스캔 모드'}"
        )

        if AUTO_TRADE_EXECUTE and upbit_client and upbit_client.access_key:
          upbit_client.sell_limit_with_slippage_protection(
              ticker=ticker, volume=sell_vol
          )

      # B. 5일선 꺾임(하향 이탈) 체크 -> 잔여 전액 매도 후 기준 가격 기록
      if curr_ma5 < prev_ma5:
        sell_vol = state["total_volume"] * state["remaining_ratio"]
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
            f"• <b>사유</b>: 5일선 하향 꺾임 -> 잔여 전액 매도 (기준가 {format_price(curr_close)} 기록)\n"
            f"• <b>주문 모드</b>: {'실제 주문' if AUTO_TRADE_EXECUTE else '모의/스캔 모드'}"
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