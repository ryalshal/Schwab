RISK_FREE_RATE: float = 0.045
CONTRACTS_PER_OPTION: int = 100
DB_PATH: str = "portfolio.db"
SNAPSHOTS_DIR: str = "snapshots"
POSITIONS_FILE: str = "positions.json"

# Analytics — allocation concentration caps
TICKER_CONCENTRATION_CAP: float = 0.40   # warn if any ticker > 40% of book
SECTOR_CONCENTRATION_CAP: float = 0.60   # warn if any sector > 60% of book

# Analytics — IV rank/percentile lookback
IV_LOOKBACK_DAYS: int = 252              # calendar days of history to use
IV_MIN_HISTORY_DAYS: int = 20            # days needed before rank is meaningful
IV_RICH_THRESHOLD: float = 70.0          # IV rank/percentile above which = "rich"
IV_CHEAP_THRESHOLD: float = 30.0         # IV rank/percentile below which = "cheap"

# Analytics — DTE proximity flag
DTE_WARNING_THRESHOLD: int = 45          # flag options with DTE <= this value

# ── Chain diff ────────────────────────────────────────────────────────────────
CHAIN_DIFF_STRIKE_BAND: float = 0.30   # flag new strikes within ±30% of held strikes

# ── Condition alerts ──────────────────────────────────────────────────────────
ALERT_TARGET_NEAR_PCT: float = 0.80    # fire "target_near" when progress ≥ 80%
ALERT_IV_CHANGE_PCT: float = 0.20      # fire "iv_change" when IV moves ≥ 20%

# ── Notifier ─────────────────────────────────────────────────────────────────
NOTIFIER_TELEGRAM_ENABLED: bool = False
NOTIFIER_IMESSAGE_ENABLED: bool = False
NOTIFIER_IMESSAGE_RECIPIENT: str = ""  # phone number or Apple ID email

NOTIFIER_EMAIL_ENABLED: bool = True
NOTIFIER_EMAIL_TO: str = "ryanaalford@gmail.com"
NOTIFIER_EMAIL_FROM: str = "ryanaalford@gmail.com"
NOTIFIER_EMAIL_SMTP_HOST: str = "smtp.gmail.com"
NOTIFIER_EMAIL_SMTP_PORT: int = 587   # STARTTLS

# ── Macro gate ────────────────────────────────────────────────────────────────
MACRO_VIX_WEIGHT:    float = 0.30
MACRO_TERM_WEIGHT:   float = 0.25   # VIX / VIX3M term structure
MACRO_BREADTH_WEIGHT: float = 0.25  # % of sector ETFs above 200-day MA
MACRO_CREDIT_WEIGHT: float = 0.20   # HYG/TLT ratio percentile

# Sector ETF breadth basket (should be above 200-day MA)
MACRO_BREADTH_BASKET: list[str] = [
    "XLK", "XLF", "XLV", "XLY", "XLI",
    "XLE", "XLP", "XLU", "XLB", "XLRE",
]

MACRO_LOOKBACK_DAYS: int = 252       # history window for VIX/credit percentile
MACRO_CAUTION_THRESHOLD: float = 40.0   # composite below this → CAUTION
MACRO_RISK_OFF_THRESHOLD: float = 25.0  # composite below this → RISK-OFF

# ── News analysis ─────────────────────────────────────────────────────────────
NEWS_MODEL: str = "claude-haiku-4-5"   # haiku for cost-efficient daily runs
NEWS_WINDOW_DAYS: int = 3              # pull headlines from last N days
NEWS_MAX_HEADLINES: int = 15           # cap before sending to Claude
NEWS_CACHE_TTL_HOURS: int = 8         # re-use SQLite cache within same day

# Sector map — checked before falling back to yfinance info
SECTOR_MAP: dict[str, str] = {
    "AAPL": "Technology",
    "MSFT": "Technology",
    "NVDA": "Technology",
    "AMD":  "Technology",
    "GOOGL":"Technology",
    "META": "Technology",
    "AMZN": "Consumer Discretionary",
    "TSLA": "Consumer Discretionary",
    "JPM":  "Financials",
    "GS":   "Financials",
    "BAC":  "Financials",
    "XOM":  "Energy",
    "CVX":  "Energy",
    "JNJ":  "Health Care",
    "UNH":  "Health Care",
    "SPY":  "ETF – Broad Market",
    "QQQ":  "ETF – Technology",
    "IWM":  "ETF – Small Cap",
    "GLD":  "ETF – Commodities",
    "TLT":  "ETF – Fixed Income",
}
