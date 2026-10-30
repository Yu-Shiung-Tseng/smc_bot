import argparse
import logging
from pathlib import Path

from market_data.binance_download import BinanceDownloader
from market_data.local_csv import LocalCsvStore

PROJECT_ROOT = Path(__file__).resolve().parent

def main():
    parser = argparse.ArgumentParser(
        description="下载 Binance 已收盤 K 線到本地 CSV"
    )

    parser.add_argument("--symbol", default="ETH/USDT")
    parser.add_argument(
        "--start",
        help="首次下載起點，沒有時區時視為 UTC",
    )
    parser.add_argument(
        "--end",
        help="選填截止時間；只保存此時間前已收盤的 K 線",
    )
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=PROJECT_ROOT / "data" / "binance_spot",
    )

    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )

    store = LocalCsvStore(args.data_dir)
    downloader = BinanceDownloader(store)

    try:
        datasets = downloader.sync_all(
            args.symbol,
            start=args.start,
            end=args.end,
        )
    except Exception:
        logging.exception("下載失敗")
        raise SystemExit(1)

    print("\n=== 本地資料摘要 ===")

    for timeframe, df in datasets.items():
        print(
            f"{timeframe:>3} | {len(df):>7} 根 | "
            f"{df.index[0]} ～ {df.index[-1]}"
        )

if __name__ == "__main__":
    main()