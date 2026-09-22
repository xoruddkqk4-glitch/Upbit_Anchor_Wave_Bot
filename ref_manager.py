# ref_manager.py
# ==============================================================================
# 수동 기준봉 등록/취소 및 사전 검증 코어 모듈
# - TARGET_TICKERS 중 기준봉 미등록 코인 추출 및 번호 매핑
# - 업비트 일봉 데이터 기반 사전 검증 (유효기간 20일, 마감봉 여부, 과거 손절선 파괴 등)
# - StateFileLock 을 활용한 bot_state.json 안전 저장
# ==============================================================================

import json
import os
import re
import pandas as pd
import requests
from dotenv import load_dotenv

from state_lock import StateFileLock

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
load_dotenv(os.path.join(BASE_DIR, ".env"))

STATE_FILE = os.path.join(BASE_DIR, "bot_state.json")

# 전략 파라미터 (Upbit_Anchor_Wave_Bot.py 및 scan_ref_candles.py와 일치)
REF_EXPIRY_DAYS = 20
SWING_LOW_LOOKBACK_DAYS = 20
PULLBACK_RATIO = 0.5

# 기본 감시 대상 20개 종목
DEFAULT_TARGET_TICKERS = [
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

EXCLUDE_TICKERS = [
    "KRW-USDT",
    "KRW-USDC",
    "KRW-APENFT",
    "KRW-EHTW",
    "KRW-PEPPER",
    "KRW-SOLO",
    "KRW-XCORE",
]


def get_target_tickers():
    """설정된 감시 대상 코인 목록 반환 (.env TARGET_TICKERS 우선)"""
    env_targets = os.getenv("TARGET_TICKERS")
    if env_targets is not None:
        targets = [t.strip() for t in env_targets.split(",") if t.strip()]
        if targets:
            return targets
    return list(DEFAULT_TARGET_TICKERS)


def load_state(state_file=STATE_FILE):
    """bot_state.json 파일 읽기"""
    if not os.path.exists(state_file):
        return {}
    try:
        with open(state_file, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        print(f"[ref_manager] 상태 파일 읽기 오류: {e}")
        return {}


def save_state(state, state_file=STATE_FILE):
    """bot_state.json 파일 원자적 임시파일 교체 저장"""
    tmp_path = f"{state_file}.tmp_{os.getpid()}"
    try:
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(state, f, indent=4, ensure_ascii=False)
        os.replace(tmp_path, state_file)
        return True
    except Exception as e:
        print(f"[ref_manager] 상태 파일 저장 실패: {e}")
        if os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except OSError:
                pass
        return False


def get_available_tickers(state_file=STATE_FILE):
    """기준봉이 아직 등록되지 않은 코인 목록을 순번과 함께 반환.

    반환:
        dict: {
            "tickers_list": [(1, "KRW-BTC"), (2, "KRW-ETH"), ...],
            "num_to_ticker": {1: "KRW-BTC", 2: "KRW-ETH", ...},
            "ticker_to_num": {"KRW-BTC": 1, "KRW-ETH": 2, ...}
        }
    """
    state = load_state(state_file)
    targets = get_target_tickers()

    available = []
    for ticker in targets:
        if ticker in EXCLUDE_TICKERS:
            continue
        st = state.get(ticker, {})
        # 활성 기준봉이 없거나 None이고, 현재 보유 중이 아닌 경우만 대상
        has_ref = st.get("active_ref_date") is not None
        is_holding = st.get("entry_bought", False) and st.get("remaining_ratio", 0) > 0
        is_reentry = st.get("base_price") is not None

        if not has_ref and not is_holding and not is_reentry:
            available.append(ticker)

    num_to_ticker = {i + 1: ticker for i, ticker in enumerate(available)}
    ticker_to_num = {ticker: i + 1 for i, ticker in enumerate(available)}
    tickers_list = [(i + 1, ticker) for i, ticker in enumerate(available)]

    return {
        "tickers_list": tickers_list,
        "num_to_ticker": num_to_ticker,
        "ticker_to_num": ticker_to_num,
    }


def get_daily_ohlcv(ticker, count=120):
    """업비트 일봉 데이터 조회 (09:00 KST 기준)"""
    url = f"https://api.upbit.com/v1/candles/days?market={ticker}&count={count}"
    try:
        res = requests.get(url, timeout=5)
        if res.status_code != 200:
            return None
        data = res.json()
        if not isinstance(data, list) or len(data) == 0:
            return None

        df = pd.DataFrame(data)
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
    except Exception as e:
        print(f"[ref_manager] 일봉 조회 오류 ({ticker}): {e}")
        return None


def validate_and_register_manual_ref(ticker, target_date_str, state_file=STATE_FILE):
    """수동 기준봉 사전 검증 및 bot_state.json 등록.

    Args:
        ticker (str): 대상 코인 (예: "KRW-BTC")
        target_date_str (str): 기준봉 날짜 (예: "2026-03-15")
        state_file (str): 상태 파일 경로

    Returns:
        tuple: (success: bool, result_or_error_msg: str or dict)
    """
    # 1. 입력 포맷 검증
    ticker = ticker.strip().upper()
    if not ticker.startswith("KRW-"):
        ticker = f"KRW-{ticker}"

    if not re.match(r"^\d{4}-\d{2}-\d{2}$", target_date_str):
        return False, "날짜 형식이 올바르지 않습니다. YYYY-MM-DD 형식으로 입력해 주세요. (예: 2026-03-15)"

    try:
        target_dt = pd.Timestamp(target_date_str)
    except Exception:
        return False, "유효한 날짜가 아닙니다. 다시 확인해 주세요."

    # 2. 일봉 데이터 조회
    df = get_daily_ohlcv(ticker, count=120)
    if df is None or len(df) < 25:
        return False, f"업비트에서 {ticker}의 일봉 데이터를 불러오지 못했습니다. 종목명을 확인해 주세요."

    curr_row = df.iloc[-1]
    curr_candle_date = curr_row.name.strftime("%Y-%m-%d")

    # 3. 날짜 시점 검증 (진행 중인 오늘 봉 및 미래 봉 방지)
    if target_date_str >= curr_candle_date:
        return (
            False,
            f"기준봉은 마감 확정된 과거 일봉만 지정 가능합니다.\n"
            f"• 입력일: {target_date_str}\n"
            f"• 진행 중인 당일 봉: {curr_candle_date}\n"
            f"• 지정 가능 최대일: 전일({df.iloc[-2].name.strftime('%Y-%m-%d')})",
        )

    # 일봉 인덱스 일치 확인 (시간 제외한 날짜 비교)
    matching_indices = [idx for idx in df.index if idx.strftime("%Y-%m-%d") == target_date_str]
    if not matching_indices:
        return False, f"{ticker}의 차트에서 {target_date_str} 날짜의 일봉을 찾을 수 없습니다."

    ref_idx = matching_indices[0]
    ref_pos = df.index.get_loc(ref_idx)

    # 4. 유효기간(REF_EXPIRY_DAYS = 20) 검증
    ref_age_days = (curr_row.name - ref_idx).days
    if ref_age_days >= REF_EXPIRY_DAYS:
        return (
            False,
            f"기준봉 유효기간({REF_EXPIRY_DAYS}일)을 초과한 캔들입니다.\n"
            f"• 경과 일수: {ref_age_days}일 (최대 허용: {REF_EXPIRY_DAYS - 1}일)\n"
            f"• 유효 기준일 범위: {(curr_row.name - pd.Timedelta(days=REF_EXPIRY_DAYS - 1)).strftime('%Y-%m-%d')} ~ {df.iloc[-2].name.strftime('%Y-%m-%d')}",
        )

    # 5. 기준봉 지표 및 갭보정 손절선 산출
    ref_row = df.loc[ref_idx]
    ref_high = float(ref_row["high"])
    ref_low = float(ref_row["low"])

    prev_close = (
        float(df["close"].iloc[ref_pos - 1]) if ref_pos > 0 else float(ref_row["open"])
    )
    has_gap_up = float(ref_row["open"]) > prev_close
    effective_ref_low = min(ref_low, prev_close) if has_gap_up else ref_low
    ref_mid = effective_ref_low + (ref_high - effective_ref_low) * PULLBACK_RATIO

    # 스윙 저점 및 파동 높이 산출
    lookback_start = max(0, ref_pos - SWING_LOW_LOOKBACK_DAYS)
    low_rel_pos = df["low"].iloc[lookback_start : ref_pos + 1].argmin()
    rise_duration = int((ref_pos - (lookback_start + low_rel_pos)) + 1)
    swing_low_price = float(df["low"].iloc[lookback_start : ref_pos + 1].min())
    wave_height = float(ref_high - swing_low_price)

    # 6. 과거 손절선 파괴(사후 이탈) 사전 검증
    # 기준봉 다음 날부터 전일(마감 확정봉)까지의 저가 체크
    closed_subsequent = df.iloc[:-1].iloc[ref_pos + 1 :]
    if not closed_subsequent.empty:
        subsequent_min_low = float(closed_subsequent["low"].min())
        if subsequent_min_low < effective_ref_low:
            broken_idx = closed_subsequent["low"].idxmin().strftime("%Y-%m-%d")
            return (
                False,
                f"❌ <b>기준봉 등록 불가 (사후 손절선 이탈 확인)</b>\n"
                f"• 종목: {ticker} (기준일: {target_date_str})\n"
                f"• 손절 기준가: {effective_ref_low:,.0f}원\n"
                f"• 이탈 발생일: {broken_idx} (저점 {subsequent_min_low:,.0f}원)\n"
                f"• 사유: 기준봉 형성 이후 저가가 손절선을 하향 이탈하여 지지 구조가 이미 파괴되었습니다.",
            )

    # 7. 현재가 손절선 이탈 검사
    curr_close = float(curr_row["close"])
    if curr_close < effective_ref_low:
        return (
            False,
            f"❌ <b>기준봉 등록 불가 (현재가 손절선 하회)</b>\n"
            f"• 종목: {ticker}\n"
            f"• 현재가: {curr_close:,.0f}원 < 손절가: {effective_ref_low:,.0f}원\n"
            f"• 사유: 현재가가 이미 기준봉 손절가보다 낮아 진입할 수 없습니다.",
        )

    # 8. bot_state.json 에 안전하게 저장 (StateFileLock 활용)
    lock = StateFileLock(state_file)
    if not lock.acquire():
        return False, "시스템이 현재 매매 처리 중(락 획득 대기 초과)입니다. 잠시 후 다시 시도해 주세요."

    try:
        state = load_state(state_file)
        curr_ticker_state = state.get(ticker, {})

        # 이미 보유 중인 포지션이 있는 경우 기준봉 덮어쓰기 방어
        if curr_ticker_state.get("entry_bought", False) and curr_ticker_state.get("remaining_ratio", 0) > 0:
            return False, f"{ticker}는 현재 매수 포지션을 보유 중이므로 기준봉을 임의로 변경할 수 없습니다."

        state[ticker] = {
            "active_ref_date": target_date_str,
            "entry_bought": False,
            "entry_date": None,
            "entry_price": 0.0,
            "total_volume": 0.0,
            "remaining_ratio": 1.0,
            "symmetry_tp_executed": False,
            "price_tp_executed": False,
            "scale_in_count": 0,
            "last_scale_in_date": None,
            "target_buy_amount": None,
            "base_price": None,
            "base_amount": None,
            "base_price_date": None,
            "wave_anchor_price": None,
            "wave_anchor_date": None,
            "time_sym_below_high_logged": False,
            "ref_high": ref_high,
            "effective_ref_low": effective_ref_low,
            "anchor_low": effective_ref_low,
            "ref_mid": ref_mid,
            "rise_duration": rise_duration,
            "wave_height": wave_height,
            "tiered_tp_executed_levels": [],
            "breakout_date": None,
            "trough_low": None,
            "manual_registered": True,
        }

        if not save_state(state, state_file):
            return False, "bot_state.json 저장에 실패했습니다."

    finally:
        lock.release()

    remaining_days = REF_EXPIRY_DAYS - ref_age_days
    return True, {
        "ticker": ticker,
        "ref_date": target_date_str,
        "ref_high": ref_high,
        "ref_mid": ref_mid,
        "effective_ref_low": effective_ref_low,
        "rise_duration": rise_duration,
        "wave_height": wave_height,
        "ref_age_days": ref_age_days,
        "remaining_days": remaining_days,
        "curr_close": curr_close,
    }


def cancel_manual_ref(ticker, state_file=STATE_FILE):
    """등록된 기준봉 감시 수동 해제 (미보유 종목 한정)"""
    ticker = ticker.strip().upper()
    if not ticker.startswith("KRW-"):
        ticker = f"KRW-{ticker}"

    lock = StateFileLock(state_file)
    if not lock.acquire():
        return False, "시스템 락 획득 실패. 잠시 후 다시 시도해 주세요."

    try:
        state = load_state(state_file)
        if ticker not in state:
            return False, f"{ticker}는 현재 등록된 상태가 없습니다."

        st = state[ticker]
        if st.get("entry_bought", False) and st.get("remaining_ratio", 0) > 0:
            return False, f"{ticker}는 매수 포지션을 보유 중이므로 감시를 해제할 수 없습니다. (매도 완료 후 해제 가능)"

        prev_ref = st.get("active_ref_date")
        if not prev_ref:
            return False, f"{ticker}는 현재 활성 기준봉이 없습니다."

        st["active_ref_date"] = None
        st["manual_registered"] = False
        st["base_price"] = None
        st["base_amount"] = None
        st["base_price_date"] = None

        if not save_state(state, state_file):
            return False, "상태 저장 실패"

        return True, f"✅ [{ticker}] 기준일({prev_ref}) 기준봉 감시가 성공적으로 해제되었습니다."
    finally:
        lock.release()
