# test_dual_timeframe_symmetry.py
import unittest
from unittest.mock import MagicMock, patch
import pandas as pd
import Upbit_Anchor_Wave_Bot as bot


class TestDualTimeframeSymmetry(unittest.TestCase):

    def setUp(self):
        bot.AUTO_TRADE_EXECUTE = False
        bot.ENABLE_DUAL_TIMEFRAME_MA5 = True
        bot.ENABLE_MA5_EXIT_BUFFER = True
        bot.MA5_EXIT_BUFFER_PCT = 0.005
        bot.MA5_4H_EXIT_BUFFER_PCT = 0.005

    def _make_daily_df(self, closes):
        dates = pd.date_range("2026-09-01", periods=len(closes), freq="D")
        return pd.DataFrame(
            {
                "open": closes,
                "high": [c + 1.0 for c in closes],
                "low": [c - 1.0 for c in closes],
                "close": closes,
                "volume": [100.0] * len(closes),
            },
            index=dates,
        )

    def _make_4h_df(self, closes):
        dates = pd.date_range("2026-09-20 00:00:00", periods=len(closes), freq="4h")
        df = pd.DataFrame(
            {
                "open": closes,
                "high": [c + 1.0 for c in closes],
                "low": [c - 1.0 for c in closes],
                "close": closes,
                "volume": [50.0] * len(closes),
            },
            index=dates,
        )
        df["MA5"] = df["close"].rolling(5).mean()
        return df

    def test_sell_whipsaw_prevented_when_4h_not_broken(self):
        """일봉 5MA는 이탈했으나 4시간봉 5MA는 지지 중인 경우 매도 미발생 (휩소 방어 검증)"""
        # 일봉: 5일선 평균 약 1000원, 현재가 990원 (0.5% 버퍼인 995원 하향 이탈)
        daily_closes = [1000.0] * 25 + [1000.0, 1000.0, 1000.0, 1000.0, 990.0]
        df_daily = self._make_daily_df(daily_closes)

        # 4시간봉: 5MA가 985원, 현재가 990원 (4시간봉 5MA 위에 있음 -> 이탈 안 됨)
        h4_closes = [980.0, 980.0, 985.0, 985.0, 990.0]
        df_4h = self._make_4h_df(h4_closes)

        st = bot.new_ticker_state()
        st.update({
            "active_ref_date": "2026-09-10",
            "ref_high": 1050.0,
            "effective_ref_low": 900.0,
            "anchor_low": 900.0,
            "ref_mid": 975.0,
            "entry_bought": True,
            "entry_price": 950.0,
            "total_volume": 1.0,
            "remaining_ratio": 1.0,
            "rise_duration": 5,
            "wave_height": 100.0,
        })
        global_state = {"KRW-BTC": st}

        mock_client = MagicMock()
        mock_client.get_minute_ohlcv.return_value = df_4h

        with patch.object(bot, "SendMessage"), patch.object(bot, "save_trade_to_google_sheet"):
            signals = bot.process_ticker_strategy(
                "KRW-BTC", df_daily, mock_client, global_state, allow_entry=False
            )

        # 4시간봉이 깨지지 않았으므로 매도가 발생하지 않고 포지션 유지
        sell_signals = [s for s in signals if "SELL" in s.get("Event", "")]
        self.assertEqual(len(sell_signals), 0)
        self.assertEqual(global_state["KRW-BTC"]["remaining_ratio"], 1.0)
        self.assertTrue(global_state["KRW-BTC"]["entry_bought"])

    def test_sell_triggered_when_both_daily_and_4h_broken(self):
        """일봉 5MA와 4시간봉 5MA가 동시 하향 이탈 시 즉시 전량 청산 검증"""
        # 일봉 5MA 약 1000원, 현재가 980원 (일봉 이탈)
        daily_closes = [1000.0] * 25 + [1000.0, 1000.0, 1000.0, 1000.0, 980.0]
        df_daily = self._make_daily_df(daily_closes)

        # 4시간봉 5MA 약 1000원, 현재가 980원 (4시간봉도 0.5% 버퍼 아래로 이탈)
        h4_closes = [1000.0, 1000.0, 1000.0, 1000.0, 980.0]
        df_4h = self._make_4h_df(h4_closes)

        st = bot.new_ticker_state()
        st.update({
            "active_ref_date": "2026-09-10",
            "ref_high": 1050.0,
            "effective_ref_low": 900.0,
            "anchor_low": 900.0,
            "ref_mid": 975.0,
            "entry_bought": True,
            "entry_price": 950.0,
            "total_volume": 1.0,
            "remaining_ratio": 1.0,
            "rise_duration": 5,
            "wave_height": 100.0,
        })
        global_state = {"KRW-BTC": st}

        mock_client = MagicMock()
        mock_client.get_minute_ohlcv.return_value = df_4h

        with patch.object(bot, "SendMessage"), patch.object(bot, "save_trade_to_google_sheet"):
            signals = bot.process_ticker_strategy(
                "KRW-BTC", df_daily, mock_client, global_state, allow_entry=False
            )

        # 일봉과 4시간봉 모두 이탈했으므로 SELL (MA5 DOWN) 실행
        sell_signals = [s for s in signals if s.get("Event") == "SELL (MA5 DOWN)"]
        self.assertEqual(len(sell_signals), 1)
        self.assertEqual(global_state["KRW-BTC"]["remaining_ratio"], 0.0)
        self.assertFalse(global_state["KRW-BTC"]["entry_bought"])
        # 매도 후 재매수 기준가(base_price) 설정 확인
        self.assertEqual(global_state["KRW-BTC"]["base_price"], 980.0)

    def test_lazy_evaluation_never_calls_4h_when_daily_intact(self):
        """일봉 5MA 지지 중에는 4시간봉 API를 전혀 호출하지 않음을 검증 (단락 평가)"""
        # 일봉 5MA 1000원, 현재가 1020원 (지지선 상회)
        daily_closes = [1000.0] * 25 + [1000.0, 1000.0, 1000.0, 1000.0, 1020.0]
        df_daily = self._make_daily_df(daily_closes)

        st = bot.new_ticker_state()
        st.update({
            "active_ref_date": "2026-09-10",
            "ref_high": 1050.0,
            "effective_ref_low": 900.0,
            "anchor_low": 900.0,
            "ref_mid": 975.0,
            "entry_bought": True,
            "entry_price": 950.0,
            "total_volume": 1.0,
            "remaining_ratio": 1.0,
            "rise_duration": 5,
            "wave_height": 100.0,
        })
        global_state = {"KRW-BTC": st}

        mock_client = MagicMock()

        with patch.object(bot, "SendMessage"), patch.object(bot, "save_trade_to_google_sheet"):
            signals = bot.process_ticker_strategy(
                "KRW-BTC", df_daily, mock_client, global_state, allow_entry=False
            )

        # 일봉이 깨지지 않았으므로 get_minute_ohlcv 호출 횟수가 정확히 0회여야 함
        mock_client.get_minute_ohlcv.assert_not_called()

    def test_zone1_reentry_triggered_on_4h_recovery_even_if_slope_down(self):
        """Zone 1 재매수: 직전 매도가 돌파 및 4시간 5MA 상향 회복 시 매수 집행 (4시간봉 기울기 우하향이어도 회복 시 진입)"""
        # 일봉: 현재가 1100원 (ref_high 1050 돌파 & base_price 1040 돌파)
        daily_closes = [1000.0] * 25 + [1010.0, 1020.0, 1030.0, 1040.0, 1100.0]
        df_daily = self._make_daily_df(daily_closes)

        # 4시간봉: 20시간 전(1200)이 높아서 5MA는 우하향 중이나, 현재가(1100)는 5MA(1094)를 상향 돌파/회복함
        h4_closes = [1200.0, 1100.0, 1050.0, 1020.0, 1100.0]
        df_4h = self._make_4h_df(h4_closes)

        st = bot.new_ticker_state()
        st.update({
            "active_ref_date": "2026-09-10",
            "ref_high": 1050.0,
            "effective_ref_low": 900.0,
            "anchor_low": 900.0,
            "ref_mid": 975.0,
            "entry_bought": False,
            "remaining_ratio": 0.0,
            "base_price": 1040.0,
            "base_amount": 300000.0,
            "base_price_date": "2026-09-25",
            "target_buy_amount": 500000.0,
            "scale_in_count": 0,
            "rise_duration": 5,
            "wave_height": 100.0,
        })
        global_state = {"KRW-BTC": st}

        mock_client = MagicMock()
        mock_client.get_minute_ohlcv.return_value = df_4h

        with patch.object(bot, "SendMessage"), patch.object(bot, "save_trade_to_google_sheet"):
            signals = bot.process_ticker_strategy(
                "KRW-BTC", df_daily, mock_client, global_state, allow_entry=True
            )

        # Zone 1 재매수 신호 발생 확인
        reentry_signals = [s for s in signals if "RE-ENTRY Zone 1" in s.get("Event", "")]
        self.assertEqual(len(reentry_signals), 1)
        self.assertTrue(global_state["KRW-BTC"]["entry_bought"])
        self.assertEqual(global_state["KRW-BTC"]["remaining_ratio"], 1.0)

    def test_zone2_reentry_triggered_on_4h_recovery(self):
        """Zone 2 재매수: 2*ATR 반등 및 4시간 5MA 상향 회복 시 매수 집행"""
        # 기준봉: ref_high 1050, ref_mid 975, anchor_low 900
        # 현재가 1000 (ref_mid 975 <= 1000 < ref_high 1050)
        daily_closes = [1000.0] * 25 + [1010.0, 990.0, 980.0, 980.0, 1000.0]
        df_daily = self._make_daily_df(daily_closes)

        # 4시간봉: 5MA가 990원, 현재가 1000원으로 5MA 위로 상향 회복
        h4_closes = [980.0, 980.0, 990.0, 990.0, 1000.0]
        df_4h = self._make_4h_df(h4_closes)

        st = bot.new_ticker_state()
        st.update({
            "active_ref_date": "2026-09-10",
            "ref_high": 1050.0,
            "effective_ref_low": 900.0,
            "anchor_low": 900.0,
            "ref_mid": 975.0,
            "entry_bought": False,
            "remaining_ratio": 0.0,
            "base_price": 1020.0,
            "base_amount": 300000.0,
            "base_price_date": "2026-09-25",
            "target_buy_amount": 500000.0,
            "trough_low": 980.0,  # 바닥 저점
            "scale_in_count": 0,
            "rise_duration": 5,
            "wave_height": 100.0,
        })
        global_state = {"KRW-BTC": st}

        mock_client = MagicMock()
        mock_client.get_minute_ohlcv.return_value = df_4h

        with patch.object(bot, "SendMessage"), patch.object(bot, "save_trade_to_google_sheet"):
            signals = bot.process_ticker_strategy(
                "KRW-BTC", df_daily, mock_client, global_state, allow_entry=True
            )

        # Zone 2 재매수 신호 발생 확인
        reentry_signals = [s for s in signals if "RE-ENTRY Zone 2" in s.get("Event", "")]
        self.assertEqual(len(reentry_signals), 1)
        self.assertTrue(global_state["KRW-BTC"]["entry_bought"])
        self.assertEqual(global_state["KRW-BTC"]["remaining_ratio"], 1.0)

    def test_sell_above_ref_high_message_reflects_4h_ma(self):
        """고가 위 청산 시 텔레그램 메시지에 4시간 5MA 상향 회복 문구가 동적으로 반영되는지 검증"""
        daily_closes = [1000.0] * 25 + [1020.0, 1030.0, 1040.0, 1050.0, 1040.0]
        df_daily = self._make_daily_df(daily_closes)

        st = bot.new_ticker_state()
        st.update({
            "active_ref_date": "2026-09-10",
            "ref_high": 1000.0,
            "effective_ref_low": 1050.0,  # 손절선이 고가 위
            "anchor_low": 900.0,
            "ref_mid": 950.0,
            "entry_bought": True,
            "entry_price": 950.0,
            "total_volume": 10.0,
            "remaining_ratio": 1.0,
        })
        global_state = {"KRW-BTC": st}
        mock_client = MagicMock()

        # 1) ENABLE_DUAL_TIMEFRAME_MA5 = True 일 때
        bot.ENABLE_DUAL_TIMEFRAME_MA5 = True
        with patch.object(
            bot,
            "execute_sell",
            return_value={"ok": True, "volume": 10.0, "price": 1040.0, "amount": 10400.0},
        ), patch.object(bot, "SendMessage") as mock_send, patch.object(
            bot, "save_trade_to_google_sheet"
        ):
            bot.process_ticker_strategy("KRW-BTC", df_daily, mock_client, global_state)
            mock_send.assert_called_once()
            sent_msg = mock_send.call_args[0][0]
            self.assertIn("4시간 5MA 상향 회복", sent_msg)
            self.assertNotIn("5일선 우상향", sent_msg)


if __name__ == "__main__":
    unittest.main()

