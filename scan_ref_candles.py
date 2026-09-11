# scan_ref_candles.py
# ==============================================================================
# [매일 09:07 KST 실행] 업비트 기준봉(Reference Candle) 전용 스캐너
# 09:07 KST에 실행되어 기준봉이 형성된 종목을 포착하고, 결과를 bot_state.json에 저장하여
# Upbit_Anchor_Wave_Bot.py와 실시간으로 상태를 공유합니다.
# ==============================================================================

import datetime
import json
import os
import time
from dotenv import load_dotenv
import pandas as pd
import requests
from telegram_alert import SendMessage

# 프로젝트 경로의 .env 명시적 로드
load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))

# 상태 저장용 JSON 파일 경로 (Upbit_Anchor_Wave_Bot.py와 공유)
STATE_FILE = "bot_state.json"

# 스캔 파라미터
CANDLE_COUNT = 120          # 일봉 데이터 조회 개수
REF_VOL_MA_PERIOD = 20      # 거래량 평균 비교 기간 (20일)
REF_VOL_MULTIPLIER = 2.0    # 거래량 급증 배수 (200% 이상)
REF_MIN_CHANGE_PCT = 0.10   # 기준봉 최소 상승률 (10% 이상 장대양봉)
PULLBACK_RATIO = 0.5        # 눌림목 기준 비율 (0.5 = 중심가)
MAX_TARGET_COUNT = 20       # 스캔 대상 최대 코인 수
API_DELAY_SEC = 0.1         # API 요청 간격

# 감시 및 매매 제외 종목 설정 (예: ['KRW-USDT', 'KRW-USDC'] 등 제외할 코인 지정)
EXCLUDE_TICKERS = [
    "KRW-USDT",
    "KRW-USDC",
    "KRW-APENFT",
    "KRW-EHTW",
    "KRW-PEPPER",
    "KRW-SOLO",
    "KRW-XCORE",
]
TARGET_TICKERS = None  # None: 거래대금 상위 코인 자동 추출


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
        print(f"[알림] 스캔 결과가 '{STATE_FILE}'에 성공적으로 저장되었습니다.")
    except Exception as e:
        print(f"[오류] 상태 파일 저장 실패: {e}")


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


def get_top_trading_volume_tickers(max_count=20, exclude_tickers=None):
    """어제 완전 마감된 일봉 1개(09:00~09:00)의 누적 거래대금 기준 상위 코인 정렬 추출 (Ticker 배치 조회를 통한 속도 최적화)"""
    if exclude_tickers is None:
        exclude_tickers = []

    warning_tickers = get_upbit_warning_tickers()
    if warning_tickers:
        print(
            f"  [안내] 업비트 실시간 유의/위험 종목 동적 자동 제외"
            f" ({len(warning_tickers)}개): {warning_tickers}"
        )

    combined_exclude = set(exclude_tickers + warning_tickers)

    try:
        url_markets = "https://api.upbit.com/v1/market/all"
        res_markets = requests.get(url_markets, timeout=5).json()
        krw_tickers = [
            item["market"]
            for item in res_markets
            if item["market"].startswith("KRW-") and item["market"] not in combined_exclude
        ]

        if not krw_tickers:
            return []

        # 1차: 1회의 Ticker 일괄 요청으로 24시간 거래대금 상위 35개 후보군을 빠르게 1차 선별 (속도 극대화)
        url_ticker = f"https://api.upbit.com/v1/ticker?markets={','.join(krw_tickers)}"
        res_ticker = requests.get(url_ticker, timeout=5).json()
        if not isinstance(res_ticker, list):
            return []

        sorted_candidates = sorted(
            res_ticker, key=lambda x: float(x.get("acc_trade_price_24h", 0)), reverse=True
        )[: max_count * 2]

        ticker_volumes = []

        # 2차: 후보군 35개 종목에 한해서만 어제 마감된 1일봉(res_candle[1])의 정확한 거래대금 추출
        for item in sorted_candidates:
            ticker = item["market"]
            try:
                url_candle = f"https://api.upbit.com/v1/candles/days?market={ticker}&count=2"
                res_candle = requests.get(url_candle, timeout=5).json()
                if isinstance(res_candle, list) and len(res_candle) >= 2:
                    yesterday_candle = res_candle[1]
                    trade_price_krw = float(
                        yesterday_candle.get(
                            "candle_acc_trade_price",
                            yesterday_candle.get("trade_price", 0)
                            * yesterday_candle.get("candle_acc_trade_volume", 0),
                        )
                    )
                    ticker_volumes.append((ticker, trade_price_krw))
                time.sleep(0.02)
            except Exception:
                continue

        # 어제 일봉 누적 거래대금 내림차순 최종 정렬
        ticker_volumes.sort(key=lambda x: x[1], reverse=True)

        sorted_tickers = [item[0] for item in ticker_volumes]
        return sorted_tickers[:max_count]
    except Exception as e:
        print(f"[오류] 전일 일봉 거래대금 상위 종목 조회 실패: {e}")
        return []


def get_krw_tickers():
    """업비트 KRW 마켓 전체 종목 조회"""
    url = "https://api.upbit.com/v1/market/all"
    res = requests.get(url, timeout=5).json()
    return [item["market"] for item in res if item["market"].startswith("KRW-")]


def get_daily_ohlcv(ticker, count=120):
    """업비트 일봉 데이터 조회"""
    url = f"https://api.upbit.com/v1/candles/days?market={ticker}&count={count}"
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


def detect_reference_candles(df):
    """기준봉(Reference Candle) 탐색"""
    df = df.copy()
    df["Vol_MA"] = df["volume"].rolling(window=REF_VOL_MA_PERIOD).mean()
    df["High_Lookback"] = (
        df["high"].shift(1).rolling(window=REF_VOL_MA_PERIOD).max()
    )
    df["Change"] = (df["close"] - df["open"]) / df["open"]

    vol_cond = df["volume"] >= df["Vol_MA"] * REF_VOL_MULTIPLIER
    change_cond = df["Change"] >= REF_MIN_CHANGE_PCT
    breakout_cond = df["close"] > df["High_Lookback"]

    df["Is_Ref_Candle"] = vol_cond & change_cond & breakout_cond
    return df


def scan_all_reference_candles():
    """매일 09:07 KST 실행: 업비트 종목별 기준봉 탐색 후 bot_state.json 갱신"""
    now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print("=" * 80)
    print(f" [스캔] [{now_str}] 매일 09:07 KST 기준봉(Reference Candle) 전용 스캐너 실행")
    print("=" * 80)

    global_state = load_state()

    # TARGET_TICKERS가 지정되어 있지 않으면 24시간 거래대금 기준 상위 코인 추출
    if TARGET_TICKERS:
        target_tickers = [t for t in TARGET_TICKERS if t not in EXCLUDE_TICKERS]
    else:
        target_tickers = get_top_trading_volume_tickers(
            MAX_TARGET_COUNT, EXCLUDE_TICKERS
        )

    detected_count = 0

    for ticker in target_tickers:
        try:
            # 이미 매수 포지션 보유 중인 코인은 스캔 건너뛰기(Skip)
            if ticker in global_state:
                state = global_state[ticker]
                if state.get("entry_bought", False):
                    print(f"  [패스] {ticker} -> 현재 매수 포지션 보유 중 (스캔 건너뜀)")
                    continue

            df = get_daily_ohlcv(ticker, count=CANDLE_COUNT)
            if df is None or len(df) < 30:
                continue

            df = detect_reference_candles(df)
            ref_indices = df.index[df["Is_Ref_Candle"]].tolist()

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

            if ref_indices:
                latest_ref_idx = ref_indices[-1]
                ref_date_str = latest_ref_idx.strftime("%Y-%m-%d")
                prev_ref_date = state.get("active_ref_date")

                # 동일한 기준일의 기준봉이 이미 등록되어 있는 경우 중복 수신 방지를 위해 스캔 패스
                if prev_ref_date == ref_date_str:
                    print(
                        f"  [패스] {ticker} -> 동일한 기준봉 감시 중 (스캔 건너뜀, 기준일: {ref_date_str})"
                    )
                    continue

                ref_row = df.loc[latest_ref_idx]
                ref_pos = df.index.get_loc(latest_ref_idx)

                ref_high = float(ref_row["high"])
                ref_low = float(ref_row["low"])

                prev_close = (
                    float(df["close"].iloc[ref_pos - 1])
                    if ref_pos > 0
                    else float(ref_row["open"])
                )
                has_gap_up = ref_row["open"] > prev_close
                effective_ref_low = min(ref_low, prev_close) if has_gap_up else ref_low
                ref_mid = effective_ref_low + (ref_high - effective_ref_low) * PULLBACK_RATIO

                lookback_start = max(0, ref_pos - 10)
                low_rel_pos = df["low"].iloc[lookback_start : ref_pos + 1].argmin()
                rise_duration = (ref_pos - (lookback_start + low_rel_pos)) + 1
                swing_low_price = float(df["low"].iloc[lookback_start : ref_pos + 1].min())
                wave_height = ref_high - swing_low_price

                curr_close = float(df.iloc[-1]["close"])

                # [사전 필터링] 현재가가 손절가(기준봉 저가) 이하로 이미 이탈한 무효화된 기준봉은 등록하지 않고 무시
                if curr_close < effective_ref_low:
                    print(
                        f"  [손절선 이탈 무시] {ticker} -> 기준일: {ref_date_str} |"
                        f" 현재가({format_price(curr_close)}) < 손절가({format_price(effective_ref_low)})"
                        " (무효화된 기준봉 무시)"
                    )
                    if not state["entry_bought"]:
                        state["active_ref_date"] = None
                    continue

                # 새로 발견되었거나 더 최신 날짜로 갱신된 기준봉 정보 업데이트
                state["active_ref_date"] = ref_date_str
                state["ref_high"] = ref_high
                state["effective_ref_low"] = effective_ref_low
                state["ref_mid"] = ref_mid
                state["rise_duration"] = int(rise_duration)
                state["wave_height"] = wave_height

                detected_count += 1
                if prev_ref_date:
                    print(
                        f"  [기준봉 갱신] {ticker} -> 이전 기준일({prev_ref_date}) => 최신 기준일({ref_date_str}) 갱신! | 현재가: {format_price(curr_close)} |"
                        f" 중심가: {format_price(ref_mid)} | 손절가: {format_price(effective_ref_low)} | 고가: {format_price(ref_high)}"
                    )
                else:
                    print(
                        f"  [포착] {ticker} -> 기준일: {ref_date_str} | 현재가: {format_price(curr_close)} |"
                        f" 중심가: {format_price(ref_mid)} | 손절가: {format_price(effective_ref_low)} | 고가: {format_price(ref_high)}"
                    )

                # 현재가 위치에 맞게 고가/중심가/손절가 계층 순서로 가격 블록 동적 구성 (가시성 강조 및 유효 소수점 최대 8자리 자동 표기)
                high_line = f"• <b>고가</b>: {format_price(ref_high)}"
                mid_line = f"• <b>중심가</b>: {format_price(ref_mid)}"
                low_line = f"• <b>손절가</b>: {format_price(effective_ref_low)}"

                if curr_close >= ref_high:
                    curr_line = f"🚀 <b>[현재가] (고가 돌파)</b>: <u><b>{format_price(curr_close)}</b></u>"
                    price_hierarchy = [curr_line, high_line, mid_line, low_line]
                elif curr_close >= ref_mid:
                    curr_line = f"📍 <b>[현재가]</b>: <u><b>{format_price(curr_close)}</b></u>"
                    price_hierarchy = [high_line, curr_line, mid_line, low_line]
                elif curr_close >= effective_ref_low:
                    curr_line = f"🎯 <b>[현재가] (눌림목 영역)</b>: <u><b>{format_price(curr_close)}</b></u>"
                    price_hierarchy = [high_line, mid_line, curr_line, low_line]
                else:
                    curr_line = f"🚨 <b>[현재가] (손절가 하회)</b>: <u><b>{format_price(curr_close)}</b></u>"
                    price_hierarchy = [high_line, mid_line, low_line, curr_line]

                price_block = "\n".join(price_hierarchy)

                title_str = "최신 기준봉 갱신!" if prev_ref_date else "09:07 KST 기준봉 포착!"
                # 텔레그램 알림 메시지 발송
                telegram_msg = (
                    f"<b>[BST 봇] {title_str}</b>\n"
                    f"• <b>종목</b>: {ticker}\n"
                    f"• <b>기준일</b>: {ref_date_str}\n"
                    f"{price_block}"
                )
                SendMessage(telegram_msg)
            else:
                # 활성 포지션(보유 중)이 아닐 때만 active_ref_date = None으로 해제
                if not state["entry_bought"]:
                    state["active_ref_date"] = None

            time.sleep(API_DELAY_SEC)

        except Exception as e:
            print(f"  [오류] {ticker} 스캔 실패: {e}")
            continue

    save_state(global_state)
    print("=" * 80)
    print(f" [완료] 스캔 완료: 총 {len(target_tickers)}개 감시 종목 중 {detected_count}개 기준봉 포착 완료")
    print("=" * 80 + "\n")


if __name__ == "__main__":
    scan_all_reference_candles()
