import argparse
import json
import logging
from pathlib import Path

from market_data.local_csv import LocalCsvStore, utc_timestamp
from strategy.mtf_fvg_strategy import MTFFVGStrategy

PROJECT_ROOT = Path(__file__).resolve().parent

def main():
    parser = argparse.ArgumentParser(
        description="指定歷史時間點，讀取本地 CSV 產出 SMC 交易計畫"
    )
    parser.add_argument("--symbol", default="ETH/USDT")
    parser.add_argument(
        "--as-of",
        required=True,
        help="決策時間點 (ISO 格式，如 2026-10-15T12:00:00Z)",
    )
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=PROJECT_ROOT / "data" / "binance_spot",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="選填：將 JSON 決策結果保存至檔案路徑",
    )

    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    store = LocalCsvStore(args.data_dir)
    as_of_dt = utc_timestamp(args.as_of)

    try:
        # 讀取截至 as_of 當時已收盤的本地 CSV
        dfs = store.load_mtf(args.symbol, as_of=as_of_dt)
    except Exception as e:
        logging.error("讀取本地數據失敗: %s", e)
        raise SystemExit(1)

    strategy = MTFFVGStrategy()
    decision = strategy.decide(args.symbol, dfs, as_of=as_of_dt)

    result_json = json.dumps(decision.to_dict(), indent=2, ensure_ascii=False)
    print("\n=== SMC 策略離線決策報告 ===")
    print(result_json)

    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(result_json, encoding="utf-8")
        print(f"\n已將報告寫入 {args.output}")

if __name__ == "__main__":
    main()