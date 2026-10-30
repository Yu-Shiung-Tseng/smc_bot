SMC Bot (Smart Money Concepts 多時區量化交易機器人)

這是一個基於 SMC (聰明錢概念) 與 多時區共振 (Multi-Timeframe) 邏輯開發的加密貨幣自動交易機器人。
目前專注於 ETH/USDT，透過本地離線回測來嚴格驗證策略，並預計將串接 BingX API 進行實盤自動化交易。

🎯 專案目標與核心策略

本專案不依賴傳統的均線或 RSI，而是模擬機構法人的交易行為：

大局觀 (HTF - 4H)： 尋找 4 小時線的 FVG (Fair Value Gap，資金缺口) 判斷當下的大趨勢方向。

進場區 (LTF - 1H)： 在 1 小時線中，尋找與 4H 趨勢同向的 FVG 作為埋伏區間。

精準觸發 (5m)： 當 5 分鐘線的價格回踩進入 1H FVG 區間，且沒有跌破不利邊界時，觸發進場。

防守與風控： 尋找同向的 OB (Order Block，訂單塊) 作為結構防守位 (Stop Loss)，並根據帳戶餘額進行嚴格的固定比例 (Risk %) 倉位計算。

📂 專案架構與模組說明

本專案採高度解耦的模組化設計，確保回測與實盤能共用同一套大腦：

/market_data/：市場資料模組。負責從 Binance (幣安) 下載歷史現貨 K 線，並處理斷點續傳、缺口修復、無未來資料污染的本地 CSV 儲存。

/indicators/：SMC 指標模組。不依賴第三方套件，自定義實作了嚴謹的 FVG, Swing High/Low, OB。嚴格區分「發生時間」與「確認可用時間」，杜絕 Look-ahead bias。

/strategy/：交易策略模組。接收多時區 K 線，過濾出符合 4H+1H+5m 共振條件的 TradePlan (交易計畫)。

/risk/：風控與倉位模組。將交易計畫轉換為實際的 SizedOrder，計算保證金、槓桿與精確的下單數量 (Coin Quantity)。

/tests/：單元測試模組。確保核心邏輯在重構時不會被破壞。

download_data.py：下載與更新歷史 K 線的 CLI 入口。

decide_local.py：本地離線策略決策測試入口。

run_backtest.py：時光機回測引擎 (模擬每一根 5m 推進)。

✅ 目前已達成里程碑

[x] 穩定且防未來資料的 Binance K 線下載器。

[x] 本地 CSV 讀寫與 DataFrame 驗證框架。

[x] 嚴謹的 SMC 指標運算 (FVG, Swing, OB 狀態追蹤)。

[x] 多時區共振決策大腦 (MTFFVGStrategy)。

[x] 風控倉位計算器 (RiskManager)。

[x] 基礎時光機回測引擎 (Backtest Engine) 雛形。

🚀 接下來要做的 (Next Steps / TODOs)

目前的系統已經具備完整的決策能力，但我們仍有以下關鍵任務需要完成：

效能優化 (最高優先級)： 目前的回測引擎在每個 5 分鐘推進時，會從頭重新計算數千根 K 線的指標，導致效能極差 (O(N²) 瓶頸)。需要導入狀態快取 (State Caching) 或增量計算機制。

串接 BingX 實盤 API (Execution)： 開發 execution/ 模組，將算好的 SizedOrder 轉換為 BingX V2 API 格式並送出真實訂單。

優化出場與止盈策略： 目前採用固定盈虧比，未來需實作更靈活的「移動止盈 (Trailing Stop)」機制。

狀態與部位記憶 (State Management)： 讓機器人能把「目前持有什麼單、進場原因」存在本地 JSON 或 SQLite，避免斷線重啟後重複下單。

排程自動化 (Scheduler)： 加入定時任務，每 5 分鐘自動醒來抓盤勢並決策。

⚙️ 如何執行 (快速上手)

# 1. 安裝依賴套件
pip install -r requirements.txt

# 2. 下載歷史資料 (例如 2026-07-01 至今)
python download_data.py --symbol ETH/USDT --start 2026-07-01

# 3. 測試單一時間點決策
python decide_local.py --symbol ETH/USDT --as-of 2026-10-20T12:00:00Z
