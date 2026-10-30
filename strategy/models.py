from dataclasses import asdict, dataclass
from typing import Any, Optional

@dataclass(frozen=True)
class TradePlan:
    signal_id: str
    symbol: str
    direction: int  # 1 為看多 (LONG), -1 為看空 (SHORT)
    as_of: str
    trigger_candle_at: str
    reference_price: float
    stop_loss: float
    fvg_top: float
    fvg_bottom: float
    fvg_source_at: str
    fvg_confirmed_at: str
    htf_fvg_source_at: str
    ob_source_at: Optional[str] = None
    ob_top: Optional[float] = None
    ob_bottom: Optional[float] = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

@dataclass(frozen=True)
class StrategyDecision:
    status: str  # "SIGNAL" | "NO_SIGNAL" | "ERROR"
    as_of: str
    symbol: str
    reason_code: str
    reason_msg: str
    plan: Optional[TradePlan] = None

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        if self.plan:
            data["plan"] = self.plan.to_dict()
        return data