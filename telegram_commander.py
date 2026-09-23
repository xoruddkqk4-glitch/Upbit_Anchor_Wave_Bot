# telegram_commander.py
# ==============================================================================
# 텔레그램 기반 트레이딩 봇 대화형 커맨더 데몬
# - /setref: 기준봉 미등록 코인 번호 목록 및 터치식 인라인 버튼 출력
# - 번호 터치/입력 후 날짜(YYYY-MM-DD) 수신 및 사전 검증 후 bot_state.json 등록
# - /status: 현재 보유 포지션 및 감시 기준봉 현황 조회
# - /cancelref: 등록된 기준봉 감시 해제 (미보유 종목)
# - /cancel: 진행 중인 입력 세션 취소
# ==============================================================================

import json
import os
import re
import sys
import time
import requests
from dotenv import load_dotenv

from ref_manager import (
    STATE_FILE,
    cancel_manual_ref,
    get_available_tickers,
    load_state,
    validate_and_register_manual_ref,
)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
load_dotenv(os.path.join(BASE_DIR, ".env"))

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
AUTHORIZED_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "").strip()

TELEGRAM_API_URL = f"https://api.telegram.org/bot{BOT_TOKEN}"

# 세션 관리 (chat_id -> session dict)
# session = {"step": "WAIT_TICKER" | "WAIT_DATE", "ticker": "KRW-BTC", "ticker_map": dict, "expire_at": float}
user_sessions = {}
SESSION_TIMEOUT_SEC = 180  # 3분 타임아웃


def format_price(price: float) -> str:
    """가격 가독성 포맷팅"""
    if price is None:
        return "-"
    if price >= 100:
        return f"{price:,.0f}원"
    elif price >= 1:
        return f"{price:,.2f}원"
    else:
        return f"{price:,.4f}원"


def send_message(chat_id, text, reply_markup=None):
    """텔레그램 메시지 발송 (HTML 파싱 지원)"""
    if not BOT_TOKEN:
        print(f"[텔레그램 토큰 없음] {text}")
        return False

    url = f"{TELEGRAM_API_URL}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML",
    }
    if reply_markup:
        payload["reply_markup"] = reply_markup

    try:
        res = requests.post(url, json=payload, timeout=7)
        return res.status_code == 200
    except Exception as e:
        print(f"[telegram_commander] 메시지 발송 오류: {e}")
        return False


def answer_callback_query(callback_query_id, text=None):
    """인라인 버튼 클릭 로딩 해제"""
    if not BOT_TOKEN:
        return
    url = f"{TELEGRAM_API_URL}/answerCallbackQuery"
    payload = {"callback_query_id": callback_query_id}
    if text:
        payload["text"] = text
    try:
        requests.post(url, json=payload, timeout=5)
    except Exception:
        pass


def is_authorized(chat_id) -> bool:
    """허용된 사용자 여부 확인"""
    if not AUTHORIZED_CHAT_ID:
        return True
    return str(chat_id).strip() == str(AUTHORIZED_CHAT_ID).strip()


def handle_help_command(chat_id):
    """도움말 및 메뉴 안내"""
    msg = (
        "<b>🤖 [BST 트레이딩 봇] 텔레그램 컨트롤러</b>\n\n"
        "사용 가능한 명령어:\n"
        "• <b>/setref</b> (또는 <code>/기준봉</code>): 기준봉 수동 등록 (번호/버튼 선택)\n"
        "• <b>/status</b> (또는 <code>/현황</code>): 포지션 및 감시 기준봉 현황 조회\n"
        "• <b>/cancelref</b> (또는 <code>/취소</code>): 등록된 기준봉 감시 해제\n"
        "• <b>/cancel</b>: 진행 중인 입력 세션 취소\n\n"
        "💡 <i>팁: <code>/setref 2 2026-03-15</code> 처럼 번호와 날짜를 한 번에 입력하실 수도 있습니다.</i>"
    )
    send_message(chat_id, msg)


def get_current_prices(tickers):
    """업비트 현재가 일괄 조회 -> {market: trade_price}"""
    valid_tickers = [t for t in tickers if t]
    if not valid_tickers:
        return {}
    try:
        url = f"https://api.upbit.com/v1/ticker?markets={','.join(valid_tickers)}"
        res = requests.get(url, timeout=4)
        if res.status_code == 200:
            data = res.json()
            if isinstance(data, list):
                return {
                    item["market"]: float(item["trade_price"])
                    for item in data
                    if "market" in item and item.get("trade_price") is not None
                }
    except Exception as e:
        print(f"[telegram_commander] 현재가 조회 오류: {e}")
    return {}


def format_watching_price_order(ref_h: float, ref_m: float, ref_l: float, curr_p: float = None) -> str:
    """
    미보유 기준봉 코인의 고가, 중심가, 손절가 및 적절한 위치의 현재가 순서 포맷팅
    예:
      고가 1,000원 > <b>현재가 900원</b> > 중심가 800원 > 손절가 600원
      고가 1,000원 > 중심가 800원 > <b>현재가 700원</b> > 손절가 600원
    """
    if curr_p is None or curr_p <= 0:
        return f"고가 {format_price(ref_h)} > 중심가 {format_price(ref_m)} > 손절가 {format_price(ref_l)} (현재가: -)"

    # 정렬용: (라벨, 가격, 동점 시 우선순위: 고가(1), 중심가(2), 손절가(3), 현재가(4))
    items = [
        ("고가", ref_h, 1),
        ("중심가", ref_m, 2),
        ("손절가", ref_l, 3),
        ("현재가", curr_p, 4),
    ]
    # 가격 내림차순 정렬 (동점 시 고정 가격선 우선 후 현재가 배치)
    items.sort(key=lambda x: (-x[1], x[2]))

    parts = []
    for label, price, _ in items:
        p_str = format_price(price)
        if label == "현재가":
            parts.append(f"<b>현재가 {p_str}</b>")
        else:
            parts.append(f"{label} {p_str}")

    return " > ".join(parts)


def handle_status_command(chat_id):
    """현재 감시 및 보유 현황 리포트"""
    state = load_state(STATE_FILE)

    holding_items = []
    reentry_items = []
    watching_items = []

    needed_tickers = set()

    for ticker, st in state.items():
        if st.get("entry_bought", False) and st.get("remaining_ratio", 0) > 0:
            holding_items.append((ticker, st))
            needed_tickers.add(ticker)
        elif st.get("base_price") is not None:
            reentry_items.append((ticker, st))
            needed_tickers.add(ticker)
        elif st.get("active_ref_date"):
            watching_items.append((ticker, st))
            needed_tickers.add(ticker)

    # 필요 종목 현재가 일괄 조회
    prices = get_current_prices(list(needed_tickers))

    lines = ["<b>📊 [BST 봇] 실시간 감시 및 포지션 현황</b>\n"]

    # 1. 보유 코인의 경우: 현재가, 손절가, 보유 비율, 현재 수익률
    lines.append(f"<b>[1. 보유 코인 ({len(holding_items)}개)]</b>")
    if holding_items:
        for ticker, st in holding_items:
            curr_p = prices.get(ticker)
            entry_p = st.get("entry_price", 0.0)
            stop_p = st.get("effective_ref_low", 0.0)
            rem_pct = int(round(st.get("remaining_ratio", 1.0) * 100))
            ref_d = st.get("active_ref_date", "-")

            curr_str = format_price(curr_p) if curr_p else "-"
            if curr_p and entry_p > 0:
                pnl_pct = (curr_p - entry_p) / entry_p * 100
                pnl_str = f"{pnl_pct:+.2f}%"
            else:
                pnl_str = "-"

            lines.append(
                f"• <b>{ticker}</b>: 현재가 {curr_str} (수익률 {pnl_str}) | 손절가 {format_price(stop_p)} | "
                f"보유 비율 {rem_pct}% (평단 {format_price(entry_p)} | 기준일 {ref_d})"
            )
    else:
        lines.append("<i>보유 중인 코인이 없습니다.</i>")
    lines.append("")

    # 2. 미보유 코인 중 기준봉이 있는 코인
    # - 일반 기준봉 감시 중: 기준봉의 고가, 중심가, 손절가, 적절한 위치의 현재가
    # - 매도가가 기준가인 상태: 기준가와 현재가 정보
    has_ref_count = len(watching_items) + len(reentry_items)
    lines.append(f"<b>[2. 미보유 코인 (기준봉 O) ({has_ref_count}개)]</b>")
    if has_ref_count > 0:
        # 일반 감시 코인
        for ticker, st in watching_items:
            ref_d = st.get("active_ref_date", "-")
            tag = "수동" if st.get("manual_registered") else "자동"
            ref_h = st.get("ref_high", 0.0)
            ref_l = st.get("effective_ref_low", 0.0)
            ref_m = st.get("ref_mid", 0.0)
            if not ref_m and ref_h and ref_l:
                ref_m = ref_l + (ref_h - ref_l) * 0.5

            curr_p = prices.get(ticker)
            order_str = format_watching_price_order(ref_h, ref_m, ref_l, curr_p)
            lines.append(f"• <b>{ticker}</b> [{tag} | 기준일 {ref_d}]\n  └ {order_str}")

        # 매도가가 기준가인 상태 (재매수 대기)
        for ticker, st in reentry_items:
            base_p = st.get("base_price", 0.0)
            ref_d = st.get("active_ref_date", "-")
            curr_p = prices.get(ticker)
            curr_str = format_price(curr_p) if curr_p else "-"
            lines.append(
                f"• <b>{ticker}</b> [재매수 대기 | 기준일 {ref_d}]\n  └ 기준가 {format_price(base_p)} | 현재가 {curr_str}"
            )
    else:
        lines.append("<i>기준봉이 있는 미보유 코인이 없습니다.</i>")
    lines.append("")

    # 3. 미보유 코인 중 기준봉이 없는 코인의 경우: 코인명 정보만
    avail_info = get_available_tickers(STATE_FILE)
    unregistered_tickers = [ticker for _, ticker in avail_info["tickers_list"]]
    coin_names = [t.replace("KRW-", "") for t in unregistered_tickers]

    lines.append(f"<b>[3. 미보유 코인 (기준봉 X) ({len(coin_names)}개)]</b>")
    if coin_names:
        lines.append(f"• {', '.join(coin_names)}")
        lines.append("💡 <i>기준봉 수동 등록: <code>/setref</code></i>")
    else:
        lines.append("<i>모든 감시 대상 코인이 보유 중이거나 기준봉 등록 상태입니다.</i>")

    send_message(chat_id, "\n".join(lines))


def handle_setref_command(chat_id, args=""):
    """기준봉 등록 명령어 처리"""
    args = args.strip()

    # 1. 단축 명령 처리: /setref <번호|티커> <날짜>
    if args:
        parts = args.split()
        if len(parts) >= 2:
            target_arg = parts[0].strip().upper()
            date_arg = parts[1].strip()

            avail_info = get_available_tickers(STATE_FILE)
            ticker = None
            if target_arg.isdigit():
                num = int(target_arg)
                ticker = avail_info["num_to_ticker"].get(num)
                if not ticker:
                    send_message(chat_id, f"❌ 입력하신 번호({num})는 등록 가능 목록에 없습니다.")
                    return
            else:
                ticker = target_arg if target_arg.startswith("KRW-") else f"KRW-{target_arg}"

            send_message(chat_id, f"⏳ <b>[{ticker}]</b> {date_arg} 일봉 데이터 검증 중...")
            ok, result = validate_and_register_manual_ref(ticker, date_arg, STATE_FILE)
            if ok:
                send_registration_success(chat_id, result)
            else:
                send_message(chat_id, f"{result}")
            return

    # 2. 대화형 인터페이스: 미등록 코인 목록 및 인라인 버튼 안내
    avail_info = get_available_tickers(STATE_FILE)
    tickers_list = avail_info["tickers_list"]

    if not tickers_list:
        send_message(
            chat_id,
            "ℹ️ 현재 기준봉을 수동 등록할 수 있는 미등록 코인이 없습니다.\n(모든 코인이 이미 기준봉이 있거나 보유 중입니다.)",
        )
        return

    # 인라인 키보드 생성 (한 줄에 3~4개씩 버튼 배치)
    inline_keyboard = []
    row = []
    text_list_lines = []

    for num, ticker in tickers_list:
        symbol = ticker.replace("KRW-", "")
        row.append({"text": f"{num}. {symbol}", "callback_data": f"sel_{ticker}"})
        text_list_lines.append(f"<b>{num}.</b> {ticker}")
        if len(row) == 3:
            inline_keyboard.append(row)
            row = []
    if row:
        inline_keyboard.append(row)

    # 3열 텍스트 목록 포맷팅
    text_content = (
        "<b>📌 [BST 봇] 수동 기준봉 등록 대상 코인</b>\n\n"
        "아래 버튼을 터치하거나 번호(예: <code>1</code>)를 텍스트로 입력하세요:\n\n"
        + "\n".join(text_list_lines)
        + "\n\n<i>취소하려면 /cancel 을 입력하세요.</i>"
    )

    reply_markup = {"inline_keyboard": inline_keyboard}

    # 세션 기록 (번호 매핑 저장)
    user_sessions[chat_id] = {
        "step": "WAIT_TICKER",
        "ticker_map": avail_info["num_to_ticker"],
        "expire_at": time.time() + SESSION_TIMEOUT_SEC,
    }

    send_message(chat_id, text_content, reply_markup=reply_markup)


def handle_ticker_selected(chat_id, ticker):
    """코인이 선택되었을 때 날짜 입력을 요청하는 단계"""
    user_sessions[chat_id] = {
        "step": "WAIT_DATE",
        "ticker": ticker,
        "expire_at": time.time() + SESSION_TIMEOUT_SEC,
    }

    msg = (
        f"선택된 코인: <b>{ticker}</b>\n\n"
        f"지정할 기준봉의 날짜를 입력해주세요.\n"
        f"• <b>입력 형식</b>: <code>YYYY-MM-DD</code> (예: <code>2026-03-15</code>)\n"
        f"• <b>유효 조건</b>: 최근 20일 이내 마감 확정 일봉\n\n"
        f"<i>취소하려면 /cancel 을 입력하세요.</i>"
    )
    send_message(chat_id, msg)


def handle_date_input(chat_id, date_str):
    """날짜를 입력받아 기준봉 검증 및 등록 집행"""
    session = user_sessions.get(chat_id)
    if not session or session.get("step") != "WAIT_DATE":
        return

    ticker = session["ticker"]
    date_str = date_str.strip()

    send_message(chat_id, f"⏳ <b>[{ticker}]</b> {date_str} 일봉 데이터 조회 및 손절선 검증 중...")

    ok, result = validate_and_register_manual_ref(ticker, date_str, STATE_FILE)
    if ok:
        user_sessions.pop(chat_id, None)
        send_registration_success(chat_id, result)
    else:
        msg = f"{result}\n\n👉 <i>다른 날짜를 다시 입력하시거나, 취소하려면 /cancel 을 입력하세요.</i>"
        send_message(chat_id, msg)


def send_registration_success(chat_id, res):
    """등록 성공 축하 및 상세 안내 메시지"""
    ticker = res["ticker"]
    ref_date = res["ref_date"]
    ref_high = res["ref_high"]
    ref_mid = res["ref_mid"]
    ref_low = res["effective_ref_low"]
    ref_age = res["ref_age_days"]
    rem_days = res["remaining_days"]
    wave_h = res["wave_height"]
    rise_dur = res["rise_duration"]
    curr_c = res["curr_close"]

    msg = (
        f"🎉 <b>[{ticker}] 수동 기준봉 등록 완료!</b>\n\n"
        f"• <b>기준일</b>: {ref_date} ({ref_age}일 경과 / 잔여 유효 <b>{rem_days}일</b>)\n"
        f"• <b>실시간 현재가</b>: {format_price(curr_c)}\n"
        f"• <b>돌파 매수 기준가(고가)</b>: <b>{format_price(ref_high)}</b>\n"
        f"• <b>눌림 매수 기준가(중심가)</b>: <b>{format_price(ref_mid)}</b> (50% 지지)\n"
        f"• <b>손절 기준선(저가)</b>: <b>{format_price(ref_low)}</b>\n"
        f"• <b>1차 파동 높이</b>: {format_price(wave_h)} ({rise_dur}일간 상승)\n\n"
        f"💡 <i>5분 주기 트레이딩 봇이 다음 실행부터 실시간 돌파/눌림목 매수 감시를 시작합니다.</i>"
    )
    send_message(chat_id, msg)


def handle_cancelref_command(chat_id, args=""):
    """등록된 기준봉 감시 수동 취소"""
    args = args.strip()
    state = load_state(STATE_FILE)

    if args:
        target = args.upper()
        if not target.startswith("KRW-"):
            target = f"KRW-{target}"
        ok, msg = cancel_manual_ref(target, STATE_FILE)
        send_message(chat_id, msg)
        return

    # 취소 가능한 활성 기준봉 목록 추출 (미보유 종목)
    cancelable = []
    for ticker, st in state.items():
        if st.get("active_ref_date") and not (
            st.get("entry_bought", False) and st.get("remaining_ratio", 0) > 0
        ):
            cancelable.append((ticker, st.get("active_ref_date")))

    if not cancelable:
        send_message(chat_id, "ℹ️ 현재 취소 가능한(보유 중이지 않은) 활성 기준봉이 없습니다.")
        return

    inline_keyboard = []
    for ticker, ref_d in cancelable:
        inline_keyboard.append(
            [{"text": f"❌ {ticker} ({ref_d}) 해제", "callback_data": f"cancel_{ticker}"}]
        )

    send_message(
        chat_id,
        "<b>취소할 기준봉 종목을 선택하세요:</b>",
        reply_markup={"inline_keyboard": inline_keyboard},
    )


def process_update(update):
    """단일 텔레그램 Update 이벤트 처리"""
    # 1. 인라인 버튼 콜백 (Callback Query)
    if "callback_query" in update:
        cb = update["callback_query"]
        cb_id = cb["id"]
        chat_id = cb["message"]["chat"]["id"]
        data = cb.get("data", "")

        if not is_authorized(chat_id):
            answer_callback_query(cb_id, "권한이 없습니다.")
            return

        if data.startswith("sel_"):
            ticker = data[4:]
            answer_callback_query(cb_id)
            handle_ticker_selected(chat_id, ticker)
        elif data.startswith("cancel_"):
            ticker = data[7:]
            answer_callback_query(cb_id)
            ok, msg = cancel_manual_ref(ticker, STATE_FILE)
            send_message(chat_id, msg)
        return

    # 2. 일반 텍스트 메시지 (Message)
    if "message" in update:
        msg = update["message"]
        chat_id = msg["chat"]["id"]
        text = msg.get("text", "").strip()

        if not text:
            return

        if not is_authorized(chat_id):
            print(f"[telegram_commander] 미인가 접근 차단 (chat_id: {chat_id})")
            return

        # 명령어 분기
        cmd_parts = text.split(maxsplit=1)
        cmd = cmd_parts[0].lower()
        args = cmd_parts[1] if len(cmd_parts) > 1 else ""

        if cmd in ["/start", "/help", "도움말"]:
            handle_help_command(chat_id)
            return
        elif cmd in ["/status", "/현황", "현황"]:
            handle_status_command(chat_id)
            return
        elif cmd in ["/setref", "/기준봉", "기준봉"]:
            handle_setref_command(chat_id, args)
            return
        elif cmd in ["/cancelref", "/취소"]:
            handle_cancelref_command(chat_id, args)
            return
        elif cmd in ["/cancel", "취소"]:
            if chat_id in user_sessions:
                user_sessions.pop(chat_id, None)
                send_message(chat_id, "진행 중인 입력 세션이 취소되었습니다.")
            else:
                send_message(chat_id, "진행 중인 세션이 없습니다.")
            return

        # 세션 대화 단계 처리
        session = user_sessions.get(chat_id)
        if session:
            # 세션 만료 체크
            if time.time() > session.get("expire_at", 0):
                user_sessions.pop(chat_id, None)
                send_message(chat_id, "⌛ 입력 시간이 초과(3분)되어 세션이 만료되었습니다. 다시 /setref 를 입력해 주세요.")
                return

            step = session.get("step")
            if step == "WAIT_TICKER":
                # 번호 입력 또는 티커 직접 입력
                ticker_map = session.get("ticker_map", {})
                if text.isdigit() and int(text) in ticker_map:
                    selected_ticker = ticker_map[int(text)]
                    handle_ticker_selected(chat_id, selected_ticker)
                else:
                    upper_t = text.upper()
                    matched = None
                    for t in ticker_map.values():
                        if t == upper_t or t == f"KRW-{upper_t}":
                            matched = t
                            break
                    if matched:
                        handle_ticker_selected(chat_id, matched)
                    else:
                        send_message(chat_id, "올바른 번호를 입력해 주세요. (취소: /cancel)")
                return

            elif step == "WAIT_DATE":
                # 날짜 입력 (YYYY-MM-DD)
                handle_date_input(chat_id, text)
                return

        # 알 수 없는 메시지인 경우 안내
        if text.startswith("/"):
            send_message(chat_id, "알 수 없는 명령어입니다. /help 를 입력하여 사용법을 확인하세요.")


def run_poller():
    """텔레그램 롱폴링 메인 루프"""
    print("=" * 60)
    print("🚀 [telegram_commander] 텔레그램 커맨더 데몬 시작")
    print(f"• 토큰 설정: {'정상' if BOT_TOKEN else '미설정 (오류)'}")
    print(f"• 인가 채팅 ID: {AUTHORIZED_CHAT_ID if AUTHORIZED_CHAT_ID else '전체 허용'}")
    print("• 종료하려면 Ctrl+C 를 누르세요.")
    print("=" * 60)

    if not BOT_TOKEN:
        print("❌ TELEGRAM_BOT_TOKEN 이 설정되어 있지 않아 데몬을 시작할 수 없습니다.")
        sys.exit(1)

    # 기존 잔존 웹훅(Webhook) 해제 (getUpdates 롱폴링 충돌 사전 방지)
    try:
        del_wh_res = requests.get(f"{TELEGRAM_API_URL}/deleteWebhook", timeout=5).json()
        if del_wh_res.get("ok"):
            print("• 기존 웹훅 상태 점검 및 해제 완료 (롱폴링 준비 완료)")
    except Exception as e:
        print(f"• 웹훅 점검 중 경고 (무시 가능): {e}")

    offset = None
    while True:
        try:
            url = f"{TELEGRAM_API_URL}/getUpdates"
            params = {"timeout": 20}
            if offset:
                params["offset"] = offset

            res = requests.get(url, params=params, timeout=25)
            if res.status_code == 200:
                data = res.json()
                if data.get("ok"):
                    for update in data.get("result", []):
                        offset = update["update_id"] + 1
                        try:
                            process_update(update)
                        except Exception as e:
                            print(f"[telegram_commander] 업데이트 처리 중 오류: {e}")
            elif res.status_code == 409:
                err_data = res.json() if res.headers.get("content-type", "").startswith("application/json") else {}
                err_desc = err_data.get("description", "")
                if "webhook" in err_desc.lower():
                    print("[telegram_commander] 잔여 웹훅 감지 -> deleteWebhook 자동 실행...")
                    try:
                        requests.get(f"{TELEGRAM_API_URL}/deleteWebhook", timeout=5)
                    except Exception:
                        pass
                else:
                    print("[telegram_commander] 다른 인스턴스에서 getUpdates 중복 실행 감지. 5초 대기...")
                time.sleep(5)
            else:
                print(f"[telegram_commander] getUpdates 실패: HTTP {res.status_code}")
                time.sleep(3)

        except requests.exceptions.Timeout:
            continue
        except requests.exceptions.ConnectionError:
            time.sleep(3)
        except KeyboardInterrupt:
            print("\n👋 [telegram_commander] 사용자에 의해 데몬이 종료되었습니다.")
            break
        except Exception as e:
            print(f"[telegram_commander] 루프 예외: {e}")
            time.sleep(2)


if __name__ == "__main__":
    run_poller()
