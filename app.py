"""Buy-Side Macro Quant Portal — self-contained Streamlit dashboard."""
from __future__ import annotations

from datetime import date, timedelta
from io import StringIO
from urllib.request import Request, urlopen
import hmac
import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import streamlit as st
import streamlit.components.v1 as components
import yfinance as yf

try:
    from scipy.signal import argrelextrema
    SCIPY_AVAILABLE = True
except ImportError:
    SCIPY_AVAILABLE = False

    def argrelextrema(data: np.ndarray, comparator, order: int = 1) -> tuple[np.ndarray]:
        """Safe fallback; SciPy's implementation is used when the declared dependency is installed."""
        values=np.asarray(data); matches=[]
        for index in range(order,len(values)-order):
            center=values[index]
            if all(bool(comparator(center,values[index-offset])) and bool(comparator(center,values[index+offset]))
                   for offset in range(1,order+1)):
                matches.append(index)
        return (np.asarray(matches,dtype=int),)

st.set_page_config(page_title="Buy-Side Quant Portal", page_icon="◈", layout="wide", initial_sidebar_state="collapsed")

# Community Cloud reads the real password from Settings > Secrets.
# The fallback is intentionally only a local-development password.
LOCAL_TEST_PASSWORD = "doge2026"


def configured_access_key() -> str:
    try:
        return str(st.secrets.get("AUTH_PASSWORD",LOCAL_TEST_PASSWORD))
    except Exception:
        # Accessing st.secrets raises when no local secrets.toml exists.
        return LOCAL_TEST_PASSWORD


def verify_access_key() -> None:
    candidate=str(st.session_state.get("_portal_key_input", ""))
    if hmac.compare_digest(candidate.encode("utf-8"),configured_access_key().encode("utf-8")):
        st.session_state["_portal_authenticated"]=True
        st.session_state["_portal_key_invalid"]=False
        st.session_state.pop("_portal_key_input",None)
    elif candidate:
        st.session_state["_portal_key_invalid"]=True


if not st.session_state.get("_portal_authenticated",False):
    st.markdown("""
    <style>
    .stApp{background:radial-gradient(circle at 50% 0%,#14243b 0,#080d15 48%,#05080e 100%)}
    .block-container{max-width:430px;padding-top:18vh}
    [data-testid="stHeader"]{background:transparent}
    .gate-mark{color:#3ed8ff;font:700 .68rem ui-monospace,monospace;letter-spacing:.20em;text-align:center}
    .gate-title{color:#eef5ff;font:650 1.5rem Inter,sans-serif;letter-spacing:.08em;text-align:center;margin:.55rem 0 .2rem}
    .gate-note{color:#71849f;font:.76rem Inter,sans-serif;text-align:center;margin-bottom:1.35rem}
    </style>
    <div class="gate-mark">RESTRICTED RESEARCH TERMINAL</div>
    <div class="gate-title">BUY-SIDE QUANT PORTAL</div>
    <div class="gate-note">请输入访问密钥并按 Enter 解锁</div>
    """,unsafe_allow_html=True)
    st.text_input("Access Key · 访问密钥",type="password",key="_portal_key_input",
                  placeholder="••••••••",on_change=verify_access_key)
    if st.session_state.get("_portal_key_invalid",False):
        st.error("访问密钥不正确。")
    # This executes before any cache function is called or any market request is made.
    st.stop()

SECTORS = {
    "XLK": ("Information Technology", "信息科技", 33.0), "XLC": ("Communication Services", "通信服务", 9.8),
    "XLY": ("Consumer Discretionary", "可选消费", 10.4), "XLI": ("Industrials", "工业", 8.6),
    "XLE": ("Energy", "能源", 2.9), "XLF": ("Financials", "金融", 13.9),
    "XLV": ("Health Care", "医疗保健", 9.6), "XLP": ("Consumer Staples", "日常消费", 5.2),
    "XLU": ("Utilities", "公用事业", 2.4), "XLRE": ("Real Estate", "房地产", 2.0),
    "XLB": ("Materials", "原材料", 2.2),
}
RRG_EXTRA = {"SMH": "Semiconductors · 半导体", "GLD": "Gold · 黄金"}
COMMODITIES = {"GLD": "黄金", "SLV": "白银", "USO": "原油", "CPER": "铜", "UUP": "美元指数", "TLT": "20年+美债"}

# Representative S&P weights for heat-map area only; all price/return data are live.
HEAT_UNIVERSE = {
    "AAPL": ("Apple", "XLK", 7.0), "MSFT": ("Microsoft", "XLK", 6.2), "NVDA": ("NVIDIA", "XLK", 7.4),
    "AVGO": ("Broadcom", "XLK", 2.2), "ORCL": ("Oracle", "XLK", .9), "CRM": ("Salesforce", "XLK", .6),
    "META": ("Meta", "XLC", 2.6), "GOOGL": ("Alphabet", "XLC", 2.0), "GOOG": ("Alphabet C", "XLC", 1.7),
    "NFLX": ("Netflix", "XLC", .8), "AMZN": ("Amazon", "XLY", 3.8), "TSLA": ("Tesla", "XLY", 1.8),
    "HD": ("Home Depot", "XLY", .7), "MCD": ("McDonald's", "XLY", .5), "GE": ("GE Aerospace", "XLI", .6),
    "RTX": ("RTX", "XLI", .5), "CAT": ("Caterpillar", "XLI", .4), "UNP": ("Union Pacific", "XLI", .3),
    "XOM": ("Exxon Mobil", "XLE", 1.1), "CVX": ("Chevron", "XLE", .6), "COP": ("ConocoPhillips", "XLE", .2),
    "SLB": ("SLB", "XLE", .1), "BRK-B": ("Berkshire", "XLF", 1.6), "JPM": ("JPMorgan", "XLF", 1.5),
    "V": ("Visa", "XLF", 1.0), "MA": ("Mastercard", "XLF", .8), "BAC": ("Bank of America", "XLF", .6),
    "GS": ("Goldman Sachs", "XLF", .3), "LLY": ("Eli Lilly", "XLV", 1.4), "JNJ": ("Johnson & Johnson", "XLV", 1.0),
    "UNH": ("UnitedHealth", "XLV", .8), "ABBV": ("AbbVie", "XLV", .8), "MRK": ("Merck", "XLV", .5),
    "WMT": ("Walmart", "XLP", .8), "COST": ("Costco", "XLP", .7), "PG": ("Procter & Gamble", "XLP", .6),
    "KO": ("Coca-Cola", "XLP", .4), "PEP": ("PepsiCo", "XLP", .3), "NEE": ("NextEra Energy", "XLU", .3),
    "SO": ("Southern Co", "XLU", .2), "DUK": ("Duke Energy", "XLU", .1), "PLD": ("Prologis", "XLRE", .2),
    "AMT": ("American Tower", "XLRE", .2), "EQIX": ("Equinix", "XLRE", .2), "LIN": ("Linde", "XLB", .4),
    "SHW": ("Sherwin-Williams", "XLB", .2), "FCX": ("Freeport-McMoRan", "XLB", .15), "APD": ("Air Products", "XLB", .1),
}
NASDAQ_UNIVERSE = {
    "NVDA": ("NVIDIA", "Electronic Technology", 8.8), "AAPL": ("Apple", "Electronic Technology", 8.1),
    "AVGO": ("Broadcom", "Electronic Technology", 5.0), "AMD": ("AMD", "Electronic Technology", 1.5),
    "MU": ("Micron", "Electronic Technology", .8), "QCOM": ("Qualcomm", "Electronic Technology", .8),
    "TXN": ("Texas Instruments", "Electronic Technology", .7), "AMAT": ("Applied Materials", "Electronic Technology", .7),
    "LRCX": ("Lam Research", "Electronic Technology", .6), "KLAC": ("KLA", "Electronic Technology", .5),
    "ADI": ("Analog Devices", "Electronic Technology", .5), "CSCO": ("Cisco", "Electronic Technology", 1.0),
    "MSFT": ("Microsoft", "Technology Services", 7.4), "GOOGL": ("Alphabet A", "Technology Services", 3.0),
    "GOOG": ("Alphabet C", "Technology Services", 2.8), "META": ("Meta", "Technology Services", 4.0),
    "NFLX": ("Netflix", "Technology Services", 1.6), "INTU": ("Intuit", "Technology Services", .6),
    "ADBE": ("Adobe", "Technology Services", .6), "PANW": ("Palo Alto", "Technology Services", .6),
    "CRWD": ("CrowdStrike", "Technology Services", .5), "PLTR": ("Palantir", "Technology Services", 1.0),
    "SNPS": ("Synopsys", "Technology Services", .4), "CDNS": ("Cadence", "Technology Services", .4),
    "AMZN": ("Amazon", "Retail Trade", 5.3), "COST": ("Costco", "Retail Trade", 1.2),
    "MELI": ("MercadoLibre", "Retail Trade", .4), "JD": ("JD.com", "Retail Trade", .2),
    "TSLA": ("Tesla", "Consumer Durables", 3.3), "BKNG": ("Booking", "Consumer Cyclical", .6),
    "ABNB": ("Airbnb", "Consumer Cyclical", .3), "SBUX": ("Starbucks", "Consumer Cyclical", .3),
    "AMGN": ("Amgen", "Health Technology", .8), "GILD": ("Gilead", "Health Technology", .6),
    "ISRG": ("Intuitive Surgical", "Health Technology", .7), "REGN": ("Regeneron", "Health Technology", .4),
    "AZN": ("AstraZeneca", "Health Technology", .5), "TMUS": ("T-Mobile", "Communications", 1.2),
    "CMCSA": ("Comcast", "Communications", .4), "PEP": ("PepsiCo", "Consumer Non-Durables", .8),
    "MDLZ": ("Mondelez", "Consumer Non-Durables", .3), "HON": ("Honeywell", "Producer Manufacturing", .6),
    "LIN": ("Linde", "Producer Manufacturing", .7), "CSX": ("CSX", "Transportation", .3),
    "MAR": ("Marriott", "Consumer Services", .3), "ADP": ("ADP", "Commercial Services", .5),
    "PYPL": ("PayPal", "Commercial Services", .3), "CEG": ("Constellation Energy", "Utilities", .5),
}
YIELD_TICKERS = {"3M": "^IRX", "5Y": "^FVX", "10Y": "^TNX", "30Y": "^TYX"}
PERIOD_BARS = {"1M":21,"3M":63,"6M":126,"YTD":None,"1Y":252,"3Y":756,"5Y":1260,"10Y":2520,"MAX":None}
REGIME_PAIRS = {"QQQ / TQQQ":("QQQ","TQQQ"),"SPY / SPXL":("SPY","SPXL"),
                "SOXX / SOXL":("SOXX","SOXL"),"XLK / TECL":("XLK","TECL")}
COLORS = {
    "XLK": "#40c4ff", "XLC": "#8b7cff", "XLY": "#ff8f5a", "XLI": "#b7c5d8", "XLE": "#00d7a3",
    "XLF": "#3a86ff", "XLV": "#ff4d76", "XLP": "#e6c85c", "XLU": "#5c7cfa", "XLRE": "#b985ff",
    "XLB": "#8bcf74", "SMH": "#ff3e68", "GLD": "#f3c94f", "SLV": "#c6d0dc", "USO": "#f26d4b",
    "CPER": "#d99152", "UUP": "#38bdf8", "TLT": "#a78bfa", "QQQ": "#ff8a3d",
}
PAPER, PLOT, GRID = "#070b12", "#0a111c", "rgba(135,151,174,.13)"

st.markdown("""
<style>
.stApp{background:radial-gradient(circle at 75% -20%,#14243b 0,#080d15 43%,#05080e 100%)}
.block-container{max-width:1900px;padding:4.75rem 1.65rem 2rem}
[data-testid="stHeader"]{background:#080c12;border-bottom:1px solid #171f2b}
[data-testid="stSidebar"]{background:#070c13;border-right:1px solid #1a2738}
[data-testid="stMetric"]{background:linear-gradient(145deg,#101a28,#090f18);border:1px solid #1c2c42;padding:.78rem .9rem;border-radius:5px;min-height:104px}
[data-testid="stMetricLabel"]{color:#8799b2;font-size:.73rem;letter-spacing:.055em;text-transform:uppercase}
[data-testid="stMetricValue"]{color:#f2f6fc;font:600 1.44rem ui-monospace,SFMono-Regular,Consolas,monospace}
[data-testid="stMetricDelta"]{font:500 .76rem ui-monospace,SFMono-Regular,Consolas,monospace}
[data-testid="stTabs"] button{font-size:.76rem;font-weight:700;letter-spacing:.075em;color:#8292a8;padding:.72rem 1.15rem}
[data-testid="stTabs"] button[aria-selected="true"]{color:#43d8ff}
[data-testid="stTabs"] [data-baseweb="tab-highlight"]{background:#35d5ff}
[data-testid="stDataFrame"]{border:1px solid #1a293d;border-radius:4px}
.portal-head{display:flex;align-items:end;justify-content:space-between;border-bottom:1px solid #1b2a3e;padding:.25rem 0 .85rem;margin-bottom:.75rem}
.portal-title{font-size:1.42rem;font-weight:700;letter-spacing:.08em;color:#edf4ff}.portal-sub{font-size:.7rem;color:#6f829d;letter-spacing:.13em;margin-top:.25rem}
.live{font:600 .7rem ui-monospace,monospace;color:#46dda9;letter-spacing:.08em}.live:before{content:'';display:inline-block;width:7px;height:7px;border-radius:50%;background:#2bd9a3;box-shadow:0 0 9px #2bd9a3;margin-right:7px}
.deck-label{font-size:.64rem;color:#52657d;letter-spacing:.16em;text-transform:uppercase;margin:.25rem 0 .42rem}
.module{border-left:2px solid #35d5ff;padding-left:.72rem;margin:.3rem 0 .48rem}.kicker{font-size:.61rem;color:#37d6ff;font-weight:750;letter-spacing:.16em;text-transform:uppercase}
.module-title{font-size:1rem;color:#e8eff9;font-weight:650;margin-top:.1rem}.module-note{font-size:.7rem;color:#7588a2;margin-top:.12rem}
hr{border-color:#192638!important;margin:.85rem 0!important}div[data-testid="stAlert"]{border-radius:4px}
</style>""", unsafe_allow_html=True)


@st.cache_data(ttl=3600, show_spinner=False)
def load_prices(tickers: tuple[str, ...], start: date, end: date) -> pd.DataFrame:
    """Bulk-download adjusted closes and normalize yfinance output shapes."""
    raw = yf.download(list(tickers), start=start, end=end, auto_adjust=True, progress=False, threads=True, group_by="column")
    if raw.empty:
        return pd.DataFrame(columns=list(tickers))
    if isinstance(raw.columns, pd.MultiIndex):
        fields = raw.columns.get_level_values(0)
        field = "Close" if "Close" in fields else "Adj Close"
        close = raw[field].copy()
    else:
        field = "Close" if "Close" in raw.columns else "Adj Close"
        close = raw[[field]].copy()
        close.columns = [tickers[0]]
    if isinstance(close, pd.Series):
        close = close.to_frame(tickers[0])
    close.index = pd.to_datetime(close.index).tz_localize(None)
    return close.reindex(columns=list(tickers)).apply(pd.to_numeric, errors="coerce").replace([np.inf, -np.inf], np.nan).sort_index()


@st.cache_data(ttl=3600, show_spinner=False)
def load_custom_prices(tickers: tuple[str, ...], period: str) -> pd.DataFrame:
    """Fetch arbitrary user-entered tickers without requiring a local data file."""
    raw = yf.download(list(tickers), period=period, auto_adjust=True, progress=False, threads=True, group_by="column")
    if raw.empty:
        return pd.DataFrame(columns=list(tickers))
    if isinstance(raw.columns, pd.MultiIndex):
        fields = raw.columns.get_level_values(0)
        field = "Close" if "Close" in fields else "Adj Close"
        close = raw[field].copy()
    else:
        field = "Close" if "Close" in raw.columns else "Adj Close"
        close = raw[[field]].copy()
        close.columns = [tickers[0]]
    if isinstance(close, pd.Series):
        close = close.to_frame(tickers[0])
    close.index = pd.to_datetime(close.index).tz_localize(None)
    return close.reindex(columns=list(tickers)).apply(pd.to_numeric, errors="coerce").replace([np.inf, -np.inf], np.nan).sort_index()


@st.cache_data(ttl=86400, show_spinner=False)
def load_sp500_companies() -> tuple[str, ...]:
    """Load a 500-company breadth universe (secondary duplicate share classes removed)."""
    # CSV-only sources keep Community Cloud deployment independent of optional lxml/html parsers.
    urls = ["https://raw.githubusercontent.com/datasets/s-and-p-500-companies/master/data/constituents.csv",
            "https://datahub.io/core/s-and-p-500-companies/r/constituents.csv"]
    table = pd.DataFrame()
    for url in urls:
        try:
            request = Request(url,headers={"User-Agent":"Mozilla/5.0 QuantDashboard/1.0"})
            payload = urlopen(request,timeout=20).read().decode("utf-8")
            table = pd.read_csv(StringIO(payload))
            if "Symbol" in table and len(table) >= 500:
                break
        except Exception:
            continue
    if table.empty or "Symbol" not in table:
        raise ValueError("S&P 500 constituent list unavailable")
    symbols = table["Symbol"].astype(str).str.replace(".", "-", regex=False).tolist()
    # The index has 503 listed securities but 500 companies; use one class for these three duplicates.
    symbols = [s for s in symbols if s not in {"GOOG", "FOX", "NWS"}]
    return tuple(symbols[:500])


@st.cache_data(ttl=3600,show_spinner=False)
def load_sp500_breadth_prices(symbols: tuple[str,...]) -> pd.DataFrame:
    """Chunk the breadth download to reduce partial failures and Yahoo throttling."""
    parts=[]
    for start in range(0,len(symbols),80):
        chunk=symbols[start:start+80]
        try:
            part=load_custom_prices(tuple(chunk),"5d")
            if not part.empty: parts.append(part)
        except Exception:
            continue
    return pd.concat(parts,axis=1).reindex(columns=list(symbols)) if parts else pd.DataFrame(columns=list(symbols))


@st.cache_data(ttl=3600, show_spinner=False)
def load_flow_data(tickers: tuple[str, ...], period: str = "3mo") -> tuple[pd.DataFrame, pd.DataFrame]:
    """Download adjusted closes and volume for signed-dollar-volume flow proxies."""
    raw = yf.download(list(tickers), period=period, auto_adjust=True, progress=False, threads=True, group_by="column")
    if raw.empty:
        return pd.DataFrame(columns=list(tickers)), pd.DataFrame(columns=list(tickers))
    if isinstance(raw.columns, pd.MultiIndex):
        close = raw["Close"].copy() if "Close" in raw.columns.get_level_values(0) else pd.DataFrame()
        volume = raw["Volume"].copy() if "Volume" in raw.columns.get_level_values(0) else pd.DataFrame()
    else:
        close = raw[["Close"]].copy(); close.columns = [tickers[0]]
        volume = raw[["Volume"]].copy(); volume.columns = [tickers[0]]
    for frame in (close, volume):
        frame.index = pd.to_datetime(frame.index).tz_localize(None)
    return (close.reindex(columns=list(tickers)).apply(pd.to_numeric,errors="coerce"),
            volume.reindex(columns=list(tickers)).apply(pd.to_numeric,errors="coerce"))


@st.cache_data(ttl=3600,show_spinner=False)
def load_ohlcv(tickers: tuple[str,...], period: str = "max") -> pd.DataFrame:
    """Batch-download full adjusted OHLCV history and return ticker-first columns."""
    raw=yf.download(list(tickers),period=period,auto_adjust=True,progress=False,threads=True,group_by="ticker")
    fields=["Open","High","Low","Close","Volume"]
    frames={}
    if raw.empty:
        return pd.DataFrame()
    for ticker in tickers:
        try:
            if isinstance(raw.columns,pd.MultiIndex):
                top=raw.columns.get_level_values(0)
                frame=raw[ticker].copy() if ticker in top else raw.xs(ticker,axis=1,level=1).copy()
            else:
                frame=raw.copy()
            frame=frame.reindex(columns=fields).apply(pd.to_numeric,errors="coerce").dropna(subset=["Open","High","Low","Close"])
            frame.index=pd.to_datetime(frame.index).tz_localize(None)
            if not frame.empty: frames[ticker]=frame
        except Exception:
            continue
    return pd.concat(frames,axis=1) if frames else pd.DataFrame()


@st.cache_data(ttl=900, show_spinner=False)
def load_market_news(symbols: tuple[str, ...], per_symbol: int = 6) -> pd.DataFrame:
    """Normalize both legacy and current yfinance news payloads."""
    rows = []
    for symbol in symbols:
        try:
            items = yf.Ticker(symbol).news or []
        except Exception:
            continue
        for item in items[:per_symbol]:
            content = item.get("content", item)
            title = content.get("title") or item.get("title")
            provider = content.get("provider", {})
            source = provider.get("displayName") if isinstance(provider, dict) else provider
            source = source or item.get("publisher") or symbol
            url_obj = content.get("canonicalUrl") or content.get("clickThroughUrl") or {}
            url = url_obj.get("url") if isinstance(url_obj, dict) else url_obj
            url = url or item.get("link")
            published = content.get("pubDate") or item.get("providerPublishTime")
            if isinstance(published, (int, float)):
                published = pd.to_datetime(published, unit="s", utc=True, errors="coerce")
            else:
                published = pd.to_datetime(published, utc=True, errors="coerce")
            if title and url:
                rows.append({"Time":published,"Source":source,"Headline":title,"URL":url,"Query":symbol})
    if not rows:
        return pd.DataFrame(columns=["Time","Source","Headline","URL","Query"])
    result = pd.DataFrame(rows).drop_duplicates("Headline")
    result["Time"] = pd.to_datetime(result["Time"],utc=True,errors="coerce")
    result["Time"] = result["Time"].dt.tz_convert("Asia/Tokyo").dt.strftime("%m-%d %H:%M")
    return result.head(24)


def last_return(series: pd.Series, periods: int) -> float:
    s = series.dropna()
    return np.nan if len(s) <= periods else float((s.iloc[-1] / s.iloc[-periods - 1] - 1) * 100)


def ytd_return(series: pd.Series) -> float:
    s = series.dropna()
    if s.empty:
        return np.nan
    y = s[s.index.year == s.index[-1].year]
    return np.nan if y.empty or y.iloc[0] == 0 else float((y.iloc[-1] / y.iloc[0] - 1) * 100)


def drawdown_from_high(series: pd.Series) -> float:
    s = series.dropna()
    return np.nan if s.empty else float((s.iloc[-1] / s.max() - 1) * 100)


def normalized_slope(series: pd.Series) -> float:
    sma = series.dropna().rolling(200, min_periods=200).mean().dropna().tail(20)
    if len(sma) < 20 or sma.iloc[-1] == 0:
        return np.nan
    return float(np.polyfit(np.arange(20, dtype=float), sma.to_numpy(dtype=float), 1)[0] / sma.iloc[-1] * 100)


def trend_label(slope: float) -> str:
    if not np.isfinite(slope): return "数据不足"
    if slope > .035: return "多头加速"
    if slope < -.035: return "空头衰退"
    return "走平震荡"


def rrg_frame(target: pd.Series, benchmark: pd.Series) -> pd.DataFrame:
    pair = pd.concat([target, benchmark], axis=1).dropna()
    if len(pair) < 111:
        return pd.DataFrame(columns=["rs_ratio", "rs_momentum"])
    ratio = pair.iloc[:, 0].div(pair.iloc[:, 1]).replace([np.inf, -np.inf], np.nan)
    rs_ratio = ratio.div(ratio.rolling(100, min_periods=100).mean()).mul(100)
    momentum = rs_ratio.div(rs_ratio.shift(10)).mul(100)
    return pd.DataFrame({"rs_ratio": rs_ratio, "rs_momentum": momentum}).dropna()


def rolling_zscore(target: pd.Series, benchmark: pd.Series, window: int) -> pd.Series:
    pair = pd.concat([target, benchmark], axis=1).dropna()
    ratio = pair.iloc[:, 0].div(pair.iloc[:, 1]).replace([np.inf, -np.inf], np.nan)
    mean, std = ratio.rolling(window, min_periods=window).mean(), ratio.rolling(window, min_periods=window).std(ddof=0).replace(0, np.nan)
    return ratio.sub(mean).div(std).replace([np.inf, -np.inf], np.nan).dropna()


def breadth_history(price_frame: pd.DataFrame, tickers: list[str]) -> pd.DataFrame:
    """Daily advance/decline statistics for the available tracked constituents."""
    usable = [t for t in tickers if t in price_frame and price_frame[t].notna().any()]
    if not usable:
        return pd.DataFrame(columns=["adv", "dec", "unch", "net_pct", "ad_line"])
    changes = price_frame[usable].ffill(limit=3).pct_change(fill_method=None)
    adv, dec = (changes > 0).sum(axis=1), (changes < 0).sum(axis=1)
    unchanged = (changes == 0).sum(axis=1)
    active = (adv + dec).replace(0, np.nan)
    net_pct = (adv - dec).div(active).mul(100)
    return pd.DataFrame({"adv": adv, "dec": dec, "unch": unchanged,
                         "net_pct": net_pct, "ad_line": (adv - dec).cumsum()})


def percent_above_ma(price_frame: pd.DataFrame, tickers: list[str], window: int) -> float:
    usable = [t for t in tickers if t in price_frame and price_frame[t].dropna().shape[0] >= window]
    if not usable:
        return np.nan
    panel = price_frame[usable].ffill(limit=3)
    current = panel.iloc[-1]
    average = panel.rolling(window, min_periods=window).mean().iloc[-1]
    valid = current.notna() & average.notna()
    signal = current[valid].gt(average[valid])
    return float(signal.mean() * 100) if not signal.empty else np.nan


def value_change_bps(series: pd.Series, periods: int) -> float:
    clean = series.dropna()
    return np.nan if len(clean) <= periods else float((clean.iloc[-1] - clean.iloc[-periods - 1]) * 100)


def display_window(data: pd.Series | pd.DataFrame, label: str) -> pd.Series | pd.DataFrame:
    """Clip only for display; indicators should be calculated on pre-roll data first."""
    if data.empty:
        return data
    if label == "YTD":
        return data[data.index.year == data.index[-1].year]
    bars = PERIOD_BARS[label]
    return data.tail(bars) if bars else data


def display_with_preroll(data: pd.Series | pd.DataFrame, label: str, preroll: int = 252) -> pd.Series | pd.DataFrame:
    """Show one extra trading year before the selected range for visible MA context."""
    if data.empty:
        return data
    if label == "YTD":
        active = data[data.index.year == data.index[-1].year]
        start_pos = max(0,data.index.searchsorted(active.index[0])-preroll) if not active.empty else 0
        return data.iloc[start_pos:]
    bars = PERIOD_BARS[label] or len(data)
    return data.tail(min(len(data),bars+preroll))


def market_sentiment(price_frame: pd.DataFrame) -> tuple[str,str,int]:
    """Classify risk appetite from transparent cross-asset relative trends."""
    checks=[]
    descriptions=[]
    pairs=[("QQQ","SPY","科技相对大盘"),("IWM","SPY","小盘相对大盘"),("HYG","LQD","高收益信用相对投资级")]
    for numerator,denominator,label in pairs:
        if numerator in price_frame and denominator in price_frame:
            move=last_return(price_frame[numerator].div(price_frame[denominator]),20)
            if np.isfinite(move):
                checks.append(1 if move>0 else -1); descriptions.append(f"{label}{move:+.1f}%")
    for numerator,label in [("GLD","黄金相对SPY"),("TLT","长债相对SPY")]:
        if numerator in price_frame and "SPY" in price_frame:
            move=last_return(price_frame[numerator].div(price_frame["SPY"]),20)
            if np.isfinite(move):
                checks.append(-1 if move>0 else 1); descriptions.append(f"{label}{move:+.1f}%")
    if "^VIX" in price_frame:
        move=last_return(price_frame["^VIX"],20)
        if np.isfinite(move):
            checks.append(-1 if move>0 else 1); descriptions.append(f"VIX月变动{move:+.1f}%")
    score=sum(checks)
    if score>=3: state="风险偏好回归 / Risk-On"
    elif score<=-3: state="避险情绪升温 / Risk-Off"
    else: state="多空分化 / Transition"
    return state,"；".join(descriptions),score


def signed_flow_score(close: pd.Series, volume: pd.Series, window: int = 20) -> float:
    pair = pd.concat([close.rename("close"),volume.rename("volume")],axis=1).dropna()
    if len(pair) < window + 1:
        return np.nan
    dollar_volume = pair["close"].mul(pair["volume"])
    signed = np.sign(pair["close"].pct_change(fill_method=None)).mul(dollar_volume)
    denominator = dollar_volume.tail(window).sum()
    return np.nan if denominator == 0 else float(signed.tail(window).sum() / denominator * 100)


def macd_series(series: pd.Series, fast: int = 8, slow: int = 17, signal: int = 9) -> pd.DataFrame:
    clean = series.dropna()
    macd = clean.ewm(span=fast, adjust=False).mean() - clean.ewm(span=slow, adjust=False).mean()
    signal_line = macd.ewm(span=signal, adjust=False).mean()
    return pd.DataFrame({"macd": macd, "signal": signal_line, "hist": macd - signal_line})


def relative_signal(target: pd.Series, benchmark: pd.Series) -> tuple[pd.DataFrame, dict[str, float | str]]:
    """Build ratio indicators and a descriptive, non-predictive regime label."""
    pair = pd.concat([target, benchmark], axis=1).dropna()
    if len(pair) < 200:
        return pd.DataFrame(), {"state": "数据不足"}
    ratio = pair.iloc[:, 0].div(pair.iloc[:, 1]).replace([np.inf, -np.inf], np.nan).dropna()
    ma60 = ratio.rolling(60, min_periods=60).mean()
    ma200 = ratio.rolling(200, min_periods=200).mean()
    mean120 = ratio.rolling(120, min_periods=120).mean()
    std120 = ratio.rolling(120, min_periods=120).std(ddof=0).replace(0, np.nan)
    zscore = ratio.sub(mean120).div(std120)
    macd = macd_series(ratio)
    frame = pd.concat([ratio.rename("ratio"), ma60.rename("ma60"), ma200.rename("ma200"),
                       zscore.rename("zscore"), macd], axis=1).dropna(subset=["ratio"])
    latest = frame.dropna().iloc[-1] if not frame.dropna().empty else None
    if latest is None:
        return frame, {"state": "数据不足"}
    below_both = latest["ratio"] < latest["ma60"] and latest["ratio"] < latest["ma200"]
    above_both = latest["ratio"] > latest["ma60"] and latest["ratio"] > latest["ma200"]
    hist_rising = len(frame.dropna()) > 1 and latest["hist"] > frame.dropna().iloc[-2]["hist"]
    if above_both and latest["zscore"] >= 2:
        state = "过热 · 考虑减仓"
    elif above_both:
        state = "强势 · 持有观察"
    elif below_both and latest["zscore"] <= -1.5 and hist_rising:
        state = "潜伏区 · 见底候选"
    elif below_both:
        state = "潜伏观察 · 等待企稳"
    else:
        state = "中性 · 均线过渡"
    stats: dict[str, float | str] = {
        "state": state, "ratio": float(latest["ratio"]), "zscore": float(latest["zscore"]),
        "vs_ma60": float((latest["ratio"] / latest["ma60"] - 1) * 100),
        "vs_ma200": float((latest["ratio"] / latest["ma200"] - 1) * 100),
        "macd_hist": float(latest["hist"]),
    }
    return frame, stats


def regime_indicators(ohlc: pd.DataFrame) -> pd.DataFrame:
    """Wilder ADX/+DI/-DI plus trend and volatility indicators."""
    frame=ohlc[["Open","High","Low","Close","Volume"]].copy().dropna(subset=["High","Low","Close"])
    high,low,close=frame["High"],frame["Low"],frame["Close"]
    up_move=high.diff(); down_move=-low.diff()
    plus_dm=pd.Series(np.where((up_move>down_move)&(up_move>0),up_move,0.0),index=frame.index)
    minus_dm=pd.Series(np.where((down_move>up_move)&(down_move>0),down_move,0.0),index=frame.index)
    true_range=pd.concat([high.sub(low),high.sub(close.shift()).abs(),low.sub(close.shift()).abs()],axis=1).max(axis=1)
    atr=true_range.ewm(alpha=1/14,adjust=False,min_periods=14).mean()
    plus_di=100*plus_dm.ewm(alpha=1/14,adjust=False,min_periods=14).mean().div(atr.replace(0,np.nan))
    minus_di=100*minus_dm.ewm(alpha=1/14,adjust=False,min_periods=14).mean().div(atr.replace(0,np.nan))
    dx=100*plus_di.sub(minus_di).abs().div(plus_di.add(minus_di).replace(0,np.nan))
    frame["ATR14"]=atr; frame["+DI"]=plus_di; frame["-DI"]=minus_di
    frame["ADX14"]=dx.ewm(alpha=1/14,adjust=False,min_periods=14).mean()
    frame["EMA20"]=close.ewm(span=20,adjust=False).mean(); frame["EMA50"]=close.ewm(span=50,adjust=False).mean()
    frame["SMA200"]=close.rolling(200,min_periods=200).mean()
    middle=close.rolling(20,min_periods=20).mean(); std=close.rolling(20,min_periods=20).std(ddof=0)
    frame["BB_MID"]=middle; frame["BB_UPPER"]=middle.add(2*std); frame["BB_LOWER"]=middle.sub(2*std)
    frame["BBW"]=frame["BB_UPPER"].sub(frame["BB_LOWER"]).div(middle.replace(0,np.nan))
    return frame


def classify_regime(frame: pd.DataFrame) -> tuple[str,dict[str,float]]:
    valid=frame.dropna(subset=["ADX14","EMA20","EMA50","SMA200","BBW"])
    if valid.empty:
        return "数据不足",{}
    last=valid.iloc[-1]; close=float(last["Close"]); adx=float(last["ADX14"])
    prior_adx=float(valid["ADX14"].iloc[-6]) if len(valid)>=6 else adx
    high20=float(valid["High"].tail(20).max()); box_high=float(valid["High"].tail(30).max()); box_low=float(valid["Low"].tail(30).min())
    zone_low=min(float(last["EMA20"]),float(last["EMA50"])); zone_high=max(float(last["EMA20"]),float(last["EMA50"]))
    pullback=(close>float(last["EMA50"]) and close<=zone_high*1.02 and close>=zone_low*.985 and high20/close-1>=.02)
    if adx<22: state="📦 箱体震荡 (Range-Bound)"
    elif close<float(last["EMA50"]) and adx>prior_adx: state="⚠️ 空头破位下跌 (Downtrend Break)"
    elif pullback: state="📈 牛市趋势回调 (Bullish Pullback)"
    elif close>float(last["EMA50"]) and float(last["+DI"])>float(last["-DI"]): state="📈 多头趋势延续 (Bull Trend)"
    else: state="🔄 趋势过渡 (Transition)"
    return state,{"close":close,"adx":adx,"plus_di":float(last["+DI"]),"minus_di":float(last["-DI"]),
                  "ema20":float(last["EMA20"]),"ema50":float(last["EMA50"]),"sma200":float(last["SMA200"]),
                  "bbw":float(last["BBW"]),"box_high":box_high,"box_low":box_low,"atr":float(last["ATR14"])}


def detect_geometric_patterns(frame: pd.DataFrame) -> dict[str,object]:
    """Detect trend breaks, double bottoms, descending channels and converging triangles."""
    recent=frame.dropna(subset=["High","Low","Close"]).tail(120).copy()
    result:dict[str,object]={"recent":recent,"trend":None,"trend_breakout":False,
                             "double_bottom":None,"channel":None,"triangle":None}
    if len(recent)<30:
        return result
    highs=recent["High"].to_numpy(dtype=float); lows=recent["Low"].to_numpy(dtype=float); closes=recent["Close"].to_numpy(dtype=float)
    maxima=argrelextrema(highs,np.greater_equal,order=4)[0]; minima=argrelextrema(lows,np.less_equal,order=4)[0]
    maxima=maxima[(maxima>0)&(maxima<len(recent)-1)]; minima=minima[(minima>0)&(minima<len(recent)-1)]
    high_points=None
    for width in (3,2):
        for start in range(len(maxima)-width,-1,-1):
            candidate=maxima[start:start+width]
            if len(candidate)==width and np.all(np.diff(highs[candidate])<0):
                high_points=candidate; break
        if high_points is not None: break
    if high_points is not None:
        slope,intercept=np.polyfit(high_points,highs[high_points],1)
        x_line=np.arange(int(high_points[0]),len(recent)); y_line=slope*x_line+intercept
        current_line=float(slope*(len(recent)-1)+intercept); previous_line=float(slope*(len(recent)-2)+intercept)
        breakout=bool(closes[-1]>current_line and closes[-2]<=previous_line)
        result["trend"]={"idx":high_points,"x":x_line,"y":y_line,"level":current_line,"slope":float(slope)}
        result["trend_breakout"]=breakout
        low_points=None
        for width in (3,2):
            for start in range(len(minima)-width,-1,-1):
                candidate=minima[start:start+width]
                if len(candidate)==width and np.all(np.diff(lows[candidate])<0):
                    low_points=candidate; break
            if low_points is not None: break
        if low_points is not None and slope<0:
            lower_intercept=float(np.mean(lows[low_points]-slope*low_points))
            x0=int(min(high_points[0],low_points[0])); channel_x=np.arange(x0,len(recent))
            result["channel"]={"x":channel_x,"upper":slope*channel_x+intercept,
                               "lower":slope*channel_x+lower_intercept,"height":float(intercept-lower_intercept)}
    # Converging triangle: fit the latest 2-4 swing highs and lows independently.
    # A valid structure must narrow toward a future apex and retain price inside both rails.
    if len(maxima)>=2 and len(minima)>=2:
        triangle_candidates=[]
        for high_count in (4,3,2):
            for low_count in (4,3,2):
                if len(maxima)<high_count or len(minima)<low_count: continue
                hi_idx=maxima[-high_count:]; lo_idx=minima[-low_count:]
                first=max(int(hi_idx[0]),int(lo_idx[0])); last=len(recent)-1
                hi_slope,hi_intercept=np.polyfit(hi_idx,highs[hi_idx],1)
                lo_slope,lo_intercept=np.polyfit(lo_idx,lows[lo_idx],1)
                width_now=(hi_slope*last+hi_intercept)-(lo_slope*last+lo_intercept)
                width_start=(hi_slope*first+hi_intercept)-(lo_slope*first+lo_intercept)
                converging=hi_slope<lo_slope and width_start>0 and width_now>0 and width_now<width_start*.82
                apex=(lo_intercept-hi_intercept)/(hi_slope-lo_slope) if abs(hi_slope-lo_slope)>1e-12 else np.inf
                apex_ok=last<apex<=last+max(90,2*(last-first))
                upper_now=hi_slope*last+hi_intercept; lower_now=lo_slope*last+lo_intercept
                inside=lower_now*.985<=closes[-1]<=upper_now*1.015
                high_fit=np.mean(np.abs(highs[hi_idx]-(hi_slope*hi_idx+hi_intercept)))
                low_fit=np.mean(np.abs(lows[lo_idx]-(lo_slope*lo_idx+lo_intercept)))
                fit_ok=(high_fit+low_fit)/max(np.mean(closes),1e-9)<.035
                if converging and apex_ok and inside and fit_ok:
                    score=(high_count+low_count)*10-(width_now/width_start)*5-(high_fit+low_fit)
                    triangle_candidates.append((score,hi_idx,lo_idx,hi_slope,hi_intercept,lo_slope,lo_intercept,apex))
        if triangle_candidates:
            _,hi_idx,lo_idx,hi_slope,hi_intercept,lo_slope,lo_intercept,apex=max(triangle_candidates,key=lambda x:x[0])
            x0=int(min(hi_idx[0],lo_idx[0])); x_line=np.arange(x0,len(recent))
            upper=hi_slope*x_line+hi_intercept; lower=lo_slope*x_line+lo_intercept
            prior_upper=hi_slope*(len(recent)-2)+hi_intercept; prior_lower=lo_slope*(len(recent)-2)+lo_intercept
            upper_now=float(upper[-1]); lower_now=float(lower[-1])
            breakout_up=bool(closes[-1]>upper_now and closes[-2]<=prior_upper)
            breakout_down=bool(closes[-1]<lower_now and closes[-2]>=prior_lower)
            if hi_slope<0 and lo_slope>0: triangle_type="对称三角收敛"
            elif abs(hi_slope)<=abs(lo_slope)*.30: triangle_type="上升三角收敛"
            elif abs(lo_slope)<=abs(hi_slope)*.30: triangle_type="下降三角收敛"
            else: triangle_type="楔形收敛"
            result["triangle"]={"x":x_line,"upper":upper,"lower":lower,"high_idx":hi_idx,"low_idx":lo_idx,
                                "type":triangle_type,"apex":float(apex),"breakout_up":breakout_up,
                                "breakout_down":breakout_down,"height":float(max(upper[0]-lower[0],0))}

    candidates=[]
    for a in range(len(minima)):
        for b in range(a+1,len(minima)):
            i,j=int(minima[a]),int(minima[b])
            if j-i<10 or j-i>80 or j<len(recent)-40: continue
            if abs(lows[i]-lows[j])/max(lows[i],lows[j])<=.015:
                peak_rel=int(np.argmax(highs[i:j+1])); peak=i+peak_rel; neckline=float(highs[peak])
                trough=max(float(lows[i]),float(lows[j]))
                # Require a visible middle rebound and keep the neckline between the two lows.
                if i<peak<j and neckline/trough-1>=.025:
                    candidates.append((j,i,peak,neckline))
    if candidates:
        _,i,peak,neckline=max(candidates,key=lambda x:x[0]); j=max(candidates,key=lambda x:x[0])[0]
        result["double_bottom"]={"idx":[i,peak,j],"prices":[float(lows[i]),float(highs[peak]),float(lows[j])],
                                 "neckline":neckline,"breakout":bool(closes[-1]>neckline),"low2":float(lows[j])}
    return result


def chart_initial_range(index: pd.Index, label: str) -> list[pd.Timestamp] | None:
    """Return only an initial viewport; underlying traces retain their full history."""
    if len(index)==0 or label=="MAX":
        return None
    offsets={"6M":pd.DateOffset(months=6),"1Y":pd.DateOffset(years=1),"3Y":pd.DateOffset(years=3)}
    end=pd.Timestamp(index[-1]); start=max(pd.Timestamp(index[0]),end-offsets[label])
    return [start,end]


def mover_frame(price_frame: pd.DataFrame, universe: dict[str, tuple]) -> pd.DataFrame:
    rows = []
    for ticker, meta in universe.items():
        if ticker not in price_frame:
            continue
        clean = price_frame[ticker].dropna()
        move = last_return(price_frame[ticker], 1)
        if clean.empty or not np.isfinite(move):
            continue
        group_key = meta[1]
        group = SECTORS[group_key][1] if group_key in SECTORS else group_key
        rows.append({"Ticker": ticker, "Name": meta[0], "Group": group,
                     "Last": float(clean.iloc[-1]), "1D %": move})
    return pd.DataFrame(rows)


def base_layout(fig: go.Figure, height: int, hovermode: str = "closest") -> go.Figure:
    fig.update_layout(template="plotly_dark", height=height, paper_bgcolor=PAPER, plot_bgcolor=PLOT,
        margin=dict(l=48, r=18, t=34, b=42), hovermode=hovermode,
        font=dict(family="Inter, Segoe UI, sans-serif", size=11, color="#b8c5d6"),
        legend=dict(orientation="h", yanchor="bottom", y=1.01, xanchor="left", x=0, font=dict(size=9), bgcolor="rgba(0,0,0,0)"),
        hoverlabel=dict(bgcolor="#101b2b", bordercolor="#2a405e", font_color="#edf4ff"))
    fig.update_xaxes(gridcolor=GRID, linecolor="#25354b", zeroline=False)
    fig.update_yaxes(gridcolor=GRID, linecolor="#25354b", zeroline=False)
    return fig


def section_header(kicker: str, title: str, note: str) -> None:
    st.markdown(f'<div class="module"><div class="kicker">{kicker}</div><div class="module-title">{title}</div><div class="module-note">{note}</div></div>', unsafe_allow_html=True)


def color_return(value: object) -> str:
    if not isinstance(value, (float, int, np.floating)) or not np.isfinite(value): return "color:#718198"
    return "color:#31d6a0;font-weight:600" if value >= 0 else "color:#ff5874;font-weight:600"


def format_num(value: float, suffix: str = "%") -> str:
    return "N/A" if not np.isfinite(value) else f"{value:+.2f}{suffix}"


with st.sidebar:
    st.markdown("### ◈ QUANT CONTROLS")
    st.caption("显示参数 · 数据每小时缓存")
    tail_length = st.slider("RRG Tail · 尾迹交易日", 5, 10, 7)
    rs_horizon = st.select_slider("RS Horizon · 观察期", options=list(PERIOD_BARS), value="1Y")
    z_window = st.slider("Z-Score Window", 60, 250, 120, 5)
    st.divider()
    st.caption("RRG / RS 基准：SPY\n\nDrawdown：近 2 年峰值\n\nAdv / Dec：核心权重股样本")

core_tickers = ["SPY", "QQQ", "IWM", "^GSPC", "^NDX", "^VIX", "HYG", "LQD"]
all_tickers = tuple(dict.fromkeys(core_tickers + list(SECTORS) + list(RRG_EXTRA) + list(COMMODITIES)
                                  + list(HEAT_UNIVERSE) + list(NASDAQ_UNIVERSE) + list(YIELD_TICKERS.values())))
end_date, start_date = date.today() + timedelta(days=1), date.today() - timedelta(days=2300)
try:
    with st.spinner("SYNCING MARKET DATA / 正在同步市场数据…"):
        prices = load_prices(all_tickers, start_date, end_date)
except Exception as exc:
    st.error(f"Market data download failed / 市场数据下载失败：{exc}")
    st.info("请检查网络后刷新；Yahoo Finance 偶发限流时可等待几分钟重试。")
    st.stop()
if prices.empty or prices.get("SPY", pd.Series(dtype=float)).dropna().empty:
    st.error("SPY 基准数据不可用，无法构建看板。")
    st.stop()

valid_columns = [c for c in prices if prices[c].notna().any()]
missing_tickers = [c for c in all_tickers if c not in valid_columns]
latest_date = prices.dropna(how="all").index.max()

# Exact company-level S&P breadth: 500 companies, with unavailable quotes shown separately.
sp500_symbols: tuple[str, ...] = ()
sp500_breadth_prices = pd.DataFrame()
try:
    sp500_symbols = load_sp500_companies()
    sp500_breadth_prices = load_sp500_breadth_prices(sp500_symbols)
except Exception:
    pass
if len(sp500_symbols) == 500 and not sp500_breadth_prices.empty:
    sp_changes = sp500_breadth_prices.ffill(limit=2).pct_change(fill_method=None).iloc[-1]
    sp_adv = int((sp_changes > 0).sum()); sp_dec = int((sp_changes < 0).sum())
    sp_unch = int((sp_changes == 0).sum()); sp_missing = 500 - sp_adv - sp_dec - sp_unch
else:
    sp_adv = sp_dec = sp_unch = 0; sp_missing = 500

try:
    sector_flow_close,sector_flow_volume=load_flow_data(tuple(SECTORS),"3mo")
except Exception:
    sector_flow_close,sector_flow_volume=pd.DataFrame(),pd.DataFrame()

st.markdown(f"""<div class="portal-head"><div><div class="portal-title">BUY-SIDE QUANT PORTAL</div>
<div class="portal-sub">CROSS-ASSET INTELLIGENCE · ROTATION · BREADTH · REGIME</div></div>
<div class="live">DATA AS OF {latest_date:%Y-%m-%d}</div></div><div class="deck-label">Global Market Pulse / 大盘核心指标</div>""", unsafe_allow_html=True)

deck = st.columns(7)
for idx, ticker in enumerate(["SPY", "QQQ", "IWM"]):
    s = prices[ticker].dropna() if ticker in prices else pd.Series(dtype=float)
    latest = float(s.iloc[-1]) if not s.empty else np.nan
    deck[idx].metric(ticker, "N/A" if not np.isfinite(latest) else f"${latest:,.2f}", format_num(last_return(s, 1)), help="调整后收盘价及最近交易日涨跌幅")
spx_dd = drawdown_from_high(prices["^GSPC"].dropna().tail(504)) if "^GSPC" in prices else np.nan
ndx_dd = drawdown_from_high(prices["^NDX"].dropna().tail(504)) if "^NDX" in prices else np.nan
deck[3].metric("SPX DRAWDOWN", format_num(spx_dd), "FROM 2Y HIGH", delta_color="off", help="相对近两年最高收盘价")
deck[4].metric("NDX DRAWDOWN", format_num(ndx_dd), "FROM 2Y HIGH", delta_color="off", help="相对近两年最高收盘价")
sp_breadth_text = "N/A" if sp_missing == 500 else f"{sp_adv}/{sp_dec}/{sp_unch}/{sp_missing}"
deck[5].metric("SPY 500 · A/D/U/M",sp_breadth_text,"SUM = 500",delta_color="off",
               help="500家公司口径：上涨 / 下跌 / 平盘 / 缺失；四项合计恒为500")
ndx_returns=pd.Series({t:last_return(prices[t],1) for t in NASDAQ_UNIVERSE if t in prices}).dropna()
ndx_adv,ndx_dec,ndx_unch=int((ndx_returns>0).sum()),int((ndx_returns<0).sum()),int((ndx_returns==0).sum())
deck[6].metric("NDX SAMPLE · A / D / U",f"{ndx_adv} / {ndx_dec} / {ndx_unch}",
               f"{len(NASDAQ_UNIVERSE)-len(ndx_returns)} MISSING",delta_color="off",help="Nasdaq-100 看板覆盖样本；不显示涨跌比率")
if missing_tickers:
    st.caption(f"⚠ 本次自动跳过无有效行情的标的：{', '.join(missing_tickers)}")

tab_rotation, tab_market, tab_heat, tab_macro, tab_technical, tab_pattern, tab_fixed, tab_pulse = st.tabs([
    "01  SECTOR ROTATION · 行业轮动", "02  MARKETS & BREADTH · 大盘表现与广度",
    "03  HEAT MAPS · 板块热力图", "04  MACRO & COMMODITIES · 宏观与大宗",
    "05  TECHNICALS · 相对强度", "06  REGIME & PATTERN · 状态形态", "07  FIXED INCOME · 固定收益", "08  EVENT PULSE · 新闻数据",
])

with tab_rotation:
    col_left, col_right = st.columns(2, gap="medium")
    with col_left:
        section_header("RELATIVE ROTATION", "RRG · 行业相对旋转", "13 个行业与核心资产相对 SPY；末端为最新交易日。")
        fig, tails = go.Figure(), []
        rrg_names = {**{k: v[1] for k, v in SECTORS.items()}, **RRG_EXTRA}
        for ticker, label in rrg_names.items():
            if ticker not in prices: continue
            tail = rrg_frame(prices[ticker], prices["SPY"]).tail(tail_length)
            if tail.empty: continue
            tails.append(tail)
            color = COLORS.get(ticker, "#aeb9c8")
            fig.add_trace(go.Scatter(x=tail["rs_ratio"], y=tail["rs_momentum"], mode="lines+markers", name=ticker,
                showlegend=False, line=dict(color=color, width=1.8),
                marker=dict(color=color, size=np.linspace(3.5, 8.5, len(tail)), opacity=np.linspace(.3, 1, len(tail)), line=dict(color="#e9f1fb", width=.35)),
                customdata=tail.index.strftime("%Y-%m-%d"),
                hovertemplate=f"<b>{ticker} · {label}</b><br>%{{customdata}}<br>RS-Ratio %{{x:.2f}}<br>RS-Momentum %{{y:.2f}}<extra></extra>"))
            last = tail.iloc[-1]
            fig.add_annotation(x=float(last["rs_ratio"]), y=float(last["rs_momentum"]), text=f"<b>{ticker}</b>", showarrow=True,
                arrowhead=2, arrowsize=.9, arrowwidth=1.2, arrowcolor=color, ax=13, ay=-13, font=dict(color=color, size=9),
                bgcolor="rgba(5,9,15,.82)", bordercolor=color, borderwidth=.8, borderpad=2)
        if tails:
            mx, my = pd.concat([x["rs_ratio"] for x in tails]), pd.concat([x["rs_momentum"] for x in tails])
            xp, yp = max(.8, float(mx.max()-mx.min())*.15), max(.8, float(my.max()-my.min())*.15)
            xr, yr = [min(99, float(mx.min())-xp), max(101, float(mx.max())+xp)], [min(99, float(my.min())-yp), max(101, float(my.max())+yp)]
        else: xr, yr = [98, 102], [98, 102]
        base_layout(fig, 570)
        fig.add_vline(x=100, line_dash="dash", line_color="#71829a", line_width=1); fig.add_hline(y=100, line_dash="dash", line_color="#71829a", line_width=1)
        for x, y, text, color, anchor in [(.02,.97,"IMPROVING · 改善","#21d9a3","left"),(.98,.97,"LEADING · 领跑","#ff5874","right"),(.02,.03,"LAGGING · 落后","#718cff","left"),(.98,.03,"WEAKENING · 衰竭","#e5c34d","right")]:
            fig.add_annotation(xref="paper", yref="paper", x=x, y=y, text=f"<b>{text}</b>", showarrow=False, xanchor=anchor, font=dict(color=color, size=9))
        fig.update_xaxes(title="RS-Ratio", range=xr); fig.update_yaxes(title="RS-Momentum", range=yr)
        st.plotly_chart(fig, use_container_width=True, config={"displaylogo": False})
    with col_right:
        section_header("RELATIVE STRENGTH", "RS vs SPX · 板块相对强弱", "相对 SPY 比率在观察期起点归一至 100；虚线为 200 日平滑。")
        fig = go.Figure()
        for ticker, (_, cn_name, _) in SECTORS.items():
            pair = prices[[ticker, "SPY"]].dropna() if ticker in prices else pd.DataFrame()
            if pair.empty: continue
            ratio_full = pair[ticker].div(pair["SPY"])
            ratio = display_window(ratio_full,rs_horizon)
            rebased = ratio.div(ratio.iloc[0]).mul(100); color = COLORS[ticker]
            fig.add_trace(go.Scatter(x=rebased.index, y=rebased, mode="lines", name=ticker, line=dict(color=color, width=1.45),
                hovertemplate=f"<b>{ticker} · {cn_name}</b><br>%{{x|%Y-%m-%d}}<br>RS %{{y:.2f}}<extra></extra>"))
            # Calculate the true 200-day smoother before clipping to the display horizon.
            smooth_full = ratio_full.rolling(200,min_periods=200).mean().div(ratio.iloc[0]).mul(100)
            smooth = display_window(smooth_full,rs_horizon)
            fig.add_trace(go.Scatter(x=smooth.index, y=smooth, mode="lines", name=f"{ticker} 200D", showlegend=False, line=dict(color=color, width=.75, dash="dot"), hoverinfo="skip"))
        spy_anchor=display_window(prices["SPY"].dropna(),rs_horizon)
        if not spy_anchor.empty:
            fig.add_trace(go.Scatter(x=spy_anchor.index,y=np.full(len(spy_anchor),100.0),name="SPY ANCHOR",
                line=dict(color="#edf2f7",width=1.8,dash="dash"),hovertemplate="<b>SPY Anchor</b><br>%{x|%Y-%m-%d}<br>100.00<extra></extra>"))
        q_pair=prices[["QQQ","SPY"]].dropna()
        if not q_pair.empty:
            q_ratio_full=q_pair["QQQ"].div(q_pair["SPY"]); q_ratio=display_window(q_ratio_full,rs_horizon)
            q_rebased=q_ratio.div(q_ratio.iloc[0]).mul(100)
            fig.add_trace(go.Scatter(x=q_rebased.index,y=q_rebased,name="QQQ / SPY ANCHOR",
                line=dict(color="#d18cff",width=2.2),hovertemplate="<b>QQQ / SPY</b><br>%{x|%Y-%m-%d}<br>%{y:.2f}<extra></extra>"))
        base_layout(fig, 570, "x unified"); fig.add_hline(y=100, line_dash="dash", line_color="#728198", line_width=1)
        fig.update_xaxes(title=None); fig.update_yaxes(title="Relative Performance · Rebased 100")
        st.plotly_chart(fig, use_container_width=True, config={"displaylogo": False})
        flow_scores={}
        for ticker in SECTORS:
            if ticker in sector_flow_close and ticker in sector_flow_volume:
                score=signed_flow_score(sector_flow_close[ticker],sector_flow_volume[ticker])
                if np.isfinite(score): flow_scores[ticker]=score
        inflow=sorted(flow_scores,key=flow_scores.get,reverse=True)[:3]
        outflow=sorted(flow_scores,key=flow_scores.get)[:3]
        strong=[]; weak=[]
        for ticker in SECTORS:
            _,stats=relative_signal(prices[ticker],prices["SPY"])
            if stats.get("state") in {"强势 · 持有观察","过热 · 考虑减仓"}: strong.append(ticker)
            if "潜伏" in str(stats.get("state","")): weak.append(ticker)
        market_state,market_drivers,_=market_sentiment(prices)
        inflow_text="、".join(f"{t}({flow_scores[t]:+.1f}%)" for t in inflow) or "数据不足"
        outflow_text="、".join(f"{t}({flow_scores[t]:+.1f}%)" for t in outflow) or "数据不足"
        st.markdown(f"""<div style="border:1px solid #24354d;background:#0a111c;padding:12px 14px;border-radius:4px;color:#aebdd0;font-size:.78rem;line-height:1.65">
        <b style="color:#f0a13a">DAILY RELATIVE-STRENGTH READOUT</b><br>
        市场状态：<b style="color:#eaf1fb">{market_state}</b>。SPY 500公司广度为 {sp_adv} 涨 / {sp_dec} 跌 / {sp_unch} 平（缺失 {sp_missing}）。<br>
        跨资产驱动：<span style="color:#8191a6">{market_drivers or '数据不足'}</span>。<br>
        相对 SPY 位于 60/200MA 上方：<b>{'、'.join(strong) or '暂无'}</b>；潜伏观察：<b>{'、'.join(weak) or '暂无'}</b>。<br>
        20日成交金额方向代理净流入领先：<span style="color:#31d6a0">{inflow_text}</span>；净流出领先：<span style="color:#ff5874">{outflow_text}</span>。<br>
        <span style="color:#65768d">资金方向为 signed-dollar-volume 代理，并非 ETF 真实申赎。</span></div>""",unsafe_allow_html=True)

with tab_market:
    tape_tab, ndx_tab, matrix_tab = st.tabs(["MARKET BREADTH TAPE", "NDX LEADERS", "SECTOR MATRIX"])
    with tape_tab:
        breadth_scope = st.radio("Breadth Universe", ["S&P CORE", "NASDAQ-100"], horizontal=True,
                                 label_visibility="collapsed", key="breadth_scope")
        universe = HEAT_UNIVERSE if breadth_scope == "S&P CORE" else NASDAQ_UNIVERSE
        benchmark = "SPY" if breadth_scope == "S&P CORE" else "QQQ"
        universe_tickers = list(universe)
        breadth = breadth_history(prices, universe_tickers)
        latest_breadth = breadth.dropna(subset=["net_pct"]).iloc[-1] if not breadth.dropna(subset=["net_pct"]).empty else None

        breadth_cards = st.columns(6)
        card_values = [
            ("ADVANCERS", int(latest_breadth["adv"]) if latest_breadth is not None else None, None),
            ("DECLINERS", int(latest_breadth["dec"]) if latest_breadth is not None else None, None),
            ("NET BREADTH", float(latest_breadth["net_pct"]) if latest_breadth is not None else np.nan, "%"),
            ("ABOVE 20DMA", percent_above_ma(prices, universe_tickers, 20), "%"),
            ("ABOVE 50DMA", percent_above_ma(prices, universe_tickers, 50), "%"),
            ("ABOVE 200DMA", percent_above_ma(prices, universe_tickers, 200), "%"),
        ]
        for col, (label, value, suffix) in zip(breadth_cards, card_values):
            if value is None or (isinstance(value, float) and not np.isfinite(value)):
                shown = "N/A"
            elif suffix == "%":
                shown = f"{value:.1f}%"
            else:
                shown = str(value)
            col.metric(label, shown, delta_color="off")

        left_chart, right_chart = st.columns(2, gap="medium")
        with left_chart:
            section_header("INDEX TREND", f"{benchmark} · Price & Moving Averages", "一年价格趋势与 20 / 50 / 200 日均线。")
            s = prices[benchmark].dropna().tail(300)
            price_fig = go.Figure()
            price_fig.add_trace(go.Scatter(x=s.index, y=s, name=benchmark, line=dict(color="#f0a13a", width=2),
                                           fill="tozeroy", fillcolor="rgba(240,161,58,.08)"))
            for window, color in [(20, "#39c6ff"), (50, "#a78bfa"), (200, "#8c99aa")]:
                ma = prices[benchmark].dropna().rolling(window, min_periods=window).mean().tail(300)
                price_fig.add_trace(go.Scatter(x=ma.index, y=ma, name=f"SMA {window}", line=dict(color=color, width=1, dash="dot")))
            base_layout(price_fig, 390, "x unified")
            price_fig.update_yaxes(title="Adjusted Close")
            st.plotly_chart(price_fig, use_container_width=True, config={"displaylogo": False})
        with right_chart:
            section_header("INTERNALS", f"{breadth_scope} · Net Breadth %", "(上涨家数 − 下跌家数) / 活跃样本；橙线为 20 日均值。")
            breadth_fig = go.Figure()
            recent = breadth.tail(300)
            breadth_fig.add_trace(go.Scatter(x=recent.index, y=recent["net_pct"], name="Daily Net Breadth",
                                             line=dict(color="#2987cf", width=1.4)))
            breadth_fig.add_trace(go.Scatter(x=recent.index, y=recent["net_pct"].rolling(20, min_periods=5).mean(),
                                             name="20D Mean", line=dict(color="#f0a13a", width=1.8)))
            base_layout(breadth_fig, 390, "x unified")
            breadth_fig.add_hline(y=0, line_dash="dash", line_color="#7a8798", line_width=1)
            breadth_fig.update_yaxes(title="Net Breadth %", range=[-105, 105])
            st.plotly_chart(breadth_fig, use_container_width=True, config={"displaylogo": False})

        movers = mover_frame(prices, universe)
        gain_col, loss_col = st.columns(2, gap="medium")
        for col, title, frame in [
            (gain_col, "TOP 10 GAINERS · 领涨", movers.nlargest(10, "1D %") if not movers.empty else movers),
            (loss_col, "TOP 10 LOSERS · 领跌", movers.nsmallest(10, "1D %") if not movers.empty else movers),
        ]:
            with col:
                section_header("LEADERSHIP TAPE", title, f"基于 {breadth_scope} 看板覆盖样本的最近交易日排名。")
                styled_movers = frame.style.format({"Last": "${:,.2f}", "1D %": "{:+.2f}%"}, na_rep="—").map(
                    color_return, subset=["1D %"])
                st.dataframe(styled_movers, use_container_width=True, hide_index=True, height=380)

    with ndx_tab:
        ndx_movers = mover_frame(prices, NASDAQ_UNIVERSE)
        gain_col, loss_col = st.columns(2, gap="medium")
        for col, title, frame in [
            (gain_col, "TOP 10 GAINERS · NDX 领涨", ndx_movers.nlargest(10, "1D %") if not ndx_movers.empty else ndx_movers),
            (loss_col, "TOP 10 LOSERS · NDX 领跌", ndx_movers.nsmallest(10, "1D %") if not ndx_movers.empty else ndx_movers),
        ]:
            with col:
                section_header("NASDAQ LEADERSHIP", title, "按最近交易日涨跌幅排序；范围为本看板 Nasdaq-100 覆盖样本。")
                styled_ndx = frame.style.format({"Last":"${:,.2f}","1D %":"{:+.2f}%"},na_rep="—").map(
                    color_return,subset=["1D %"])
                st.dataframe(styled_ndx,use_container_width=True,hide_index=True,height=405)
        section_header("INDEX LEADERSHIP", "Nasdaq Core Holdings · Rebased 100", "核心权重股过去一年归一化走势。")
        ndx_fig = go.Figure()
        top_holdings = sorted(NASDAQ_UNIVERSE, key=lambda t: NASDAQ_UNIVERSE[t][2], reverse=True)[:10]
        for ticker in top_holdings:
            if ticker not in prices:
                continue
            s = prices[ticker].dropna().tail(252)
            if s.empty:
                continue
            rebased = s.div(s.iloc[0]).mul(100)
            ndx_fig.add_trace(go.Scatter(x=rebased.index,y=rebased,name=ticker,mode="lines",line=dict(width=1.5),
                                         hovertemplate=f"<b>{ticker}</b><br>%{{x|%Y-%m-%d}}<br>%{{y:.2f}}<extra></extra>"))
        base_layout(ndx_fig,360,"x unified")
        ndx_fig.add_hline(y=100,line_dash="dot",line_color="#718198",line_width=1)
        ndx_fig.update_yaxes(title="Rebased 100")
        st.plotly_chart(ndx_fig,use_container_width=True,config={"displaylogo":False})

    with matrix_tab:
        col_left, col_right = st.columns(2, gap="medium")
        rows = []
        for ticker, (en_name, cn_name, weight) in SECTORS.items():
            s = prices[ticker] if ticker in prices else pd.Series(dtype=float); day = last_return(s, 1)
            rows.append({"Sector":f"{en_name} · {cn_name}","ETF Code":ticker,"SPY Weight (%)":weight,"1D Return":day,
                         "1W Return":last_return(s,5),"1M Return":last_return(s,21),"YTD Return":ytd_return(s),
                         "Contribution (bp)":weight*day if np.isfinite(day) else np.nan})
        perf_df = pd.DataFrame(rows)
        with col_left:
            section_header("SECTOR ATTRIBUTION", "Sector Performance & Contribution", "SPY 行业代理权重、跨周期收益与单日贡献；权重为静态近似值。")
            styled = perf_df.style.format({"SPY Weight (%)":"{:.1f}","1D Return":"{:+.2f}%","1W Return":"{:+.2f}%","1M Return":"{:+.2f}%","YTD Return":"{:+.2f}%","Contribution (bp)":"{:+.2f}"}, na_rep="—").map(color_return, subset=["1D Return","1W Return","1M Return","YTD Return","Contribution (bp)"])
            st.dataframe(styled, use_container_width=True, hide_index=True, height=510)
        with col_right:
            section_header("LONG-TERM REGIME", "200-Day MA Slope · 趋势雷达", "SMA200 最近 20 个交易日回归斜率，经当前 SMA200 归一化。")
            slope_rows=[]
            for ticker,(en_name,cn_name,_) in SECTORS.items():
                slope=normalized_slope(prices[ticker]) if ticker in prices else np.nan
                slope_rows.append({"Sector":f"{en_name} · {cn_name}","ETF":ticker,"Slope % / Day":slope,"Trend State":trend_label(slope)})
            slope_df=pd.DataFrame(slope_rows)
            st.dataframe(slope_df.style.format({"Slope % / Day":"{:+.4f}%"},na_rep="—").map(color_return,subset=["Slope % / Day"]),use_container_width=True,hide_index=True,height=260)
            fig=go.Figure()
            for ticker,(_,cn_name,_) in SECTORS.items():
                s=prices[ticker].dropna().tail(252) if ticker in prices else pd.Series(dtype=float)
                if s.empty: continue
                rebased=s.div(s.iloc[0]).mul(100)
                fig.add_trace(go.Scatter(x=rebased.index,y=rebased,mode="lines",name=ticker,line=dict(color=COLORS[ticker],width=1.25),hovertemplate=f"<b>{ticker} · {cn_name}</b><br>%{{x|%Y-%m-%d}}<br>%{{y:.2f}}<extra></extra>"))
            base_layout(fig,310,"x unified"); fig.add_hline(y=100,line_dash="dot",line_color="#718198",line_width=1)
            fig.update_layout(margin=dict(l=45,r=14,t=28,b=35)); fig.update_yaxes(title="1Y Rebased 100")
            st.plotly_chart(fig,use_container_width=True,config={"displaylogo":False})

with tab_heat:
    heat_control_0,heat_control_1,heat_control_2,_=st.columns([1.35,1.2,1,3.5])
    with heat_control_0:
        heat_mode=st.radio("Heat Map Engine",["TradingView Official","Quant Native"],horizontal=True,
                           label_visibility="collapsed",key="heat_mode")
    with heat_control_1:
        heat_index = st.radio("Heat Map Universe", ["S&P 500 CORE", "NASDAQ-100"], horizontal=True,
                              label_visibility="collapsed", key="heat_index")
    with heat_control_2:
        heat_period = st.radio("Return Window", ["1D", "1M"], horizontal=True,
                               label_visibility="collapsed", key="heat_period")
    heat_universe = HEAT_UNIVERSE if heat_index == "S&P 500 CORE" else NASDAQ_UNIVERSE
    section_header("STOCK HEATMAP",f"{heat_index} · {heat_period} Change",
                   "官方模式直接嵌入 TradingView Stock Heatmap；本地模式使用 yfinance 与 Plotly。")
    if heat_mode == "TradingView Official":
        tv_source="SPX500" if heat_index=="S&P 500 CORE" else "NASDAQ100"
        tv_color="change" if heat_period=="1D" else "Perf.1M"
        components.html(f'''<style>html,body{{height:100%;margin:0;overflow:hidden;background:#000}}.tradingview-widget-container{{height:730px!important;width:100%!important}}.tradingview-widget-container__widget{{height:700px!important;width:100%!important}}</style>
        <div class="tradingview-widget-container" style="height:730px;width:100%;background:#000">
        <div class="tradingview-widget-container__widget" style="height:700px;width:100%"></div>
        <div class="tradingview-widget-copyright"><a href="https://www.tradingview.com/heatmap/stock/" rel="noopener nofollow" target="_blank"><span style="color:#2962ff">Stock Heatmap</span></a> by TradingView</div>
        <script type="text/javascript" src="https://s3.tradingview.com/external-embedding/embed-widget-stock-heatmap.js" async>
        {{"dataSource":"{tv_source}","blockSize":"market_cap_basic","blockColor":"{tv_color}","grouping":"sector","locale":"en","colorTheme":"dark","hasTopBar":true,"isDataSetEnabled":true,"isZoomEnabled":true,"hasSymbolTooltip":true,"isMonoSize":false,"width":"100%","height":700}}
        </script></div>''',height=750,scrolling=False)
        st.caption("TradingView 官方组件由 TradingView 直接提供行情和渲染；若网络策略拦截第三方脚本，请切换 Quant Native。")
    else:
        rows=[]; periods=1 if heat_period=="1D" else 21
        for ticker,meta in heat_universe.items():
            if ticker not in prices: continue
            ret=last_return(prices[ticker],periods)
            if not np.isfinite(ret): continue
            if heat_index=="S&P 500 CORE": company,sector_etf,weight=meta; group=f"{sector_etf} · {SECTORS[sector_etf][1]}"
            else: company,group,weight=meta
            rows.append({"Group":group,"Ticker":ticker,"Company":company,"Market Weight":weight,"Return":ret,"Tile Text":f"{ret:+.2f}%"})
        heat_df=pd.DataFrame(rows)
        if heat_df.empty: st.warning("热力图样本暂无有效数据。")
        else:
            floor=2.0 if heat_period=="1D" else 5.0; limit=max(floor,float(heat_df["Return"].abs().quantile(.92)))
            fig=px.treemap(heat_df,path=[px.Constant(heat_index),"Group","Ticker"],values="Market Weight",color="Return",
                color_continuous_scale=[(0,"#b51f32"),(.32,"#5c1d29"),(.5,"#34373c"),(.68,"#125338"),(1,"#00a85a")],
                range_color=(-limit,limit),custom_data=["Company","Return","Market Weight","Tile Text"])
            tile_text=[str(custom[3]) if str(node_id).count("/")>=2 else "" for node_id,custom in zip(fig.data[0].ids,fig.data[0].customdata)]
            fig.update_traces(text=tile_text,texttemplate="<b>%{label}</b><br>%{text}",hovertemplate="<b>%{label}</b><br>%{customdata[0]}<br>Return %{customdata[1]:+.2f}%<br>Weight proxy %{customdata[2]:.2f}%<extra></extra>",textfont=dict(size=15,color="#f7f8fa"),marker=dict(line=dict(color="#05070a",width=2.2)),root_color="#000000",tiling=dict(packing="squarify",pad=2))
            fig.update_layout(template="plotly_dark",height=720,paper_bgcolor="#000000",plot_bgcolor="#000000",margin=dict(l=2,r=2,t=10,b=2),font=dict(family="Inter, Segoe UI, sans-serif",color="#f1f5fb"),coloraxis_colorbar=dict(title=f"{heat_period} %",thickness=11,len=.58,tickformat="+.1f"))
            st.plotly_chart(fig,use_container_width=True,config={"displaylogo":False})

    section_header("FLOW PROXY",f"{heat_index} · 20D Signed Dollar Volume","正值代表上涨日成交金额占优，负值代表下跌日成交金额占优；这是方向代理，不是真实基金申赎。")
    try:
        flow_close,flow_volume=load_flow_data(tuple(heat_universe),"3mo")
    except Exception:
        flow_close,flow_volume=pd.DataFrame(),pd.DataFrame()
    flow_rows=[]
    for ticker,meta in heat_universe.items():
        if ticker not in flow_close or ticker not in flow_volume: continue
        score=signed_flow_score(flow_close[ticker],flow_volume[ticker])
        if not np.isfinite(score): continue
        if heat_index=="S&P 500 CORE": company,sector_etf,weight=meta; group=f"{sector_etf} · {SECTORS[sector_etf][1]}"
        else: company,group,weight=meta
        flow_rows.append({"Group":group,"Ticker":ticker,"Company":company,"Market Weight":weight,"Flow":score,"Flow Text":f"{score:+.1f}%"})
    flow_df=pd.DataFrame(flow_rows)
    if flow_df.empty: st.warning("资金方向代理暂无有效成交量数据。")
    else:
        flow_limit=max(20.0,float(flow_df["Flow"].abs().quantile(.92)))
        flow_fig=px.treemap(flow_df,path=[px.Constant(f"{heat_index} FLOW"),"Group","Ticker"],values="Market Weight",color="Flow",
            color_continuous_scale=[(0,"#a61b3b"),(.5,"#2e333b"),(1,"#087f60")],range_color=(-flow_limit,flow_limit),
            custom_data=["Company","Flow","Flow Text"])
        flow_text=[str(custom[2]) if str(node_id).count("/")>=2 else "" for node_id,custom in zip(flow_fig.data[0].ids,flow_fig.data[0].customdata)]
        flow_fig.update_traces(text=flow_text,texttemplate="<b>%{label}</b><br>%{text}",hovertemplate="<b>%{label}</b><br>%{customdata[0]}<br>20D Flow Proxy %{customdata[1]:+.1f}%<extra></extra>",marker=dict(line=dict(color="#05070a",width=2)),root_color="#000",tiling=dict(pad=2))
        flow_fig.update_layout(template="plotly_dark",height=540,paper_bgcolor="#000",plot_bgcolor="#000",margin=dict(l=2,r=2,t=8,b=2),coloraxis_colorbar=dict(title="Flow %",thickness=11,len=.58))
        st.plotly_chart(flow_fig,use_container_width=True,config={"displaylogo":False})

with tab_macro:
    col_left,col_right=st.columns(2,gap="medium")
    with col_left:
        section_header("CROSS-ASSET TAPE","Commodities Monitor · 大宗资产跟踪","贵金属、能源、美元与久期资产的多周期收益面板。")
        rows=[]
        for ticker,name in COMMODITIES.items():
            s=prices[ticker] if ticker in prices else pd.Series(dtype=float); clean=s.dropna()
            rows.append({"Asset":name,"Ticker":ticker,"Last":float(clean.iloc[-1]) if not clean.empty else np.nan,"1D":last_return(s,1),"1W":last_return(s,5),"1M":last_return(s,21),"3M":last_return(s,63),"YTD":ytd_return(s)})
        df=pd.DataFrame(rows)
        styled=df.style.format({"Last":"${:,.2f}","1D":"{:+.2f}%","1W":"{:+.2f}%","1M":"{:+.2f}%","3M":"{:+.2f}%","YTD":"{:+.2f}%"},na_rep="—").map(color_return,subset=["1D","1W","1M","3M","YTD"])
        st.dataframe(styled,use_container_width=True,hide_index=True,height=510)
    with col_right:
        section_header("MEAN REVERSION RADAR","Rolling Z-Score · 多资产极值","GLD、TLT、QQQ 相对 SPY 的滚动标准分；±2σ 为统计极值区。")
        fig=go.Figure()
        for ticker,name in {"GLD":"黄金","TLT":"长债","QQQ":"科技股"}.items():
            if ticker not in prices: continue
            z=rolling_zscore(prices[ticker],prices["SPY"],z_window).tail(252)
            if z.empty: continue
            fig.add_trace(go.Scatter(x=z.index,y=z,mode="lines",name=f"{ticker} · {name}",line=dict(color=COLORS[ticker],width=1.8),hovertemplate=f"<b>{ticker} · {name}</b><br>%{{x|%Y-%m-%d}}<br>Z %{{y:.2f}}σ<extra></extra>"))
        base_layout(fig,570,"x unified")
        fig.add_hline(y=2,line_dash="dash",line_color="#ff4f70",line_width=1.2,annotation_text="+2σ OVERBOUGHT",annotation_font_color="#ff6a84")
        fig.add_hline(y=-2,line_dash="dash",line_color="#18d39c",line_width=1.2,annotation_text="−2σ OVERSOLD",annotation_font_color="#2be0ac")
        fig.add_hline(y=0,line_dash="dot",line_color="#718198",line_width=1)
        fig.update_xaxes(title=None); fig.update_yaxes(title="Rolling Z-Score (σ)")
        st.plotly_chart(fig,use_container_width=True,config={"displaylogo":False})

with tab_technical:
    section_header("TECHNICALS", "Relative Strength · MA Regime · Z-Score", "蓝线为相对强度比率；低于两条均线进入潜伏观察区，高于两条均线结合 Z-Score 判断持有或过热。")
    control_1, control_2, control_3, control_4 = st.columns([1.2,1,1,1])
    with control_1:
        preset = st.selectbox("Preset", ["CUSTOM","XLE / SPY","XLK / SPY","SMH / SPY","GDX / GLD","TLT / SPY"], key="rs_preset")
    preset_pair = preset.replace(" ", "").split("/") if preset != "CUSTOM" else None
    with control_2:
        numerator_input = st.text_input("Numerator · 分子", value=preset_pair[0] if preset_pair else "XLE", key=f"rs_num_{preset}")
    with control_3:
        denominator_input = st.text_input("Denominator · 分母", value=preset_pair[1] if preset_pair else "SPY", key=f"rs_den_{preset}")
    with control_4:
        technical_period = st.selectbox("History",list(PERIOD_BARS),index=4,key="rs_period")
    numerator = "".join(c for c in numerator_input.upper().strip().replace(".", "-") if c.isalnum() or c in "-^=")[:15]
    denominator = "".join(c for c in denominator_input.upper().strip().replace(".", "-") if c.isalnum() or c in "-^=")[:15]

    ratio_data = pd.DataFrame()
    if numerator and denominator:
        try:
            requested=list(dict.fromkeys([numerator,denominator,"SPY","QQQ"]))
            ratio_data=load_custom_prices(tuple(requested),"max")
        except Exception as exc:
            st.warning(f"自定义相对强度数据下载失败：{exc}")
    pair_ok = (numerator in ratio_data and denominator in ratio_data and
               not ratio_data[numerator].dropna().empty and not ratio_data[denominator].dropna().empty)
    if not pair_ok:
        st.warning("请输入 Yahoo Finance 可识别的分子与分母代码。")
    else:
        ratio_frame, ratio_stats = relative_signal(ratio_data[numerator],ratio_data[denominator])
        if ratio_frame.empty:
            st.warning("有效共同交易历史不足 200 日，无法完成 60/200 日均线分析。")
        else:
            stat_cols = st.columns(5)
            stat_cols[0].metric("REGIME / 状态",str(ratio_stats["state"]),delta_color="off")
            stat_cols[1].metric("RATIO",f"{ratio_stats['ratio']:.5f}",delta_color="off")
            stat_cols[2].metric("Z-SCORE",f"{ratio_stats['zscore']:+.2f}σ",delta_color="off")
            stat_cols[3].metric("VS 60MA",f"{ratio_stats['vs_ma60']:+.2f}%")
            stat_cols[4].metric("VS 200MA",f"{ratio_stats['vs_ma200']:+.2f}%")

            active_ratio=display_window(ratio_frame,technical_period)
            plot_ratio=display_with_preroll(ratio_frame,technical_period)
            technical_fig = make_subplots(rows=2,cols=1,shared_xaxes=True,vertical_spacing=.08,row_heights=[.68,.32])
            technical_fig.add_trace(go.Scatter(x=plot_ratio.index,y=plot_ratio["ratio"],name="Ratio · 蓝线",
                line=dict(color="#4f86d9",width=2)),row=1,col=1)
            technical_fig.add_trace(go.Scatter(x=plot_ratio.index,y=plot_ratio["ma60"],name="60MA",
                line=dict(color="#e56f24",width=1.7)),row=1,col=1)
            technical_fig.add_trace(go.Scatter(x=plot_ratio.index,y=plot_ratio["ma200"],name="200MA",
                line=dict(color="#a8adb5",width=1.6)),row=1,col=1)
            hist_colors=np.where(plot_ratio["hist"]>=0,"#29a987","#e74b5e")
            technical_fig.add_trace(go.Bar(x=plot_ratio.index,y=plot_ratio["hist"],name="Histogram",
                marker_color=hist_colors,opacity=.8),row=2,col=1)
            technical_fig.add_trace(go.Scatter(x=plot_ratio.index,y=plot_ratio["macd"],name="MACD 8/17",
                line=dict(color="#4f86d9",width=1.4)),row=2,col=1)
            technical_fig.add_trace(go.Scatter(x=plot_ratio.index,y=plot_ratio["signal"],name="Signal 9",
                line=dict(color="#e56f24",width=1.3)),row=2,col=1)
            base_layout(technical_fig,620,"x unified")
            technical_fig.update_layout(title=dict(text=f"{numerator} / {denominator} · Ratio + 60/200MA · MACD (8,17,9)",font=dict(size=12,color="#f0a13a")))
            technical_fig.update_yaxes(title="Relative Ratio",row=1,col=1)
            technical_fig.update_yaxes(title="MACD",row=2,col=1,zeroline=True,zerolinecolor="#697789")
            if not active_ratio.empty and active_ratio.index[0]>plot_ratio.index[0]:
                technical_fig.add_vline(x=active_ratio.index[0].to_pydatetime(),line_dash="dot",line_color="#74849a",
                    annotation_text=f"{technical_period} ACTIVE WINDOW",annotation_position="top left")
            st.plotly_chart(technical_fig,use_container_width=True,config={"displaylogo":False})

            anchor_col,readout_col=st.columns([1.25,.75],gap="medium")
            with anchor_col:
                section_header("ANCHOR COMPARISON", "SPY / QQQ Anchored Performance", "分子、分母、SPY 与 QQQ 在所选有效周期起点统一锚定为 100。")
                anchor_fig=go.Figure(); anchor_colors={numerator:"#4f86d9",denominator:"#e56f24","SPY":"#e8edf4","QQQ":"#a78bfa"}
                for ticker in dict.fromkeys([numerator,denominator,"SPY","QQQ"]):
                    if ticker not in ratio_data: continue
                    series=display_window(ratio_data[ticker].dropna(),technical_period)
                    if series.empty: continue
                    rebased=series.div(series.iloc[0]).mul(100)
                    anchor_fig.add_trace(go.Scatter(x=rebased.index,y=rebased,name=ticker,line=dict(color=anchor_colors.get(ticker,"#8ca0b8"),width=1.8),
                        hovertemplate=f"<b>{ticker}</b><br>%{{x|%Y-%m-%d}}<br>%{{y:.2f}}<extra></extra>"))
                base_layout(anchor_fig,360,"x unified"); anchor_fig.add_hline(y=100,line_dash="dot",line_color="#718198",line_width=1)
                anchor_fig.update_yaxes(title="Anchored 100")
                st.plotly_chart(anchor_fig,use_container_width=True,config={"displaylogo":False})
            with readout_col:
                sentiment,drivers,sentiment_score=market_sentiment(prices)
                section_header("RISK APPETITE", "Cross-Asset Market State", "使用科技/小盘/信用与黄金/长债/VIX 相对趋势判断。")
                state_color="#31d6a0" if sentiment_score>=3 else ("#ff5874" if sentiment_score<=-3 else "#e8bd55")
                st.markdown(f"""<div style="border:1px solid #24354d;background:#0a111c;padding:16px;border-radius:4px;line-height:1.7;color:#aebdd0;min-height:285px">
                <div style="font-size:1.15rem;font-weight:750;color:{state_color}">{sentiment}</div>
                <div style="margin-top:8px">当前 {numerator}/{denominator}：<b>{ratio_stats['state']}</b>，相对60MA {ratio_stats['vs_ma60']:+.2f}%，相对200MA {ratio_stats['vs_ma200']:+.2f}%。</div>
                <div style="margin-top:8px;color:#8191a6">驱动：{drivers or '数据不足'}</div>
                <div style="margin-top:8px;color:#65768d">分数 {sentiment_score:+d}；正值偏风险偏好，负值偏避险。锚定曲线用于横向比较，不代表绝对估值。</div></div>""",unsafe_allow_html=True)

    section_header("REGIME SCANNER", "Bottoming & Overheat Scanner · 见底与过热扫描", "规则：蓝线低于 60/200MA 为潜伏观察；Z≤−1.5 且 MACD 柱回升为见底候选；蓝线高于两线为持有，Z≥+2 为过热减仓。")
    scan_candidates = list(dict.fromkeys(list(SECTORS) + ["SMH","GLD","SLV","TLT","USO","CPER","QQQ","IWM"]
                                     + sorted(NASDAQ_UNIVERSE,key=lambda t:NASDAQ_UNIVERSE[t][2],reverse=True)[:15]))
    scan_rows=[]
    for ticker in scan_candidates:
        if ticker not in prices or ticker == "SPY":
            continue
        _, stats = relative_signal(prices[ticker],prices["SPY"])
        if stats.get("state") == "数据不足":
            continue
        scan_rows.append({"Ticker":ticker,"State":stats["state"],"Z-Score":stats["zscore"],
                          "vs 60MA %":stats["vs_ma60"],"vs 200MA %":stats["vs_ma200"],"MACD Hist":stats["macd_hist"]})
    scan_df=pd.DataFrame(scan_rows)
    bottom_col,hot_col=st.columns(2,gap="medium")
    with bottom_col:
        section_header("BOTTOM WATCH", "潜伏 / 见底候选", "相对强度蓝线位于两条均线下方，按 Z-Score 从低到高排列。")
        bottom=scan_df[scan_df["State"].astype(str).str.contains("潜伏")].sort_values("Z-Score").head(12) if not scan_df.empty else scan_df
        st.dataframe(bottom.style.format({"Z-Score":"{:+.2f}","vs 60MA %":"{:+.2f}%","vs 200MA %":"{:+.2f}%","MACD Hist":"{:+.5f}"},na_rep="—").map(color_return,subset=["Z-Score","vs 60MA %","vs 200MA %"]),use_container_width=True,hide_index=True,height=320)
    with hot_col:
        section_header("HOLD / TRIM", "强势持有 / 过热减仓", "蓝线位于两条均线之上；优先显示 Z-Score 最高标的。")
        hot=scan_df[scan_df["State"].astype(str).str.contains("持有|过热",regex=True)].sort_values("Z-Score",ascending=False).head(12) if not scan_df.empty else scan_df
        st.dataframe(hot.style.format({"Z-Score":"{:+.2f}","vs 60MA %":"{:+.2f}%","vs 200MA %":"{:+.2f}%","MACD Hist":"{:+.5f}"},na_rep="—").map(color_return,subset=["Z-Score","vs 60MA %","vs 200MA %"]),use_container_width=True,hide_index=True,height=320)

    st.divider()
    section_header("SINGLE-TICKER TECHNICALS", "单一标的技术分析", "输入任意 Yahoo Finance 代码，自动抓取价格并绘制 20/50/200MA 与滚动 Z-Score。")
    single_col_1,single_col_2,_=st.columns([1,1,4])
    with single_col_1:
        single_input=st.text_input("Ticker",value="QQQ",key="single_ticker")
    with single_col_2:
        single_period=st.selectbox("History",list(PERIOD_BARS),index=4,key="single_period")
    single_ticker="".join(c for c in single_input.upper().strip().replace(".","-") if c.isalnum() or c in "-^=")[:15]
    single_data=pd.DataFrame()
    if single_ticker:
        try:
            if single_ticker in ratio_data and not ratio_data[single_ticker].dropna().empty:
                single_data=ratio_data[[single_ticker]].copy()
            else:
                single_data=load_custom_prices((single_ticker,),"max")
        except Exception as exc:
            st.warning(f"单标的数据下载失败：{exc}")
    if single_ticker not in single_data or single_data[single_ticker].dropna().empty:
        st.warning("该代码没有返回有效价格数据。")
    else:
        s=single_data[single_ticker].dropna()
        sma20=s.rolling(20,min_periods=20).mean(); sma50=s.rolling(50,min_periods=50).mean(); sma200=s.rolling(200,min_periods=200).mean()
        mean120=s.rolling(120,min_periods=120).mean(); std120=s.rolling(120,min_periods=120).std(ddof=0).replace(0,np.nan)
        price_z=s.sub(mean120).div(std120)
        latest_price=float(s.iloc[-1]); latest_z=float(price_z.dropna().iloc[-1]) if not price_z.dropna().empty else np.nan
        dist200=float((latest_price/sma200.dropna().iloc[-1]-1)*100) if not sma200.dropna().empty else np.nan
        slope=normalized_slope(s)
        single_stats=st.columns(4)
        single_stats[0].metric("PRICE",f"${latest_price:,.2f}")
        single_stats[1].metric("VS 200MA",format_num(dist200))
        single_stats[2].metric("PRICE Z-SCORE",format_num(latest_z,"σ"))
        single_stats[3].metric("200MA SLOPE",format_num(slope,"% / day"))
        single_full=pd.DataFrame({"price":s,"sma20":sma20,"sma50":sma50,"sma200":sma200,"zscore":price_z})
        single_active=display_window(single_full,single_period)
        single_plot=display_with_preroll(single_full,single_period)
        single_fig=make_subplots(rows=2,cols=1,shared_xaxes=True,vertical_spacing=.07,row_heights=[.72,.28])
        single_fig.add_trace(go.Scatter(x=single_plot.index,y=single_plot["price"],name=single_ticker,line=dict(color="#4f86d9",width=2)),row=1,col=1)
        for name,column,color in [("SMA20","sma20","#31d6a0"),("SMA50","sma50","#e56f24"),("SMA200","sma200","#a8adb5")]:
            single_fig.add_trace(go.Scatter(x=single_plot.index,y=single_plot[column],name=name,line=dict(color=color,width=1.4)),row=1,col=1)
        single_fig.add_trace(go.Scatter(x=single_plot.index,y=single_plot["zscore"],name="Z-Score",line=dict(color="#a78bfa",width=1.7)),row=2,col=1)
        base_layout(single_fig,620,"x unified")
        single_fig.add_hline(y=2,line_dash="dash",line_color="#ff4f70",row=2,col=1)
        single_fig.add_hline(y=-2,line_dash="dash",line_color="#18d39c",row=2,col=1)
        single_fig.add_hline(y=0,line_dash="dot",line_color="#718198",row=2,col=1)
        if not single_active.empty and single_active.index[0]>single_plot.index[0]:
            single_fig.add_vline(x=single_active.index[0].to_pydatetime(),line_dash="dot",line_color="#74849a",
                annotation_text=f"{single_period} ACTIVE WINDOW",annotation_position="top left")
        single_fig.update_layout(title=dict(text=f"{single_ticker} · Price / Moving Averages / Z-Score",font=dict(size=12,color="#f0a13a")))
        single_fig.update_yaxes(title="Price",row=1,col=1); single_fig.update_yaxes(title="Z",row=2,col=1)
        st.plotly_chart(single_fig,use_container_width=True,config={"displaylogo":False})
    st.caption("信号是基于相对强度、均线和统计偏离的研究分类，不是确定性底部预测，也不构成投资建议。")

with tab_pattern:
    regime_head,regime_control_1,regime_control_2,regime_control_3=st.columns([4.6,1.35,1.05,1.05],vertical_alignment="bottom")
    with regime_head:
        section_header("REGIME & PATTERN DETECTION","趋势状态机与几何形态自动识别",
                       "全历史数据常驻图表；6M / 1Y / 3Y 仅改变初始视窗，可随时向左拖回历史。")
    with regime_control_1:
        selected_pair=st.selectbox("Trading Pair",list(REGIME_PAIRS),key="regime_pair")
    base_symbol,leveraged_symbol=REGIME_PAIRS[selected_pair]
    with regime_control_2:
        target_symbol=st.selectbox("Analyze",[base_symbol,leveraged_symbol],index=1,key="regime_target")
    with regime_control_3:
        regime_horizon=st.selectbox("Chart Range",["6M","1Y","3Y","MAX"],index=3,key="regime_horizon")
    if not SCIPY_AVAILABLE:
        st.caption("⚠ SciPy 尚未安装，当前使用安全回退极值算法；安装 requirements.txt 后自动启用 scipy.signal.argrelextrema。")

    regime_data=pd.DataFrame()
    try:
        regime_data=load_ohlcv((base_symbol,leveraged_symbol),"max")
    except Exception as exc:
        st.warning(f"OHLCV 数据下载失败：{exc}")
    available_regime=set(regime_data.columns.get_level_values(0)) if not regime_data.empty else set()
    if regime_data.empty or any(t not in available_regime for t in (base_symbol,leveraged_symbol)):
        st.warning("所选标的没有返回足够的 OHLCV 数据。")
    else:
        indicator_frame=regime_indicators(regime_data[target_symbol])
        regime_state,regime_stats=classify_regime(indicator_frame)
        patterns=detect_geometric_patterns(indicator_frame)
        if not regime_stats:
            st.warning("至少需要 200 个有效交易日才能运行状态机。")
        else:
            detected=[]
            if patterns.get("trend_breakout"): detected.append("🚀 突破下降趋势线")
            double_bottom=patterns.get("double_bottom")
            if double_bottom and double_bottom["breakout"]: detected.append("🔥 W底结构突破")
            triangle=patterns.get("triangle")
            if triangle:
                triangle_signal=triangle["type"]
                if triangle["breakout_up"]: triangle_signal="🚀 "+triangle_signal+"向上突破"
                elif triangle["breakout_down"]: triangle_signal="⚠️ "+triangle_signal+"向下破位"
                detected.append("🔺 "+triangle_signal)
            if patterns.get("channel"): detected.append("📉 下降通道")
            if not detected: detected.append("未确认突破形态")
            latest=float(regime_stats["close"]); ema50=float(regime_stats["ema50"])
            ema50_distance=(latest/ema50-1)*100
            pair_close=regime_data[leveraged_symbol]["Close"].div(regime_data[base_symbol]["Close"]).dropna()
            pair_momentum=last_return(pair_close,20)
            cards=st.columns(6)
            cards[0].metric("CURRENT REGIME",regime_state,delta_color="off")
            cards[1].metric("PATTERN SIGNAL"," · ".join(detected),delta_color="off")
            cards[2].metric("ADX 14",f"{regime_stats['adx']:.2f}",f"+DI {regime_stats['plus_di']:.1f} / −DI {regime_stats['minus_di']:.1f}",delta_color="off")
            cards[3].metric("VS EMA50",f"{ema50_distance:+.2f}%")
            cards[4].metric("BBW 20",f"{regime_stats['bbw']*100:.2f}%",delta_color="off")
            cards[5].metric(f"{leveraged_symbol}/{base_symbol} · 1M",format_num(pair_momentum),delta_color="normal")

            # Keep every downloaded bar in the traces. The horizon only controls the initial viewport.
            plotted=indicator_frame.copy()
            initial_range=chart_initial_range(plotted.index,regime_horizon)
            pattern_fig=make_subplots(rows=2,cols=1,shared_xaxes=True,vertical_spacing=.06,row_heights=[.78,.22])
            pattern_fig.add_trace(go.Candlestick(x=plotted.index,open=plotted["Open"],high=plotted["High"],low=plotted["Low"],close=plotted["Close"],
                name=target_symbol,increasing_line_color="#24c990",decreasing_line_color="#ee5266",increasing_fillcolor="#168b67",decreasing_fillcolor="#a72c42"),row=1,col=1)
            for name,column,color,width in [("EMA20","EMA20","#35d5ff",1.5),("EMA50","EMA50","#f0a13a",1.7),("SMA200","SMA200","#a8adb5",1.5)]:
                pattern_fig.add_trace(go.Scatter(x=plotted.index,y=plotted[column],name=name,line=dict(color=color,width=width)),row=1,col=1)
            if regime_state.startswith("📦"):
                box_start=indicator_frame.index[-30]
                pattern_fig.add_shape(type="rect",x0=box_start,x1=indicator_frame.index[-1],y0=regime_stats["box_low"],y1=regime_stats["box_high"],
                    line=dict(color="#e8bd55",width=1.5,dash="dash"),fillcolor="rgba(232,189,85,.08)",row=1,col=1)
                pattern_fig.add_annotation(x=indicator_frame.index[-1],y=regime_stats["box_high"],text="30D RESISTANCE",showarrow=False,xanchor="right",font=dict(color="#e8bd55",size=10),row=1,col=1)
            recent=patterns["recent"]
            trend=patterns.get("trend")
            if trend:
                trend_dates=recent.index[trend["x"]]
                pattern_fig.add_trace(go.Scatter(x=trend_dates,y=trend["y"],name="Descending Trendline",
                    line=dict(color="#31d6a0" if patterns["trend_breakout"] else "#e8bd55",width=2.4,dash="dash")),row=1,col=1)
                high_idx=trend["idx"]
                pattern_fig.add_trace(go.Scatter(x=recent.index[high_idx],y=recent["High"].iloc[high_idx],name="Lower Highs",mode="markers",
                    marker=dict(color="#e8bd55",size=9,symbol="diamond")),row=1,col=1)
                if patterns["trend_breakout"]:
                    pattern_fig.add_annotation(x=recent.index[-1],y=recent["High"].iloc[-1],text="🚀 TRENDLINE BREAK",showarrow=True,
                        arrowhead=2,arrowcolor="#31d6a0",ax=-55,ay=48,font=dict(color="#31d6a0",size=11),row=1,col=1)
            channel=patterns.get("channel")
            if channel:
                channel_dates=recent.index[channel["x"]]
                pattern_fig.add_trace(go.Scatter(x=channel_dates,y=channel["upper"],name="Channel Upper",line=dict(color="#38c6d9",width=1.5)),row=1,col=1)
                pattern_fig.add_trace(go.Scatter(x=channel_dates,y=channel["lower"],name="Channel Lower",line=dict(color="#38c6d9",width=1.5),fill="tonexty",fillcolor="rgba(56,198,217,.07)"),row=1,col=1)
            if double_bottom:
                w_idx=double_bottom["idx"]
                w_dates=[recent.index[i] for i in w_idx]
                w_prices=list(double_bottom["prices"])
                if double_bottom["breakout"]: w_dates.append(recent.index[-1]); w_prices.append(float(recent["Close"].iloc[-1]))
                pattern_fig.add_trace(go.Scatter(x=w_dates,y=w_prices,name="W Bottom",mode="lines+markers",
                    line=dict(color="#27d3e2",width=3),marker=dict(size=9,color="#27d3e2")),row=1,col=1)
                pattern_fig.add_hline(y=double_bottom["neckline"],line_dash="dash",line_color="#d18cff",line_width=2,
                    annotation_text="W NECKLINE",annotation_font_color="#d18cff",row=1,col=1)
            if triangle:
                triangle_dates=recent.index[triangle["x"]]
                triangle_color="#31d6a0" if triangle["breakout_up"] else "#ff5874" if triangle["breakout_down"] else "#f6c453"
                pattern_fig.add_trace(go.Scatter(x=triangle_dates,y=triangle["upper"],name=f"{triangle['type']} · Upper",
                    line=dict(color=triangle_color,width=2.6)),row=1,col=1)
                pattern_fig.add_trace(go.Scatter(x=triangle_dates,y=triangle["lower"],name=f"{triangle['type']} · Lower",
                    line=dict(color=triangle_color,width=2.6),fill="tonexty",fillcolor="rgba(246,196,83,.075)"),row=1,col=1)
                pattern_fig.add_trace(go.Scatter(x=recent.index[triangle["high_idx"]],y=recent["High"].iloc[triangle["high_idx"]],
                    name="Triangle Highs",mode="markers",marker=dict(color=triangle_color,size=8,symbol="triangle-down")),row=1,col=1)
                pattern_fig.add_trace(go.Scatter(x=recent.index[triangle["low_idx"]],y=recent["Low"].iloc[triangle["low_idx"]],
                    name="Triangle Lows",mode="markers",marker=dict(color=triangle_color,size=8,symbol="triangle-up")),row=1,col=1)
                if triangle["breakout_up"] or triangle["breakout_down"]:
                    arrow_text="🚀 TRIANGLE BREAKOUT" if triangle["breakout_up"] else "⚠ TRIANGLE BREAKDOWN"
                    arrow_y=float(recent["High"].iloc[-1] if triangle["breakout_up"] else recent["Low"].iloc[-1])
                    pattern_fig.add_annotation(x=recent.index[-1],y=arrow_y,text=arrow_text,showarrow=True,arrowhead=2,
                        arrowcolor=triangle_color,ax=-65,ay=45 if triangle["breakout_up"] else -45,
                        font=dict(color=triangle_color,size=11),row=1,col=1)
            pattern_fig.add_trace(go.Scatter(x=plotted.index,y=plotted["ADX14"],name="ADX14",line=dict(color="#f0a13a",width=2)),row=2,col=1)
            pattern_fig.add_trace(go.Scatter(x=plotted.index,y=plotted["+DI"],name="+DI",line=dict(color="#31d6a0",width=1.3)),row=2,col=1)
            pattern_fig.add_trace(go.Scatter(x=plotted.index,y=plotted["-DI"],name="−DI",line=dict(color="#ff5874",width=1.3)),row=2,col=1)
            pattern_fig.add_hline(y=22,line_dash="dot",line_color="#8593a5",annotation_text="ADX 22",row=2,col=1)
            base_layout(pattern_fig,720,"x unified")
            pattern_fig.update_layout(title=dict(text=f"{target_symbol} · Regime & Geometric Pattern Engine",font=dict(size=13,color="#f0a13a")),
                                      dragmode="zoom",uirevision=f"regime-{target_symbol}",xaxis_rangeslider_visible=False)
            if initial_range:
                pattern_fig.update_xaxes(range=initial_range,autorange=False)
            else:
                pattern_fig.update_xaxes(autorange=True)
            pattern_fig.update_xaxes(fixedrange=False,showspikes=True,spikemode="across",spikesnap="cursor")
            pattern_fig.update_yaxes(fixedrange=False,showspikes=True,spikesnap="cursor")
            pattern_fig.update_xaxes(rangeselector=dict(
                buttons=[dict(count=6,label="6M",step="month",stepmode="backward"),
                         dict(count=1,label="1Y",step="year",stepmode="backward"),
                         dict(count=3,label="3Y",step="year",stepmode="backward"),
                         dict(label="MAX",step="all")],
                bgcolor="#0b1421",activecolor="#273b55",bordercolor="#26384e",borderwidth=1,
                font=dict(color="#9fb0c5",size=10),x=.72,xanchor="left",y=1.13,yanchor="top"),row=1,col=1)
            pattern_fig.update_yaxes(title="Price",row=1,col=1); pattern_fig.update_yaxes(title="ADX / DI",row=2,col=1)
            st.plotly_chart(pattern_fig,use_container_width=True,config={"displaylogo":False,"scrollZoom":True,
                "doubleClick":"reset","modeBarButtonsToAdd":["drawline","eraseshape"]})

            # Geometry-derived research levels; no long-entry prompt is issued in an active downtrend break.
            recent30=indicator_frame.tail(30); entry=float(regime_stats["ema20"]); stop=float(recent30["Low"].min())
            rationale="EMA20 回踩试错；跌破近30日低点失效"
            geometry=max(entry-stop,float(regime_stats["atr"]))
            if double_bottom and double_bottom["breakout"]:
                entry=float(double_bottom["neckline"]); stop=float(double_bottom["low2"]); geometry=entry-stop
                rationale="颈线回踩试错；Low2 为结构硬防守"
            elif patterns.get("trend_breakout") and trend:
                entry=float(trend["level"]); stop=float(recent30["Low"].min())
                geometry=float(channel["height"]) if channel and float(channel["height"])>0 else max(entry-stop,float(regime_stats["atr"]))
                rationale="下降趋势线突破后的回踩试错"
            elif triangle and triangle["breakout_up"]:
                entry=float(triangle["upper"][-1]); stop=float(triangle["lower"][-1])
                geometry=max(float(triangle["height"]),entry-stop,float(regime_stats["atr"]))
                rationale=f"{triangle['type']}上轨回踩试错；下轨为结构防守"
            elif regime_state.startswith("📦"):
                box_range=float(regime_stats["box_high"]-regime_stats["box_low"])
                entry=float(regime_stats["box_low"]+.15*box_range); stop=float(regime_stats["box_low"]-.25*regime_stats["atr"]); geometry=box_range
                rationale="箱体下沿上方15%区域试错"
            target1=float(entry+geometry/3)
            level_cols=st.columns(3)
            level_cols[0].metric("买入试错位",f"${entry:,.2f}",rationale,delta_color="off")
            level_cols[1].metric("硬防守止损位",f"${stop:,.2f}","跌破则几何结构失效",delta_color="inverse")
            level_cols[2].metric("第一目标位 · 1/3",f"${target1:,.2f}","按识别结构高度的三分之一",delta_color="off")
            if regime_state.startswith("⚠️"):
                st.error("当前为趋势性空头破位：试错位仅作结构观察，等待价格重新站回 EMA50 且 ADX/DI 改善后再评估。")
            elif double_bottom and double_bottom["breakout"]:
                st.success(f"🔥 W底结构已站上颈线 ${double_bottom['neckline']:.2f}；Low2 ${double_bottom['low2']:.2f} 为结构防守位。")
            elif patterns.get("trend_breakout"):
                st.success("🚀 最新收盘价完成下降趋势线交叉突破；关注突破位回踩是否守住。")
            elif triangle and (triangle["breakout_up"] or triangle["breakout_down"]):
                direction="向上突破" if triangle["breakout_up"] else "向下破位"
                if triangle["breakout_up"]:
                    st.success(f"{triangle['type']}已{direction}；收敛边界与突破 K 线已在主图高亮。")
                else:
                    st.error(f"{triangle['type']}已{direction}；等待重新收复下轨或风险释放完成。")
            else:
                st.info("当前未确认新的几何突破；状态卡与水平位用于观察，不应单独作为交易指令。")
            st.caption("图表交互：拖动空白区域框选可同时缩放 X/Y 轴；拖动坐标轴刻度可单独缩放该轴；滚轮缩放，双击恢复完整历史。")
            st.caption("自动形态识别存在滞后和误判可能。杠杆 ETF 受每日再平衡、波动损耗与路径依赖影响，不能用基础 ETF 的长期倍数简单外推。")

with tab_fixed:
    section_header("RATES TERMINAL", "U.S. Treasury Yield Curve · 美债期限结构",
                   "Yahoo Finance 可稳定覆盖的 13周、5年、10年与30年收益率指数；变化单位为基点。")
    yield_rows = []
    curve_snapshots = {"LATEST": [], "1W AGO": [], "1M AGO": [], "YTD START": []}
    maturities = list(YIELD_TICKERS)
    tenor_years = {"3M": .25, "5Y": 5, "10Y": 10, "30Y": 30}
    for maturity, ticker in YIELD_TICKERS.items():
        s = prices[ticker].dropna() if ticker in prices else pd.Series(dtype=float)
        if s.empty:
            continue
        year_data = s[s.index.year == s.index[-1].year]
        latest = float(s.iloc[-1])
        week = float(s.iloc[-6]) if len(s) > 5 else np.nan
        month = float(s.iloc[-22]) if len(s) > 21 else np.nan
        ytd = float(year_data.iloc[0]) if not year_data.empty else np.nan
        curve_snapshots["LATEST"].append((tenor_years[maturity], maturity, latest))
        curve_snapshots["1W AGO"].append((tenor_years[maturity], maturity, week))
        curve_snapshots["1M AGO"].append((tenor_years[maturity], maturity, month))
        curve_snapshots["YTD START"].append((tenor_years[maturity], maturity, ytd))
        yield_rows.append({"Maturity":maturity,"Ticker":ticker,"Yield":latest,
                           "1D (bps)":value_change_bps(s,1),"1W (bps)":value_change_bps(s,5),
                           "1M (bps)":value_change_bps(s,21),
                           "YTD (bps)":float((latest-ytd)*100) if np.isfinite(ytd) else np.nan})

    yield_df = pd.DataFrame(yield_rows)
    rate_cards = st.columns(4)
    for col, maturity in zip(rate_cards, maturities):
        row = yield_df[yield_df["Maturity"] == maturity]
        if row.empty:
            col.metric(maturity, "N/A", delta_color="off")
        else:
            col.metric(f"UST {maturity}", f"{row.iloc[0]['Yield']:.3f}%",
                       f"{row.iloc[0]['1D (bps)']:+.1f} bps", help=YIELD_TICKERS[maturity])

    curve_col, history_col = st.columns(2, gap="medium")
    with curve_col:
        section_header("TERM STRUCTURE", "Yield Curve Snapshots", "最新、1周前、1月前和年初的四节点收益率曲线。")
        curve_fig = go.Figure()
        curve_colors = {"LATEST":"#f0a13a","1W AGO":"#287bc1","1M AGO":"#a4a9b0","YTD START":"#27914c"}
        for label, points in curve_snapshots.items():
            valid = sorted([p for p in points if np.isfinite(p[2])])
            if not valid:
                continue
            curve_fig.add_trace(go.Scatter(x=[p[0] for p in valid],y=[p[2] for p in valid],mode="lines+markers",
                name=label,line=dict(color=curve_colors[label],width=2),marker=dict(size=6),
                customdata=[p[1] for p in valid],hovertemplate=f"<b>{label}</b><br>%{{customdata}} · %{{y:.3f}}%<extra></extra>"))
        base_layout(curve_fig,420,"x unified")
        curve_fig.update_xaxes(title="Maturity",tickvals=[.25,5,10,30],ticktext=["3M","5Y","10Y","30Y"],type="log")
        curve_fig.update_yaxes(title="Yield %",ticksuffix="%")
        st.plotly_chart(curve_fig,use_container_width=True,config={"displaylogo":False})
    with history_col:
        section_header("RATES HISTORY", "Treasury Yields · 1Y", "关键期限收益率过去一年的联动与陡峭化变化。")
        history_fig = go.Figure()
        history_colors = {"3M":"#f0a13a","5Y":"#2987cf","10Y":"#a4a9b0","30Y":"#35a85d"}
        for maturity,ticker in YIELD_TICKERS.items():
            if ticker not in prices:
                continue
            s=prices[ticker].dropna().tail(252)
            if s.empty:
                continue
            history_fig.add_trace(go.Scatter(x=s.index,y=s,name=maturity,line=dict(color=history_colors[maturity],width=1.8),
                hovertemplate=f"<b>UST {maturity}</b><br>%{{x|%Y-%m-%d}}<br>%{{y:.3f}}%<extra></extra>"))
        base_layout(history_fig,420,"x unified")
        history_fig.update_yaxes(title="Yield %",ticksuffix="%")
        st.plotly_chart(history_fig,use_container_width=True,config={"displaylogo":False})

    section_header("LEVEL & CHANGE", "Treasury Yields · Level & Change", "红色表示收益率下行，绿色表示收益率上行。")
    if yield_df.empty:
        st.warning("本次未获得美债收益率指数数据。")
    else:
        yield_style=yield_df.style.format({"Yield":"{:.3f}%","1D (bps)":"{:+.1f}","1W (bps)":"{:+.1f}","1M (bps)":"{:+.1f}","YTD (bps)":"{:+.1f}"},na_rep="—").map(
            color_return,subset=["1D (bps)","1W (bps)","1M (bps)","YTD (bps)"])
        st.dataframe(yield_style,use_container_width=True,hide_index=True,height=220)

with tab_pulse:
    section_header("EVENT PULSE", "Breaking News & Market Data · 爆点新闻与数据", "新闻来自 Yahoo Finance；市场影响由可复现的价格、波动率、信用与广度规则评估。")
    signal_rows=[]
    spy=prices["SPY"].dropna(); spy200=spy.rolling(200,min_periods=200).mean().iloc[-1]
    spy_dist=(spy.iloc[-1]/spy200-1)*100
    signal_rows.append({"Indicator":"SPY vs 200DMA","Current":f"{spy_dist:+.2f}%","Signal":"利多" if spy_dist>0 else "利空",
                        "Score":1 if spy_dist>0 else -1,"Interpretation":"指数位于长期趋势线上方" if spy_dist>0 else "指数跌破长期趋势线"})
    if "^VIX" in prices and not prices["^VIX"].dropna().empty:
        vix=prices["^VIX"].dropna(); vix_now=float(vix.iloc[-1]); vix_day=last_return(vix,1)
        vix_score=1 if vix_now<20 and vix_day<=0 else (-1 if vix_now>25 or vix_day>8 else 0)
        signal_rows.append({"Indicator":"VIX","Current":f"{vix_now:.2f} ({vix_day:+.1f}% 1D)","Signal":{1:"利多",0:"中性",-1:"利空"}[vix_score],
                            "Score":vix_score,"Interpretation":"低波动 / 回落" if vix_score==1 else ("波动率压力上升" if vix_score==-1 else "波动率处于中间区间")})
    if all(t in prices for t in ["HYG","LQD"]):
        credit=prices["HYG"].div(prices["LQD"]); change=last_return(credit,20); score=1 if change>.3 else (-1 if change<-.3 else 0)
        signal_rows.append({"Indicator":"HYG / LQD Credit","Current":f"{change:+.2f}% 1M","Signal":{1:"利多",0:"中性",-1:"利空"}[score],"Score":score,
                            "Interpretation":"信用风险偏好改善" if score==1 else ("信用风险偏好走弱" if score==-1 else "信用环境平稳")})
    small_ratio=prices["IWM"].div(prices["SPY"]); small_change=last_return(small_ratio,20); score=1 if small_change>.5 else (-1 if small_change<-.5 else 0)
    signal_rows.append({"Indicator":"IWM / SPY Breadth","Current":f"{small_change:+.2f}% 1M","Signal":{1:"利多",0:"中性",-1:"利空"}[score],"Score":score,
                        "Interpretation":"小盘扩散、风险偏好改善" if score==1 else ("行情集中于大盘股" if score==-1 else "大小盘表现接近")})
    breadth_net=(sp_adv-sp_dec)/500*100 if sp_missing<500 else np.nan
    score=1 if np.isfinite(breadth_net) and breadth_net>15 else (-1 if np.isfinite(breadth_net) and breadth_net<-15 else 0)
    signal_rows.append({"Indicator":"S&P 500 Company Breadth","Current":"N/A" if not np.isfinite(breadth_net) else f"{breadth_net:+.1f}% net",
                        "Signal":{1:"利多",0:"中性",-1:"利空"}[score],"Score":score,
                        "Interpretation":"上涨公司明显占优" if score==1 else ("下跌公司明显占优" if score==-1 else "市场内部较均衡或数据不完整")})
    if all(t in prices for t in ["CPER","GLD"]):
        cyclical=prices["CPER"].div(prices["GLD"]); change=last_return(cyclical,20); score=1 if change>1 else (-1 if change<-1 else 0)
        signal_rows.append({"Indicator":"Copper / Gold","Current":f"{change:+.2f}% 1M","Signal":{1:"利多",0:"中性",-1:"利空"}[score],"Score":score,
                            "Interpretation":"周期预期升温" if score==1 else ("防御资产相对占优" if score==-1 else "宏观周期信号中性")})
    if "UUP" in prices:
        dollar_change=last_return(prices["UUP"],20); score=1 if dollar_change<-.7 else (-1 if dollar_change>.7 else 0)
        signal_rows.append({"Indicator":"U.S. Dollar · UUP","Current":f"{dollar_change:+.2f}% 1M","Signal":{1:"利多",0:"中性",-1:"利空"}[score],"Score":score,
                            "Interpretation":"美元回落缓解金融条件" if score==1 else ("美元走强压制风险资产" if score==-1 else "美元变化温和")})
    signal_df=pd.DataFrame(signal_rows)
    composite=int(signal_df["Score"].sum()); max_score=max(1,len(signal_df)); normalized=composite/max_score*100
    regime="RISK-ON · 偏利多" if normalized>=25 else ("RISK-OFF · 偏利空" if normalized<=-25 else "MIXED · 中性分化")
    pulse_cards=st.columns(4)
    pulse_cards[0].metric("COMPOSITE REGIME",regime,delta_color="off")
    pulse_cards[1].metric("SIGNAL SCORE",f"{composite:+d} / {max_score}",delta_color="off")
    pulse_cards[2].metric("SPY BREADTH",f"{sp_adv} A · {sp_dec} D",f"{sp_missing} missing",delta_color="off")
    pulse_cards[3].metric("VIX",f"{prices['^VIX'].dropna().iloc[-1]:.2f}" if "^VIX" in prices and not prices["^VIX"].dropna().empty else "N/A",delta_color="off")
    data_col,news_col=st.columns([.9,1.1],gap="medium")
    with data_col:
        section_header("DATA IMPACT", "Market Impact Matrix · 对股市影响", "绿色利多、红色利空、灰色中性；规则只反映当前数据状态。")
        impact_style=signal_df.drop(columns=["Score"]).style.map(
            lambda v:"color:#31d6a0;font-weight:700" if v=="利多" else ("color:#ff5874;font-weight:700" if v=="利空" else "color:#9aa8b9"),subset=["Signal"])
        st.dataframe(impact_style,use_container_width=True,hide_index=True,height=430)
    with news_col:
        section_header("BREAKING TAPE", "Market-Moving Headlines · 爆点新闻", "聚合 SPY、QQQ、VIX 与大型科技相关最新标题；点击标题打开原文。")
        try:
            news_df=load_market_news(("SPY","QQQ","^VIX","NVDA"),7)
        except Exception:
            news_df=pd.DataFrame()
        if news_df.empty:
            st.info("本次 Yahoo Finance 未返回新闻，稍后刷新即可重试。")
        else:
            st.dataframe(news_df[["Time","Source","Headline","URL"]],use_container_width=True,hide_index=True,height=430,
                column_config={"URL":st.column_config.LinkColumn("Open",display_text="↗ Read")})
    st.caption("自动解读依据市场代理指标而非自然语言情绪模型；突发新闻本身仍需阅读原文并核验发布时间。")

st.caption(f"DATA {latest_date:%Y-%m-%d} · SOURCE YAHOO FINANCE · ADJUSTED DAILY CLOSE · 1H CACHE · STATIC SECTOR / CONSTITUENT WEIGHTS ARE VISUAL PROXIES · FOR RESEARCH ONLY, NOT INVESTMENT ADVICE")
