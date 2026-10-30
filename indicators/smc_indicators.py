from dataclasses import dataclass
import pandas as pd

from market_data.local_csv import (
    TIMEFRAME_MS,
    missing_opens,
    utc_timestamp,
    validate_frame,
)

EVENT_COLUMNS = [
    "kind",
    "direction",
    "source_at",
    "confirmed_at",
    "top",
    "bottom",
    "first_touched_at",
    "invalidated_at",
    "status",
]

TIME_COLUMNS = [
    "source_at",
    "confirmed_at",
    "first_touched_at",
    "invalidated_at",
]

@dataclass(frozen=True)
class SMCConfig:
    swing_length: int = 5
    ob_lookback: int = 50

    def __post_init__(self):
        if self.swing_length < 1:
            raise ValueError("swing_length 必須 >= 1")
        if self.ob_lookback < 1:
            raise ValueError("ob_lookback 必須 >= 1")

def make_event(
    kind,
    direction,
    source_at,
    confirmed_at,
    top,
    bottom,
):
    return {
        "kind": kind,
        "direction": direction,
        "source_at": source_at,
        "confirmed_at": confirmed_at,
        "top": float(top),
        "bottom": float(bottom),
        "first_touched_at": pd.NaT,
        "invalidated_at": pd.NaT,
        "status": (
            "confirmed"
            if kind.startswith("swing_")
            else "active"
        ),
    }

def events_frame(events):
    """固定欄位與型別，讓空結果也能被一致處理。"""
    frame = pd.DataFrame(events, columns=EVENT_COLUMNS)

    frame["direction"] = frame["direction"].astype("int64")
    frame["top"] = frame["top"].astype("float64")
    frame["bottom"] = frame["bottom"].astype("float64")

    for column in TIME_COLUMNS:
        frame[column] = pd.to_datetime(
            frame[column],
            utc=True,
        )
    return frame

class SMCIndicators:
    def __init__(self, config=None):
        self.config = config or SMCConfig()

    @staticmethod
    def _update_zones(zones, candle, closed_at):
        """
        僅更新先前已確認的區域。
        touched 與 invalidated 都記錄在本根收盤時間。
        不從 OHLC 推斷根內觸價的確切時刻或先後順序。
        """
        high = float(candle["high"])
        low = float(candle["low"])
        close = float(candle["close"])

        for zone in zones:
            if zone["status"] == "invalidated":
                continue

            overlaps = (
                low <= zone["top"]
                and high >= zone["bottom"]
            )

            if overlaps and pd.isna(zone["first_touched_at"]):
                zone["first_touched_at"] = closed_at
                zone["status"] = "touched"

            invalidated = (
                close < zone["bottom"]
                if zone["direction"] == 1
                else close > zone["top"]
            )

            if invalidated:
                zone["invalidated_at"] = closed_at
                zone["status"] = "invalidated"

    def calculate(
        self,
        df: pd.DataFrame,
        timeframe: str,
        *,
        as_of,
    ) -> dict[str, pd.DataFrame]:
        """
        只使用 as_of 當時已收盤的資料。
        """
        cutoff = utc_timestamp(as_of)
        duration = pd.Timedelta(
            milliseconds=TIMEFRAME_MS[timeframe]
        )

        # 必須先截斷，再計算指標。
        data = df.loc[df.index + duration <= cutoff].copy()
        validate_frame(data, timeframe)
        gaps = missing_opens(data, timeframe)

        if len(gaps):
            raise ValueError(
                f"{timeframe} 資料缺漏 {len(gaps)} 根，"
                f"第一個缺口：{gaps[0]}"
            )

        fvg_events = []
        swing_events = []
        ob_events = []

        # 僅存放當時已確認的最近 Swing。
        latest_high = None
        latest_low = None
        length = self.config.swing_length

        for i in range(len(data)):
            candle = data.iloc[i]
            closed_at = data.index[i] + duration

            # 先更新既有區域，再新增本根才確認的區域。
            self._update_zones(fvg_events, candle, closed_at)
            self._update_zones(ob_events, candle, closed_at)

            # ---------- FVG ----------
            if i >= 2:
                first = data.iloc[i - 2]
                middle = data.iloc[i - 1]

                bullish = (
                    first["high"] < candle["low"]
                    and middle["close"] > middle["open"]
                )
                bearish = (
                    first["low"] > candle["high"]
                    and middle["close"] < middle["open"]
                )

                if bullish:
                    fvg_events.append(
                        make_event(
                            kind="fvg", direction=1,
                            source_at=data.index[i - 1],
                            confirmed_at=closed_at,
                            top=candle["low"], bottom=first["high"],
                        )
                    )
                elif bearish:
                    fvg_events.append(
                        make_event(
                            kind="fvg", direction=-1,
                            source_at=data.index[i - 1],
                            confirmed_at=closed_at,
                            top=first["low"], bottom=candle["high"],
                        )
                    )

            # ---------- Swing ----------
            # 中心位置為 i-length，此時右邊 N 根才剛收盤。
            if i >= 2 * length:
                center = i - length
                left = data.iloc[center - length:center]
                right = data.iloc[center + 1:i + 1]
                center_candle = data.iloc[center]

                high = float(center_candle["high"])
                low = float(center_candle["low"])

                is_high = (
                    high > left["high"].max()
                    and high > right["high"].max()
                )
                is_low = (
                    low < left["low"].min()
                    and low < right["low"].min()
                )

                if is_high:
                    latest_high = {
                        "index": center,
                        "level": high,
                        "broken": False,
                    }
                    swing_events.append(
                        make_event(
                            kind="swing_high", direction=0,
                            source_at=data.index[center],
                            confirmed_at=closed_at,
                            top=high, bottom=high,
                        )
                    )

                if is_low:
                    latest_low = {
                        "index": center,
                        "level": low,
                        "broken": False,
                    }
                    swing_events.append(
                        make_event(
                            kind="swing_low", direction=0,
                            source_at=data.index[center],
                            confirmed_at=closed_at,
                            top=low, bottom=low,
                        )
                    )

            # ---------- OB ----------
            if i == 0:
                continue

            previous_close = float(data.iloc[i - 1]["close"])
            close = float(candle["close"])

            for direction, swing in ((1, latest_high), (-1, latest_low)):
                if swing is None or swing["broken"]:
                    continue

                level = swing["level"]
                crossed = (
                    previous_close <= level < close
                    if direction == 1
                    else previous_close >= level > close
                )

                if not crossed:
                    continue

                # 即使沒找到合適 OB，也不重複處理同一突破。
                swing["broken"] = True
                search_start = max(swing["index"], i - self.config.ob_lookback)
                
                # OB尋找邏輯: (簡單版佔位，完整細節可根據需求再深化)
                # 這裡為了維持原意，暫時只標記已突破，後續可以依據黑K/紅K找OB
                # (交接文件中提到會尋找最近反向 K 線)
                
        return {
            "fvg": events_frame(fvg_events),
            "swings": events_frame(swing_events),
            "ob": events_frame(ob_events)
        }