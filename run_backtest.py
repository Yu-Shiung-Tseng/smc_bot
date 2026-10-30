import argparse
import logging
import pandas as pd
from pathlib import Path
from tqdm import tqdm

from market_data.local_csv import LocalCsvStore, utc_timestamp
from strategy.mtf_fvg_strategy import MTFFVGStrategy
from risk.models import RiskConfig
from risk.risk_manager import RiskManager

PROJECT_ROOT = Path(__file__).resolve().parent

def main():
    parser = argparse.ArgumentParser(description="執行本地 SMC 策略時光機回測 (計算歷史勝率)")
    parser.add_argument("--symbol", default="ETH/USDT")
    parser.add_argument("--start", default="2026-10-15T00:00:00Z", help="回測起始時間 (給指標暖機用)")
    parser.add_argument("--end", default="2026-10-30T00:00:00Z", help="回測結束時間")
    parser.add_argument("--data-dir", type=Path, default=PROJECT_ROOT / "data" / "binance_spot")
    args = parser.parse_args()

    logging.basicConfig(level=logging.WARNING) # 回測時調低日誌層級，避免印出太多東西
    print(f"🚀 啟動 SMC 回測引擎 ({args.symbol})...")
    
    store = LocalCsvStore(args.data_dir)
    # 預先載入所有資料 (以 end 為截止)
    end_dt = utc_timestamp(args.end)
    full_dfs = store.load_mtf(args.symbol, as_of=end_dt)
    
    start_dt = utc_timestamp(args.start)
    df_5m = full_dfs["5m"]
    
    # 找出在 start_dt 之後的所有 5m K 線時間點作為「決策觸發點」
    simulation_times = df_5m[df_5m.index >= start_dt].index
    
    strategy = MTFFVGStrategy()
    risk_manager = RiskManager(RiskConfig(initial_balance=1000.0, reward_to_risk=2.0))
    
    current_balance = 1000.0
    position = None # 格式: SizedOrder
    used_signal_ids = set()
    trade_history = []
    
    print(f"⏱️ 準備模擬 {len(simulation_times)} 個 5 分鐘決策點...")
    
    for current_time in tqdm(simulation_times, desc="回測進度"):
        # 1. 如果持有倉位，檢查是否觸發停損 (SL) 或停利 (TP)
        if position:
            current_candle = df_5m.loc[current_time]
            high, low = current_candle['high'], current_candle['low']
            
            sl_hit, tp_hit = False, False
            exit_price = 0.0
            
            if position.plan.direction == 1: # 多單
                if low <= position.stop_loss: sl_hit = True; exit_price = position.stop_loss
                elif high >= position.take_profit: tp_hit = True; exit_price = position.take_profit
            else: # 空單
                if high >= position.stop_loss: sl_hit = True; exit_price = position.stop_loss
                elif low <= position.take_profit: tp_hit = True; exit_price = position.take_profit
                
            if sl_hit or tp_hit:
                # 計算損益
                pnl = (exit_price - position.entry_price) * position.qty_coin * position.plan.direction
                # 扣除兩次手續費 (開倉+平倉)
                fees = (position.entry_price * position.qty_coin + exit_price * position.qty_coin) * 0.0005
                net_pnl = pnl - fees
                current_balance += net_pnl
                
                trade_history.append({
                    "進場時間": position.plan.as_of,
                    "出場時間": current_time.isoformat(),
                    "方向": "LONG" if position.plan.direction == 1 else "SHORT",
                    "結果": "WIN 🟢" if tp_hit else "LOSS 🔴",
                    "淨利潤": round(net_pnl, 2),
                    "餘額": round(current_balance, 2)
                })
                position = None # 平倉清空
            continue # 如果還在持倉中，就不尋找新訊號

        # 2. 空手狀態：呼叫策略尋找新訊號
        # 截斷未來資料，確保策略只能看到 current_time 之前的資料
        sliced_dfs = {
            "4h": full_dfs["4h"][full_dfs["4h"].index <= current_time],
            "1h": full_dfs["1h"][full_dfs["1h"].index <= current_time],
            "5m": full_dfs["5m"][full_dfs["5m"].index <= current_time]
        }
        
        decision = strategy.decide(args.symbol, sliced_dfs, as_of=current_time, used_signal_ids=used_signal_ids)
        
        if decision.status == "SIGNAL" and decision.plan:
            # 3. 風控計算與開倉
            order = risk_manager.size_order(decision.plan, current_balance)
            if order:
                position = order
                used_signal_ids.add(decision.plan.signal_id)

    # 4. 回測結束，計算你要求的「勝率報告」
    print("\n\n" + "="*40)
    print("📊 SMC 策略歷史回測與勝率報告")
    print("="*40)
    
    if not trade_history:
        print("這段時間內沒有觸發任何交易。可能是盤勢不符或時間區間太短。")
    else:
        df_trades = pd.DataFrame(trade_history)
        wins = len(df_trades[df_trades["結果"] == "WIN 🟢"])
        total_trades = len(df_trades)
        win_rate = (wins / total_trades) * 100
        
        print(df_trades.to_string(index=False))
        print("-" * 40)
        print(f"💰 初始本金: 1000.00 USDT")
        print(f"💰 最終餘額: {current_balance:.2f} USDT")
        print(f"📈 總利潤率: {((current_balance - 1000) / 1000) * 100:.2f}%")
        print(f"🎯 總交易次數: {total_trades} 次")
        print(f"🏆 策略勝率 (Win Rate): {win_rate:.2f}%")
        print("="*40)

if __name__ == "__main__":
    main()