import logging
import time

import ccxt
import pandas as pd

from .local_csv import (
    COLUMNS,
    TIMEFRAME_MS,
    LocalCsvStore,
    empty_frame,
    missing_opens,
    utc_timestamp,
    validate_frame,
)

logger = logging.getLogger(__name__)

class BinanceDownloader:
    def __init__(self, store: LocalCsvStore):
        self.store = store

        self.exchange = ccxt.binance({
            "enableRateLimit": True,
            "timeout": 30_000,
            "options": {"defaultType": "spot"},
        })

    def _request(self, function, *args, **kwargs):
        for attempt in range(4):
            try:
                return function(*args, **kwargs)
            except (ccxt.NetworkError, ccxt.RateLimitExceeded):
                if attempt == 3:
                    raise
                wait = 2 ** (attempt + 1)
                logger.warning("網路或限流錯誤，%s 秒後重試", wait)
                time.sleep(wait)

    def sync(
        self,
        symbol: str,
        timeframe: str,
        *,
        end,
        start=None,
    ) -> pd.DataFrame:
        step_ms = TIMEFRAME_MS[timeframe]
        step = pd.Timedelta(milliseconds=step_ms)

        # 此邊界之前的 K 線才允許保存。
        end_boundary = utc_timestamp(end).floor(step)
        end_ms = int(end_boundary.value // 1_000_000)

        path = self.store.path_for(symbol, timeframe)

        if path.exists():
            # 允許讀入存在缺口的資料，以便重新下載修補。
            old = self.store.read(symbol, timeframe, strict=False)
            # 例如更換截止時間時，不能保留截止時間之後的資料。
            old = old.loc[old.index + step <= end_boundary].copy()
        else:
            old = empty_frame()

        requested_start = (
            utc_timestamp(start).ceil(step)
            if start is not None
            else None
        )

        if old.empty:
            if requested_start is None:
                raise ValueError(
                    f"{symbol} {timeframe} 首次下載必須指定 --start"
                )
            fetch_start = requested_start
        else:
            # 重抓最後一根已保存 K 線，合併時用新資料覆蓋。
            fetch_start = old.index[-1]
            gaps = missing_opens(old, timeframe)
            if len(gaps):
                fetch_start = min(fetch_start, gaps[0])
            # 若指定更早的日期，補抓更早的資料。
            if requested_start is not None:
                fetch_start = min(fetch_start, requested_start)

        if fetch_start >= end_boundary:
            raise ValueError(
                f"{timeframe} 起始時間必須早於可用截止時間"
            )

        cursor = int(fetch_start.value // 1_000_000)
        collected = []

        while cursor < end_ms:
            batch = self._request(
                self.exchange.fetch_ohlcv,
                symbol,
                timeframe,
                since=cursor,
                limit=1000,
            )

            if not batch:
                break

            batch = sorted(batch, key=lambda candle: candle[0])

            # 只接收指定範圍內、已收盤的 K 線。
            accepted = [
                candle
                for candle in batch
                if cursor <= candle[0]
                and candle[0] + step_ms <= end_ms
            ]
            collected.extend(accepted)

            last_timestamp = int(batch[-1][0])
            next_cursor = last_timestamp + step_ms

            if next_cursor <= cursor:
                raise RuntimeError("下載分頁沒有向前推進")

            cursor = next_cursor

            logger.info(
                "%s %s：本次收到 %s 根，累計新資料 %s 根",
                symbol,
                timeframe,
                len(accepted),
                len(collected),
            )

        if collected:
            fresh = pd.DataFrame(
                collected,
                columns=["timestamp", *COLUMNS],
            )
            timestamps = fresh.pop("timestamp")
            fresh.index = pd.DatetimeIndex(
                pd.to_datetime(timestamps, unit="ms", utc=True),
                name="timestamp",
            )
            fresh = fresh.astype(float)
        else:
            fresh = empty_frame()

        merged = pd.concat([old, fresh])

        merged = (
            merged.loc[~merged.index.duplicated(keep="last")]
            .sort_index()
        )

        if merged.empty:
            raise RuntimeError(
                f"{symbol} {timeframe} 未取得資料，不寫入檔案"
            )

        validate_frame(merged, timeframe)

        gaps = missing_opens(merged, timeframe)

        if len(gaps):
            raise RuntimeError(
                f"{symbol} {timeframe} 仍有 {len(gaps)} 根缺漏，"
                f"第一個缺口：{gaps[0]}。原檔案不覆蓋。"
            )

        # 檢查最晚的已收盤 K 線是否取得。
        expected_last = end_boundary - step

        if merged.index[-1] != expected_last:
            raise RuntimeError(
                f"{symbol} {timeframe} 尾端資料不足："
                f"預期 {expected_last}，取得 {merged.index[-1]}。"
                "請稍後重試；原檔案不覆蓋。"
            )

        # 檢查使用者要求的歷史起點是否有取得。
        if (
            requested_start is not None
            and merged.index[0] > requested_start
        ):
            raise RuntimeError(
                f"{symbol} {timeframe} 無法取得指定起點 "
                f"{requested_start}，最早只有 {merged.index[0]}。"
                "請檢查商品上市時間或調整 --start。"
            )

        saved_path = self.store.write(symbol, timeframe, merged)

        logger.info(
            "已保存 %s，共 %s 根，範圍 %s ～ %s",
            saved_path,
            len(merged),
            merged.index[0],
            merged.index[-1],
        )

        return merged

    def sync_all(self, symbol: str, *, start=None, end=None):
        self._request(self.exchange.load_markets)

        if symbol not in self.exchange.markets:
            raise ValueError(f"Binance 不存在商品：{symbol}")

        server_ms = self._request(self.exchange.fetch_time)

        # 留五秒緩衝，避免剛收盤時資料尚未發布完成。
        safe_end = pd.to_datetime(
            server_ms - 5_000,
            unit="ms",
            utc=True,
        )

        if end is not None:
            safe_end = min(safe_end, utc_timestamp(end))

        return {
            timeframe: self.sync(
                symbol,
                timeframe,
                start=start,
                end=safe_end,
            )
            for timeframe in TIMEFRAME_MS
        }