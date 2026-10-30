from dataclasses import asdict, dataclass
from typing import Any
from strategy.models import TradePlan

@dataclass(frozen=True)
class RiskConfig:
    initial_balance: float = 1000.0    # 初始本金 USDT
    risk_per_trade: float = 0.02       # 每次交易願承受的最高虧損比例 (2%)
    max_leverage: float = 10.0         # 最大允許槓桿
    fee_rate: float = 0.0005           # 模擬交易所手續費 (0.05%)
    reward_to_risk: float = 2.0        # 盈虧比 (預設 1:2，賺要是賠的兩倍)

@dataclass(frozen=True)
class SizedOrder:
    plan: TradePlan
    entry_price: float
    stop_loss: float
    take_profit: float
    qty_coin: float             # 下單數量 (ETH)
    position_value: float       # 倉位總價值 (USDT)
    margin_required: float      # 需要動用的保證金 (USDT)
    leverage_used: float        # 實際使用的槓桿
    expected_loss: float        # 若觸發止損的預期虧損金額

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["plan"] = self.plan.to_dict()
        return data