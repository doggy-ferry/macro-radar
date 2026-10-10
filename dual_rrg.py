"""Verified primary-market flow RRG mathematics (no trading-volume proxy)."""
from __future__ import annotations

import numpy as np
import pandas as pd


FLOW_TICKERS = ("XLK", "XLE", "XLF", "XLI", "XLY", "XLC", "XLV", "XLP", "XLU", "XLRE", "XLB", "SMH", "SOXX")


def flow_quadrant(x: float, y: float) -> str:
    if not np.isfinite(x) or not np.isfinite(y):
        return "N/A"
    return ("Leading" if y >= 100 else "Weakening") if x >= 100 else ("Improving" if y >= 100 else "Lagging")


def convergence_label(price_quadrant: str, flow_quadrant_name: str, five_day_flow: float) -> str:
    if flow_quadrant_name == "N/A" or not np.isfinite(five_day_flow):
        return "待核实 · 官方份额不足"
    if price_quadrant in {"Lagging", "Improving"} and flow_quadrant_name in {"Leading", "Improving"} and five_day_flow > 0:
        return "🔥 机构抢跑起爆"
    if price_quadrant == "Leading" and flow_quadrant_name == "Leading":
        return "🚀 真金主升浪"
    if price_quadrant == "Leading" and flow_quadrant_name in {"Lagging", "Weakening"}:
        return "⚠️ 缩量虚火诱多"
    if price_quadrant == "Lagging" and flow_quadrant_name == "Lagging":
        return "❄️ 双弱阴跌深渊"
    return "中性 · 继续观察"


def build_flow_rrg(prices: pd.DataFrame, share_records: dict[str, pd.DataFrame]) -> tuple[dict[str, pd.DataFrame], dict[str, float]]:
    """Use adjacent, *observed* share counts only; missing dates never imply zero flow.

    A cross-section is calculated for each trading day from valid 20-day
    intensity readings. A ticker needs a full 26-day lookback plus five recent
    coordinates to display a tail. Sparse historical baselines are not expanded.
    """
    if prices.empty:
        return {}, {}
    calendar = pd.DatetimeIndex(pd.to_datetime(prices.index).tz_localize(None)).normalize()
    intensity = pd.DataFrame(index=calendar, columns=FLOW_TICKERS, dtype=float)
    five_day_flows: dict[str, float] = {}
    for ticker in FLOW_TICKERS:
        records = share_records.get(ticker)
        if ticker not in prices or records is None or records.empty:
            continue
        required = {"date", "shares_outstanding"}
        if not required.issubset(records.columns):
            continue
        shares = records[["date", "shares_outstanding"]].copy()
        shares["date"] = pd.to_datetime(shares["date"], errors="coerce").dt.normalize()
        shares["shares_outstanding"] = pd.to_numeric(shares["shares_outstanding"], errors="coerce")
        shares = shares.dropna().query("shares_outstanding > 0").drop_duplicates("date", keep="last").set_index("date")
        shares = shares["shares_outstanding"].reindex(calendar)  # Deliberately never forward-fill.
        close = pd.Series(pd.to_numeric(prices[ticker], errors="coerce").to_numpy(), index=calendar)
        close = close.where(close.gt(0))
        flow = shares.diff().mul(close.shift(1)).where(shares.notna() & shares.shift(1).notna())
        aum = shares.mul(close)
        rolling_flow = flow.rolling(20, min_periods=20).sum()
        intensity[ticker] = rolling_flow.div(aum.where(aum.gt(0))).mul(100)
    count = intensity.notna().sum(axis=1)
    center = intensity.mean(axis=1)
    spread = intensity.std(axis=1, ddof=0).replace(0, np.nan)
    x_panel = intensity.sub(center, axis=0).div(spread, axis=0).mul(5).add(100).where(count.ge(2), axis=0)
    y_panel = x_panel.sub(x_panel.shift(5)).mul(2).add(100)
    trails: dict[str, pd.DataFrame] = {}
    for ticker in FLOW_TICKERS:
        coordinates = pd.DataFrame({"flow_ratio": x_panel[ticker], "flow_momentum": y_panel[ticker]})
        valid = coordinates.dropna()
        if valid.empty:
            continue
        last_date = valid.index[-1]
        # Issuer files commonly lag quotes by one session; older histories are stale.
        if calendar.get_loc(last_date) < len(calendar) - 2:
            continue
        tail = coordinates.loc[:last_date].tail(5)
        records = share_records.get(ticker)
        if len(tail) != 5 or not tail.notna().all().all() or records is None:
            continue
        observed = records[["date", "shares_outstanding"]].copy()
        observed["date"] = pd.to_datetime(observed["date"], errors="coerce").dt.normalize()
        observed["shares_outstanding"] = pd.to_numeric(observed["shares_outstanding"], errors="coerce")
        shares = observed.dropna().drop_duplicates("date", keep="last").set_index("date")["shares_outstanding"].reindex(calendar)
        close = pd.Series(pd.to_numeric(prices[ticker], errors="coerce").to_numpy(), index=calendar)
        recent_flow = shares.diff().mul(close.shift(1)).loc[:last_date].tail(5)
        if recent_flow.notna().all():
            trails[ticker] = tail
            five_day_flows[ticker] = float(recent_flow.sum())
    return trails, five_day_flows
