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
from state_lock import StateFileLock

# 프로젝트 경로의 .env 명시적 로드
load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))

# 한국 표준시(KST, UTC+9) 타임존 정의 (서버 OS 기본 타임존이 UTC여도 항상 정확한 서울 시간 보장)
KST = datetime.timezone(datetime.timedelta(hours=9))

# 상태 저장용 JSON 파일 경로 (Upbit_Anchor_Wave_Bot.py와 공유)
STATE_FILE = "bot_state.json"

# 스캔 파라미터
CANDLE_COUNT = 120          # 일봉 데이터 조회 개수
REF_VOL_MA_PERIOD = 20      # 거래량 평균 비교 기간 (20일)
REF_VOL_MULTIPLIER = 2.0    # 거래량 급증 배수 (200% 이상)
REF_MIN_CHANGE_PCT = 0.10   # 기준봉 최소 상승률 (10% 이상 장대양봉)
PULLBACK_RATIO = 0.5        # 눌림목 기준 비율 (0.5 = 중심가)
REF_EXPIRY_DAYS = 20        # 기준봉 유효기간(일). Upbit_Anchor_Wave_Bot.py와 동일 값 유지 (불일치 시 만료<->재등록 순환 발생)
PREV_HIGH_LOOKBACK_DAYS = 20  # 기준봉 판정용 전고점 룩백(일). Upbit_Anchor_Wave_Bot.py와 동일 값 유지 (불일치 시 봇·스캐너가 다른 기준봉 탐지)
SWING_LOW_LOOKBACK_DAYS = 20  # 1차 파동 스윙 저점 탐색 기간(일). Upbit_Anchor_Wave_Bot.py와 동일 값 유지
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
]  # 지정된 20개 감시 코인 목록 (빈 리스트 [] 지정 시 전일 거래대금 상위 20개 자동 탐색)

# .env 환경변수 TARGET_TICKERS가 설정되어 있으면 우선 적용 (예: TARGET_TICKERS=KRW-BTC,KRW-ETH 또는 빈 문자열)
env_targets = os.getenv("TARGET_TICKERS")
if env_targets is not None:
    TARGET_TICKERS = [t.strip() for t in env_targets.split(",") if t.strip()]


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
        df["high"].shift(1).rolling(window=PREV_HIGH_LOOKBACK_DAYS).max()
    )
    df["Change"] = (df["close"] - df["open"]) / df["open"]

    vol_cond = df["volume"] >= df["Vol_MA"] * REF_VOL_MULTIPLIER
    change_cond = df["Change"] >= REF_MIN_CHANGE_PCT
    breakout_cond = df["close"] > df["High_Lookback"]

    df["Is_Ref_Candle"] = vol_cond & change_cond & breakout_cond
    return df


def scan_all_reference_candles():
    """상태 파일 락을 잡은 뒤 기준봉 스캔 본체를 실행 (락 획득 실패 시 이번 스캔 건너뜀)

    09:05 봇 실행이 아직 끝나지 않은 채 09:07 스캔이 시작되면 봇이 기록한 체결 상태를
    스캐너의 오래된 사본이 덮어써 유실되므로, 봇 실행이 끝날 때까지 대기한 뒤 진행한다.
    """
    lock = StateFileLock(STATE_FILE, timeout_sec=180)
    if not lock.acquire():
        msg = (
            f"[경고] 상태 파일 락 획득 실패({lock.lock_path}) -> 09:07 기준봉 스캔 건너뜀."
            " 봇 실행이 장시간 겹치고 있는지 확인 필요"
        )
        print(msg)
        SendMessage(f"<b>⚠️ [BST 스캐너] {msg}</b>")
        return
    try:
        _scan_all_reference_candles_locked()
    finally:
        lock.release()


def _scan_all_reference_candles_locked():
    """매일 09:07 KST 실행: 업비트 종목별 기준봉 탐색 후 bot_state.json 갱신 및 텔레그램 일괄 발송"""
    now_str = datetime.datetime.now(KST).strftime("%Y-%m-%d %H:%M:%S")
    print("=" * 80)
    print(f" [스캔] [{now_str}] 매일 09:07 KST 기준봉(Reference Candle) 전용 스캐너 실행")
    print("=" * 80)

    global_state = load_state()

    # TARGET_TICKERS가 1개라도 지정되어 있으면 해당 감시 대상 종목만 스캔 (거래대금 상위 20개 조건 미적용)
    # 감시 대상 종목을 입력하지 않았을 때(빈 리스트 [])만 전일 일봉 거래대금 상위 20개 코인을 자동 추출
    if TARGET_TICKERS and len(TARGET_TICKERS) > 0:
        target_tickers = [t for t in TARGET_TICKERS if t not in EXCLUDE_TICKERS]
    else:
        top_volume_tickers = get_top_trading_volume_tickers(
            MAX_TARGET_COUNT, EXCLUDE_TICKERS
        )
        existing_active = [
            t
            for t, st in global_state.items()
            if (st.get("active_ref_date") or st.get("entry_bought", False))
            and t not in EXCLUDE_TICKERS
        ]
        target_tickers = list(dict.fromkeys(top_volume_tickers + existing_active))

    detected_count = 0
    all_reported_candles = []

    for ticker in target_tickers:
        try:
            df = get_daily_ohlcv(ticker, count=CANDLE_COUNT)
            if df is None or len(df) < 30:
                continue

            curr_close = float(df.iloc[-1]["close"])

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

            # 2. 이미 매수 포지션 보유 중이거나 5일선 매도 후 재매수 대기 중인 코인은
            # 기존 활성 기준봉 상태를 유지하며 09:07 보고서에 정상 포함 (스캔 건너뛰기 대신 보고)
            if state.get("entry_bought", False):
                tag = "보유 중" if state.get("remaining_ratio", 0) > 0 else "재매수 대기"
                ref_date_str = state.get("active_ref_date") or "미지정"
                ref_high = state.get("ref_high", 0.0)
                ref_mid = state.get("ref_mid", 0.0)
                effective_ref_low = state.get("effective_ref_low", 0.0)

                print(
                    f"  [{tag}] {ticker} -> 기준일: {ref_date_str} | 현재가: {format_price(curr_close)} |"
                    f" 중심가: {format_price(ref_mid)} | 손절가: {format_price(effective_ref_low)} | 고가: {format_price(ref_high)}"
                )

                all_reported_candles.append({
                    "ticker": ticker,
                    "ref_date": ref_date_str,
                    "tag": tag,
                    "curr_close": curr_close,
                    "ref_high": ref_high,
                    "ref_mid": ref_mid,
                    "effective_ref_low": effective_ref_low,
                })
                time.sleep(API_DELAY_SEC)
                continue

            df = detect_reference_candles(df)
            # 마감 확정봉만 탐지(진행 중 마지막 봉 제외) + 유효기간(REF_EXPIRY_DAYS) 내 기준봉만 후보로 인정
            closed_df = df.iloc[:-1]
            latest_date = df.index[-1]
            ref_indices = [
                idx
                for idx in closed_df.index[closed_df["Is_Ref_Candle"]].tolist()
                if (latest_date - idx).days < REF_EXPIRY_DAYS
            ]

            if ref_indices:
                latest_ref_idx = ref_indices[-1]
                ref_date_str = latest_ref_idx.strftime("%Y-%m-%d")
                prev_ref_date = state.get("active_ref_date")

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

                lookback_start = max(0, ref_pos - SWING_LOW_LOOKBACK_DAYS)
                low_rel_pos = df["low"].iloc[lookback_start : ref_pos + 1].argmin()
                rise_duration = (ref_pos - (lookback_start + low_rel_pos)) + 1
                swing_low_price = float(df["low"].iloc[lookback_start : ref_pos + 1].min())
                wave_height = ref_high - swing_low_price

                # [사전 필터링 1] 기준봉 형성 이후 마감 확정봉들 중 저가가 손절선(저가)을 이탈한 적이 있는지 검증 (과거 이탈 영구 무효화)
                # 기준봉이 한 번이라도 손절가를 깼다면 해당 지지 구조는 이미 붕괴된 것이며, 이전 일봉은 확인할 필요 없이 즉시 영구 무효화
                closed_subsequent = closed_df.iloc[ref_pos + 1 :]
                broken_in_history = False
                broken_date_str = ""
                broken_low_val = 0.0

                if not closed_subsequent.empty:
                    subsequent_min_low = float(closed_subsequent["low"].min())
                    if subsequent_min_low < effective_ref_low:
                        broken_in_history = True
                        broken_idx = closed_subsequent["low"].idxmin()
                        broken_date_str = broken_idx.strftime("%Y-%m-%d")
                        broken_low_val = subsequent_min_low

                if broken_in_history:
                    print(
                        f"  [손절선 기이탈 무효화] {ticker} -> 기준일: {ref_date_str} |"
                        f" 사후 저점({broken_date_str}, {format_price(broken_low_val)}) < 손절가({format_price(effective_ref_low)})"
                        " (손절선 파괴로 기준봉 영구 무효화 -> 진입 제외)"
                    )
                    if not state["entry_bought"]:
                        state["active_ref_date"] = None
                    continue

                # [사전 필터링 2] 현재가가 손절가(기준봉 저가) 이하로 이미 이탈한 무효화된 기준봉은 해제 후 패스
                if curr_close < effective_ref_low:
                    print(
                        f"  [손절선 이탈 무시] {ticker} -> 기준일: {ref_date_str} |"
                        f" 현재가({format_price(curr_close)}) < 손절가({format_price(effective_ref_low)})"
                        " (무효화된 기준봉 무시)"
                    )
                    if not state["entry_bought"]:
                        state["active_ref_date"] = None
                    continue

                # 유효한 기준봉 업데이트
                state["active_ref_date"] = ref_date_str
                state["ref_high"] = ref_high
                state["effective_ref_low"] = effective_ref_low
                state["ref_mid"] = ref_mid
                state["rise_duration"] = int(rise_duration)
                state["wave_height"] = wave_height

                if prev_ref_date == ref_date_str:
                    tag = "감시 중"
                    print(
                        f"  [감시 중] {ticker} -> 기준일: {ref_date_str} | 현재가: {format_price(curr_close)} |"
                        f" 중심가: {format_price(ref_mid)} | 손절가: {format_price(effective_ref_low)} | 고가: {format_price(ref_high)}"
                    )
                elif prev_ref_date:
                    tag = "최신 갱신"
                    detected_count += 1
                    print(
                        f"  [기준봉 갱신] {ticker} -> 이전 기준일({prev_ref_date}) => 최신 기준일({ref_date_str}) 갱신! | 현재가: {format_price(curr_close)} |"
                        f" 중심가: {format_price(ref_mid)} | 손절가: {format_price(effective_ref_low)} | 고가: {format_price(ref_high)}"
                    )
                else:
                    tag = "신규 포착"
                    detected_count += 1
                    print(
                        f"  [신규 포착] {ticker} -> 기준일: {ref_date_str} | 현재가: {format_price(curr_close)} |"
                        f" 중심가: {format_price(ref_mid)} | 손절가: {format_price(effective_ref_low)} | 고가: {format_price(ref_high)}"
                    )

                all_reported_candles.append({
                    "ticker": ticker,
                    "ref_date": ref_date_str,
                    "tag": tag,
                    "curr_close": curr_close,
                    "ref_high": ref_high,
                    "ref_mid": ref_mid,
                    "effective_ref_low": effective_ref_low,
                })
            else:
                # ref_indices가 추출되지 않은 경우라도, 기존 active_ref_date가 유효하고 손절가 상회 시 감시 중으로 포함
                active_ref_date = state.get("active_ref_date")
                effective_ref_low = state.get("effective_ref_low", 0.0)
                ref_mid = state.get("ref_mid", 0.0)
                ref_high = state.get("ref_high", 0.0)

                if active_ref_date and effective_ref_low > 0:
                    ref_age_days = (df.index[-1] - pd.Timestamp(active_ref_date)).days
                    ref_ts = pd.Timestamp(active_ref_date)
                    is_broken = False
                    if ref_ts in df.index:
                        pos = df.index.get_loc(ref_ts)
                        sub_closed = closed_df.iloc[pos + 1 :]
                        if not sub_closed.empty and float(sub_closed["low"].min()) < effective_ref_low:
                            is_broken = True

                    if is_broken:
                        if not state["entry_bought"]:
                            print(
                                f"  [손절선 기이탈 무효화] {ticker} -> 기준일: {active_ref_date} 사후 손절선 이탈 확인 감시 해제"
                            )
                            state["active_ref_date"] = None
                    elif ref_age_days >= REF_EXPIRY_DAYS:
                        if not state["entry_bought"]:
                            print(
                                f"  [기준봉 만료] {ticker} -> 기준일: {active_ref_date} ({ref_age_days}일 경과"
                                f" >= {REF_EXPIRY_DAYS}일) 감시 해제"
                            )
                            state["active_ref_date"] = None
                    elif curr_close >= effective_ref_low:
                        print(
                            f"  [기존 감시 유지] {ticker} -> 기준일: {active_ref_date} | 현재가: {format_price(curr_close)} |"
                            f" 중심가: {format_price(ref_mid)} | 손절가: {format_price(effective_ref_low)} | 고가: {format_price(ref_high)}"
                        )
                        all_reported_candles.append({
                            "ticker": ticker,
                            "ref_date": active_ref_date,
                            "tag": "감시 중",
                            "curr_close": curr_close,
                            "ref_high": ref_high,
                            "ref_mid": ref_mid,
                            "effective_ref_low": effective_ref_low,
                        })
                    else:
                        if not state["entry_bought"]:
                            state["active_ref_date"] = None
                else:
                    if not state["entry_bought"]:
                        state["active_ref_date"] = None

            time.sleep(API_DELAY_SEC)

        except Exception as e:
            print(f"  [오류] {ticker} 스캔 실패: {e}")
            continue

    save_state(global_state)

    # 텔레그램 일괄(단일) 메시지 발송
    now_kst = datetime.datetime.now(KST).strftime("%Y-%m-%d %H:%M KST")
    if all_reported_candles:
        new_count = sum(1 for c in all_reported_candles if c["tag"] in ["신규 포착", "최신 갱신"])
        keep_count = sum(1 for c in all_reported_candles if c["tag"] in ["감시 중", "보유 중", "재매수 대기"])

        header_text = (
            "<b>📊 [BST 봇] 09:07 KST 기준봉 감시 현황 보고</b>\n"
            f"• <b>스캔 일시</b>: {now_kst}\n"
            f"• <b>총 유효 기준봉</b>: <b>{len(all_reported_candles)}개</b> (신규/갱신: {new_count}개 | 감시/보유 중: {keep_count}개)\n"
            "----------------------------------------"
        )

        candle_blocks = []
        for c in all_reported_candles:
            ticker = c["ticker"]
            ref_date = c["ref_date"]
            tag_str = f"[{c['tag']}]"
            curr_close = c["curr_close"]
            ref_high = c["ref_high"]
            ref_mid = c["ref_mid"]
            effective_ref_low = c["effective_ref_low"]

            if curr_close >= ref_high:
                pos_icon = "🚀"
                pos_label = "고가 돌파"
            elif curr_close >= ref_mid:
                pos_icon = "📍"
                pos_label = "중심가 상회"
            elif curr_close >= effective_ref_low:
                pos_icon = "🎯"
                pos_label = "눌림목 영역"
            else:
                pos_icon = "🚨"
                pos_label = "손절가 하회"

            price_line = f"{pos_icon} <b>[현재가] ({pos_label})</b>: {format_price(curr_close)}"
            high_line = f"• 고가: {format_price(ref_high)}"
            mid_line = f"• 중심가: {format_price(ref_mid)}"
            low_line = f"• 손절가: {format_price(effective_ref_low)}"

            # 가격 사다리(Price Ladder) 순서에 맞춰 현재가 행을 동적으로 배치
            if curr_close >= ref_high:
                price_rows = [price_line, high_line, mid_line, low_line]
            elif curr_close >= ref_mid:
                price_rows = [high_line, price_line, mid_line, low_line]
            elif curr_close >= effective_ref_low:
                price_rows = [high_line, mid_line, price_line, low_line]
            else:
                price_rows = [high_line, mid_line, low_line, price_line]

            block = (
                f"<b>• {ticker}</b> <code>{tag_str}</code> (기준일: {ref_date})\n"
                + "\n".join(price_rows)
            )
            candle_blocks.append(block)

        all_blocks = [header_text] + candle_blocks
        full_text = "\n\n".join(all_blocks)

        if len(full_text) <= 3800:
            SendMessage(full_text)
        else:
            chunk = header_text
            for c_block in candle_blocks:
                if len(chunk) + len(c_block) + 2 > 3800:
                    SendMessage(chunk.strip())
                    chunk = "<b>📊 [BST 봇] 기준봉 감시 현황 (이어서)</b>\n----------------------------------------\n\n" + c_block
                else:
                    chunk += "\n\n" + c_block
            if chunk.strip():
                SendMessage(chunk.strip())
    else:
        empty_msg = (
            "<b>📊 [BST 봇] 09:07 KST 기준봉 감시 현황 보고</b>\n"
            f"• <b>스캔 일시</b>: {now_kst}\n"
            "• <b>안내</b>: 현재 포착되었거나 유효하게 감시 중인 기준봉 종목이 없습니다."
        )
        SendMessage(empty_msg)

    print("=" * 80)
    print(f" [완료] 스캔 완료: 총 {len(target_tickers)}개 감시 종목 중 {len(all_reported_candles)}개 유효 기준봉 보고 완료 (신규/갱신: {detected_count}개)")
    print("=" * 80 + "\n")


if __name__ == "__main__":
    scan_all_reference_candles()
