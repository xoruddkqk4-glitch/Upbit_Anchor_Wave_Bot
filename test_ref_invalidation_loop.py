# test_ref_invalidation_loop.py
# 기준봉 지지선 붕괴 감시 해제 후 신규 기준봉 오인 재등록 및 알림 무한 반복 방지 검증 테스트

import unittest
from unittest.mock import MagicMock, patch
import pandas as pd
import numpy as np

import Upbit_Anchor_Wave_Bot as bot


class TestRefInvalidationLoop(unittest.TestCase):

    def setUp(self):
        # 30일치 더미 일봉 데이터 생성 (2026-09-10 ~ 2026-10-08)
        dates = pd.date_range(start="2026-09-10 09:00:00", periods=29, freq="D")
        
        # 기본 가격 100원, 거래량 1000
        df = pd.DataFrame(
            {
                "open": [100.0] * 29,
                "high": [105.0] * 29,
                "low": [98.0] * 29,
                "close": [101.0] * 29,
                "volume": [1000000.0] * 29,
                "value": [100000000.0] * 29,
            },
            index=dates,
        )

        # 2026-09-28 일봉을 강력한 기준봉으로 설정
        # (전일 종가 101 대비 당일 거래대금 및 등락폭 조건 충족)
        ref_idx = pd.Timestamp("2026-09-28 09:00:00")
        df.loc[ref_idx, "open"] = 105.0
        df.loc[ref_idx, "high"] = 150.0
        df.loc[ref_idx, "low"] = 100.0  # 기준봉 저가: 100.0원
        df.loc[ref_idx, "close"] = 140.0
        df.loc[ref_idx, "volume"] = 50000000.0
        df.loc[ref_idx, "value"] = 7000000000.0

        # 그 이후 확정봉들(2026-09-29 ~ 2026-10-06)은 기준봉 저가(100.0원) 위에서 거래됨
        post_dates = dates[(dates > ref_idx) & (dates < dates[-1])]
        for d in post_dates:
            df.loc[d, "open"] = 120.0
            df.loc[d, "high"] = 130.0
            df.loc[d, "low"] = 110.0  # 모두 100.0원 초과
            df.loc[d, "close"] = 125.0
            df.loc[d, "volume"] = 10000000.0
            df.loc[d, "value"] = 1200000000.0

        # 오늘 봉 (2026-10-08 09:00:00 진행 중 마지막 봉)
        # 현재가가 95.0원으로 기준봉 저가(100.0원)를 깬 상태
        curr_idx = dates[-1]
        df.loc[curr_idx, "open"] = 110.0
        df.loc[curr_idx, "high"] = 112.0
        df.loc[curr_idx, "low"] = 94.0   # 저점 붕괴
        df.loc[curr_idx, "close"] = 95.0 # 현재가 붕괴
        df.loc[curr_idx, "volume"] = 10000000.0
        df.loc[curr_idx, "value"] = 1000000000.0

        # 지표 계산
        df["MA5"] = df["close"].rolling(window=5).mean()
        df["MA20"] = df["close"].rolling(window=20).mean()
        df["Vol_MA20"] = df["volume"].rolling(window=20).mean()

        self.df = df
        self.ticker = "KRW-TEST"

    @patch("Upbit_Anchor_Wave_Bot.SendMessage")
    def test_no_repeated_breakdown_alerts_on_subsequent_runs(self, mock_send):
        """기준봉 붕괴로 감시 해제된 후, 다음 실행 주기에서 동일 기준봉이 재등록되어 알림이 반복 발송되지 않는지 검증"""
        global_state = {}

        # 1회차 실행: 초기 상태에서 진입
        # 사전 필터링에 의해 당일 저점 및 현재가가 기준봉 저가 미만이므로 아예 신규 등록되지 않아야 함
        bot.process_ticker_strategy(self.ticker, self.df, None, global_state)
        
        # 1회차 결과: 등록되지 않아야 하며, 알림 발송도 0회여야 함
        self.assertIsNone(global_state[self.ticker].get("active_ref_date"))
        self.assertEqual(mock_send.call_count, 0)

        # 만약 기존에 정상 등록되어 감시 중이던 기준봉이 붕괴된 시나리오 시뮬레이션
        global_state[self.ticker]["active_ref_date"] = "2026-09-28"
        global_state[self.ticker]["effective_ref_low"] = 100.0
        global_state[self.ticker]["anchor_low"] = 100.0
        global_state[self.ticker]["ref_high"] = 150.0
        global_state[self.ticker]["ref_mid"] = 125.0
        global_state[self.ticker]["entry_bought"] = False
        global_state[self.ticker]["remaining_ratio"] = 1.0

        mock_send.reset_mock()

        # 2회차 실행: 감시 중이던 기준봉의 지지선 붕괴 감지
        bot.process_ticker_strategy(self.ticker, self.df, None, global_state)

        # 지지선 붕괴 감시 해제 알림이 정확히 1회 발송되어야 함
        self.assertEqual(mock_send.call_count, 1)
        sent_text = mock_send.call_args[0][0]
        self.assertIn("기준봉 지지선 붕괴 (감시 해제)", sent_text)
        
        # 상태는 초기화되어 active_ref_date가 None이어야 함
        self.assertIsNone(global_state[self.ticker].get("active_ref_date"))

        # 3회차 실행 (5분 뒤 다음 주기 시뮬레이션):
        mock_send.reset_mock()
        bot.process_ticker_strategy(self.ticker, self.df, None, global_state)

        # 핵심 검증: 재등록되지 않고, 알림 발송 횟수가 0이어야 함! (무한 반복 루프 차단 확인)
        self.assertIsNone(global_state[self.ticker].get("active_ref_date"))
        self.assertEqual(mock_send.call_count, 0, "붕괴 후 다음 주기에서 중복 알림이 발송되지 않아야 합니다.")


if __name__ == "__main__":
    unittest.main()
