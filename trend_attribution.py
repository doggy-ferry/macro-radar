"""Vectorized slope and single-factor daily-return attribution calculations."""
from __future__ import annotations

import numpy as np
import pandas as pd


SLOPE_WINDOWS = (20, 50, 200)


def sma_slope_panel(close: pd.Series, lookback: int = 5) -> pd.DataFrame:
    """Full-history SMA and percentage-point-per-day slope, with no partial MAs."""
    series = pd.to_numeric(close, errors="coerce").replace([np.inf, -np.inf], np.nan)
    series = series.dropna().sort_index()
    if series.index.has_duplicates:
        series = series[~series.index.duplicated(keep="last")]
    panel = pd.DataFrame(index=series.index)
    for window in SLOPE_WINDOWS:
        ma = series.rolling(window, min_periods=window).mean()
        previous = ma.shift(lookback).where(lambda values: values.ne(0))
        panel[f"SMA{window}"] = ma
        panel[f"SMA{window} Slope"] = ma.sub(previous).div(lookback * previous).mul(100)
    return panel.replace([np.inf, -np.inf], np.nan)


def slope_statistics(panel: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for window in SLOPE_WINDOWS:
        column = f"SMA{window} Slope"
        source = panel[column] if column in panel else pd.Series(dtype=float)
        series = pd.to_numeric(source, errors="coerce").dropna()
        rows.append({
            "Moving Average": f"{window}DMA",
            "Current": float(series.iloc[-1]) if not series.empty else np.nan,
            "Mean": float(series.mean()) if not series.empty else np.nan,
            "Std": float(series.std(ddof=0)) if not series.empty else np.nan,
            "Min": float(series.min()) if not series.empty else np.nan,
            "Max": float(series.max()) if not series.empty else np.nan,
            "% days negative": float(series.lt(0).mean() * 100) if not series.empty else np.nan,
            "Observations": len(series),
        })
    return pd.DataFrame(rows)


def slope_regime(panel: pd.DataFrame) -> str:
    columns = [f"SMA{window} Slope" for window in SLOPE_WINDOWS]
    if panel.empty or not set(columns).issubset(panel.columns):
        return "INSUFFICIENT"
    latest = panel[columns].iloc[-1]
    if not np.isfinite(latest.to_numpy(dtype=float)).all():
        return "INSUFFICIENT"
    if latest.lt(0).all():
        return "SYSTEMIC_BREAK"
    if latest["SMA200 Slope"] > 0 and latest["SMA20 Slope"] < 0:
        return "BULLISH_DIP"
    return "MIXED"


def beta_return_decomposition(target: pd.Series, market: pd.Series,
                              window: int = 252) -> dict[str, float] | None:
    """252 aligned close-to-close returns; zero-rate daily beta residual, not CAPM alpha."""
    paired = pd.concat([target.rename("target"), market.rename("market")], axis=1, sort=False)
    paired = paired.apply(pd.to_numeric, errors="coerce").replace([np.inf, -np.inf], np.nan)
    paired = paired.sort_index()
    if paired.index.has_duplicates:
        paired = paired[~paired.index.duplicated(keep="last")]
    paired = paired.where(paired.gt(0))
    # Compute on the full common calendar before dropping nulls: an omitted
    # target quote must not turn a multi-session move into a false "1D" return.
    returns = paired.pct_change(fill_method=None).dropna().tail(window)
    if len(returns) < window:
        return None
    target_std = float(returns["target"].std(ddof=1))
    market_std = float(returns["market"].std(ddof=1))
    if not np.isfinite(target_std) or not np.isfinite(market_std) or market_std <= 0:
        return None
    correlation = float(returns["target"].corr(returns["market"]))
    if not np.isfinite(correlation):
        return None
    beta = correlation * target_std / market_std
    market_1d = float(returns["market"].iloc[-1] * 100)
    target_1d = float(returns["target"].iloc[-1] * 100)
    explained = beta * market_1d
    return {
        "beta": beta,
        "correlation": correlation,
        "target_std": target_std * 100,
        "market_std": market_std * 100,
        "target_1d": target_1d,
        "market_1d": market_1d,
        "explained_pp": explained,
        "specific_pp": target_1d - explained,
        "observations": len(returns),
        "asof": returns.index[-1],
    }
