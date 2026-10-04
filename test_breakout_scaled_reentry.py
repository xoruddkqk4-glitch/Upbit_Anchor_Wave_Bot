# test_breakout_scaled_reentry.py
# 돌파 매수 1/3 분할 진입, 보유 중 1/3 추가 매수, 고가 위 청산 후 피라미딩 재매수 단위 검증

import unittest
from unittest.mock import MagicMock, patch
import pandas as pd
import Upbit_Anchor_Wave_Bot as bot


class TestBreakoutScaledReentry(unittest.TestCase):

    def setUp(self):
        bot.AUTO_TRADE_EXECUTE = False

    def _make_state(self, overrides=None):
        st = bot.new_ticker_state()
        st.update({
            "active_ref_date": "2026-03-25",
            "ref_high": 1000.0,
            "effective_ref_low": 900.0,
            "anchor_low": 900.0,
            "ref_mid": 950.0,
            "rise_duration": 5,
            "wave_height": 200.0,
            "target_buy_amount": 500000.0,
            "entry_bought": False,
            "remaining_ratio": 0.0,
        })
        if overrides:
            st.update(overrides)
        return {"KRW-BTC": st}

    def test_new_breakout_buys_one_third(self):
        """신규 돌파 발생 시 목표 배정액(500,000원)의 1/3만 1차 진입하고 scale_in_count=1 확인"""
        global_state = self._make_state({
            "entry_bought": False,
            "scale_in_count": 0,
        })

        # 30일치 데이터 (마지막 날 2026-03-30, active_ref_date 2026-03-25로부터 5일 경과)
        dates = pd.date_range("2026-03-01", periods=30, freq="D")
        df = pd.DataFrame(
            {
                "open": [980.0] * 29 + [1000.0],
                "high": [990.0] * 29 + [1020.0],
                "low": [970.0] * 29 + [995.0],
                "close": [980.0] * 29 + [1010.0],
                "volume": [1000.0] * 30,
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

        with patch.object(bot, "execute_buy", side_effect=mock_buy):
            with patch.object(bot, "SendMessage"):
                with patch.object(bot, "save_trade_to_google_sheet"):
                    bot.process_ticker_strategy("KRW-BTC", df, mock_upbit, global_state)

        # 50만 원의 1/3인 약 166,666.67원 매수 확인
        self.assertEqual(len(buy_calls), 1)
        expected_tranche = 500000.0 / 3.0
        self.assertAlmostEqual(buy_calls[0]["amount"], expected_tranche, delta=1.0)

        st = global_state["KRW-BTC"]
        self.assertTrue(st["entry_bought"])
        self.assertEqual(st["scale_in_count"], 1)
        self.assertEqual(st["target_buy_amount"], 500000.0)
        self.assertEqual(st["breakout_date"], dates[-1].strftime("%Y-%m-%d"))

    def test_breakout_add_buys_one_third(self):
        """1/3 보유 중 돌파 시 1/3 추가 매수하여 scale_in_count=2 확인"""
        global_state = self._make_state({
            "entry_bought": True,
            "entry_price": 950.0,
            "total_volume": 166666.67 / 950.0,  # 1/3 진입된 상태
            "remaining_ratio": 1.0,
            "scale_in_count": 1,
            "last_scale_in_date": "2026-03-29",  # 어제 일봉
            "symmetry_tp_executed": False,
            "price_tp_executed": False,
        })

        dates = pd.date_range("2026-03-01", periods=30, freq="D")
        df = pd.DataFrame(
            {
                "open": [980.0] * 29 + [1000.0],
                "high": [990.0] * 29 + [1020.0],
                "low": [970.0] * 29 + [995.0],
                "close": [980.0] * 29 + [1010.0],
                "volume": [1000.0] * 30,
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

        with patch.object(bot, "execute_buy", side_effect=mock_buy):
            with patch.object(bot, "SendMessage"):
                with patch.object(bot, "save_trade_to_google_sheet"):
                    bot.process_ticker_strategy("KRW-BTC", df, mock_upbit, global_state)

        # 1/3 추가 매수 확인
        self.assertEqual(len(buy_calls), 1)
        expected_tranche = 500000.0 / 3.0
        self.assertAlmostEqual(buy_calls[0]["amount"], expected_tranche, delta=1.0)

        st = global_state["KRW-BTC"]
        self.assertEqual(st["scale_in_count"], 2)

    def test_breakout_add_caps_at_max_amount(self):
        """35만 원 이미 투자된 상태에서 돌파 시 잔여 금액(15만 원)만 매수되어 50만 원 상한 준수"""
        initial_invested = 350000.0
        global_state = self._make_state({
            "entry_bought": True,
            "entry_price": 950.0,
            "total_volume": initial_invested / 950.0,
            "remaining_ratio": 1.0,
            "scale_in_count": 2,
            "last_scale_in_date": "2026-03-29",
            "symmetry_tp_executed": False,
            "price_tp_executed": False,
        })

        dates = pd.date_range("2026-03-01", periods=30, freq="D")
        df = pd.DataFrame(
            {
                "open": [980.0] * 29 + [1000.0],
                "high": [990.0] * 29 + [1020.0],
                "low": [970.0] * 29 + [995.0],
                "close": [980.0] * 29 + [1010.0],
                "volume": [1000.0] * 30,
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

        with patch.object(bot, "execute_buy", side_effect=mock_buy):
            with patch.object(bot, "SendMessage"):
                with patch.object(bot, "save_trade_to_google_sheet"):
                    bot.process_ticker_strategy("KRW-BTC", df, mock_upbit, global_state)

        # 50만 원 - 35만 원 = 15만 원만 매수되어 50만 원 초과하지 않음
        self.assertEqual(len(buy_calls), 1)
        self.assertAlmostEqual(buy_calls[0]["amount"], 150000.0, delta=1.0)

        st = global_state["KRW-BTC"]
        self.assertEqual(st["scale_in_count"], 3)

    def test_zone1_reentry_adds_one_third_to_base_amount(self):
        """고가 위 청산(base_amount=170,000원) 후 Zone 1 재매수 시 17만 + 1/3(16.6만) = 약 33.6만 원 매수 확인"""
        global_state = self._make_state({
            "entry_bought": False,
            "base_price": 1050.0,  # 1050원에 고가 위 청산
            "base_amount": 170000.0,  # 17만 원 회수
            "base_price_date": "2026-03-28",
            "scale_in_count": 0,
        })

        # 현재가 1060원 (매도가 1050원 돌파 & ref_high 1000원 돌파), 5일선 우상향
        dates = pd.date_range("2026-03-01", periods=30, freq="D")
        closes = [1000.0] * 25 + [1010.0, 1020.0, 1030.0, 1040.0, 1060.0]
        df = pd.DataFrame(
            {
                "open": closes,
                "high": [c + 10.0 for c in closes],
                "low": [c - 10.0 for c in closes],
                "close": closes,
                "volume": [1000.0] * 30,
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

        with patch.object(bot, "execute_buy", side_effect=mock_buy):
            with patch.object(bot, "SendMessage"):
                with patch.object(bot, "save_trade_to_google_sheet"):
                    bot.process_ticker_strategy("KRW-BTC", df, mock_upbit, global_state)

        # 170,000원 + 166,666.67원 = 약 336,666.67원 매수 확인
        self.assertEqual(len(buy_calls), 1)
        expected_amount = 170000.0 + (500000.0 / 3.0)
        self.assertAlmostEqual(buy_calls[0]["amount"], expected_amount, delta=1.0)

        st = global_state["KRW-BTC"]
        self.assertTrue(st["entry_bought"])
        self.assertEqual(st["scale_in_count"], 2)  # 약 2/3 수준
        self.assertEqual(st["target_buy_amount"], 500000.0)

    def test_zone1_reentry_caps_at_max_amount(self):
        """고가 위 청산(base_amount=400,000원) 후 Zone 1 재매수 시 40만 + 16.6만 = 56.6만 원이지만 50만 원 상한에 걸림 확인"""
        global_state = self._make_state({
            "entry_bought": False,
            "base_price": 1050.0,
            "base_amount": 400000.0,  # 40만 원 회수
            "base_price_date": "2026-03-28",
            "scale_in_count": 0,
        })

        dates = pd.date_range("2026-03-01", periods=30, freq="D")
        closes = [1000.0] * 25 + [1010.0, 1020.0, 1030.0, 1040.0, 1060.0]
        df = pd.DataFrame(
            {
                "open": closes,
                "high": [c + 10.0 for c in closes],
                "low": [c - 10.0 for c in closes],
                "close": closes,
                "volume": [1000.0] * 30,
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

        with patch.object(bot, "execute_buy", side_effect=mock_buy):
            with patch.object(bot, "SendMessage"):
                with patch.object(bot, "save_trade_to_google_sheet"):
                    bot.process_ticker_strategy("KRW-BTC", df, mock_upbit, global_state)

        # 500,000원 상한 매수 확인
        self.assertEqual(len(buy_calls), 1)
        self.assertEqual(buy_calls[0]["amount"], 500000.0)

        st = global_state["KRW-BTC"]
        self.assertEqual(st["scale_in_count"], 3)


if __name__ == "__main__":
    unittest.main()
