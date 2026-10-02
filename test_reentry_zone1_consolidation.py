# test_reentry_zone1_consolidation.py
import unittest
from unittest.mock import MagicMock, patch
import pandas as pd
import Upbit_Anchor_Wave_Bot as bot


class TestReentryZone1Consolidation(unittest.TestCase):

    def setUp(self):
        bot.AUTO_TRADE_EXECUTE = False

    def test_zone1_reentry_consolidates_order_and_message(self):
        """Zone 1 재매수 시 목표 배정액(500,000원) 전액 1회 매수 및 단일 알림 확인"""
        global_state = {
            "KRW-ETH": {
                "active_ref_date": "2026-09-28",
                "ref_high": 3690000.0,
                "effective_ref_low": 3600000.0,
                "anchor_low": 3600000.0,
                "ref_mid": 3645000.0,
                "entry_bought": False,
                "entry_price": 0.0,
                "total_volume": 0.0,
                "remaining_ratio": 0.0,
                "base_price": 3625000.0,
                "base_amount": 486174.0,
                "base_price_date": "2026-09-30",
                "target_buy_amount": 500000.0,
                "scale_in_count": 0,
                "rise_duration": 7,
                "wave_height": 546000.0,
            }
        }

        # 30일치 데이터: 현재가 3,691,000원 (ref_high 3,690,000 돌파), 5일선 우상향
        dates = pd.date_range("2026-09-01", periods=30, freq="D")
        closes = [3600000.0] * 25 + [3610000.0, 3620000.0, 3650000.0, 3670000.0, 3691000.0]
        df = pd.DataFrame(
            {
                "open": closes,
                "high": [c + 10000.0 for c in closes],
                "low": [c - 10000.0 for c in closes],
                "close": closes,
                "volume": [100.0] * 30,
            },
            index=dates,
        )

        mock_upbit = MagicMock()
        buy_calls = []

        def mock_buy(client, ticker, amount, price):
            buy_calls.append({"amount": amount, "price": price})
            return {
                "ok": True,
                "price": price,
                "volume": amount / price,
                "amount": amount,
            }

        sent_messages = []

        def mock_send(msg):
            sent_messages.append(msg)

        with patch.object(bot, "execute_buy", side_effect=mock_buy):
            with patch.object(bot, "SendMessage", side_effect=mock_send):
                with patch.object(bot, "save_trade_to_google_sheet"):
                    bot.process_ticker_strategy("KRW-ETH", df, mock_upbit, global_state)

        # 1. execute_buy가 정확히 1회만 호출되었는지 확인 (500,000원 전액)
        self.assertEqual(len(buy_calls), 1, f"매수 주문이 1회가 아닌 {len(buy_calls)}회 호출됨")
        self.assertEqual(buy_calls[0]["amount"], 500000.0)

        # 2. 텔레그램 메시지가 1건만 발송되었는지 확인
        self.assertEqual(len(sent_messages), 1, f"텔레그램 메시지가 1건이 아닌 {len(sent_messages)}건 발송됨")
        self.assertIn("고가 돌파 재매수 완료! (Zone 1 BREAKOUT ALL-IN)", sent_messages[0])
        self.assertIn("KRW-ETH", sent_messages[0])
        self.assertIn("500,000원", sent_messages[0])

        # 3. 포지션 상태 검증
        st = global_state["KRW-ETH"]
        self.assertTrue(st["entry_bought"])
        self.assertEqual(st["remaining_ratio"], 1.0)
        self.assertEqual(st["scale_in_count"], 3)
        self.assertIsNone(st["base_price"])
        self.assertEqual(st["target_buy_amount"], 500000.0)

    def test_zone2_reentry_keeps_base_amount(self):
        """Zone 2 재매수 시에는 직전 매도 금액(486,174원)만 매수되고 고가 돌파 잔액 매수가 즉시 발동하지 않는지 확인"""
        global_state = {
            "KRW-ETH": {
                "active_ref_date": "2026-09-28",
                "ref_high": 3700000.0,
                "effective_ref_low": 3600000.0,
                "anchor_low": 3600000.0,
                "ref_mid": 3640000.0,
                "entry_bought": False,
                "entry_price": 0.0,
                "total_volume": 0.0,
                "remaining_ratio": 0.0,
                "base_price": 3625000.0,
                "base_amount": 486174.0,
                "base_price_date": "2026-09-30",
                "target_buy_amount": 500000.0,
                "scale_in_count": 0,
                "atr": 10000.0,
                "trough_low": 3625000.0,
                "rise_duration": 7,
                "wave_height": 546000.0,
            }
        }

        # 현재가 3,680,000원 (ref_mid 3,640,000원과 ref_high 3,700,000원 사이 -> Zone 2)
        dates = pd.date_range("2026-09-01", periods=30, freq="D")
        closes = [3600000.0] * 25 + [3610000.0, 3620000.0, 3630000.0, 3650000.0, 3680000.0]
        df = pd.DataFrame(
            {
                "open": closes,
                "high": [c + 1000.0 for c in closes],
                "low": [c - 1000.0 for c in closes],
                "close": closes,
                "volume": [100.0] * 30,
            },
            index=dates,
        )

        mock_upbit = MagicMock()
        buy_calls = []

        def mock_buy(client, ticker, amount, price):
            buy_calls.append({"amount": amount, "price": price})
            return {
                "ok": True,
                "price": price,
                "volume": amount / price,
                "amount": amount,
            }

        sent_messages = []

        def mock_send(msg):
            sent_messages.append(msg)

        with patch.object(bot, "execute_buy", side_effect=mock_buy):
            with patch.object(bot, "SendMessage", side_effect=mock_send):
                with patch.object(bot, "save_trade_to_google_sheet"):
                    bot.process_ticker_strategy("KRW-ETH", df, mock_upbit, global_state)

        # Zone 2: 직전 매도금액(486,174원) 1회만 매수
        self.assertEqual(len(buy_calls), 1)
        self.assertEqual(buy_calls[0]["amount"], 486174.0)

        # 텔레그램 메시지 1건 (Zone 2)
        self.assertEqual(len(sent_messages), 1)
        self.assertIn("Zone 2 (하이브리드 2*N 반등)", sent_messages[0])


if __name__ == "__main__":
    unittest.main()
