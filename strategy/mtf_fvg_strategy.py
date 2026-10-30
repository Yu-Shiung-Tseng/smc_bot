#多時區 SMC 策略核心邏輯 (4H 趨勢過濾 + 1H FVG 區間 + 5m 回踩觸發 + 1H OB 止損防守)。
import hashlib
import pandas as pd
from typing import Optional

from indicators.smc_indicators import SMCIndicators, SMCConfig
from market_data.local_csv import TIMEFRAME_MS, utc_timestamp
from strategy.models import StrategyDecision, TradePlan

class MTFFVGStrategy:
    def __init__(self, config: Optional[SMCConfig] = None):
        self.indicators = SMCIndicators(config or SMCConfig())

    def _generate_signal_id(self, symbol: str, direction: int, fvg_source_at: str) -> str:
        raw = f"{symbol}_{direction}_{fvg_source_at}"
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]

    def decide(
        self,
        symbol: str,
        dfs: dict[str, pd.DataFrame],
        as_of,
        used_signal_ids: Optional[set[str]] = None,
    ) -> StrategyDecision:
        used_signal_ids = used_signal_ids or set()
        as_of_dt = utc_timestamp(as_of)
        as_of_str = as_of_dt.isoformat()

        # 1. 資料覆蓋與新鮮度檢查
        for tf in ["4h", "1h", "5m"]:
            if tf not in dfs or dfs[tf].empty:
                return StrategyDecision(
                    status="ERROR",
                    as_of=as_of_str,
                    symbol=symbol,
                    reason_code="MISSING_TIMEFRAME",
                    reason_msg=f"缺少 {tf} 週期的資料",
                )

            duration = pd.Timedelta(milliseconds=TIMEFRAME_MS[tf])
            valid_candles = dfs[tf].loc[dfs[tf].index + duration <= as_of_dt]
            if valid_candles.empty:
                return StrategyDecision(
                    status="ERROR",
                    as_of=as_of_str,
                    symbol=symbol,
                    reason_code="STALE_DATA",
                    reason_msg=f"{tf} 在 {as_of_str} 前沒有已收盤的 K 線",
                )

        # 2. 計算 4H / 1H / 5m SMC 指標
        ind_4h = self.indicators.calculate(dfs["4h"], "4h", as_of=as_of_dt)
        ind_1h = self.indicators.calculate(dfs["1h"], "1h", as_of=as_of_dt)
        ind_5m = self.indicators.calculate(dfs["5m"], "5m", as_of=as_of_dt)

        fvgs_4h = ind_4h["fvg"]
        fvgs_1h = ind_1h["fvg"]
        obs_1h = ind_1h["ob"]
        df_5m = dfs["5m"].loc[dfs["5m"].index + pd.Timedelta(minutes=5) <= as_of_dt]

        if fvgs_4h.empty:
            return StrategyDecision(
                status="NO_SIGNAL",
                as_of=as_of_str,
                symbol=symbol,
                reason_code="NO_HTF_FVG",
                reason_msg="4H 未偵測到任何已確認的 FVG",
            )

        # 3. 確定 4H 大趨勢方向 (取最新的 4H FVG)
        latest_4h_fvg = fvgs_4h.iloc[-1]
        htf_direction = int(latest_4h_fvg["direction"])

        # 4. 尋找 1H 中與大趨勢同方向的候選 FVG
        matching_1h_fvgs = fvgs_1h[
            (fvgs_1h["direction"] == htf_direction) &
            (fvgs_1h["status"].isin(["active", "touched"]))
        ]

        if matching_1h_fvgs.empty:
            return StrategyDecision(
                status="NO_SIGNAL",
                as_of=as_of_str,
                symbol=symbol,
                reason_code="NO_MATCHING_1H_FVG",
                reason_msg=f"1H 沒有與 4H 趨勢方向 ({htf_direction}) 一致的有效 FVG",
            )

        # 選擇最新的一個 1H 候選 FVG
        candidate_fvg = matching_1h_fvgs.iloc[-1]
        fvg_top = float(candidate_fvg["top"])
        fvg_bottom = float(candidate_fvg["bottom"])
        fvg_source_at = pd.Timestamp(candidate_fvg["source_at"]).isoformat()
        fvg_confirmed_at = pd.Timestamp(candidate_fvg["confirmed_at"]).isoformat()

        signal_id = self._generate_signal_id(symbol, htf_direction, fvg_source_at)
        if signal_id in used_signal_ids:
            return StrategyDecision(
                status="NO_SIGNAL",
                as_of=as_of_str,
                symbol=symbol,
                reason_code="SIGNAL_ALREADY_USED",
                reason_msg=f"該 FVG 訊號 ({signal_id}) 先前已執行過交易",
            )

        # 5. 5m 級別進場觸發檢查 (判斷當下最新收盤的 5m K 線是否回踩 FVG)
        latest_5m_candle = df_5m.iloc[-1]
        trigger_candle_at = df_5m.index[-1].isoformat()
        ref_price = float(latest_5m_candle["close"])
        high_5m = float(latest_5m_candle["high"])
        low_5m = float(latest_5m_candle["low"])

        retraced = (low_5m <= fvg_top) and (high_5m >= fvg_bottom)

        if not retraced:
            return StrategyDecision(
                status="NO_SIGNAL",
                as_of=as_of_str,
                symbol=symbol,
                reason_code="NO_RETRACE_TRIGGER",
                reason_msg=f"最新 5m K 線 (價格: {ref_price}) 未進入 1H FVG 區間 [{fvg_bottom}, {fvg_top}]",
            )

        # 檢查 5m 是否收盤穿越不利邊界 (做多不能收低於 bottom, 做空不能收高於 top)
        invalidated = (ref_price < fvg_bottom) if htf_direction == 1 else (ref_price > fvg_top)
        if invalidated:
            return StrategyDecision(
                status="NO_SIGNAL",
                as_of=as_of_str,
                symbol=symbol,
                reason_code="TRIGGER_CANDLE_INVALIDATED",
                reason_msg=f"觸發 5m K 線收盤價 ({ref_price}) 突破了 FVG 不利邊界，區域失效",
            )

        # 6. 尋找 1H 同方向 OB 作為結構止損參考
        stop_loss = fvg_bottom * 0.995 if htf_direction == 1 else fvg_top * 1.005
        ob_source_at, ob_top, ob_bottom = None, None, None

        if not obs_1h.empty:
            matching_obs = obs_1h[
                (obs_1h["direction"] == htf_direction) &
                (obs_1h["status"].isin(["active", "touched"]))
            ]
            if not matching_obs.empty:
                latest_ob = matching_obs.iloc[-1]
                ob_source_at = pd.Timestamp(latest_ob["source_at"]).isoformat()
                ob_top = float(latest_ob["top"])
                ob_bottom = float(latest_ob["bottom"])
                # 多單止損設在 OB 底部下方，空單設在 OB 頂部上方
                stop_loss = ob_bottom * 0.999 if htf_direction == 1 else ob_top * 1.001

        plan = TradePlan(
            signal_id=signal_id,
            symbol=symbol,
            direction=htf_direction,
            as_of=as_of_str,
            trigger_candle_at=trigger_candle_at,
            reference_price=ref_price,
            stop_loss=stop_loss,
            fvg_top=fvg_top,
            fvg_bottom=fvg_bottom,
            fvg_source_at=fvg_source_at,
            fvg_confirmed_at=fvg_confirmed_at,
            htf_fvg_source_at=pd.Timestamp(latest_4h_fvg["source_at"]).isoformat(),
            ob_source_at=ob_source_at,
            ob_top=ob_top,
            ob_bottom=ob_bottom,
        )

        return StrategyDecision(
            status="SIGNAL",
            as_of=as_of_str,
            symbol=symbol,
            reason_code="STRATEGY_TRIGGERED",
            reason_msg="成功觸發多時區 SMC 共振進場訊號！",
            plan=plan,
        )