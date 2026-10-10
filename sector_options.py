"""Conservative ETF options-imbalance classification from dated chain snapshots."""
from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd


def sector_option_signal(chain: pd.DataFrame, spot: float, as_of: date,
                         moneyness: float = .10, min_volume: int = 1000) -> dict[str, object]:
    unknown = {"label": "N/A · 期权链不可用", "call_vol": 0, "put_vol": 0, "contracts": 0}
    required = {"Expiration", "Type", "strike", "volume", "openInterest"}
    if chain is None or chain.empty or not required.issubset(chain.columns) or not np.isfinite(spot) or spot <= 0:
        return unknown
    frame = chain.copy()
    expiry = pd.to_datetime(frame["Expiration"], errors="coerce")
    dte = (expiry.dt.normalize() - pd.Timestamp(as_of)).dt.days
    strike = pd.to_numeric(frame["strike"], errors="coerce")
    volume = pd.to_numeric(frame["volume"], errors="coerce").fillna(0)
    oi = pd.to_numeric(frame["openInterest"], errors="coerce").fillna(0)
    option_type = frame["Type"].astype(str)
    otm = ((option_type == "Call") & strike.gt(spot)) | ((option_type == "Put") & strike.lt(spot))
    eligible = (dte.between(7, 30) & strike.sub(spot).abs().div(spot).le(moneyness)
                & otm & oi.gt(0) & volume.ge(min_volume) & volume.gt(oi.mul(1.5)))
    flagged = pd.DataFrame({"Type": option_type, "Vol": volume}).loc[eligible]
    call_vol = int(flagged.loc[flagged["Type"].eq("Call"), "Vol"].sum())
    put_vol = int(flagged.loc[flagged["Type"].eq("Put"), "Vol"].sum())
    if call_vol > put_vol * 1.5 and call_vol > 0:
        label = "🔥 Call 抢筹伏兵"
    elif put_vol > call_vol * 1.5 and put_vol > 0:
        label = "🛡️ Put 巨量避险"
    else:
        label = "⚪ 平衡"
    return {"label": label, "call_vol": call_vol, "put_vol": put_vol, "contracts": len(flagged)}
