import logging
from typing import Optional
from risk.models import RiskConfig, SizedOrder
from strategy.models import TradePlan

logger = logging.getLogger(__name__)

class RiskManager:
    def __init__(self, config: Optional[RiskConfig] = None):
        self.config = config or RiskConfig()

    def size_order(self, plan: TradePlan, current_balance: float) -> Optional[SizedOrder]:
        """
        根據帳戶餘額、止損距離與風險承受度，計算出安全的下單數量。
        """
        entry_price = plan.reference_price
        sl_price = plan.stop_loss

        # 1. 計算止損距離 (%)
        sl_distance_pct = abs(entry_price - sl_price) / entry_price
        if sl_distance_pct == 0:
            logger.warning("止損距離為 0，拒絕計算倉位")
            return None

        # 2. 計算允許虧損的金額 (USDT)
        risk_amount = current_balance * self.config.risk_per_trade

        # 3. 計算倉位總價值 (USDT)
        # 公式: 倉位價值 = 允許虧損金額 / 止損距離比例
        position_value = risk_amount / sl_distance_pct
        
        # 4. 槓桿與保證金檢查
        margin_required = position_value / self.config.max_leverage
        if margin_required > current_balance:
            logger.warning(
                f"所需保證金 ({margin_required:.2f}) 超過當前餘額 ({current_balance:.2f})，"
                "進行降倉調整。"
            )
            # 降倉至全倉可用餘額的 95% (保留空間扣手續費)
            margin_required = current_balance * 0.95
            position_value = margin_required * self.config.max_leverage
            # 重新計算預期虧損
            risk_amount = position_value * sl_distance_pct

        # 5. 計算下單數量 (Coin) 與止盈價
        qty_coin = position_value / entry_price
        
        # 預設採用固定盈虧比計算 TP (後續可改為移動止盈)
        if plan.direction == 1:
            take_profit = entry_price + (entry_price - sl_price) * self.config.reward_to_risk
        else:
            take_profit = entry_price - (sl_price - entry_price) * self.config.reward_to_risk

        return SizedOrder(
            plan=plan,
            entry_price=entry_price,
            stop_loss=sl_price,
            take_profit=take_profit,
            qty_coin=qty_coin,
            position_value=position_value,
            margin_required=margin_required,
            leverage_used=self.config.max_leverage,
            expected_loss=risk_amount
        )