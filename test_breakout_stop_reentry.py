# test_breakout_stop_reentry.py
# 돌파 매수 후 매도가격과 기준봉 고가(ref_high) / 원천 저가(anchor_low) 비교 분기 단위 검증

import unittest
from unittest.mock import MagicMock, patch
import pandas as pd

import Upbit_Anchor_Wave_Bot as bot


class TestBreakoutStopReentry(unittest.TestCase):

    def setUp(self):
        bot.AUTO_TRADE_EXECUTE = False

    def test_sell_below_ref_high_but_anchor_intact_keeps_ref(self):
        """고가 이하 손절이지만 원천 저가 Intact -> 기준봉 유지 + 손절선 복원"""
        global_state = {
            "KRW-BTC": {
                "active_ref_date": "2026-03-10",
                "ref_high": 1000.0,
                "effective_ref_low": 980.0,  # 돌파 -2% 상향 손절
                "anchor_low": 900.0,  # 원천 저가
                "ref_mid": 950.0,
                "rise_duration": 5,
                "wave_height": 200.0,
                "entry_bought": True,
                "entry_price": 1010.0,
                "total_volume": 10.0,
                "remaining_ratio": 1.0,
                "base_price": None,
                "breakout_date": "2026-03-11",
                "last_trailing_stop_date": None,
                "scale_in_count": 3,
                "tiered_tp_executed_levels": [],
            }
        }

        # 현재가 970원: 상향 손절(980) 이탈, 원천 저가(900) Intact
        dates = pd.date_range("2026-03-01", periods=30, freq="D")
        df = pd.DataFrame(
            {
                "open": [990.0] * 30,
                "high": [1020.0] * 30,
                "low": [960.0] * 30,
                "close": [970.0] * 30,
                "volume": [1000.0] * 30,
            },
            index=dates,
        )

        mock_upbit = MagicMock()
        with patch.object(
            bot,
            "execute_sell",
            return_value={"ok": True, "volume": 10.0, "price": 970.0, "amount": 9700.0},
        ):
            with patch.object(bot, "SendMessage"):
                with patch.object(bot, "save_trade_to_google_sheet"):
                    bot.process_ticker_strategy("KRW-BTC", df, mock_upbit, global_state)

        st = global_state["KRW-BTC"]
        self.assertFalse(st["entry_bought"])
        self.assertIsNone(st["base_price"])  # 재매수 대기 아님 → 눌림목 감시
        self.assertEqual(st["active_ref_date"], "2026-03-10")
        self.assertEqual(st["ref_high"], 1000.0)
        self.assertEqual(st["anchor_low"], 900.0)
        self.assertEqual(st["effective_ref_low"], 900.0)  # 원천 저가로 복원
        self.assertIsNone(st["breakout_date"])
        self.assertEqual(st["scale_in_count"], 0)
        self.assertEqual(st["remaining_ratio"], 0.0)

    def test_sell_below_anchor_low_resets_state(self):
        """원천 저가까지 하향 이탈한 손절 -> 상태 완전 초기화"""
        global_state = {
            "KRW-BTC": {
                "active_ref_date": "2026-03-10",
                "ref_high": 1000.0,
                "effective_ref_low": 900.0,  # 이미 원천 저가와 동일(또는 저가 손절)
                "anchor_low": 900.0,
                "ref_mid": 950.0,
                "rise_duration": 5,
                "wave_height": 200.0,
                "entry_bought": True,
                "entry_price": 1010.0,
                "total_volume": 10.0,
                "remaining_ratio": 1.0,
                "base_price": None,
            }
        }

        # 현재가 880원 < 원천 저가 900원 → 구조적 지지 붕괴
        dates = pd.date_range("2026-03-01", periods=30, freq="D")
        df = pd.DataFrame(
            {
                "open": [920.0] * 30,
                "high": [950.0] * 30,
                "low": [870.0] * 30,
                "close": [880.0] * 30,
                "volume": [1000.0] * 30,
            },
            index=dates,
        )

        mock_upbit = MagicMock()
        with patch.object(
            bot,
            "execute_sell",
            return_value={"ok": True, "volume": 10.0, "price": 880.0, "amount": 8800.0},
        ):
            with patch.object(bot, "SendMessage"):
                with patch.object(bot, "save_trade_to_google_sheet"):
                    bot.process_ticker_strategy("KRW-BTC", df, mock_upbit, global_state)

        st = global_state["KRW-BTC"]
        self.assertFalse(st["entry_bought"])
        self.assertIsNone(st["base_price"])
        self.assertIsNone(st["active_ref_date"])

    def test_sell_above_ref_high_enters_reentry_wait(self):
        """기준봉 고가(ref_high) 위에서 매도된 경우 -> base_price 설정 및 재매수 대기 모드 진입 확인"""
        global_state = {
            "KRW-BTC": {
                "active_ref_date": "2026-03-10",
                "ref_high": 1000.0,
                "effective_ref_low": 1050.0,  # 트레일링 스탑 또는 비상 손절선이 고가 위인 상황
                "anchor_low": 900.0,
                "ref_mid": 900.0,
                "rise_duration": 5,
                "wave_height": 200.0,
                "entry_bought": True,
                "entry_price": 1100.0,
                "total_volume": 10.0,
                "remaining_ratio": 1.0,
                "base_price": None,
            }
        }

        # 30일치 더미 데이터 (현재가 1040원 < 손절가 1050원, 그러나 여전히 ref_high 1000원 위!)
        dates = pd.date_range("2026-03-01", periods=30, freq="D")
        df = pd.DataFrame(
            {
                "open": [1060.0] * 30,
                "high": [1120.0] * 30,
                "low": [1030.0] * 30,
                "close": [1040.0] * 30,
                "volume": [1000.0] * 30,
            },
            index=dates,
        )

        mock_upbit = MagicMock()
        with patch.object(
            bot,
            "execute_sell",
            return_value={
                "ok": True,
                "volume": 10.0,
                "price": 1040.0,
                "amount": 10400.0,
            },
        ):
            with patch.object(bot, "SendMessage"):
                with patch.object(bot, "save_trade_to_google_sheet"):
                    bot.process_ticker_strategy("KRW-BTC", df, mock_upbit, global_state)

        # 1040원 > 1000원(ref_high) 이므로 base_price = 1040원, active_ref_date 보존
        st = global_state["KRW-BTC"]
        self.assertFalse(st["entry_bought"])
        self.assertEqual(st["base_price"], 1040.0)
        self.assertEqual(st["active_ref_date"], "2026-03-10")
        self.assertEqual(st["ref_high"], 1000.0)
        self.assertEqual(st["trough_low"], 1040.0)


if __name__ == "__main__":
    unittest.main()
