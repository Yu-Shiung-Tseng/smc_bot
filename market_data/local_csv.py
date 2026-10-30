from pathlib import Path
import os
import tempfile

import numpy as np
import pandas as pd

TIMEFRAME_MS = {
    "5m": 5 * 60 * 1000,
    "1h": 60 * 60 * 1000,
    "4h": 4 * 60 * 60 * 1000,
}

COLUMNS = ["open", "high", "low", "close", "volume"]

def utc_timestamp(value) -> pd.Timestamp:
    """沒有時區的輸入一律解讀為 UTC。"""
    timestamp = pd.Timestamp(value)

    if pd.isna(timestamp):
        raise ValueError("時間不可為空")

    if timestamp.tzinfo is None:
        return timestamp.tz_localize("UTC")

    return timestamp.tz_convert("UTC")

def empty_frame() -> pd.DataFrame:
    return pd.DataFrame(
        columns=COLUMNS,
        index=pd.DatetimeIndex([], tz="UTC", name="timestamp"),
        dtype=float,
    )

def validate_frame(df: pd.DataFrame, timeframe: str) -> None:
    """驗證結構、價格、時間邊界。缺口由 missing_opens 檢查。"""
    if timeframe not in TIMEFRAME_MS:
        raise ValueError(f"不支援的週期：{timeframe}")

    if list(df.columns) != COLUMNS:
        raise ValueError(f"欄位必須為：{COLUMNS}")

    if not isinstance(df.index, pd.DatetimeIndex):
        raise ValueError("索引必須是 DatetimeIndex")

    if df.index.tz is None or str(df.index.tz) != "UTC":
        raise ValueError("時間索引必須使用 UTC")

    if df.index.hasnans:
        raise ValueError("時間索引包含空值")

    if df.index.has_duplicates:
        raise ValueError("資料包含重複時間")

    if not df.index.is_monotonic_increasing:
        raise ValueError("資料時間必須遞增")

    if df.empty:
        return

    values = df[COLUMNS].to_numpy(dtype=float)

    if not np.isfinite(values).all():
        raise ValueError("OHLCV 包含 NaN 或無限值")

    if (df[["open", "high", "low", "close"]] <= 0).any().any():
        raise ValueError("價格必須大於零")

    if (df["volume"] < 0).any():
        raise ValueError("成交量不可為負數")

    if (df["high"] < df[["open", "close", "low"]].max(axis=1)).any():
        raise ValueError("high 小於其他價格欄位")

    if (df["low"] > df[["open", "close", "high"]].min(axis=1)).any():
        raise ValueError("low 大於其他價格欄位")

    step = pd.Timedelta(milliseconds=TIMEFRAME_MS[timeframe])

    if not (df.index == df.index.floor(step)).all():
        raise ValueError("K 線時間沒有對齊週期邊界")

def missing_opens(
    df: pd.DataFrame,
    timeframe: str,
) -> pd.DatetimeIndex:
    """列出第一根與最後一根之間缺少的 K 線開盤時間。"""
    if len(df) < 2:
        return pd.DatetimeIndex([], tz="UTC", name="timestamp")

    expected = pd.date_range(
        start=df.index[0],
        end=df.index[-1],
        freq=pd.Timedelta(milliseconds=TIMEFRAME_MS[timeframe]),
        name="timestamp",
    )

    return expected.difference(df.index)

class LocalCsvStore:
    def __init__(self, root="data/binance_spot"):
        self.root = Path(root)

    def path_for(self, symbol: str, timeframe: str) -> Path:
        if timeframe not in TIMEFRAME_MS:
            raise ValueError(f"不支援的週期：{timeframe}")

        safe_symbol = symbol.replace("/", "_").replace(":", "_")
        return self.root / safe_symbol / f"{timeframe}.csv"

    def read(
        self,
        symbol: str,
        timeframe: str,
        *,
        as_of=None,
        strict=True,
    ) -> pd.DataFrame:
        path = self.path_for(symbol, timeframe)

        if not path.exists():
            raise FileNotFoundError(f"本地資料不存在：{path}")

        raw = pd.read_csv(path)

        if list(raw.columns) != ["timestamp", *COLUMNS]:
            raise ValueError(f"CSV 欄位不正確：{path}")

        timestamps = pd.to_numeric(raw.pop("timestamp"), errors="raise")

        df = raw[COLUMNS].astype(float)
        df.index = pd.DatetimeIndex(
            pd.to_datetime(timestamps, unit="ms", utc=True),
            name="timestamp",
        )

        validate_frame(df, timeframe)

        if as_of is not None:
            cutoff = utc_timestamp(as_of)
            duration = pd.Timedelta(
                milliseconds=TIMEFRAME_MS[timeframe]
            )
            # timestamp 是開盤時間，必須加上週期才是收盤時間。
            df = df.loc[df.index + duration <= cutoff].copy()

        if strict:
            gaps = missing_opens(df, timeframe)
            if len(gaps):
                raise ValueError(
                    f"{path} 有 {len(gaps)} 根缺漏 K 線，"
                    f"第一個缺口：{gaps[0]}"
                )

        return df

    def write(
        self,
        symbol: str,
        timeframe: str,
        df: pd.DataFrame,
    ) -> Path:
        validate_frame(df, timeframe)

        if df.empty:
            raise ValueError("不保存空資料")

        path = self.path_for(symbol, timeframe)
        path.parent.mkdir(parents=True, exist_ok=True)

        output = df.copy()

        # 使用數值時間戳，避免 CSV 日期格式與時區歧義。
        timestamp_ms = [
            int(timestamp.value // 1_000_000)
            for timestamp in df.index
        ]
        output.insert(0, "timestamp", timestamp_ms)

        # 先寫暫存檔，再替換正式檔，避免留下半份 CSV。
        fd, temporary = tempfile.mkstemp(
            dir=path.parent,
            suffix=".tmp",
        )
        os.close(fd)

        try:
            output.to_csv(temporary, index=False)
            os.replace(temporary, path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)

        return path

    def load_mtf(
        self,
        symbol: str,
        *,
        as_of=None,
        strict=True,
    ) -> dict[str, pd.DataFrame]:
        return {
            timeframe: self.read(
                symbol,
                timeframe,
                as_of=as_of,
                strict=strict,
            )
            for timeframe in TIMEFRAME_MS
        }