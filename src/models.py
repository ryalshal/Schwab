from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class OptionPosition:
    asset_type: str          # "option"
    ticker: str
    option_type: str         # "call" | "put"
    strike: float
    expiry: str              # YYYY-MM-DD
    entry_price: float       # per-share premium paid
    contracts: int           # number of contracts (1 contract = 100 shares)
    entry_date: str          # YYYY-MM-DD
    id: Optional[str] = None
    target_price: Optional[float] = None   # per share
    stop_price: Optional[float] = None     # per share

    def __post_init__(self) -> None:
        if self.id is None:
            expiry_compact = self.expiry.replace("-", "")
            flag = self.option_type[0].upper()
            self.id = f"{self.ticker}_{flag}{int(self.strike)}_{expiry_compact}"

    @property
    def entry_value(self) -> float:
        return self.entry_price * 100 * self.contracts


@dataclass
class SharePosition:
    asset_type: str          # "shares"
    ticker: str
    entry_price: float       # per share
    contracts: int           # share count
    entry_date: str          # YYYY-MM-DD
    id: str
    target_price: Optional[float] = None
    stop_price: Optional[float] = None

    @property
    def entry_value(self) -> float:
        return self.entry_price * self.contracts


Position = OptionPosition | SharePosition


@dataclass
class Greeks:
    delta: float
    gamma: float
    theta: float   # per calendar day, in dollars per share
    vega: float    # per 1 percentage-point move in IV, in dollars per share


@dataclass
class OptionMarketData:
    bid: Optional[float]
    ask: Optional[float]
    last: float
    iv: float
    volume: int
    open_interest: int
    mark: float    # mid when bid+ask available, else last


@dataclass
class SpotMarketData:
    last: float
    mark: float    # same as last for equities


@dataclass
class OptionValuation:
    position_id: str
    ticker: str
    option_type: str
    strike: float
    expiry: str
    contracts: int
    mark: float
    current_value: float        # mark * 100 * contracts
    entry_value: float
    unrealized_pnl: float
    unrealized_pnl_pct: float
    dte: int
    greeks: Greeks
    iv: float
    progress_to_target: Optional[float]   # % of way from entry → target
    progress_to_stop: Optional[float]     # % of way from entry → stop
    market_data: OptionMarketData


@dataclass
class ShareValuation:
    position_id: str
    ticker: str
    contracts: int
    mark: float
    current_value: float
    entry_value: float
    unrealized_pnl: float
    unrealized_pnl_pct: float
    progress_to_target: Optional[float]
    progress_to_stop: Optional[float]
    market_data: SpotMarketData


Valuation = OptionValuation | ShareValuation
