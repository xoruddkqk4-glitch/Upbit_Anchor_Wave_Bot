# test_manual_ref.py
# ref_manager 및 telegram_commander 핵심 로직 단위 검증 테스트

import json
import os
import shutil
import tempfile
import unittest
import pandas as pd
from unittest.mock import MagicMock, patch

import ref_manager


class TestManualRefManager(unittest.TestCase):

    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.test_state_file = os.path.join(self.test_dir, "test_bot_state.json")
        # 더미 상태 데이터 준비 (KRW-NEAR: 보유 중, KRW-WAVES: 기준봉 등록 중)
        dummy_state = {
            "KRW-NEAR": {
                "active_ref_date": "2026-09-06",
                "entry_bought": True,
                "remaining_ratio": 0.5,
            },
            "KRW-WAVES": {
                "active_ref_date": "2026-09-08",
                "entry_bought": False,
                "remaining_ratio": 1.0,
            },
        }
        with open(self.test_state_file, "w", encoding="utf-8") as f:
            json.dump(dummy_state, f)

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_get_available_tickers(self):
        """보유 중이거나 기준봉이 등록된 종목을 제외하고 번호 목록을 올바르게 생성하는지 확인"""
        res = ref_manager.get_available_tickers(self.test_state_file)
        avail = res["tickers_list"]
        num_map = res["num_to_ticker"]

        # KRW-NEAR와 KRW-WAVES는 제외되어야 함
        tickers = [t for _, t in avail]
        self.assertNotIn("KRW-NEAR", tickers)
        self.assertNotIn("KRW-WAVES", tickers)

        # 번호가 1부터 순차적으로 매핑되는지 확인
        self.assertEqual(avail[0][0], 1)
        self.assertEqual(num_map[1], avail[0][1])

    @patch("ref_manager.get_daily_ohlcv")
    def test_validate_expiry_days(self, mock_ohlcv):
        """20일 이상 경과된 오래된 캔들 등록 시 거부되는지 확인"""
        # 30일치 더미 일봉 생성 (기준일은 25일 전)
        dates = pd.date_range("2026-02-01", periods=30, freq="D")
        df = pd.DataFrame(
            {
                "open": [100.0] * 30,
                "high": [110.0] * 30,
                "low": [95.0] * 30,
                "close": [105.0] * 30,
                "volume": [1000.0] * 30,
            },
            index=dates,
        )
        mock_ohlcv.return_value = df

        old_date = dates[2].strftime("%Y-%m-%d")  # 약 27일 전
        ok, msg = ref_manager.validate_and_register_manual_ref(
            "KRW-BTC", old_date, self.test_state_file
        )
        self.assertFalse(ok)
        self.assertIn("기준봉 유효기간(20일)을 초과한 캔들", msg)

    @patch("ref_manager.get_daily_ohlcv")
    def test_validate_broken_in_history(self, mock_ohlcv):
        """기준봉 형성 이후 손절선(저가)을 이미 이탈한 캔들 거부 확인"""
        dates = pd.date_range("2026-03-01", periods=35, freq="D")
        # index 20 (2026-03-21): 기준봉 (고가 120, 저가 90) -> 약 14일 전 (유효기간 20일 이내)
        # index 25 (2026-03-26): 손절선 이탈 (저가 85 < 90)
        lows = [95.0] * 35
        lows[20] = 90.0  # 기준봉 저가
        lows[25] = 85.0  # 사후 손절선 이탈

        df = pd.DataFrame(
            {
                "open": [100.0] * 35,
                "high": [120.0] * 35,
                "low": lows,
                "close": [105.0] * 35,
                "volume": [1000.0] * 35,
            },
            index=dates,
        )
        mock_ohlcv.return_value = df

        target_date = dates[20].strftime("%Y-%m-%d")
        ok, msg = ref_manager.validate_and_register_manual_ref(
            "KRW-BTC", target_date, self.test_state_file
        )
        self.assertFalse(ok)
        self.assertIn("사후 손절선 이탈 확인", msg)

    @patch("ref_manager.get_daily_ohlcv")
    def test_successful_registration(self, mock_ohlcv):
        """정상적인 기준봉 등록 시 bot_state.json에 올바르게 저장되는지 확인"""
        dates = pd.date_range("2026-03-01", periods=35, freq="D")
        # index 20 (2026-03-21): 기준봉, 이후 저가는 92 이상 유지
        lows = [95.0] * 35
        lows[20] = 90.0

        df = pd.DataFrame(
            {
                "open": [100.0] * 35,
                "high": [120.0] * 35,
                "low": lows,
                "close": [105.0] * 35,
                "volume": [1000.0] * 35,
            },
            index=dates,
        )
        mock_ohlcv.return_value = df

        target_date = dates[20].strftime("%Y-%m-%d")
        ok, res = ref_manager.validate_and_register_manual_ref(
            "KRW-BTC", target_date, self.test_state_file
        )
        self.assertTrue(ok)
        self.assertEqual(res["ticker"], "KRW-BTC")
        self.assertEqual(res["ref_date"], target_date)
        self.assertEqual(res["effective_ref_low"], 90.0)

        # bot_state.json 확인
        with open(self.test_state_file, "r", encoding="utf-8") as f:
            saved = json.load(f)
        self.assertIn("KRW-BTC", saved)
        self.assertEqual(saved["KRW-BTC"]["active_ref_date"], target_date)
        self.assertTrue(saved["KRW-BTC"]["manual_registered"])

    def test_cancel_manual_ref(self):
        """기준봉 수동 취소 동작 확인"""
        ok, msg = ref_manager.cancel_manual_ref("KRW-WAVES", self.test_state_file)
        self.assertTrue(ok)

        # 취소 후 active_ref_date 가 None인지 확인
        with open(self.test_state_file, "r", encoding="utf-8") as f:
            saved = json.load(f)
        self.assertIsNone(saved["KRW-WAVES"]["active_ref_date"])

        # 보유 중인 코인(KRW-NEAR)은 취소 불가 확인
        ok, msg = ref_manager.cancel_manual_ref("KRW-NEAR", self.test_state_file)
        self.assertFalse(ok)
        self.assertIn("매수 포지션을 보유 중", msg)


class TestTelegramCommander(unittest.TestCase):

    def setUp(self):
        import telegram_commander
        self.tc = telegram_commander
        self.tc.user_sessions.clear()

    def test_authorization(self):
        """인가된 채팅 ID 검증"""
        with patch.object(self.tc, "AUTHORIZED_CHAT_ID", "12345"):
            self.assertTrue(self.tc.is_authorized("12345"))
            self.assertTrue(self.tc.is_authorized(12345))
            self.assertFalse(self.tc.is_authorized("99999"))

    @patch("telegram_commander.send_message")
    def test_process_update_number_selection(self, mock_send):
        """세션이 WAIT_TICKER일 때 번호 입력 시 코인 선택 및 날짜 입력 단계로 전환 확인"""
        chat_id = 12345
        self.tc.user_sessions[chat_id] = {
            "step": "WAIT_TICKER",
            "ticker_map": {1: "KRW-XRP", 2: "KRW-BTC"},
            "expire_at": 9999999999.0,
        }

        update = {
            "message": {
                "chat": {"id": chat_id},
                "text": "2",
            }
        }
        with patch.object(self.tc, "is_authorized", return_value=True):
            self.tc.process_update(update)

        self.assertIn(chat_id, self.tc.user_sessions)
        self.assertEqual(self.tc.user_sessions[chat_id]["step"], "WAIT_DATE")
        self.assertEqual(self.tc.user_sessions[chat_id]["ticker"], "KRW-BTC")
        mock_send.assert_called()

    @patch("telegram_commander.send_message")
    @patch("telegram_commander.answer_callback_query")
    def test_process_callback_query_selection(self, mock_ans, mock_send):
        """인라인 버튼 클릭(callback_query) 시 코인 선택 및 날짜 입력 요청 확인"""
        chat_id = 12345
        update = {
            "callback_query": {
                "id": "cb_123",
                "message": {"chat": {"id": chat_id}},
                "data": "sel_KRW-SOL",
            }
        }
        with patch.object(self.tc, "is_authorized", return_value=True):
            self.tc.process_update(update)

        self.tc.user_sessions[chat_id] = {
            "step": "WAIT_DATE",
            "ticker": "KRW-SOL",
            "expire_at": 9999999999.0,
        }
        mock_ans.assert_called_with("cb_123")
        mock_send.assert_called()

    def test_format_watching_price_order(self):
        """미보유 기준봉 코인의 고가, 중심가, 손절가 및 현재가 순서 배치 단위 테스트"""
        ref_h = 1000.0
        ref_m = 800.0
        ref_l = 600.0

        # 1. 현재가가 고가 위인 경우: 현재가 > 고가 > 중심가 > 손절가
        res1 = self.tc.format_watching_price_order(ref_h, ref_m, ref_l, curr_p=1200.0)
        self.assertIn("<b>현재가 1,200원</b> > 고가 1,000원 > 중심가 800원 > 손절가 600원", res1)

        # 2. 현재가가 고가와 중심가 사이: 고가 > 현재가 > 중심가 > 손절가
        res2 = self.tc.format_watching_price_order(ref_h, ref_m, ref_l, curr_p=900.0)
        self.assertIn("고가 1,000원 > <b>현재가 900원</b> > 중심가 800원 > 손절가 600원", res2)

        # 3. 현재가가 중심가와 손절가 사이: 고가 > 중심가 > 현재가 > 손절가
        res3 = self.tc.format_watching_price_order(ref_h, ref_m, ref_l, curr_p=700.0)
        self.assertIn("고가 1,000원 > 중심가 800원 > <b>현재가 700원</b> > 손절가 600원", res3)

        # 4. 현재가가 손절가 아래인 경우: 고가 > 중심가 > 손절가 > 현재가
        res4 = self.tc.format_watching_price_order(ref_h, ref_m, ref_l, curr_p=500.0)
        self.assertIn("고가 1,000원 > 중심가 800원 > 손절가 600원 > <b>현재가 500원</b>", res4)

        # 5. 현재가 조회 불가(None/0)인 경우: fallback 포맷
        res5 = self.tc.format_watching_price_order(ref_h, ref_m, ref_l, curr_p=None)
        self.assertIn("고가 1,000원 > 중심가 800원 > 손절가 600원 (현재가: -)", res5)

    @patch("telegram_commander.send_message")
    @patch("telegram_commander.get_current_prices")
    @patch("telegram_commander.load_state")
    @patch("telegram_commander.get_available_tickers")
    def test_handle_status_command(self, mock_avail, mock_state, mock_prices, mock_send):
        """/status 명령어 실행 시 보유, 미보유(기준봉O), 미보유(기준봉X) 정보 출력 검증"""
        # 더미 상태 설정
        mock_state.return_value = {
            "KRW-NEAR": {
                "active_ref_date": "2026-09-06",
                "entry_bought": True,
                "entry_price": 3000.0,
                "remaining_ratio": 0.5,
                "effective_ref_low": 2800.0,
            },
            "KRW-WAVES": {
                "active_ref_date": "2026-09-08",
                "entry_bought": False,
                "remaining_ratio": 1.0,
                "ref_high": 400.0,
                "ref_mid": 350.0,
                "effective_ref_low": 300.0,
                "manual_registered": False,
            },
            "KRW-ETH": {
                "active_ref_date": "2026-09-10",
                "entry_bought": False,
                "base_price": 3500000.0,
                "remaining_ratio": 0.0,
            },
        }
        # 현재가 모킹
        mock_prices.return_value = {
            "KRW-NEAR": 3300.0,    # +10% 수익
            "KRW-WAVES": 380.0,    # 고가(400) > 현재가(380) > 중심가(350) > 손절가(300)
            "KRW-ETH": 3600000.0,  # 기준가 3,500,000원, 현재가 3,600,000원
        }
        # 미등록 코인 모킹
        mock_avail.return_value = {
            "tickers_list": [(1, "KRW-BTC"), (2, "KRW-SOL"), (3, "KRW-XRP")]
        }

        self.tc.handle_status_command(12345)

        mock_send.assert_called_once()
        msg = mock_send.call_args[0][1]

        # 1. 보유 코인 검증 (현재가, 손절가, 보유 비율, 현재 수익률)
        self.assertIn("[1. 보유 코인 (1개)]", msg)
        self.assertIn("KRW-NEAR", msg)
        self.assertIn("현재가 3,300원", msg)
        self.assertIn("수익률 +10.00%", msg)
        self.assertIn("손절가 2,800원", msg)
        self.assertIn("보유 비율 50%", msg)

        # 2. 미보유 코인 (기준봉 O) 검증
        self.assertIn("[2. 미보유 코인 (기준봉 O) (2개)]", msg)
        # 일반 감시 코인 (KRW-WAVES)
        self.assertIn("KRW-WAVES", msg)
        self.assertIn("고가 400원 > <b>현재가 380원</b> > 중심가 350원 > 손절가 300원", msg)
        # 매도가가 기준가인 상태 (KRW-ETH)
        self.assertIn("KRW-ETH", msg)
        self.assertIn("[재매수 대기", msg)
        self.assertIn("기준가 3,500,000원", msg)
        self.assertIn("현재가 3,600,000원", msg)

        # 3. 미보유 코인 (기준봉 X) 검증 (코인명 정보만)
        self.assertIn("[3. 미보유 코인 (기준봉 X) (3개)]", msg)
        self.assertIn("BTC, SOL, XRP", msg)


if __name__ == "__main__":
    unittest.main()

