import datetime
import hashlib
import json
import os
import time
import urllib.parse
import uuid
import jwt
import numpy as np
import pandas as pd
import requests

# ==============================================================================
# [1. 사용자 설정 및 옵션 파라미터 (Top Options)]
# ==============================================================================

# 업비트 API 키 (실제 자동매매 사용 시 입력, 스캔 전용 실행 시 빈 문자열 유지)
UPBIT_ACCESS_KEY = "YOUR_UPBIT_ACCESS_KEY"
UPBIT_SECRET_KEY = "YOUR_SECRET_KEY"

# 매매 및 실행 모드 설정
AUTO_TRADE_EXECUTE = (
    False  # False: 스캔/분석 결과 출력 모드, True: 실제 업비트 자동 주문 실행
)

# 감시 종목 설정 (None: 업비트 원화 마켓 전체, 또는 특정 종목 지정 ['KRW-BTC', 'KRW-ETH'])
TARGET_TICKERS = None
MAX_TARGET_COUNT = 20  # 업비트 전체 대상일 때 감시할 최대 코인 개수 제한 (20개)

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
  """종목별 실시간 트레이딩 상태를 JSON 파일에 영구 저장"""
  try:
    with open(STATE_FILE, "w", encoding="utf-8") as f:
      json.dump(state, f, ensure_ascii=False, indent=4)
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

    # [손절 체크] 기준봉 저가(마진노선) 이탈 시 데이터 초기화[cite: 3]
    if curr_close < effective_ref_low:
      if state["remaining_ratio"] > 0 and state["entry_bought"]:
        signals.append({
            "Ticker": ticker,
            "Event": "SELL (STOP LOSS)",
            "Price": curr_close,
            "Reason": "기준봉 손절가(마진노선) 이탈 -> 기준 가격 데이터 초기화[cite: 3]",
        })
        if AUTO_TRADE_EXECUTE and upbit_client:
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

    # [재매수 체크] 5일선 꺾여 기록된 기준 가격 현재가 상향 돌파 시 최대 금액(100만원) 재매수
    if (
        state["base_price"] is not None
        and curr_close > state["base_price"]
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
              f"기준 가격({triggered_base_price}) 현재가 상향 돌파 -> 100만원"
              " 재매수"
          ),
          "Entry_Price": round(entry_price, 2),
      })

      if AUTO_TRADE_EXECUTE and upbit_client:
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
        price_cond = curr_low <= ref_mid
        rebound_cond = (
            (curr_close > curr_open) if REQUIRE_BULLISH_REBOUND else True
        )
        is_pullback = price_cond and rebound_cond

      is_breakout = False
      if ENABLE_BREAKOUT_ENTRY:
        is_breakout = curr_close > ref_high

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

        signals.append({
            "Ticker": ticker,
            "Event": (
                "BUY (SCALE-IN)" if state["scale_in_count"] > 1 else "BUY"
            ),
            "Entry_Price": round(state["entry_price"], 2),
        })

        if AUTO_TRADE_EXECUTE and upbit_client:
          tranche_amount = ORDER_AMOUNT_KRW / target_scale_in_steps
          upbit_client.buy_limit_with_slippage_protection(
              ticker=ticker, amount_krw=tranche_amount
          )

    # [매도 및 5일선 관리 체크]
    if state["entry_bought"] and state["remaining_ratio"] > 0:
      entry_price = state["entry_price"]
      current_return = (curr_close - entry_price) / entry_price

      # A. 대칭 조건 만족 시 보유량의 50% 익절[cite: 2]
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
            "Reason": "대칭 조건 달성 -> 50% 익절 완료[cite: 2]",
        })

        if AUTO_TRADE_EXECUTE and upbit_client:
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

        if AUTO_TRADE_EXECUTE and upbit_client:
          upbit_client.sell_limit_with_slippage_protection(
              ticker=ticker, volume=sell_vol
          )

  return signals


# ==============================================================================
# [4. 메인 실행 함수 (5분 주기 Crontab 연동)]
# ==============================================================================


def run_market_scan():
  """5분마다 실행되어 09:07 스캐너(scan_ref_candles.py)가 공유한 활성 기준봉 종목만 실시간 점검"""
  global_state = load_state()
  client = UpbitClient(UPBIT_ACCESS_KEY, UPBIT_SECRET_KEY)

  # 09:07 스캐너에 의해 기준봉이 포착되었거나(active_ref_date 존재) 매수 포지션이 존재하는 종목만 선별
  active_tickers = [
      ticker
      for ticker, st in global_state.items()
      if st.get("active_ref_date") is not None or st.get("entry_bought", False)
  ]

  if TARGET_TICKERS:
    tickers = TARGET_TICKERS
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