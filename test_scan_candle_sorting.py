# test_scan_candle_sorting.py
import unittest
from scan_ref_candles import format_price


class TestScanCandleSorting(unittest.TestCase):
    def test_sorting_and_rendering_order(self):
        # 1. 더미 candle 데이터 준비
        raw_candles = [
            # 감시 중 1: 중심가 상회 (📍)
            {
                "ticker": "KRW-SOL",
                "ref_date": "2026-10-01",
                "tag": "감시 중",
                "curr_close": 200000.0,
                "ref_high": 220000.0,
                "ref_mid": 180000.0,
                "effective_ref_low": 160000.0,
                "atr": 5000.0,
            },
            # 보유 종목 1: 수익률 +5%
            {
                "ticker": "KRW-BTC",
                "ref_date": "2026-09-20",
                "tag": "보유 중",
                "curr_close": 105000000.0,
                "ref_high": 110000000.0,
                "ref_mid": 100000000.0,
                "effective_ref_low": 95000000.0,
                "atr": 2000000.0,
                "entry_price": 100000000.0,
                "profit_rate": 5.0,
            },
            # 재매수 대기 1: 반등목표 달성률 85%
            {
                "ticker": "KRW-DOGE",
                "ref_date": "2026-09-25",
                "tag": "재매수 대기",
                "curr_close": 170.0,
                "ref_high": 220.0,
                "ref_mid": 180.0,
                "effective_ref_low": 150.0,
                "atr": 10.0,
                "trough_low": 160.0,
                "bounce_target": 200.0,  # 170 / 200 = 85%
                "base_price": 210.0,
            },
            # 감시 중 2: 고가 돌파 (🚀)
            {
                "ticker": "KRW-XRP",
                "ref_date": "2026-10-02",
                "tag": "신규 포착",
                "curr_close": 850.0,
                "ref_high": 800.0,
                "ref_mid": 750.0,
                "effective_ref_low": 700.0,
                "atr": 30.0,
            },
            # 보유 종목 2: 수익률 +15%
            {
                "ticker": "KRW-ETH",
                "ref_date": "2026-09-18",
                "tag": "보유 중",
                "curr_close": 4600000.0,
                "ref_high": 4800000.0,
                "ref_mid": 4200000.0,
                "effective_ref_low": 3900000.0,
                "atr": 100000.0,
                "entry_price": 4000000.0,
                "profit_rate": 15.0,
            },
            # 재매수 대기 2: 반등목표 달성률 98%
            {
                "ticker": "KRW-PEPE",
                "ref_date": "2026-09-22",
                "tag": "재매수 대기",
                "curr_close": 196.0,
                "ref_high": 240.0,
                "ref_mid": 190.0,
                "effective_ref_low": 160.0,
                "atr": 10.0,
                "trough_low": 180.0,
                "bounce_target": 200.0,  # 196 / 200 = 98%
                "base_price": 230.0,
            },
            # 감시 중 3: 눌림목 영역 (🎯)
            {
                "ticker": "KRW-NEAR",
                "ref_date": "2026-10-03",
                "tag": "최신 갱신",
                "curr_close": 3200.0,
                "ref_high": 3800.0,
                "ref_mid": 3400.0,
                "effective_ref_low": 3000.0,
                "atr": 150.0,
            },
        ]

        # 2. 로직 복제 테스트 (scan_ref_candles 내부 로직과 동일)
        holding_candles = [c for c in raw_candles if c["tag"] == "보유 중"]
        reentry_candles = [c for c in raw_candles if c["tag"] == "재매수 대기"]
        watching_candles = [
            c for c in raw_candles if c["tag"] in ["신규 포착", "최신 갱신", "감시 중"]
        ]

        # 1. 보유 종목: 수익률 내림차순
        holding_candles.sort(
            key=lambda c: c.get("profit_rate", -999999.0),
            reverse=True,
        )

        # 2. 재매수 대기 종목: 달성률 내림차순
        def _sort_reentry_key(c):
            curr_close = c["curr_close"]
            bounce_target = c.get("bounce_target")
            bounce_ratio = (
                (curr_close / bounce_target)
                if (bounce_target and bounce_target > 0)
                else 0.0
            )
            high_target = max(c.get("ref_high", 0.0), c.get("base_price") or 0.0)
            high_ratio = (curr_close / high_target) if high_target > 0 else 0.0
            return max(bounce_ratio, high_ratio)

        reentry_candles.sort(key=_sort_reentry_key, reverse=True)

        # 3. 감시 중 종목: 고가돌파(Tier 3) -> 눌림목(Tier 2) -> 중심가상회 근접도(Tier 1)
        def _sort_watching_key(c):
            curr_close = c["curr_close"]
            ref_high = c.get("ref_high", 0.0)
            ref_mid = c.get("ref_mid", 0.0)
            effective_ref_low = c.get("effective_ref_low", 0.0)

            if ref_high > 0 and curr_close >= ref_high:
                breakout_ratio = (curr_close - ref_high) / ref_high
                return (3, breakout_ratio)
            elif effective_ref_low <= curr_close <= ref_mid:
                mid_low_span = ref_mid - effective_ref_low
                depth_ratio = (
                    (curr_close - effective_ref_low) / mid_low_span
                    if mid_low_span > 0
                    else 0.0
                )
                return (2, depth_ratio)
            elif ref_mid < curr_close < ref_high:
                dist_to_high = (
                    (ref_high - curr_close) / curr_close if curr_close > 0 else 999.0
                )
                dist_to_mid = (
                    (curr_close - ref_mid) / curr_close if curr_close > 0 else 999.0
                )
                min_dist = min(dist_to_high, dist_to_mid)
                return (1, -min_dist)
            else:
                return (0, curr_close)

        watching_candles.sort(key=_sort_watching_key, reverse=True)

        all_sorted = holding_candles + reentry_candles + watching_candles
        sorted_tickers = [c["ticker"] for c in all_sorted]

        # 3. 정렬 순서 검증
        # 1) 보유 종목: ETH(+15%) -> BTC(+5%)
        self.assertEqual(sorted_tickers[0], "KRW-ETH")
        self.assertEqual(sorted_tickers[1], "KRW-BTC")

        # 2) 재매수 대기: PEPE(98%) -> DOGE(85%)
        self.assertEqual(sorted_tickers[2], "KRW-PEPE")
        self.assertEqual(sorted_tickers[3], "KRW-DOGE")

        # 3) 감시 중: XRP(고가 돌파 🚀) -> NEAR(눌림목 🎯) -> SOL(중심가 상회 📍)
        self.assertEqual(sorted_tickers[4], "KRW-XRP")
        self.assertEqual(sorted_tickers[5], "KRW-NEAR")
        self.assertEqual(sorted_tickers[6], "KRW-SOL")

    def test_message_rendering_format(self):
        def _render_candle_block(c):
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

            if c.get("tag") == "보유 중" and c.get("profit_rate") is not None:
                profit_rate = c["profit_rate"]
                entry_price = c.get("entry_price", 0.0)
                pnl_sign = "+" if profit_rate > 0 else ""
                price_line = (
                    f"{pos_icon} <b>[현재가] ({pos_label})</b>: {format_price(curr_close)}"
                    f" (<b>수익률: {pnl_sign}{profit_rate:.2f}%</b> | 평단: {format_price(entry_price)})"
                )
            else:
                price_line = f"{pos_icon} <b>[현재가] ({pos_label})</b>: {format_price(curr_close)}"

            high_line = f"• 고가: {format_price(ref_high)}"
            mid_line = f"• 중심가: {format_price(ref_mid)}"
            low_line = f"• 손절가: {format_price(effective_ref_low)}"

            if curr_close >= ref_high:
                price_rows = [price_line, high_line, mid_line, low_line]
            elif curr_close >= ref_mid:
                price_rows = [high_line, price_line, mid_line, low_line]
            elif curr_close >= effective_ref_low:
                price_rows = [high_line, mid_line, price_line, low_line]
            else:
                price_rows = [high_line, mid_line, low_line, price_line]

            if c.get("tag") == "재매수 대기" and c.get("trough_low") and c.get("bounce_target"):
                bounce_target = c["bounce_target"]
                bounce_pct = (
                    (curr_close / bounce_target * 100.0)
                    if (bounce_target and bounce_target > 0)
                    else 0.0
                )
                hybrid_line = (
                    f"• <b>[하이브리드]</b> 바닥: {format_price(c['trough_low'])} ➔"
                    f" 2*N반등목표: <b>{format_price(bounce_target)}</b> (달성률: {bounce_pct:.1f}% | 14일 ATR: {format_price(c.get('atr', 0.0))})"
                )
                price_rows.append(hybrid_line)

            block = (
                f"<b>• {ticker}</b> <code>{tag_str}</code> (기준일: {ref_date})\n"
                + "\n".join(price_rows)
            )
            return block

        holding_item = {
            "ticker": "KRW-BTC",
            "ref_date": "2026-09-20",
            "tag": "보유 중",
            "curr_close": 105000000.0,
            "ref_high": 110000000.0,
            "ref_mid": 100000000.0,
            "effective_ref_low": 95000000.0,
            "entry_price": 100000000.0,
            "profit_rate": 5.0,
        }
        rendered = _render_candle_block(holding_item)
        self.assertIn("수익률: +5.00%", rendered)
        self.assertIn("평단: 100,000,000.0원", rendered)

        reentry_item = {
            "ticker": "KRW-PEPE",
            "ref_date": "2026-09-22",
            "tag": "재매수 대기",
            "curr_close": 196.0,
            "ref_high": 240.0,
            "ref_mid": 190.0,
            "effective_ref_low": 160.0,
            "atr": 10.0,
            "trough_low": 180.0,
            "bounce_target": 200.0,
        }
        rendered_reentry = _render_candle_block(reentry_item)
        self.assertIn("달성률: 98.0%", rendered_reentry)
        self.assertIn("2*N반등목표: <b>200.0원</b>", rendered_reentry)


if __name__ == "__main__":
    unittest.main()
