import os
import pandas as pd
import numpy as np
import ccxt
from dotenv import load_dotenv
from smartmoneyconcepts import smc

# 載入 .env 檔案
load_dotenv()

class SmartMoneyCryptoBot:
    def __init__(self, symbol="ETH/USDT", leverage=10, sl_percent_limit=0.05):
        # 初始化 BingX API (讀取環境變數)
        self.exchange = ccxt.bingx({
            'apiKey': os.getenv("BINGX_API_KEY"),
            'secret': os.getenv("BINGX_SECRET_KEY"),
            'enableRateLimit': True,
        })
        self.symbol = symbol
        self.leverage = leverage
        self.sl_percent_limit = sl_percent_limit

    def fetch_market_data(self, timeframe='1h', limit=200):
        """
        透過 CCXT 獲取 BingX 的真實 K 線資料，並整理成 SMC 套件需要的格式
        """
        print(f"正在獲取 {self.symbol} {timeframe} K線數據...")
        # 抓取公開的 OHLCV 資料 (即使沒有 API Key 也可以抓)
        ohlcv = self.exchange.fetch_ohlcv(self.symbol, timeframe, limit=limit)
        
        # SMC 套件要求欄位必須是小寫的 open, high, low, close, volume
        df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
        df.set_index('timestamp', inplace=True)
        # 確保資料為浮點數
        df = df.astype(float)
        return df

    def analyze_smc_signals(self, df_1h):
        """
        核心邏輯：計算 SMC 指標，並判斷是否產生進場訊號
        """
        print("正在計算 SMC 聰明錢指標 (FVG & OB)...")
        # 1. 透過 smc 套件計算指標
        fvg_df = smc.fvg(df_1h)
        ob_df = smc.ob(df_1h)
        
        # 將指標合併回原始 K 線 DataFrame
        df = pd.concat([df_1h, fvg_df, ob_df], axis=1)
        
        is_entry = False
        side = None
        entry_price = 0.0
        sl_price = 0.0
        tp_price = 0.0 

        current_price = df['close'].iloc[-1]
        
        # 尋找最近「未被填補 (Unmitigated)」的看多 FVG (FVG == 1)
        # MitigatedIndex 如果是 0 或 NaN，代表還沒被回補
        bullish_fvgs = df[(df['FVG'] == 1)]
        
        # 尋找看多的訂單塊 (OB == 1)
        bullish_obs = df[(df['OB'] == 1)]

        if not bullish_fvgs.empty and not bullish_obs.empty:
            side = "LONG"
            # 取最後一個（最近發生）的 FVG 與 OB
            latest_fvg = bullish_fvgs.iloc[-1]
            latest_ob = bullish_obs.iloc[-1]
            
            nearest_fvg_top = latest_fvg['Top']
            nearest_fvg_bottom = latest_fvg['Bottom']
            nearest_ob_bottom = latest_ob['Bottom']
            
            print(f"近期看多 FVG 區間: {nearest_fvg_bottom} ~ {nearest_fvg_top}")
            
            # 判斷是否進場：當前價格回踩到 FVG 區間內
            if nearest_fvg_bottom <= current_price <= nearest_fvg_top:
                print("觸發進場條件！價格落入失衡區。")
                is_entry = True
                entry_price = current_price
                
                # 止損邏輯：結構止損 (OB下緣) 與保護止損 取較安全者
                structural_sl = nearest_ob_bottom * 0.999 
                hard_sl = entry_price * (1 - self.sl_percent_limit)
                sl_price = max(structural_sl, hard_sl) 

                # 止盈邏輯：抓 5% 作為移動止盈觸發點
                tp_price = entry_price * 1.05 
        else:
            print("目前圖表上找不到未填補的多頭 FVG 或 OB。")

        return [is_entry, side, entry_price, sl_price, tp_price]

    def execute_bingx_order(self, signal):
        """
        執行 BingX 下單
        """
        is_entry, side, entry_price, sl_price, tp_price = signal
        if not is_entry:
            print("== 結論：目前無進場訊號 ==")
            return

        print(f"== 結論：準備進場 ==")
        print(f"方向: {side} | 價格: {entry_price} | 止損: {sl_price} | 移動止盈激活價: {tp_price}")
        # 這裡未來可以放真實的 ccxt create_order 語法

if __name__ == "__main__":
    # 測試執行
    bot = SmartMoneyCryptoBot(symbol="ETH/USDT")
    
    # 抓取最近 200 根 1 小時 K 線
    df_1h = bot.fetch_market_data(timeframe='1h', limit=200)
    
    # 分析訊號
    signal = bot.analyze_smc_signals(df_1h)
    
    # 模擬下單決策
    bot.execute_bingx_order(signal)