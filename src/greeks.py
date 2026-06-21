"""
Black-Scholes greeks — pure math, stdlib only.

All inputs are per-share / annualised.  Theta is returned as the daily
dollar-per-share decay (divide the annual figure by 365).
Vega is per 1 percentage-point change in IV (i.e. d_price / d_sigma * 0.01).
"""
from __future__ import annotations
import math
from src.models import Greeks


# ---------------------------------------------------------------------------
# Normal distribution helpers
# ---------------------------------------------------------------------------

def _norm_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def _norm_pdf(x: float) -> float:
    return math.exp(-0.5 * x * x) / math.sqrt(2.0 * math.pi)


# ---------------------------------------------------------------------------
# d1 / d2
# ---------------------------------------------------------------------------

def _d1_d2(
    S: float,   # spot price
    K: float,   # strike
    T: float,   # time to expiry in years
    r: float,   # risk-free rate
    sigma: float,  # annualised IV
) -> tuple[float, float]:
    if T <= 0 or sigma <= 0:
        raise ValueError(f"T and sigma must be positive (got T={T}, sigma={sigma})")
    vol_sqrt_T = sigma * math.sqrt(T)
    d1 = (math.log(S / K) + (r + 0.5 * sigma ** 2) * T) / vol_sqrt_T
    d2 = d1 - vol_sqrt_T
    return d1, d2


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def compute_greeks(
    spot: float,
    strike: float,
    dte: int,         # calendar days to expiry
    iv: float,        # annualised implied vol as a decimal (e.g. 0.30)
    option_type: str, # "call" or "put"
    risk_free_rate: float = 0.045,
) -> Greeks:
    """Return Black-Scholes greeks for one option contract (per-share basis)."""
    T = dte / 365.0
    if T <= 0:
        # Expired — greeks are degenerate
        intrinsic = max(0.0, spot - strike) if option_type == "call" else max(0.0, strike - spot)
        delta = (1.0 if option_type == "call" else -1.0) if intrinsic > 0 else 0.0
        return Greeks(delta=delta, gamma=0.0, theta=0.0, vega=0.0)

    S, K, r, sigma = spot, strike, risk_free_rate, iv
    d1, d2 = _d1_d2(S, K, T, r, sigma)
    pdf_d1 = _norm_pdf(d1)
    sqrt_T = math.sqrt(T)
    disc = math.exp(-r * T)

    if option_type == "call":
        delta = _norm_cdf(d1)
        theta_annual = (
            -S * pdf_d1 * sigma / (2.0 * sqrt_T)
            - r * K * disc * _norm_cdf(d2)
        )
    else:
        delta = _norm_cdf(d1) - 1.0
        theta_annual = (
            -S * pdf_d1 * sigma / (2.0 * sqrt_T)
            + r * K * disc * _norm_cdf(-d2)
        )

    gamma = pdf_d1 / (S * sigma * sqrt_T)
    theta = theta_annual / 365.0          # per calendar day
    vega = S * pdf_d1 * sqrt_T * 0.01    # per 1 pp move in IV

    return Greeks(delta=delta, gamma=gamma, theta=theta, vega=vega)
