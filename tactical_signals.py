"""Secondary-market participation and RRG setup diagnostics.

Trading volume is never described as ETF creation/redemption flow.
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def participation_metrics(ohlcv: pd.DataFrame) -> dict[str, float]:
    result = {"rvol": np.nan, "dollar_volume_m": np.nan,
              "volume_trend_pct": np.nan, "avwap": np.nan, "avwap_distance_pct": np.nan}
    required = {"High", "Low", "Close", "Volume"}
    if ohlcv is None or not required.issubset(ohlcv.columns):
        return result
    frame = ohlcv[list(required)].apply(pd.to_numeric, errors="coerce").dropna()
    frame = frame[frame["Volume"].gt(0) & frame["Close"].gt(0)]
    if frame.empty:
        return result
    volume = frame["Volume"]
    close = float(frame["Close"].iloc[-1])
    result["dollar_volume_m"] = close * float(volume.iloc[-1]) / 1e6
    if len(volume) >= 21:
        prior_20 = float(volume.iloc[-21:-1].mean())
        if prior_20 > 0:
            result["rvol"] = float(volume.iloc[-1] / prior_20)
    if len(volume) >= 20:
        avg20 = float(volume.iloc[-20:].mean())
        if avg20 > 0:
            result["volume_trend_pct"] = (float(volume.iloc[-5:].mean()) / avg20 - 1) * 100
    # Recent highest-volume session is a reproducible cost anchor, not a claim
    # to know any institution's actual execution prices or holdings.
    recent = frame.tail(20)
    anchor = recent["Volume"].idxmax()
    anchored = frame.loc[anchor:]
    typical = (anchored["High"] + anchored["Low"] + anchored["Close"]) / 3
    denominator = float(anchored["Volume"].sum())
    if denominator > 0:
        result["avwap"] = float((typical * anchored["Volume"]).sum() / denominator)
        result["avwap_distance_pct"] = (close / result["avwap"] - 1) * 100
    return result


def early_rrg_signals(rrg: pd.DataFrame, close: pd.Series, benchmark: pd.Series,
                      *, volume_trend_pct: float = np.nan,
                      five_day_official_flow: float = np.nan) -> tuple[bool, bool]:
    """Return (early_ambush, overbought) using only available evidence."""
    if rrg is None or len(rrg) < 4:
        return False, False
    tail = rrg[["rs_ratio", "rs_momentum"]].tail(4).apply(pd.to_numeric, errors="coerce")
    if not np.isfinite(tail.to_numpy()).all():
        return False, False
    x, y = map(float, tail.iloc[-1])
    improving = x < 100 and y >= 100
    rising_3d = y > float(tail["rs_momentum"].iloc[-4])
    pair = pd.concat([close, benchmark], axis=1).dropna()
    if len(pair) < 20:
        return False, False
    price = pair.iloc[:, 0]
    ratio = price.div(pair.iloc[:, 1]).replace([np.inf, -np.inf], np.nan).dropna()
    price_ema = price.ewm(span=20, adjust=False).mean()
    rs_ema = ratio.ewm(span=20, adjust=False).mean()
    recovered = bool(price.iloc[-1] >= price_ema.iloc[-1] or ratio.iloc[-1] >= rs_ema.iloc[-1])
    participation = bool((np.isfinite(volume_trend_pct) and volume_trend_pct > 0) or
                         (np.isfinite(five_day_official_flow) and five_day_official_flow > 0))
    ambush = improving and rising_3d and recovered and participation
    leading = x >= 100 and y >= 100
    momentum_dropping = bool(tail["rs_momentum"].iloc[-1] < tail["rs_momentum"].iloc[-2] < tail["rs_momentum"].iloc[-3])
    overbought = leading and (momentum_dropping or x > 105)
    return ambush, overbought
