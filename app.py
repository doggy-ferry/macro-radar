"""Buy-Side Macro Quant Portal — self-contained Streamlit dashboard."""
from __future__ import annotations

from datetime import date, datetime, time as dt_time, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed
from io import BytesIO, StringIO
from pathlib import Path
from urllib.request import Request, urlopen
import hmac
import hashlib
import html
import json
import re
import zipfile
from xml.etree import ElementTree as ET
import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import pytz
import requests
import streamlit as st
import streamlit.components.v1 as components
import yfinance as yf
from ui_theme import inject_theme, apply_quant_theme

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
AI_THEMES = {
    "宏观 11 大行业 ETF": ["XLK","XLE","XLI","XLY","XLC","XLF","XLV","XLP","XLU","XLRE","XLB","SMH"],
    "AI 算力与半导体龙头": ["NVDA","AMD","TSM","AVGO","ASML","MU"],
    "AI 物理基建 (电力/核能/液冷)": ["VST","CEG","CCJ","OKLO","VRT","ETN"],
    "关键资源与地缘避险": ["FCX","CPER","LMT","RTX","ITA","XLE"],
}
TACTICAL_NAMES = {
    "NVDA":"NVIDIA","AMD":"Advanced Micro Devices","TSM":"TSMC","AVGO":"Broadcom","ASML":"ASML Holding","MU":"Micron",
    "VST":"Vistra","CEG":"Constellation Energy","CCJ":"Cameco","OKLO":"Oklo","VRT":"Vertiv","ETN":"Eaton",
    "FCX":"Freeport-McMoRan","CPER":"Copper ETF","LMT":"Lockheed Martin","RTX":"RTX","ITA":"Aerospace & Defense ETF",
    "SMH":"Semiconductor ETF",
}
OPTION_POOL = ("QQQ","SPY","SMH","SOXX","NVDA","TSLA","MU","ITA","XLE")
LEVERAGED_ETFS = ("TQQQ","SOXL")
PRIMARY_FLOW_ETFS = {
    "TQQQ": {"label":"TQQQ (3x 纳指)","threshold":500_000_000.0,"class":"杠杆 ETF"},
    "SOXL": {"label":"SOXL (3x 半导体)","threshold":500_000_000.0,"class":"杠杆 ETF"},
    "QQQ": {"label":"QQQ (纳指基准)","threshold":1_500_000_000.0,"class":"基石 ETF"},
    "SPY": {"label":"SPY (标普基准)","threshold":1_500_000_000.0,"class":"基石 ETF"},
}
COLORS = {
    "XLK": "#40c4ff", "XLC": "#8b7cff", "XLY": "#ff8f5a", "XLI": "#b7c5d8", "XLE": "#00d7a3",
    "XLF": "#3a86ff", "XLV": "#ff4d76", "XLP": "#e6c85c", "XLU": "#5c7cfa", "XLRE": "#b985ff",
    "XLB": "#8bcf74", "SMH": "#ff3e68", "GLD": "#f3c94f", "SLV": "#c6d0dc", "USO": "#f26d4b",
    "CPER": "#d99152", "UUP": "#38bdf8", "TLT": "#a78bfa", "QQQ": "#ff8a3d",
}
with st.sidebar:
    theme_choice = st.selectbox(
        "🎨 终端皮肤风格 (Theme HUD)",
        ["Bloomberg Pro (买方经典)", "Cyberpunk 2077 (赛博朋克)", "Matrix Green (黑客终端)"],
        index=1,
        key="portal_theme_choice",
    )
inject_theme(st.session_state.portal_theme_choice)


@st.cache_data(ttl=900, show_spinner=False)
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


@st.cache_data(ttl=45,show_spinner=False)
def fetch_live_pulse() -> pd.DataFrame:
    """Lightweight intraday tape isolated from the 15-minute research cache."""
    symbols=("SPY","QQQ","IWM","^VIX"); eastern=pytz.timezone("US/Eastern")

    def close_panel(raw: pd.DataFrame) -> pd.DataFrame:
        if raw is None or raw.empty: return pd.DataFrame(columns=symbols)
        if isinstance(raw.columns,pd.MultiIndex):
            level0=raw.columns.get_level_values(0)
            panel=raw["Close"].copy() if "Close" in level0 else raw.xs("Close",axis=1,level=1).copy()
        else:
            panel=raw[["Close"]].copy(); panel.columns=[symbols[0]]
        if isinstance(panel,pd.Series): panel=panel.to_frame()
        return panel.reindex(columns=symbols).apply(pd.to_numeric,errors="coerce")

    try:
        minute_raw=yf.download(list(symbols),period="5d",interval="1m",prepost=True,auto_adjust=False,
                               progress=False,threads=True,group_by="column")
    except Exception:
        minute_raw=pd.DataFrame()
    try:
        daily_raw=yf.download(list(symbols),period="10d",interval="1d",auto_adjust=False,
                              progress=False,threads=True,group_by="column")
    except Exception:
        daily_raw=pd.DataFrame()
    minute,daily=close_panel(minute_raw),close_panel(daily_raw)
    rows=[]
    for symbol in symbols:
        intraday=minute[symbol].dropna() if symbol in minute else pd.Series(dtype=float)
        day=daily[symbol].dropna() if symbol in daily else pd.Series(dtype=float)
        latest=np.nan; previous=np.nan; stamp=pd.NaT
        if not intraday.empty:
            latest=float(intraday.iloc[-1]); stamp=pd.Timestamp(intraday.index[-1])
            if stamp.tzinfo is None: stamp=eastern.localize(stamp.to_pydatetime())
            else: stamp=stamp.tz_convert(eastern)
            day_dates=[pd.Timestamp(index).date() for index in day.index]
            if day_dates:
                previous=float(day.iloc[-2] if day_dates[-1]>=stamp.date() and len(day)>=2 else day.iloc[-1])
        elif not day.empty:
            latest=float(day.iloc[-1]); previous=float(day.iloc[-2]) if len(day)>=2 else np.nan
            stamp=pd.Timestamp(day.index[-1])
            stamp=eastern.localize(datetime.combine(stamp.date(),dt_time(16,0)))
        change=(latest/previous-1)*100 if np.isfinite(latest) and np.isfinite(previous) and previous!=0 else np.nan
        rows.append({"Ticker":"VIX" if symbol=="^VIX" else symbol,"YahooTicker":symbol,"Price":latest,
                     "ChangePct":change,"QuoteTimeET":stamp})
    return pd.DataFrame(rows).set_index("Ticker")


@st.cache_data(ttl=900, show_spinner=False)
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


@st.cache_data(ttl=900, show_spinner=False)
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


@st.cache_data(ttl=900,show_spinner=False)
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


@st.cache_data(ttl=900, show_spinner=False)
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


@st.cache_data(ttl=900,show_spinner=False)
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


def us_market_status(now_et: datetime | None = None) -> dict[str,str]:
    """US/Eastern session badge and countdown using weekday cash-session conventions."""
    eastern=pytz.timezone("US/Eastern")
    now=now_et or datetime.now(eastern)
    if now.tzinfo is None:
        now=eastern.localize(now)
    today=now.date(); clock=now.time().replace(tzinfo=None); weekday=now.weekday()
    pre_open,regular_open,regular_close,after_close=dt_time(4,0),dt_time(9,30),dt_time(16,0),dt_time(20,0)
    if weekday<5 and pre_open<=clock<regular_open:
        label,color,event="🟡 PRE-MARKET","#f6c453","距离开盘"
        target=eastern.localize(datetime.combine(today,regular_open))
    elif weekday<5 and regular_open<=clock<regular_close:
        label,color,event="🟢 MARKET OPEN","#31d6a0","距离收盘"
        target=eastern.localize(datetime.combine(today,regular_close))
    elif weekday<5 and regular_close<=clock<after_close:
        label,color,event="🔵 AFTER-HOURS","#4f86d9","距离下次开盘"
        next_day=today+timedelta(days=1)
        while next_day.weekday()>=5: next_day+=timedelta(days=1)
        target=eastern.localize(datetime.combine(next_day,regular_open))
    else:
        label,color,event="🔴 MARKET CLOSED","#697689","距离下次开盘"
        next_day=today if weekday<5 and clock<regular_open else today+timedelta(days=1)
        while next_day.weekday()>=5: next_day+=timedelta(days=1)
        target=eastern.localize(datetime.combine(next_day,regular_open))
    seconds=max(0,int((target-now).total_seconds())); hours,rem=divmod(seconds,3600); minutes=rem//60
    return {"label":label,"color":color,"time":now.strftime("%Y-%m-%d %H:%M ET"),
            "countdown":f"{event} {hours:02d}h {minutes:02d}m"}


@st.cache_data(ttl=900,show_spinner=False)
def load_option_snapshot(symbol: str,max_expiries: int=2,allow_saved_snapshot: bool=False) -> tuple[pd.DataFrame,float]:
    """Download 7-30 DTE option chains; individual expiries fail independently."""
    ticker=yf.Ticker(symbol); spot=np.nan
    try:
        spot=float(ticker.fast_info["last_price"])
    except Exception:
        try:
            history=ticker.history(period="5d",auto_adjust=True)
            spot=float(history["Close"].dropna().iloc[-1])
        except Exception:
            pass
    try:
        expiries=list(ticker.options or [])
    except Exception:
        expiries=[]
    today=datetime.now(pytz.timezone("US/Eastern")).date(); selected=[]
    for expiry in expiries:
        try:
            dte=(pd.Timestamp(expiry).date()-today).days
            if 7<=dte<=30: selected.append(expiry)
        except Exception:
            continue
    frames=[]
    for expiry in selected[:max(1,max_expiries)]:
        try:
            chain=ticker.option_chain(expiry)
            for option_type,source in (("Call",chain.calls),("Put",chain.puts)):
                frame=source.copy()
                if frame.empty: continue
                frame["Type"]=option_type; frame["Expiration"]=expiry
                frames.append(frame)
        except Exception:
            continue
    if not frames:
        if not allow_saved_snapshot:
            return pd.DataFrame(),spot
        try:
            saved=pd.read_csv(Path(__file__).resolve().parent/"data"/"options_chain_latest.csv")
            saved=saved[saved["Symbol"].eq(symbol)].copy()
            saved["SnapshotAtUTC"]=pd.to_datetime(saved["SnapshotAtUTC"],utc=True,errors="coerce")
            newest=saved["SnapshotAtUTC"].max()
            if pd.isna(newest) or pd.Timestamp.now(tz="UTC")-newest>pd.Timedelta(days=7):
                return pd.DataFrame(),spot
            saved=saved[saved["SnapshotAtUTC"].eq(newest)]
            saved["Expiration"]=saved["Expiration"].astype(str)
            saved=saved[pd.to_datetime(saved["Expiration"],errors="coerce").dt.date.ge(today)]
            saved=saved[saved["Expiration"].isin(sorted(saved["Expiration"].unique())[:max(1,max_expiries)])]
            if saved.empty: return pd.DataFrame(),spot
            for column in ("strike","volume","openInterest","impliedVolatility","bid","ask","lastPrice"):
                saved[column]=pd.to_numeric(saved[column],errors="coerce")
            spot=float(pd.to_numeric(saved["SpotAtCapture"],errors="coerce").dropna().iloc[-1])
            saved.attrs["source"]="SAVED SNAPSHOT"
            saved.attrs["asof_utc"]=newest.isoformat()
            return saved,spot
        except (OSError,KeyError,ValueError,IndexError,pd.errors.ParserError):
            return pd.DataFrame(),spot
    result=pd.concat(frames,ignore_index=True)
    for column in ("strike","volume","openInterest","impliedVolatility","bid","ask","lastPrice"):
        if column not in result: result[column]=np.nan
        result[column]=pd.to_numeric(result[column],errors="coerce")
    result.attrs["source"]="LIVE YAHOO"
    result.attrs["asof_utc"]=pd.Timestamp.now(tz="UTC").isoformat()
    return result,spot


def unusual_option_rows(chain: pd.DataFrame,spot: float,ratio_floor: float=1.5,volume_floor: int=1000,
                        moneyness_limit: float=.20) -> pd.DataFrame:
    if chain.empty or not np.isfinite(spot):
        return pd.DataFrame(columns=["Expiration","Strike","Moneyness","Type","Vol","OI","Vol/OI","IV","Signal"])
    data=chain.copy(); data["volume"]=data["volume"].fillna(0); data["openInterest"]=data["openInterest"].fillna(0)
    data["Vol/OI"]=data["volume"].div(data["openInterest"].replace(0,np.nan))
    data["Moneyness"]=data["strike"].sub(spot).div(spot).mul(100)
    otm=((data["Type"]=="Call")&(data["strike"]>spot))|((data["Type"]=="Put")&(data["strike"]<spot))
    near_spot=data["strike"].sub(spot).abs().div(spot)<=moneyness_limit
    data=data[otm&near_spot&(data["volume"]>=volume_floor)&(data["Vol/OI"]>=ratio_floor)].copy()
    if data.empty:
        return pd.DataFrame(columns=["Expiration","Strike","Moneyness","Type","Vol","OI","Vol/OI","IV","Signal"])
    data["Signal"]=np.where(data["Type"].eq("Call"),"🔥 OTM Call 异动","🛡️ OTM Put 异动")
    data["IV"]=data["impliedVolatility"]*100
    data=data.rename(columns={"strike":"Strike","volume":"Vol","openInterest":"OI"})
    return data[["Expiration","Strike","Moneyness","Type","Vol","OI","Vol/OI","IV","Signal"]].sort_values(["Vol/OI","Vol"],ascending=False)


def continuation_price_diagnostics(ohlcv: pd.DataFrame) -> dict:
    """Diagnose whether a recent high-volume breakout is holding through consolidation."""
    empty={"detected":False,"reason":"过去 10 个交易日未检测到 RVOL ≥ 2.0 且涨幅 ≥ 3% 的放量突破。"}
    required={"High","Low","Close","Volume"}
    if ohlcv is None or ohlcv.empty or not required.issubset(ohlcv.columns):
        return empty
    data=ohlcv[list(required)].apply(pd.to_numeric,errors="coerce").sort_index()
    data=data.dropna(subset=["High","Low","Close","Volume"])
    data=data[data["Volume"]>0]
    if len(data)<22:
        return {"detected":False,"reason":"有效 OHLCV 历史不足 22 个交易日，无法计算突破量比。"}

    data["Return"]=data["Close"].pct_change()
    # Exclude the event day from the denominator so RVOL is not diluted by itself.
    data["AvgVolume20"]=data["Volume"].shift(1).rolling(20,min_periods=10).mean()
    data["RVOL"]=data["Volume"].div(data["AvgVolume20"].replace(0,np.nan))
    candidates=data.tail(10)
    candidates=candidates[(candidates["RVOL"]>=2.0)&(candidates["Return"]>=.03)]
    if candidates.empty:
        return empty

    anchor=pd.Timestamp(candidates.index[-1])
    anchor_loc=int(data.index.get_loc(anchor)); anchored=data.loc[anchor:].copy()
    typical=(anchored["High"]+anchored["Low"]+anchored["Close"])/3
    cumulative_volume=anchored["Volume"].cumsum().replace(0,np.nan)
    avwap=typical.mul(anchored["Volume"]).cumsum().div(cumulative_volume)
    latest_price=float(data["Close"].iloc[-1]); latest_avwap=float(avwap.iloc[-1])
    ema20=data["Close"].ewm(span=20,adjust=False,min_periods=20).mean()
    latest_ema20=float(ema20.iloc[-1]) if np.isfinite(ema20.iloc[-1]) else np.nan
    ema_distance=abs(latest_price/latest_ema20-1)*100 if np.isfinite(latest_ema20) and latest_ema20 else np.nan
    breakout_volume=float(data.loc[anchor,"Volume"])
    post_volume=data.loc[anchor:,"Volume"].iloc[1:]
    dryup=float(post_volume.mean()/breakout_volume) if len(post_volume) and breakout_volume else np.nan
    avwap_pass=bool(latest_price>=latest_avwap)
    dryup_pass=bool(np.isfinite(dryup) and dryup<=.45)
    ema_pass=bool(np.isfinite(ema_distance) and ema_distance<=2.5)

    avwap_label="🟢 守住机构成本线" if avwap_pass else "🚨 跌破机构底线"
    if not np.isfinite(dryup):
        dryup_label="⏳ 突破刚发生，等待缩量样本"
    elif dryup<=.45:
        dryup_label="🟢 筹码高度锁仓 (成交量极度萎缩)"
    elif dryup>.70:
        dryup_label="⚠️ 放量滞涨 (警惕派发)"
    else:
        dryup_label="🟡 温和缩量，继续观察"
    if not np.isfinite(ema_distance):
        ema_label="⚪ EMA20 数据不足"
    elif ema_distance<=2.5:
        ema_label="🟢 均线回踩到位 (蓄势待发)"
    elif ema_distance>6:
        ema_label="⏳ 乖离过大 (仍在等待均线)"
    else:
        ema_label="🟡 均线靠拢中"
    return {
        "detected":True,"anchor":anchor,"days_since":len(data)-1-anchor_loc,
        "breakout_return":float(data.loc[anchor,"Return"]*100),"breakout_rvol":float(data.loc[anchor,"RVOL"]),
        "price":latest_price,"avwap":latest_avwap,"avwap_series":avwap,"avwap_pass":avwap_pass,
        "dryup":dryup,"dryup_pass":dryup_pass,"ema20":latest_ema20,"ema_distance":ema_distance,
        "ema_pass":ema_pass,"avwap_label":avwap_label,"dryup_label":dryup_label,"ema_label":ema_label,
    }


def continuation_option_oi_carry(symbol: str,chain: pd.DataFrame,spot: float) -> dict:
    """Compare near-spot unusual Call OI across locally observed ET-date snapshots.

    Yahoo exposes only current OI, not historical OI. This condition is counted only
    after the session has observed the same contracts on at least two different ET dates.
    """
    neutral={"passed":None,"label":"⚪ OI 净增待次日快照确认","detail":"Yahoo 无历史 OI；首次观测不计分"}
    if chain is None or chain.empty or not np.isfinite(spot):
        return {"passed":None,"label":"⚪ 期权链不可用","detail":"本次抓取未返回 7–30 DTE 合约"}
    data=chain.copy()
    for column in ("strike","volume","openInterest"):
        if column not in data: data[column]=np.nan
        data[column]=pd.to_numeric(data[column],errors="coerce")
    calls=data[(data.get("Type")=="Call")&(data["strike"]>=spot)&(data["strike"]<=spot*1.15)].copy()
    if calls.empty:
        return {"passed":None,"label":"⚪ 无近月近价 Call","detail":"现价上方 15% 内没有可跟踪合约"}
    calls["volume"]=calls["volume"].fillna(0); calls["openInterest"]=calls["openInterest"].fillna(0)
    calls["Vol/OI"]=calls["volume"].div(calls["openInterest"].replace(0,np.nan))
    unusual=calls[(calls["volume"]>=500)&(calls["Vol/OI"]>=1.5)]

    def contract_key(row: pd.Series) -> str:
        raw=row.get("contractSymbol")
        if pd.notna(raw) and str(raw): return str(raw)
        return f"{row.get('Expiration','')}|{float(row['strike']):.3f}"

    current_map={contract_key(row):float(row["openInterest"]) for _,row in calls.iterrows()}
    watch=[contract_key(row) for _,row in unusual.iterrows()]
    et_day=datetime.now(pytz.timezone("US/Eastern")).date().isoformat()
    history=st.session_state.setdefault("_continuation_oi_history",{})
    symbol_history=history.setdefault(symbol,{})
    symbol_history[et_day]={"oi":current_map,"watch":watch}
    for old_day in sorted(symbol_history)[:-4]:
        symbol_history.pop(old_day,None)
    observed_days=sorted(symbol_history)
    if len(observed_days)<2:
        if watch:
            neutral["detail"]=f"已建立 {len(watch)} 张异动 Call 合约基线，待下一交易日复核"
        else:
            neutral["detail"]="今日未发现 Vol/OI ≥ 1.5 且 Vol ≥ 500 的近价 Call"
        return neutral
    prior=symbol_history[observed_days[-2]]; current=symbol_history[observed_days[-1]]
    tracked=set(prior.get("watch",[])); common=tracked.intersection(current.get("oi",{}))
    if not common:
        return {"passed":None,"label":"⚪ OI Carry 暂不可比","detail":"前一快照异动合约已到期或未返回"}
    delta=sum(current["oi"][key]-prior["oi"].get(key,0) for key in common)
    if delta>0:
        return {"passed":True,"label":"🟢 异动 Call OI 沉淀确认","detail":f"同合约 OI 净增 {delta:,.0f} 张"}
    return {"passed":False,"label":"⚠️ Call OI 未沉淀","detail":f"同合约 OI 变化 {delta:,.0f} 张"}


@st.cache_data(ttl=900,show_spinner=False)
def load_theme_option_uoa(symbols: tuple[str,...]) -> pd.DataFrame:
    """Scan one selected theme; a failure in one ticker/expiry never blocks the table."""
    rows=[]
    for symbol in symbols:
        try:
            chain,spot=load_option_snapshot(symbol,8)
            unusual=unusual_option_rows(chain,spot,ratio_floor=1.5,volume_floor=500,moneyness_limit=.15)
            if unusual.empty: continue
            unusual.insert(0,"Ticker",symbol)
            unusual["Signal"]=np.where(unusual["Type"].eq("Call"),
                "🔥 近虚值 Call 抢筹候选","🛡️ 近虚值 Put 防守候选")
            rows.append(unusual)
        except Exception:
            continue
    if not rows:
        return pd.DataFrame(columns=["Ticker","Expiration","Strike","Moneyness","Type","Vol","OI","Vol/OI","Signal"])
    result=pd.concat(rows,ignore_index=True)
    return result[["Ticker","Expiration","Strike","Moneyness","Type","Vol","OI","Vol/OI","Signal"]].sort_values(
        ["Vol/OI","Vol"],ascending=False).reset_index(drop=True)


def theme_tactical_scoreboard(price_frame: pd.DataFrame,ohlcv: pd.DataFrame,tickers: list[str],benchmark: str) -> pd.DataFrame:
    """Cross-sectional price, relative-strength regime and relative-volume snapshot."""
    rows=[]
    for ticker in tickers:
        if ticker not in price_frame or benchmark not in price_frame: continue
        pair=price_frame[[ticker,benchmark]].dropna()
        if len(pair)<200: continue
        ratio=pair[ticker].div(pair[benchmark]).replace([np.inf,-np.inf],np.nan).dropna()
        if len(ratio)<200: continue
        latest=float(ratio.iloc[-1]); ema20=float(ratio.ewm(span=20,adjust=False).mean().iloc[-1])
        ema50=float(ratio.ewm(span=50,adjust=False).mean().iloc[-1]); sma200=float(ratio.rolling(200,min_periods=200).mean().iloc[-1])
        d20=(latest/ema20-1)*100 if ema20 else np.nan; d50=(latest/ema50-1)*100 if ema50 else np.nan
        above20,above50,above200=latest>ema20,latest>ema50,latest>sma200
        if above20 and above50 and above200: regime="🔥 绝对强势"
        elif above20 and above50: regime="⚡ 超跌反弹"
        elif above200: regime="⚠️ 强势回调"
        else: regime="❄️ 弱势破位"
        close=pair[ticker].dropna(); price=float(close.iloc[-1]); day_return=last_return(close,1)
        rvol=np.nan
        try:
            ticker_frame=ohlcv[ticker].dropna(subset=["Close"]) if ticker in ohlcv.columns.get_level_values(0) else pd.DataFrame()
            volume=pd.to_numeric(ticker_frame.get("Volume"),errors="coerce").dropna()
            if len(volume)>=21 and float(volume.iloc[-21:-1].mean())>0:
                rvol=float(volume.iloc[-1]/volume.iloc[-21:-1].mean())
        except Exception:
            pass
        rows.append({
            "Ticker":f"{ticker} · {TACTICAL_NAMES.get(ticker,SECTORS.get(ticker,(ticker,ticker,0))[1])}",
            "Price":f"${price:,.2f} · {day_return:+.2f}%" if np.isfinite(day_return) else f"${price:,.2f}",
            "RS vs 20EMA":f"{'🟢 Above' if above20 else '🔴 Below'} ({d20:+.2f}%)",
            "RS vs 50EMA":f"{'🟢 Above' if above50 else '🔴 Below'} ({d50:+.2f}%)",
            "RVOL (20D)":f"🔥 异常放量 · {rvol:.2f}x" if np.isfinite(rvol) and rvol>=1.8 else (f"{rvol:.2f}x" if np.isfinite(rvol) else "N/A"),
            "Regime 状态定性":regime,
            "_MomentumScore":float(np.nan_to_num(d20)+np.nan_to_num(d50)+np.nan_to_num(day_return)*.25),
            "_RVOL":rvol,
        })
    return pd.DataFrame(rows)


def option_skew_proxy(chain: pd.DataFrame,spot: float) -> tuple[float,pd.DataFrame]:
    """±4% OTM IV ratio proxy; Yahoo's public chain does not include option delta."""
    if chain.empty or not np.isfinite(spot): return np.nan,pd.DataFrame()
    nearest_expiry=sorted(chain["Expiration"].dropna().astype(str).unique())[0]
    subset=chain[chain["Expiration"].astype(str).eq(nearest_expiry)].copy()
    calls=subset[subset["Type"].eq("Call")].dropna(subset=["strike","impliedVolatility"])
    puts=subset[subset["Type"].eq("Put")].dropna(subset=["strike","impliedVolatility"])
    if calls.empty or puts.empty: return np.nan,pd.DataFrame()
    call_row=calls.iloc[(calls["strike"]-spot*1.04).abs().argsort()[:1]]
    put_row=puts.iloc[(puts["strike"]-spot*.96).abs().argsort()[:1]]
    put_iv=float(put_row["impliedVolatility"].iloc[0]); call_iv=float(call_row["impliedVolatility"].iloc[0])
    ratio=call_iv/put_iv if put_iv>0 else np.nan
    curve=subset[subset["strike"].between(spot*.75,spot*1.25)].copy()
    return ratio,curve


FLOW_RECORD_COLUMNS=["date","shares_outstanding","nav","source_url","source_note"]


def _normalise_flow_records(frame: pd.DataFrame) -> pd.DataFrame:
    """Return a strict, duplicate-free issuer record table; malformed rows are ignored."""
    if frame is None or frame.empty: return pd.DataFrame(columns=FLOW_RECORD_COLUMNS)
    clean=frame.copy()
    for column in FLOW_RECORD_COLUMNS:
        if column not in clean: clean[column]=""
    clean["date"]=pd.to_datetime(clean["date"],errors="coerce").dt.tz_localize(None).dt.normalize()
    clean["shares_outstanding"]=pd.to_numeric(clean["shares_outstanding"],errors="coerce")
    clean["nav"]=pd.to_numeric(clean["nav"],errors="coerce")
    clean=clean.dropna(subset=["date","shares_outstanding","nav"])
    clean=clean[clean["shares_outstanding"].gt(0)&clean["nav"].gt(0)]
    return clean[FLOW_RECORD_COLUMNS].sort_values("date").drop_duplicates("date",keep="last").reset_index(drop=True)


def _read_baseline_records(symbol: str) -> pd.DataFrame:
    data_dir=Path(__file__).resolve().parent/"data"; frames=[]
    for path in (data_dir/f"{symbol.lower()}_shares_baseline.csv",
                 data_dir/f"{symbol.lower()}_historical_shares.csv",
                 data_dir/f"{symbol.lower()}_flow_history.csv"):
        try:
            if path.exists() and path.stat().st_size:
                frames.append(pd.read_csv(path))
        except Exception:
            continue
    json_path=data_dir/f"{symbol.lower()}_shares_baseline.json"
    try:
        if json_path.exists():
            payload=json.loads(json_path.read_text(encoding="utf-8"))
            frames.append(pd.DataFrame(payload.get("records",payload) if isinstance(payload,dict) else payload))
    except Exception:
        pass
    return _normalise_flow_records(pd.concat(frames,ignore_index=True) if frames else pd.DataFrame())


def _xlsx_first_sheet(payload: bytes) -> list[list[object]]:
    """Small dependency-free XLSX reader used for State Street's public SPY workbook."""
    namespace="{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
    with zipfile.ZipFile(BytesIO(payload)) as archive:
        shared=[]
        if "xl/sharedStrings.xml" in archive.namelist():
            root=ET.fromstring(archive.read("xl/sharedStrings.xml"))
            for item in root.findall(f"{namespace}si"):
                shared.append("".join(node.text or "" for node in item.iter(f"{namespace}t")))
        sheet_name=next((name for name in archive.namelist() if name.startswith("xl/worksheets/sheet") and name.endswith(".xml")),None)
        if not sheet_name: return []
        root=ET.fromstring(archive.read(sheet_name)); rows=[]
        for row in root.iter(f"{namespace}row"):
            values=[]
            for cell in row.findall(f"{namespace}c"):
                ref=cell.attrib.get("r","A1"); letters="".join(ch for ch in ref if ch.isalpha())
                column=0
                for letter in letters: column=column*26+ord(letter.upper())-64
                while len(values)<column: values.append(None)
                node=cell.find(f"{namespace}v"); value=node.text if node is not None else None
                if cell.attrib.get("t")=="s" and value is not None:
                    try: value=shared[int(value)]
                    except Exception: pass
                elif cell.attrib.get("t")=="inlineStr":
                    value="".join(item.text or "" for item in cell.iter(f"{namespace}t"))
                values[column-1]=value
            rows.append(values)
        return rows


def _deep_find_number(obj: object, names: set[str]) -> float:
    if isinstance(obj,dict):
        for key,value in obj.items():
            normal=re.sub(r"[^a-z]","",str(key).lower())
            if normal in names:
                try: return float(str(value).replace(",","").replace("$",""))
                except Exception: pass
        for value in obj.values():
            found=_deep_find_number(value,names)
            if np.isfinite(found): return found
    elif isinstance(obj,list):
        for value in obj:
            found=_deep_find_number(value,names)
            if np.isfinite(found): return found
    return np.nan


@st.cache_data(ttl=900,show_spinner=False)
def fetch_issuer_flow_records(symbol: str) -> pd.DataFrame:
    """Fetch only issuer-published NAV/share observations; no price-volume proxy."""
    symbol=symbol.upper().strip(); headers={"User-Agent":"Mozilla/5.0 (compatible; BuySideQuantPortal/1.0)"}
    try:
        if symbol=="TQQQ":
            url="https://accounts.profunds.com/etfdata/ByFund/TQQQ-historical_nav.csv"
            raw=pd.read_csv(StringIO(urlopen(Request(url,headers=headers),timeout=20).read().decode("utf-8-sig",errors="replace")))
            return _normalise_flow_records(pd.DataFrame({
                "date":raw.get("Date"),"shares_outstanding":pd.to_numeric(raw.get("Shares Outstanding (000)"),errors="coerce")*1000,
                "nav":raw.get("NAV"),"source_url":url,"source_note":"ProShares official daily NAV file",
            }))
        if symbol=="SPY":
            url="https://www.ssga.com/library-content/products/fund-data/etfs/us/navhist-us-en-spy.xlsx"
            rows=_xlsx_first_sheet(urlopen(Request(url,headers=headers),timeout=25).read())
            header_index=next((i for i,row in enumerate(rows) if row and str(row[0]).strip().lower()=="date"),None)
            if header_index is None: return pd.DataFrame(columns=FLOW_RECORD_COLUMNS)
            header=[str(item).strip() if item is not None else "" for item in rows[header_index]]
            raw=pd.DataFrame(rows[header_index+1:],columns=header)
            return _normalise_flow_records(pd.DataFrame({
                "date":raw.get("Date"),"shares_outstanding":raw.get("Shares Outstanding"),"nav":raw.get("NAV"),
                "source_url":url,"source_note":"State Street official SPY NAV history",
            }))
        if symbol=="SOXL":
            url="https://www.direxion.com/product/daily-semiconductor-bull-bear-3x-etfs"
            page=urlopen(Request(url,headers=headers),timeout=25).read().decode("utf-8",errors="replace")
            match=re.search(r'<script[^>]+id=["\']__NEXT_DATA__["\'][^>]*>(.*?)</script>',page,re.S|re.I)
            payload=json.loads(html.unescape(match.group(1))) if match else {}
            candidates=[]
            def collect(item: object) -> None:
                if isinstance(item,dict):
                    if str(item.get("Ticker",item.get("ticker",""))).upper()=="SOXL": candidates.append(item)
                    for value in item.values(): collect(value)
                elif isinstance(item,list):
                    for value in item: collect(value)
            collect(payload)
            fund=candidates[0] if candidates else {}
            shares=_deep_find_number(fund,{"sharesoutstanding","outstandingshares"})
            nav=_deep_find_number(fund,{"nav","netassetvalue"})
            raw_date=str(fund.get("Pricing",{}).get("TradeDate",fund.get("TradeDate",""))) if isinstance(fund,dict) else ""
            observed=pd.to_datetime(raw_date,format="%m%d%Y",errors="coerce")
            if np.isfinite(shares) and np.isfinite(nav) and pd.notna(observed):
                return _normalise_flow_records(pd.DataFrame([{"date":observed,"shares_outstanding":shares,"nav":nav,
                    "source_url":url,"source_note":"Direxion official product page"}]))
        if symbol=="QQQ":
            url=("https://dng-api.invesco.com/cache/v1/accounts/en_US/shareclasses/46090E103/prices"
                 "?idType=cusip&productType=ETF&variationType=priceListing&productSubType=ETF")
            api_headers={**headers,"User-Agent":"BuySideQuantPortal/1.0"}
            payload=json.loads(urlopen(Request(url,headers=api_headers),timeout=25).read().decode("utf-8",errors="replace"))
            return _normalise_flow_records(pd.DataFrame([{
                "date":payload.get("effectiveDate"),"shares_outstanding":payload.get("sharesOutstanding"),
                "nav":payload.get("nav"),"source_url":url,"source_note":"Invesco official QQQ prices API",
            }]))
    except Exception:
        pass
    return pd.DataFrame(columns=FLOW_RECORD_COLUMNS)


def _persist_latest_flow_record(symbol: str, records: pd.DataFrame) -> str:
    """Atomically append a new issuer observation; cloud ephemeral files fail safely."""
    if records.empty: return "NO NEW ISSUER SHARE RECORD"
    path=Path(__file__).resolve().parent/"data"/f"{symbol.lower()}_flow_history.csv"
    try:
        path.parent.mkdir(parents=True,exist_ok=True)
        existing=pd.read_csv(path) if path.exists() and path.stat().st_size else pd.DataFrame(columns=FLOW_RECORD_COLUMNS)
        combined=_normalise_flow_records(pd.concat([existing,records.tail(1)],ignore_index=True))
        if not existing.empty and len(combined)==len(_normalise_flow_records(existing)):
            return "LOCAL LOGGER CURRENT"
        temporary=path.with_suffix(".csv.tmp")
        combined.to_csv(temporary,index=False,date_format="%Y-%m-%d")
        temporary.replace(path)
        return "LOCAL LOGGER UPDATED"
    except Exception as exc:
        return f"LOGGER READ-ONLY / {type(exc).__name__}"


@st.cache_data(ttl=900,show_spinner=False)
def load_primary_flow(symbol: str) -> pd.DataFrame:
    """Merge verified baselines, issuer updates and price, assigning zero to missing record dates."""
    symbol=symbol.upper().strip(); end=date.today()+timedelta(days=1); start=end-timedelta(days=550)
    try:
        history=yf.Ticker(symbol).history(start=start,end=end,auto_adjust=True)[["Close"]].dropna(subset=["Close"])
    except Exception:
        history=pd.DataFrame()
    if history.empty: return pd.DataFrame()
    history.index=pd.to_datetime(history.index)
    if history.index.tz is not None: history.index=history.index.tz_convert(None)
    history=history.groupby(history.index.normalize()).last().sort_index()

    baseline=_read_baseline_records(symbol); live=fetch_issuer_flow_records(symbol)
    logger_status=_persist_latest_flow_record(symbol,live)
    logged=_read_baseline_records(symbol)
    records=_normalise_flow_records(pd.concat([baseline,logged,live],ignore_index=True))
    if not records.empty: records=records.set_index("date")

    data=history.copy(); data["HasOfficialRecord"]=data.index.isin(records.index) if not records.empty else False
    if records.empty:
        data["Shares"]=np.nan; data["NAV"]=np.nan; data["DailyFlow"]=0.0
        data["Source"]="NO VERIFIED ISSUER SHARES DATA"; data["OfficialAsOf"]=pd.NaT
        data["HasVerifiedShares"]=False; data["LoggerStatus"]=logger_status; data["RecordCount"]=0
        return data.tail(180)

    data["Shares"]=records["shares_outstanding"].reindex(data.index).ffill()
    data["NAV"]=records["nav"].reindex(data.index)
    prior_nav=records["nav"].shift(1)
    reported_delta=records["shares_outstanding"].diff()
    # A sparse baseline must never collapse weeks/months of creations into one fake daily spike.
    adjacent=records.index.to_series().diff().dt.days.le(5)
    record_flow=(reported_delta*prior_nav).where(adjacent,0.0)
    data["DailyFlow"]=record_flow.reindex(data.index).where(data["HasOfficialRecord"],0.0).fillna(0.0)
    data["OfficialAsOf"]=records.index.max(); data["HasVerifiedShares"]=True
    source_notes=records["source_note"].dropna().astype(str); source_notes=source_notes[source_notes.str.len().gt(0)]
    data["Source"]=" + ".join(dict.fromkeys(source_notes.tail(4))) or "LOCAL VERIFIED BASELINE"
    data["LoggerStatus"]=logger_status; data["RecordCount"]=len(records)
    return data.dropna(subset=["Close"]).tail(180)


def sector_rs_scoreboard(price_frame: pd.DataFrame) -> pd.DataFrame:
    rows=[]
    for ticker,(name,cn_name,_) in SECTORS.items():
        if ticker not in price_frame: continue
        pair=price_frame[[ticker,"SPY"]].dropna(); ratio=pair[ticker].div(pair["SPY"])
        if len(ratio)<200: continue
        latest=float(ratio.iloc[-1]); ma20=float(ratio.ewm(span=20,adjust=False).mean().iloc[-1])
        ma50=float(ratio.ewm(span=50,adjust=False).mean().iloc[-1]); ma200=float(ratio.rolling(200).mean().iloc[-1])
        above20,above50,above200=latest>ma20,latest>ma50,latest>ma200
        if above20 and above50 and above200: regime="🔥 绝对强势"
        elif above20 and above50 and not above200: regime="⚡ 超跌反弹"
        elif not above20 and not above50 and above200: regime="⚠️ 强势回调"
        elif not above20 and not above50 and not above200: regime="❄️ 弱势破位"
        else: regime="🔄 均线过渡"
        rows.append({"Sector":f"{name} · {cn_name}","ETF":ticker,"RS vs 20EMA":(latest/ma20-1)*100,
                     "RS vs 50EMA":(latest/ma50-1)*100,"RS vs 200SMA":(latest/ma200-1)*100,"Regime 定性":regime})
    return pd.DataFrame(rows)


def rrg_improving_crossovers(price_frame: pd.DataFrame,tickers: list[str],benchmark: str="SPY") -> list[str]:
    transitions=[]
    if benchmark not in price_frame: return transitions
    for ticker in tickers:
        if ticker not in price_frame: continue
        frame=rrg_frame(price_frame[ticker],price_frame[benchmark]).tail(4)
        if len(frame)<4: continue
        current=frame.iloc[-1]; prior=frame.iloc[:-1]
        if current["rs_ratio"]<100 and current["rs_momentum"]>100 and ((prior["rs_ratio"]<100)&(prior["rs_momentum"]<100)).any():
            transitions.append(ticker)
    return transitions


def circuit_breaker_state(price_frame: pd.DataFrame) -> dict[str,object]:
    broken=[]
    for ticker in ("SPY","QQQ"):
        s=price_frame[ticker].dropna() if ticker in price_frame else pd.Series(dtype=float)
        sma=s.rolling(200,min_periods=200).mean()
        if not sma.dropna().empty and float(s.iloc[-1])<float(sma.iloc[-1]): broken.append(ticker)
    credit_warning=False; credit_change=np.nan
    if {"HYG","LQD"}.issubset(price_frame.columns):
        credit=price_frame[["HYG","LQD"]].dropna(); ratio=credit["HYG"].div(credit["LQD"])
        if len(ratio)>=50:
            credit_change=last_return(ratio,20); credit_warning=bool(ratio.iloc[-1]<ratio.rolling(50).mean().iloc[-1] and credit_change<0)
    vix_ratio=np.nan
    if {"^VIX","^VIX3M"}.issubset(price_frame.columns):
        vix_pair=price_frame[["^VIX","^VIX3M"]].dropna()
        if not vix_pair.empty and vix_pair.iloc[-1,1]>0: vix_ratio=float(vix_pair.iloc[-1,0]/vix_pair.iloc[-1,1])
    return {"broken":broken,"credit_warning":credit_warning,"credit_change":credit_change,
            "vix_ratio":vix_ratio,"vix_inverted":bool(np.isfinite(vix_ratio) and vix_ratio>=1)}


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


def _secret(name: str, fallback: str = "") -> str:
    """Read an optional Streamlit secret without requiring a local secrets.toml."""
    try:
        return str(st.secrets.get(name,fallback))
    except Exception:
        return fallback


def send_webhook_notification(channel: str, message: str, webhook_url: str = "",
                              bot_token: str = "", chat_id: str = "") -> tuple[bool,str]:
    """Send one short notification; credentials never enter cache or disk."""
    try:
        if channel == "Telegram Bot":
            if not bot_token.strip() or not chat_id.strip():
                return False,"请填写 Bot Token 与 Chat ID。"
            endpoint=f"https://api.telegram.org/bot{bot_token.strip()}/sendMessage"
            response=requests.post(endpoint,json={"chat_id":chat_id.strip(),"text":message,
                "parse_mode":"Markdown","disable_web_page_preview":True},timeout=3)
        elif channel == "Discord Webhook":
            if not webhook_url.strip(): return False,"请填写 Webhook URL。"
            response=requests.post(webhook_url.strip(),json={"username":"Buy-Side Quant Portal",
                "embeds":[{"title":"◈ QUANT ALERT CENTER","description":message,"color":15158332,
                           "footer":{"text":"Automated research signal · Not investment advice"}}]},timeout=3)
        else:
            if not webhook_url.strip(): return False,"请填写 Webhook URL。"
            url=webhook_url.strip()
            if "open.feishu.cn" in url or "larksuite.com" in url:
                payload={"msg_type":"text","content":{"text":message}}
            else:
                payload={"text":message,"content":message,"message":message}
            response=requests.post(url,json=payload,timeout=3)
        response.raise_for_status()
        return True,f"HTTP {response.status_code} · 推送成功"
    except requests.RequestException as exc:
        status=getattr(getattr(exc,"response",None),"status_code",None)
        return False,f"推送失败"+(f"（HTTP {status}）" if status else "（网络超时或地址不可达）")
    except Exception:
        return False,"推送失败（配置格式无效）"


def evaluate_market_alerts(breaker_state: dict[str,object], flows: dict[str,pd.DataFrame],
                           skews: dict[str,float], option_data: dict[str,tuple[pd.DataFrame,float]],
                           improving_names: list[str], asof: object) -> list[dict[str,object]]:
    """Central, deterministic alert matrix used by the briefing and webhook dispatcher."""
    alerts=[]; asof_text=str(pd.Timestamp(asof).date()) if pd.notna(asof) else str(date.today())
    def add(level: int, category: str, message: str) -> None:
        identity=f"{asof_text}|{level}|{category}|{message}"
        alerts.append({"ID":hashlib.sha256(identity.encode("utf-8")).hexdigest()[:18],
            "Level":level,"Severity":{1:"🚨 L1 · CIRCUIT BREAKER",2:"🔥 L2 · HIGH CONVICTION",3:"⚡ L3 · TACTICAL"}[level],
            "Category":category,"Message":message,"As Of":asof_text})
    broken=list(breaker_state.get("broken",[]) or [])
    if broken: add(1,"200 SMA TREND LOCK",f"{', '.join(broken)} 跌破 200SMA；杠杆多头配置进入风控锁定。")
    if bool(breaker_state.get("vix_inverted",False)):
        ratio=float(breaker_state.get("vix_ratio",np.nan)); add(1,"VIX TERM INVERSION",f"VIX/VIX3M = {ratio:.3f}，波动率期限结构倒挂。")
    for symbol,frame in flows.items():
        if frame.empty or "DailyFlow" not in frame: continue
        last=frame.iloc[-1]; value=float(last.get("DailyFlow",np.nan)); verified=bool(last.get("HasVerifiedShares",False))
        official=bool(last.get("HasOfficialRecord",False))
        if verified and official and np.isfinite(value) and value>=500_000_000:
            add(2,"PRIMARY ETF FLOW",f"{symbol} 官方份额对应单日净申购 ${value/1e6:,.0f}M，突破 $500M。")
    for symbol,value in skews.items():
        if np.isfinite(value) and value>=.95: add(2,"OPTION IV SKEW",f"{symbol} Call/Put IV Skew = {value:.2f}，达到潜在 Gamma 挤压阈值。")
    tactical=[]
    for symbol,(chain,spot) in option_data.items():
        if chain.empty or not np.isfinite(spot): continue
        frame=chain.copy()
        for field in ("volume","openInterest","lastPrice","bid","ask","strike"):
            frame[field]=pd.to_numeric(frame.get(field,np.nan),errors="coerce")
        frame["ratio"]=frame["volume"].div(frame["openInterest"].replace(0,np.nan))
        frame["premium"]=frame["volume"].mul(frame["lastPrice"].fillna((frame["bid"]+frame["ask"])/2)).mul(100)
        frame=frame[(frame["strike"].sub(spot).abs().div(spot)<=.20)&(frame["ratio"]>=2.5)&
                    (frame["volume"]>=1000)&(frame["premium"]>=5_000_000)]
        if not frame.empty:
            top=frame.sort_values("premium",ascending=False).iloc[0]
            tactical.append(f"{symbol} {top.get('Type','Option')} {top['strike']:g} · Vol/OI {top['ratio']:.1f} · ${top['premium']/1e6:.1f}M")
    if tactical: add(3,"OPTIONS UOA","；".join(tactical[:5]))
    if improving_names: add(3,"RRG ROTATION",f"{', '.join(improving_names[:8])} 最近 3 日由 Lagging 扎入 Improving。")
    return alerts


STATIC_XRAY_HOLDINGS={
    "QQQ":[("NVDA","NVIDIA",8.8),("AAPL","Apple",8.1),("MSFT","Microsoft",7.4),("AVGO","Broadcom",5.0),
           ("AMZN","Amazon",5.3),("META","Meta",4.0),("GOOGL","Alphabet A",3.0),("GOOG","Alphabet C",2.8),
           ("TSLA","Tesla",3.3),("COST","Costco",1.2)],
    "SOXX":[("NVDA","NVIDIA",8.5),("AVGO","Broadcom",8.2),("AMD","AMD",7.3),("MU","Micron",6.5),
            ("LRCX","Lam Research",6.0),("KLAC","KLA",5.5),("AMAT","Applied Materials",5.3),("TSM","TSMC",4.3),
            ("ASML","ASML",4.0),("TXN","Texas Instruments",4.0)],
}


def _holdings_from_records(records: object) -> pd.DataFrame:
    candidates=[]
    def walk(node: object) -> None:
        if isinstance(node,list):
            if node and all(isinstance(item,dict) for item in node): candidates.append(node)
            for item in node: walk(item)
        elif isinstance(node,dict):
            for value in node.values(): walk(value)
    walk(records)
    rows=[]
    for candidate in candidates:
        for item in candidate:
            normal={re.sub(r"[^a-z]","",str(k).lower()):v for k,v in item.items()}
            ticker=next((normal[k] for k in normal if k in {"ticker","symbol","holdingticker"}),None)
            weight=next((normal[k] for k in normal if k in {"weight","weighting","weightpercent","percentofnetassets","percenttna"}),None)
            name=next((normal[k] for k in normal if k in {"name","company","holdingname","securityname"}),ticker)
            try: value=float(str(weight).replace("%","").replace(",",""))
            except Exception: continue
            if ticker and np.isfinite(value) and value>0: rows.append((str(ticker).strip(),str(name or ticker).strip(),value))
        if len(rows)>=5: break
    return pd.DataFrame(rows,columns=["Ticker","Name","Weight"])


@st.cache_data(ttl=3600,show_spinner=False)
def load_etf_holdings(fund: str) -> tuple[pd.DataFrame,str]:
    """Issuer-first top holdings with an explicit dated visual baseline fallback."""
    try:
        if fund=="QQQ":
            url="https://dng-api.invesco.com/cache/v1/accounts/en_US/shareclasses/46090E103/holdings/fund?idType=cusip&productType=ETF"
            response=requests.get(url,headers={"User-Agent":"Mozilla/5.0"},timeout=10); response.raise_for_status()
            frame=_holdings_from_records(response.json())
            source="Invesco official holdings API"
        else:
            url="https://www.ishares.com/us/products/239705/ishares-phlx-semiconductor-etf/1467271812596.ajax?fileType=csv&fileName=SOXX_holdings&dataType=fund"
            response=requests.get(url,headers={"User-Agent":"Mozilla/5.0"},timeout=10); response.raise_for_status()
            text=response.content.decode("utf-8-sig",errors="ignore"); lines=text.splitlines()
            start=next(i for i,line in enumerate(lines) if line.startswith("Ticker,"))
            raw=pd.read_csv(StringIO("\n".join(lines[start:])))
            weight_col=next(c for c in raw if "Weight" in str(c)); name_col=next(c for c in raw if str(c).strip()=="Name")
            frame=raw.rename(columns={"Ticker":"Ticker",name_col:"Name",weight_col:"Weight"})[["Ticker","Name","Weight"]]
            frame["Weight"]=pd.to_numeric(frame["Weight"],errors="coerce")
            frame=frame[frame["Ticker"].astype(str).str.fullmatch(r"[A-Z][A-Z0-9.\-]*",na=False)]
            source="iShares official SOXX holdings CSV"
        frame=frame.dropna(subset=["Ticker","Weight"]).sort_values("Weight",ascending=False).head(20)
        if len(frame)<5: raise ValueError("issuer payload did not contain holdings")
        return frame.reset_index(drop=True),source
    except Exception:
        fallback=pd.DataFrame(STATIC_XRAY_HOLDINGS[fund],columns=["Ticker","Name","Weight"])
        return fallback,f"Built-in reference baseline ({fund}; issuer endpoint unavailable)"


@st.cache_data(ttl=3600,show_spinner=False)
def load_fred_series(series_ids: tuple[str,...]) -> tuple[pd.DataFrame,dict[str,str]]:
    """Merge current official observations with a dated, bundled offline snapshot."""
    headers={
        "User-Agent":"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept":"text/html,application/xhtml+xml,application/xml;q=0.9,text/csv,*/*;q=0.8",
    }
    snapshot_path=Path(__file__).resolve().parent/"data"/"fred_offline_snapshot.csv"
    try:
        snapshot=pd.read_csv(snapshot_path,index_col="DATE",parse_dates=["DATE"])
        snapshot=snapshot.apply(pd.to_numeric,errors="coerce").sort_index()
        snapshot=snapshot[~snapshot.index.isna()]
    except (OSError,ValueError,pd.errors.ParserError):
        snapshot=pd.DataFrame()

    def fetch_one(series_id: str) -> pd.Series:
        # OFR FSI is published by the Office of Financial Research, not as FRED's OFRFSI ID.
        url=("https://www.financialresearch.gov/financial-stress-index/data/fsi.csv"
             if series_id=="OFRFSI" else
             f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={series_id}")
        response=requests.get(url,headers=headers,timeout=10)
        response.raise_for_status()
        raw=pd.read_csv(StringIO(response.text))
        date_col="Date" if series_id=="OFRFSI" else raw.columns[0]
        value_col="OFR FSI" if series_id=="OFRFSI" else series_id
        if date_col not in raw or value_col not in raw:
            raise ValueError(f"unexpected CSV columns for {series_id}")
        dates=pd.to_datetime(raw[date_col],errors="coerce")
        values=pd.to_numeric(raw[value_col],errors="coerce")
        item=pd.Series(values.to_numpy(),index=dates,name=series_id).dropna()
        item=item[~item.index.isna()]
        if item.empty:
            raise ValueError(f"no numeric observations for {series_id}")
        return item[~item.index.duplicated(keep="last")].sort_index()

    live={}
    # A failed FRED endpoint should cost at most one timeout window, not eight in series.
    with ThreadPoolExecutor(max_workers=min(6,len(series_ids) or 1)) as pool:
        futures={pool.submit(fetch_one,series_id):series_id for series_id in series_ids}
        for future in as_completed(futures):
            try:
                live[futures[future]]=future.result()
            except Exception:
                # One malformed or blocked source must never prevent the other series rendering.
                pass
    combined={}; status={}
    for series_id in series_ids:
        offline=(snapshot[series_id].dropna() if series_id in snapshot else pd.Series(dtype=float))
        if series_id in live:
            combined[series_id]=live[series_id].combine_first(offline)
            status[series_id]="live"
        elif not offline.empty:
            combined[series_id]=offline
            status[series_id]="offline"
        else:
            status[series_id]="unavailable"
    frame=pd.concat(combined,axis=1).sort_index() if combined else pd.DataFrame()
    return frame,status


def inflation_release_table(fred: pd.DataFrame) -> pd.DataFrame:
    monthly=fred.resample("ME").last() if not fred.empty else pd.DataFrame()
    result=pd.DataFrame(index=monthly.index)
    if "PCEPI" in monthly: result["Headline PCE · YoY"]=monthly["PCEPI"].pct_change(12,fill_method=None)*100
    if "PCEPILFE" in monthly: result["Core PCE · YoY"]=monthly["PCEPILFE"].pct_change(12,fill_method=None)*100
    if "PCETRIM1M158SFRBDAL" in monthly:
        one=monthly["PCETRIM1M158SFRBDAL"]
        result["Trimmed Mean PCE · 1M ann."]=one
        result["Trimmed Mean PCE · 6M ann."]=(one.div(100).add(1).pow(1/12).rolling(6).apply(np.prod,raw=True).pow(2)-1)*100
    if "PCETRIM12M159SFRBDAL" in monthly: result["Trimmed Mean PCE · 12M"]=monthly["PCETRIM12M159SFRBDAL"]
    if "PI" in monthly: result["Personal Income · MoM"]=monthly["PI"].pct_change(fill_method=None)*100
    if "PCE" in monthly: result["Personal Spending · MoM"]=monthly["PCE"].pct_change(fill_method=None)*100
    result=result.dropna(how="all").tail(12).T
    result.columns=[stamp.strftime("%Y-%m") for stamp in result.columns]
    return result


def heat_style_table(frame: pd.DataFrame) -> pd.io.formats.style.Styler:
    def row_colors(row: pd.Series) -> list[str]:
        values=pd.to_numeric(row,errors="coerce"); finite=values[np.isfinite(values)]
        if finite.empty: return ["color:#718198" for _ in row]
        low,high=float(finite.min()),float(finite.max()); span=max(high-low,1e-9)
        styles=[]
        for value in values:
            if not np.isfinite(value): styles.append("color:#718198;background:#0b121d"); continue
            position=(float(value)-low)/span
            if position>.66: styles.append("color:#ffd6dc;background:rgba(151,35,57,.55);font-weight:700")
            elif position<.34: styles.append("color:#c9ffe9;background:rgba(20,112,82,.48);font-weight:700")
            else: styles.append("color:#d7e0ec;background:#101823")
        return styles
    return frame.style.format("{:.2f}",na_rep="—").apply(row_colors,axis=1)


def base_layout(fig: go.Figure, height: int, hovermode: str = "closest") -> go.Figure:
    current_theme = st.session_state.get("portal_theme_choice", "Bloomberg Pro (买方经典)")
    return apply_quant_theme(fig, height, hovermode, theme_name=current_theme)


def section_header(kicker: str, title: str, note: str) -> None:
    st.markdown(f'<div class="module"><div class="kicker">{kicker}</div><div class="module-title">{title}</div><div class="module-note">{note}</div></div>', unsafe_allow_html=True)


def color_return(value: object) -> str:
    if not isinstance(value, (float, int, np.floating)) or not np.isfinite(value): return "color:#718198"
    return "color:#31d6a0;font-weight:600" if value >= 0 else "color:#ff5874;font-weight:600"


def format_num(value: float, suffix: str = "%") -> str:
    return "N/A" if not np.isfinite(value) else f"{value:+.2f}{suffix}"


with st.sidebar:
    st.markdown("### ◈ QUANT CONTROLS")
    st.caption("研究数据缓存 15 分钟 · 顶部行情独立缓存 45 秒")
    live_pulse_auto_refresh=st.toggle("顶部实时盘面 · 60s 局部刷新",value=True,
        help="仅重跑 Global Market Pulse Fragment，不触发 RRG、期权链与宏观数据重新下载。")
    tail_length = st.slider("RRG Tail · 尾迹交易日", 5, 10, 5)
    rs_horizon = st.select_slider("RS Horizon · 观察期", options=list(PERIOD_BARS), value="1Y")
    z_window = st.slider("Z-Score Window", 60, 250, 120, 5)
    with st.expander("🔔 预警推送配置 (Alert Settings)",expanded=False):
        alert_channel=st.selectbox("Webhook 类型",["Discord Webhook","Telegram Bot","通用 Webhook (LINE/飞书/Server酱)"],key="alert_channel")
        alert_webhook_url=""; alert_bot_token=""; alert_chat_id=""
        if alert_channel=="Telegram Bot":
            alert_bot_token=st.text_input("Bot Token",value=_secret("TELEGRAM_BOT_TOKEN"),type="password",key="alert_bot_token")
            alert_chat_id=st.text_input("Chat ID",value=_secret("TELEGRAM_CHAT_ID"),key="alert_chat_id")
        else:
            alert_webhook_url=st.text_input("Webhook URL",value=_secret("ALERT_WEBHOOK_URL"),type="password",key="alert_webhook_url")
        alert_auto_send=st.toggle("自动推送 L1 / L2",value=False,key="alert_auto_send",
            help="只发送此前未成功推送过的当日警报；浏览器会话内自动去重。")
        if st.button("📨 发送测试通知 (Test Ping)",use_container_width=True):
            test_message="**TEST PING · 连接验证**\nBuy-Side Quant Portal 预警通道已连通。\n`Research only · Not investment advice`"
            ok,note=send_webhook_notification(alert_channel,test_message,alert_webhook_url,alert_bot_token,alert_chat_id)
            (st.success if ok else st.error)(note)
    st.divider()
    st.caption("Tab 01 RRG / RS 基准：QQQ / SPY 可切换\n\nDrawdown：近 2 年峰值\n\nAdv / Dec：核心权重股样本")

core_tickers = ["SPY", "QQQ", "IWM", "^GSPC", "^NDX", "^VIX", "^VIX3M", "HYG", "LQD"]
theme_tickers=[ticker for members in AI_THEMES.values() for ticker in members]
all_tickers = tuple(dict.fromkeys(core_tickers + list(SECTORS) + list(RRG_EXTRA) + list(COMMODITIES)
                                  + list(HEAT_UNIVERSE) + list(NASDAQ_UNIVERSE) + list(YIELD_TICKERS.values())
                                  + theme_tickers + list(OPTION_POOL) + list(PRIMARY_FLOW_ETFS)))
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

breakers=circuit_breaker_state(prices)


@st.fragment(run_every="60s" if live_pulse_auto_refresh else None)
def render_live_market_pulse() -> None:
    """Refresh only the header tape; heavy research modules stay outside this fragment."""
    session=us_market_status(); eastern=pytz.timezone("US/Eastern")
    refreshed_at=datetime.now(eastern)
    try:
        pulse=fetch_live_pulse()
    except Exception:
        pulse=pd.DataFrame()
    quote_stamps=[]
    if not pulse.empty and "QuoteTimeET" in pulse:
        quote_stamps=[stamp for stamp in pulse["QuoteTimeET"].tolist() if pd.notna(stamp)]
    quote_asof=max(quote_stamps).strftime("%H:%M:%S ET") if quote_stamps else "DAILY FALLBACK"
    st.markdown(f"""<div class="portal-head"><div><div class="portal-title">BUY-SIDE QUANT PORTAL</div>
    <div class="portal-sub">CROSS-ASSET INTELLIGENCE · ROTATION · OPTIONS · PRIMARY FLOW · SYSTEM RISK</div></div>
    <div class="market-clock"><span style="color:{session['color']}">{session['label']}</span><small>{session['time']} · {session['countdown']}</small></div>
    <div class="live">LAST UPDATED {refreshed_at:%H:%M:%S} ET<br><span style="color:#71849a">QUOTE {quote_asof}</span></div></div>
    <div class="deck-label">Global Market Pulse / 实时盘面 · 60s Fragment · 45s Quote Cache</div>""",unsafe_allow_html=True)

    deck=st.columns(8)
    for idx,(display_ticker,source_ticker) in enumerate((("SPY","SPY"),("QQQ","QQQ"),("IWM","IWM"),("VIX","^VIX"))):
        live_price=live_change=np.nan
        if not pulse.empty and display_ticker in pulse.index:
            live_price=float(pulse.loc[display_ticker,"Price"]); live_change=float(pulse.loc[display_ticker,"ChangePct"])
        if not np.isfinite(live_price):
            fallback=prices[source_ticker].dropna() if source_ticker in prices else pd.Series(dtype=float)
            live_price=float(fallback.iloc[-1]) if not fallback.empty else np.nan; live_change=last_return(fallback,1)
        value="N/A" if not np.isfinite(live_price) else (f"{live_price:,.2f}" if display_ticker=="VIX" else f"${live_price:,.2f}")
        deck[idx].metric(display_ticker,value,format_num(live_change),delta_color="inverse" if display_ticker=="VIX" else "normal",
            help="1分钟行情优先；不可用时回退至最近日线。VIX 上涨使用反向风险配色。")

    spx_dd=drawdown_from_high(prices["^GSPC"].dropna().tail(504)) if "^GSPC" in prices else np.nan
    ndx_dd=drawdown_from_high(prices["^NDX"].dropna().tail(504)) if "^NDX" in prices else np.nan
    deck[4].metric("SPX DRAWDOWN",format_num(spx_dd),"FROM 2Y HIGH",delta_color="off",help="15分钟研究缓存：相对近两年最高收盘价")
    deck[5].metric("NDX DRAWDOWN",format_num(ndx_dd),"FROM 2Y HIGH",delta_color="off",help="15分钟研究缓存：相对近两年最高收盘价")
    sp_breadth_text="N/A" if sp_missing==500 else f"{sp_adv}/{sp_dec}/{sp_unch}/{sp_missing}"
    deck[6].metric("SPY 500 · A/D/U/M",sp_breadth_text,"SUM = 500",delta_color="off",
        help="500家公司日线口径：上涨 / 下跌 / 平盘 / 缺失；四项合计恒为500")
    ndx_returns=pd.Series({ticker:last_return(prices[ticker],1) for ticker in NASDAQ_UNIVERSE if ticker in prices}).dropna()
    ndx_adv,ndx_dec,ndx_unch=int((ndx_returns>0).sum()),int((ndx_returns<0).sum()),int((ndx_returns==0).sum())
    deck[7].metric("NDX SAMPLE · A / D / U",f"{ndx_adv} / {ndx_dec} / {ndx_unch}",
        f"{len(NASDAQ_UNIVERSE)-len(ndx_returns)} MISSING",delta_color="off",help="Nasdaq-100 看板覆盖样本；不显示涨跌比率")


render_live_market_pulse()

if breakers["broken"]:
    st.markdown(f'<div class="risk-lock">🚨 战略风控锁死：{", ".join(breakers["broken"])} 跌破 200SMA，杠杆多头（TQQQ / SOXL）配置权限关闭</div>',unsafe_allow_html=True)

if missing_tickers:
    st.caption(f"⚠ 本次自动跳过无有效行情的标的：{', '.join(missing_tickers)}")

tab_briefing,tab_rotation,tab_market,tab_heat,tab_macro,tab_technical,tab_pattern,tab_options,tab_flow,tab_circuit,tab_fixed,tab_xray,tab_deep,tab_pulse = st.tabs([
    "00  BRIEFING · 每日情报", "01  SECTOR & AI THEMES RRG · 轮动",
    "02  MARKETS & BREADTH · 大盘表现与广度",
    "03  HEAT MAPS · 板块热力图", "04  MACRO & COMMODITIES · 宏观与大宗",
    "05  TECHNICALS · 相对强度", "06  REGIME & PATTERN · 状态形态",
    "07  OPTIONS UOA & GAMMA · 期权", "08  PRIMARY ETF FLOW · 一级市场",
    "09  CIRCUIT BREAKERS · 系统风控", "10  FIXED INCOME · 固定收益",
    "11  ETF X-RAY · 穿透敞口", "12  MACRO DEEP DIVE · FRED", "13  EVENT PULSE · 新闻数据",
])

with tab_briefing:
    section_header("DAILY COMMAND CENTER","00 Briefing · 每日情报总控台","多维共振摘要；Yahoo 数据缺失时相应信号自动降级，不阻塞其他模块。")
    flow_snapshots={}
    # Briefing needs only the two leveraged products; QQQ/SPY are fetched lazily
    # when selected in Tab 08 so their issuer workbooks do not slow every rerun.
    for symbol in LEVERAGED_ETFS:
        try: flow_snapshots[symbol]=load_primary_flow(symbol)
        except Exception: flow_snapshots[symbol]=pd.DataFrame()
    option_snapshots={}
    for symbol in OPTION_POOL:
        try: option_snapshots[symbol]=load_option_snapshot(symbol,1)
        except Exception: option_snapshots[symbol]=(pd.DataFrame(),np.nan)
    latest_flows={symbol:(float(frame["DailyFlow"].dropna().iloc[-1]) if not frame.empty and not frame["DailyFlow"].dropna().empty else np.nan)
                  for symbol,frame in flow_snapshots.items()}
    flow_verified={symbol:(bool(frame["HasVerifiedShares"].iloc[-1]) if not frame.empty and "HasVerifiedShares" in frame else False)
                   for symbol,frame in flow_snapshots.items()}
    extreme_flow=[s for s in LEVERAGED_ETFS if np.isfinite(latest_flows.get(s,np.nan))
                  and latest_flows[s]>=500_000_000 and flow_verified.get(s,False)]
    skew_values={}
    for symbol in ("QQQ","SPY"):
        chain,spot=option_snapshots.get(symbol,(pd.DataFrame(),np.nan)); skew_values[symbol]=option_skew_proxy(chain,spot)[0]
    skew_alert=[s for s,v in skew_values.items() if np.isfinite(v) and v>=.95]
    rotation_universe=list(dict.fromkeys(list(SECTORS)+theme_tickers))
    improving=rrg_improving_crossovers(prices,rotation_universe)
    firewall_safe=not breakers["broken"] and not breakers["credit_warning"] and not breakers["vix_inverted"]
    alert_cards=st.columns(4)
    unavailable_flows=[symbol for symbol in LEVERAGED_ETFS if not flow_verified.get(symbol,False)]
    alert_cards[0].metric("🚨 杠杆 ETF 一级市场", "🔥 机构级抄底流入确认" if extreme_flow else "OFFICIAL FLOW WATCH",
        "、".join(f"{s} ${latest_flows[s]/1e6:,.0f}M" for s in extreme_flow) if extreme_flow else
        (f"待补官方份额：{'、'.join(unavailable_flows)}" if unavailable_flows else "TQQQ / SOXL · $500M 阈值"),delta_color="off")
    alert_cards[1].metric("⚡ Gamma 挤压 & 偏度", "⚡ 偏度严重倒挂 / 潜在轧空" if skew_alert else "SKEW NORMAL",
        " · ".join(f"{s} {skew_values[s]:.2f}" for s in skew_values if np.isfinite(skew_values[s])) or "期权链暂不可用",delta_color="off")
    alert_cards[2].metric("🎯 RRG 弱转强", "、".join(improving[:5]) if improving else "暂无确认",
        "近3日 Lagging → Improving",delta_color="off")
    alert_cards[3].metric("🛡️ 地缘与宏观防火墙", "🟢 战略环境安全" if firewall_safe else "🚨 触发风控熔断",
        f"200SMA {len(breakers['broken'])} · Credit {'RISK' if breakers['credit_warning'] else 'OK'} · VIX {'INV' if breakers['vix_inverted'] else 'OK'}",delta_color="off")

    uoa_reports=[]
    for symbol,(chain,spot) in option_snapshots.items():
        unusual=unusual_option_rows(chain,spot,2.0,1000,.20).head(3)
        if unusual.empty: continue
        unusual.insert(0,"Symbol",symbol); uoa_reports.append(unusual)
    uoa_report=pd.concat(uoa_reports,ignore_index=True) if uoa_reports else pd.DataFrame()
    ai_momentum=[]
    for theme,members in AI_THEMES.items():
        if theme.startswith("宏观"): continue
        returns={ticker:last_return(prices[ticker],5) for ticker in members if ticker in prices}
        valid={ticker:value for ticker,value in returns.items() if np.isfinite(value)}
        if valid:
            leader=max(valid,key=valid.get); ai_momentum.append((theme,float(np.mean(list(valid.values()))),leader,valid[leader]))
    ai_momentum.sort(key=lambda item:item[1],reverse=True)
    section_header("QUANT DIAGNOSTIC","今日量化诊断清单","异常期权为监控池扫描；Volume/OI 无法单独确认主动买卖或开平仓方向。")
    uoa_text="；".join(f"{row['Symbol']} {row['Type']} {row['Strike']:g} · Vol/OI {row['Vol/OI']:.1f}" for _,row in uoa_report.head(5).iterrows()) if not uoa_report.empty else "监控池内暂无 Vol > 2×OI 且成交量≥1000 的近月虚值合约"
    ai_text="；".join(f"{theme.replace('AI · ','')}：{leader} {leader_ret:+.1f}%（主题5日均值 {avg:+.1f}%）" for theme,avg,leader,leader_ret in ai_momentum[:3]) or "AI 主题数据不足"
    st.markdown(f"""
- **期权异常榜：** {uoa_text}
- **AI 动能榜：** {ai_text}
- **系统风控：** 指数破位 `{', '.join(breakers['broken']) or '无'}`；信用流动性 `{'收紧' if breakers['credit_warning'] else '正常'}`；VIX期限结构 `{'倒挂' if breakers['vix_inverted'] else '正向'}`。
- **执行纪律：** 只有趋势、广度、期权与一级市场资金流形成共振时才升级信号等级；单一代理指标不构成交易指令。
""")

    active_alerts=evaluate_market_alerts(breakers,flow_snapshots,skew_values,option_snapshots,improving,latest_date)
    existing_log=st.session_state.setdefault("_active_alert_log",[])
    known_ids={item.get("ID") for item in existing_log}
    for item in active_alerts:
        if item["ID"] not in known_ids:
            existing_log.insert(0,{**item,"Unread":True})
    st.session_state["_active_alert_log"]=existing_log[:100]

    if alert_auto_send:
        priority=[item for item in active_alerts if int(item["Level"])<=2]
        sent_ids=set(st.session_state.get("_sent_alert_ids",[])); pending=[item for item in priority if item["ID"] not in sent_ids]
        if pending:
            body="**BUY-SIDE QUANT PORTAL · ACTIVE ALERTS**\n"+"\n".join(
                f"{item['Severity']} | **{item['Category']}**\n{item['Message']}" for item in pending)
            ok,note=send_webhook_notification(alert_channel,body,alert_webhook_url,alert_bot_token,alert_chat_id)
            if ok:
                sent_ids.update(item["ID"] for item in pending); st.session_state["_sent_alert_ids"]=list(sent_ids)[-200:]
                st.toast(f"预警已推送 · {len(pending)} 条",icon="🔔")
            elif alert_webhook_url or (alert_bot_token and alert_chat_id):
                st.warning(f"自动推送未完成：{note}")

    section_header("ALERT CENTER","今日未读警报日志 · Active Alerts Log","L1/L2 可自动推送；相同数据日与规则触发在当前浏览器会话内只发送一次。")
    log_frame=pd.DataFrame(st.session_state.get("_active_alert_log",[]))
    unread_count=int(log_frame["Unread"].sum()) if not log_frame.empty and "Unread" in log_frame else 0
    log_left,log_right=st.columns([5,1],vertical_alignment="bottom")
    log_left.caption(f"ACTIVE {len(active_alerts)} · UNREAD {unread_count} · HISTORY {len(log_frame)}")
    if log_right.button("全部标为已读",use_container_width=True,disabled=unread_count==0):
        for item in st.session_state.get("_active_alert_log",[]): item["Unread"]=False
        st.rerun()
    if log_frame.empty:
        st.success("🟢 当前规则矩阵没有触发警报。")
    else:
        display_log=log_frame[["Unread","Severity","Category","Message","As Of"]].copy()
        display_log["Unread"]=display_log["Unread"].map({True:"● NEW",False:"READ"})
        st.dataframe(display_log,use_container_width=True,hide_index=True,height=min(330,72+35*len(display_log)))

with tab_rotation:
    rotation_head,rotation_control,benchmark_control=st.columns([4.6,1.75,1.0],vertical_alignment="bottom")
    with rotation_head:
        section_header("MULTI-ASSET ROTATION","01 Sector & AI Themes RRG · 个股主题下钻","行业、AI 基建与地缘主题的相对旋转、量能和期权战术共振。")
    with rotation_control:
        selected_theme=st.selectbox("Theme 观测池",list(AI_THEMES),key="rrg_theme_selector")
    with benchmark_control:
        rrg_benchmark=st.selectbox("RRG Benchmark",["QQQ","SPY"],key="rrg_benchmark")
    selected_rrg_tickers=AI_THEMES[selected_theme]
    theme_crossovers=rrg_improving_crossovers(prices,selected_rrg_tickers,rrg_benchmark)
    if theme_crossovers:
        st.success(f"🎯 弱转强自动诊断：{'、'.join(theme_crossovers)} 最近3日由 Lagging 跨入 Improving。")
    else:
        st.info("弱转强自动诊断：当前主题暂无 Lagging → Improving 的三日确认信号。")
    col_left, col_right = st.columns(2, gap="medium")
    with col_left:
        section_header("RELATIVE ROTATION", f"RRG · {selected_theme}", f"相对 {rrg_benchmark}；末端为最新交易日，尾迹长度由侧边栏控制。")
        fig, tails = go.Figure(), []
        rrg_names = {ticker:(SECTORS[ticker][1] if ticker in SECTORS else TACTICAL_NAMES.get(ticker,RRG_EXTRA.get(ticker,ticker))) for ticker in selected_rrg_tickers}
        palette=px.colors.qualitative.Bold+px.colors.qualitative.Safe
        for ticker, label in rrg_names.items():
            if ticker not in prices: continue
            tail = rrg_frame(prices[ticker], prices[rrg_benchmark]).tail(tail_length)
            if tail.empty: continue
            tails.append(tail)
            color = COLORS.get(ticker,palette[list(rrg_names).index(ticker)%len(palette)])
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
        section_header("RELATIVE STRENGTH", f"Theme RS vs {rrg_benchmark} · 主题相对强弱", "当前观测池比率在观察期起点归一至 100；点线为 200 日平滑。")
        fig = go.Figure()
        for index,ticker in enumerate(selected_rrg_tickers):
            pair = prices[[ticker,rrg_benchmark]].dropna() if ticker in prices else pd.DataFrame()
            if pair.empty: continue
            ratio_full = pair[ticker].div(pair[rrg_benchmark])
            ratio = display_window(ratio_full,rs_horizon)
            if ratio.empty: continue
            rebased = ratio.div(ratio.iloc[0]).mul(100); color = COLORS.get(ticker,palette[index%len(palette)])
            label=rrg_names.get(ticker,ticker)
            fig.add_trace(go.Scatter(x=rebased.index, y=rebased, mode="lines", name=ticker, line=dict(color=color, width=1.45),
                hovertemplate=f"<b>{ticker} · {label}</b><br>%{{x|%Y-%m-%d}}<br>RS %{{y:.2f}}<extra></extra>"))
            # Calculate the true 200-day smoother before clipping to the display horizon.
            smooth_full = ratio_full.rolling(200,min_periods=200).mean().div(ratio.iloc[0]).mul(100)
            smooth = display_window(smooth_full,rs_horizon)
            fig.add_trace(go.Scatter(x=smooth.index, y=smooth, mode="lines", name=f"{ticker} 200D", showlegend=False, line=dict(color=color, width=.75, dash="dot"), hoverinfo="skip"))
        benchmark_anchor=display_window(prices[rrg_benchmark].dropna(),rs_horizon)
        if not benchmark_anchor.empty:
            fig.add_trace(go.Scatter(x=benchmark_anchor.index,y=np.full(len(benchmark_anchor),100.0),name=f"{rrg_benchmark} ANCHOR",
                line=dict(color="#edf2f7",width=1.8,dash="dash"),hovertemplate=f"<b>{rrg_benchmark} Anchor</b><br>%{{x|%Y-%m-%d}}<br>100.00<extra></extra>"))
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

    section_header("TACTICAL STOCK RADAR",f"个股多空强弱与异常量能 · {selected_theme}",f"价格、相对 {rrg_benchmark} 均线结构与 20 日相对量比；可按动能或 RVOL 快速排序。")
    try:
        theme_ohlcv=load_ohlcv(tuple(selected_rrg_tickers),"1y")
    except Exception:
        theme_ohlcv=pd.DataFrame()
    tactical=theme_tactical_scoreboard(prices,theme_ohlcv,selected_rrg_tickers,rrg_benchmark)
    tactical_sort=st.radio("战术排序",["动能强 → 弱","RVOL 高 → 低","观测池顺序"],horizontal=True,key="theme_tactical_sort")
    if tactical.empty:
        st.warning("当前主题个股历史或成交量数据不足，暂无法生成战术矩阵。")
    else:
        if tactical_sort=="动能强 → 弱": tactical=tactical.sort_values("_MomentumScore",ascending=False)
        elif tactical_sort=="RVOL 高 → 低": tactical=tactical.sort_values("_RVOL",ascending=False,na_position="last")
        else:
            order={ticker:index for index,ticker in enumerate(selected_rrg_tickers)}
            tactical=tactical.assign(_order=tactical["Ticker"].str.split(" · ").str[0].map(order)).sort_values("_order").drop(columns="_order")
        tactical_display=tactical.drop(columns=["_MomentumScore","_RVOL"])
        tactical_style=tactical_display.style.map(
            lambda value:"background-color:rgba(246,196,83,.16);color:#f6c453;font-weight:700" if "异常放量" in str(value) else "",
            subset=["RVOL (20D)"])
        st.dataframe(tactical_style,use_container_width=True,hide_index=True,height=min(470,42+36*len(tactical_display)))

    section_header("THEME OPTIONS UOA",f"今日期权伏击清单 · {selected_theme}","自动扫描主题成分股 7–30 DTE、现价 ±15% 的近虚值合约；阈值为 Volume ≥ 1.5×OI 且 Volume ≥ 500。")
    with st.spinner("SCANNING THEME OPTIONS / 正在扫描主题期权链…"):
        try:
            theme_uoa=load_theme_option_uoa(tuple(selected_rrg_tickers))
        except Exception:
            theme_uoa=pd.DataFrame()
    if theme_uoa.empty:
        st.info("当前主题成分股未检测到极端虚值期权抢筹异动")
    else:
        uoa_style=theme_uoa.head(120).style.format({
            "Strike":"${:,.2f}","Moneyness":"{:+.2f}%","Vol":"{:,.0f}","OI":"{:,.0f}","Vol/OI":"{:.2f}x"
        },na_rep="—").map(lambda value:"color:#31d6a0;font-weight:700" if str(value)=="Call" else
            ("color:#ff8f5a;font-weight:700" if str(value)=="Put" else ""),subset=["Type"])
        st.dataframe(uoa_style,use_container_width=True,hide_index=True,height=min(510,42+35*min(len(theme_uoa),120)))
        st.caption("Volume/OI 仅表示成交量相对存量异常，Yahoo 公开链不提供逐笔主动买卖与开平仓方向；‘抢筹/防守候选’需结合价格、IV 与后续 OI 复核。")

    scoreboard=sector_rs_scoreboard(prices)
    section_header("SECTOR SCOREBOARD","11 大行业多空全景矩阵","各行业 ETF / SPY 相对强度与 20EMA、50EMA、200SMA 的位置关系。")
    score_sort=st.radio("状态排序",["默认行业顺序","强 → 弱","弱 → 强"],horizontal=True,key="scoreboard_sort")
    if not scoreboard.empty and score_sort!="默认行业顺序":
        regime_rank={"🔥 绝对强势":4,"⚡ 超跌反弹":3,"🔄 均线过渡":2,"⚠️ 强势回调":1,"❄️ 弱势破位":0}
        scoreboard=scoreboard.assign(_rank=scoreboard["Regime 定性"].map(regime_rank).fillna(2)).sort_values("_rank",ascending=score_sort=="弱 → 强").drop(columns="_rank")
    if scoreboard.empty:
        st.warning("行业相对强度历史不足。")
    else:
        score_style=scoreboard.style.format({"RS vs 20EMA":"{:+.2f}%","RS vs 50EMA":"{:+.2f}%","RS vs 200SMA":"{:+.2f}%"},na_rep="—").map(
            color_return,subset=["RS vs 20EMA","RS vs 50EMA","RS vs 200SMA"])
        st.dataframe(score_style,use_container_width=True,hide_index=True,height=455)

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
            fig.update_traces(text=tile_text,texttemplate="<b>%{label}</b><br>%{text}",hovertemplate="<b>%{label}</b><br>%{customdata[0]}<br>Return %{customdata[1]:+.2f}%<br>Weight proxy %{customdata[2]:.2f}%<extra></extra>",textfont=dict(size=15,color="#f7f8fa"),marker=dict(line=dict(color="#05070a",width=2.2)),root_color="#0a0d14",tiling=dict(packing="squarify",pad=2))
            base_layout(fig,720)
            fig.update_layout(margin=dict(l=2,r=2,t=10,b=2),coloraxis_colorbar=dict(title=f"{heat_period} %",thickness=11,len=.58,tickformat="+.1f"))
            st.plotly_chart(fig,use_container_width=True,config={"displaylogo":False})

    section_header("TRADING PRESSURE",f"{heat_index} · 20D Secondary-Market Activity","仅衡量二级市场上涨/下跌日成交活跃度，不代表 ETF 申赎或一级市场资金流。")
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
    if flow_df.empty: st.warning("二级市场成交活跃度暂无有效数据。")
    else:
        flow_limit=max(20.0,float(flow_df["Flow"].abs().quantile(.92)))
        flow_fig=px.treemap(flow_df,path=[px.Constant(f"{heat_index} ACTIVITY"),"Group","Ticker"],values="Market Weight",color="Flow",
            color_continuous_scale=[(0,"#a61b3b"),(.5,"#2e333b"),(1,"#087f60")],range_color=(-flow_limit,flow_limit),
            custom_data=["Company","Flow","Flow Text"])
        flow_text=[str(custom[2]) if str(node_id).count("/")>=2 else "" for node_id,custom in zip(flow_fig.data[0].ids,flow_fig.data[0].customdata)]
        flow_fig.update_traces(text=flow_text,texttemplate="<b>%{label}</b><br>%{text}",hovertemplate="<b>%{label}</b><br>%{customdata[0]}<br>20D Trading Pressure %{customdata[1]:+.1f}%<extra></extra>",marker=dict(line=dict(color="#05070a",width=2)),root_color="#0a0d14",tiling=dict(pad=2))
        base_layout(flow_fig,540)
        flow_fig.update_layout(margin=dict(l=2,r=2,t=8,b=2),coloraxis_colorbar=dict(title="Activity %",thickness=11,len=.58))
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

        continuation={"detected":False,"reason":"OHLCV 数据暂不可用。"}
        try:
            continuation_panel=load_ohlcv((single_ticker,),"1y")
            if not continuation_panel.empty and single_ticker in continuation_panel.columns.get_level_values(0):
                continuation=continuation_price_diagnostics(continuation_panel[single_ticker])
        except Exception as exc:
            continuation={"detected":False,"reason":f"延续度诊断数据抓取失败：{exc}"}

        oi_carry={"passed":None,"label":"⚪ OI 净增待确认","detail":"未触发突破诊断，暂不抓取期权链"}
        if continuation.get("detected"):
            try:
                continuation_chain,continuation_spot=load_option_snapshot(single_ticker,8)
                oi_carry=continuation_option_oi_carry(single_ticker,continuation_chain,continuation_spot)
            except Exception as exc:
                oi_carry={"passed":None,"label":"⚪ OI 数据不可用","detail":f"期权链抓取失败：{exc}"}

            continuation_score=sum([
                bool(continuation.get("avwap_pass")),bool(continuation.get("dryup_pass")),
                bool(continuation.get("ema_pass")),oi_carry.get("passed") is True,
            ])
            if not continuation.get("avwap_pass"):
                continuation_badge="❄️ 假突破失效（放弃观察）"; continuation_class="continuation-red"
            elif continuation_score>=3:
                continuation_badge="🔥 强趋势二次蓄势（胜率高，关注箱体突破）"; continuation_class="continuation-gold"
            else:
                continuation_badge="🔎 突破后整理观察（等待更多共振）"; continuation_class="continuation-watch"
            dryup_text=f"{continuation['dryup']:.2f}×" if np.isfinite(continuation.get("dryup",np.nan)) else "等待样本"
            ema_text=f"{continuation['ema_distance']:.2f}%" if np.isfinite(continuation.get("ema_distance",np.nan)) else "N/A"
            avwap_gap=(continuation["price"]/continuation["avwap"]-1)*100 if continuation.get("avwap") else np.nan
            st.markdown(f"""
            <div class="continuation-panel">
              <div class="continuation-head">
                <div><span class="continuation-title">CONTINUATION FILTER · 个股异动与突破延续度</span><br><span class="continuation-badge {continuation_class}">{continuation_badge}</span></div>
                <div class="continuation-meta">SCORE {continuation_score}/4 · ANCHOR {continuation['anchor']:%Y-%m-%d} · +{continuation['breakout_return']:.2f}% · RVOL {continuation['breakout_rvol']:.2f}× · {continuation['days_since']} BARS AGO</div>
              </div>
              <div class="continuation-grid">
                <div class="continuation-item"><div class="continuation-label">01 · ANCHORED VWAP</div><div class="continuation-value">${continuation['avwap']:,.2f} · {avwap_gap:+.2f}%</div><div class="continuation-note">{continuation['avwap_label']}</div></div>
                <div class="continuation-item"><div class="continuation-label">02 · VOLUME DRY-UP</div><div class="continuation-value">{dryup_text}</div><div class="continuation-note">{continuation['dryup_label']}</div></div>
                <div class="continuation-item"><div class="continuation-label">03 · EMA20 CONVERGENCE</div><div class="continuation-value">{ema_text}</div><div class="continuation-note">{continuation['ema_label']}</div></div>
                <div class="continuation-item"><div class="continuation-label">04 · OPTIONS OI CARRY</div><div class="continuation-value">CROSS-DAY CHECK</div><div class="continuation-note">{oi_carry['label']} · {oi_carry['detail']}</div></div>
              </div>
            </div>
            """,unsafe_allow_html=True)
        else:
            st.info(f"CONTINUATION FILTER · {continuation.get('reason','当前未触发放量突破条件')}")

        single_full=pd.DataFrame({"price":s,"sma20":sma20,"sma50":sma50,"sma200":sma200,"zscore":price_z})
        single_full["avwap"]=np.nan
        if continuation.get("detected"):
            single_full["avwap"]=continuation["avwap_series"].reindex(single_full.index)
        single_active=display_window(single_full,single_period)
        single_plot=display_with_preroll(single_full,single_period)
        single_fig=make_subplots(rows=2,cols=1,shared_xaxes=True,vertical_spacing=.07,row_heights=[.72,.28])
        single_fig.add_trace(go.Scatter(x=single_plot.index,y=single_plot["price"],name=single_ticker,line=dict(color="#4f86d9",width=2)),row=1,col=1)
        for name,column,color in [("SMA20","sma20","#31d6a0"),("SMA50","sma50","#e56f24"),("SMA200","sma200","#a8adb5")]:
            single_fig.add_trace(go.Scatter(x=single_plot.index,y=single_plot[column],name=name,line=dict(color=color,width=1.4)),row=1,col=1)
        if continuation.get("detected"):
            single_fig.add_trace(go.Scatter(x=single_plot.index,y=single_plot["avwap"],name="Anchored VWAP",
                line=dict(color="#f4c34f",width=2.2,dash="dash")),row=1,col=1)
        single_fig.add_trace(go.Scatter(x=single_plot.index,y=single_plot["zscore"],name="Z-Score",line=dict(color="#a78bfa",width=1.7)),row=2,col=1)
        base_layout(single_fig,620,"x unified")
        single_fig.add_hline(y=2,line_dash="dash",line_color="#ff4f70",row=2,col=1)
        single_fig.add_hline(y=-2,line_dash="dash",line_color="#18d39c",row=2,col=1)
        single_fig.add_hline(y=0,line_dash="dot",line_color="#718198",row=2,col=1)
        if not single_active.empty and single_active.index[0]>single_plot.index[0]:
            single_fig.add_vline(x=single_active.index[0].to_pydatetime(),line_dash="dot",line_color="#74849a",
                annotation_text=f"{single_period} ACTIVE WINDOW",annotation_position="top left")
        if continuation.get("detected") and continuation["anchor"]>=single_plot.index.min():
            single_fig.add_vline(x=continuation["anchor"].to_pydatetime(),line_dash="dot",line_color="#f4c34f",
                annotation_text="VOLUME BREAKOUT",annotation_position="top right",row=1,col=1)
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

with tab_options:
    option_head,option_control,moneyness_control=st.columns([4.4,1.1,1.7],vertical_alignment="bottom")
    with option_head:
        section_header("OPTIONS INTELLIGENCE","Options UOA & Gamma · 期权异动雷达","扫描7–30 DTE 虚值合约；所有链路均独立容错并受15分钟缓存保护。")
    with option_control:
        option_symbol=st.selectbox("Underlying",OPTION_POOL,key="option_radar_symbol")
    with moneyness_control:
        moneyness_pct=st.slider("行权价偏离范围 · Strike Moneyness",10,30,15,5,format="±%d%%",key="uoa_moneyness")
    try:
        chain,spot=load_option_snapshot(option_symbol,4,allow_saved_snapshot=True)
    except Exception:
        chain,spot=pd.DataFrame(),np.nan
    unusual=unusual_option_rows(chain,spot,1.5,1000,moneyness_pct/100)
    skew_ratio,skew_curve=option_skew_proxy(chain,spot)
    option_cards=st.columns(4)
    option_cards[0].metric("SPOT","N/A" if not np.isfinite(spot) else f"${spot:,.2f}")
    option_cards[1].metric("UOA CONTRACTS",f"{len(unusual)}",">=1.5× OI · Vol>=1000",delta_color="off")
    option_cards[2].metric("±4% OTM IV SKEW","N/A" if not np.isfinite(skew_ratio) else f"{skew_ratio:.3f}",
                           "⚡ 倒挂警戒" if np.isfinite(skew_ratio) and skew_ratio>=.95 else "Call IV / Put IV",delta_color="off")
    chain_source=chain.attrs.get("source","UNAVAILABLE") if not chain.empty else "UNAVAILABLE"
    option_cards[3].metric("CHAIN STATUS",chain_source,f"{chain['Expiration'].nunique() if not chain.empty else 0} expiries",delta_color="off")
    if chain.empty:
        st.warning(f"{option_symbol} 近月期权链暂不可用；Yahoo 限流或非交易时段可能导致空响应，请稍后重试。")
    else:
        asof_utc=chain.attrs.get("asof_utc","")
        st.caption(f"期权链来源：{chain_source} · 采集时间 UTC：{asof_utc}。历史快照仅供回看，不代表实时盘口或今日异动。")
        uoa_col,skew_col=st.columns(2,gap="medium")
        with uoa_col:
            section_header("VOL > OI SCANNER","异常大单扫描",f"仅保留现价 ±{moneyness_pct}% 内的虚值合约；Volume >= 1.5×OI 且 Volume >= 1000。")
            if unusual.empty:
                st.info("当前链未发现满足阈值的虚值合约。")
            else:
                unusual_style=unusual.head(60).style.format({"Strike":"${:,.2f}","Moneyness":"{:+.1f}%","Vol":"{:,.0f}","OI":"{:,.0f}","Vol/OI":"{:.2f}×","IV":"{:.1f}%"},na_rep="—")
                st.dataframe(unusual_style,use_container_width=True,hide_index=True,height=430)
        with skew_col:
            section_header("IV SKEW CURVE","Strike vs Implied Volatility","最近到期日；绿色为 Call IV，橙红为 Put IV。")
            skew_fig=go.Figure()
            for option_type,color in (("Call","#31d6a0"),("Put","#ff7857")):
                curve=skew_curve[skew_curve["Type"].eq(option_type)].sort_values("strike") if not skew_curve.empty else pd.DataFrame()
                if curve.empty: continue
                skew_fig.add_trace(go.Scatter(x=curve["strike"],y=curve["impliedVolatility"]*100,name=f"{option_type} IV",
                    mode="lines+markers",line=dict(color=color,width=2),marker=dict(size=5),hovertemplate="$%{x:.2f}<br>IV %{y:.1f}%<extra></extra>"))
            base_layout(skew_fig,430,"x unified"); skew_fig.add_vline(x=spot,line_dash="dash",line_color="#f4f7fb",annotation_text=f"SPOT {spot:.2f}")
            skew_fig.update_xaxes(title="Strike"); skew_fig.update_yaxes(title="Implied Volatility",ticksuffix="%")
            st.plotly_chart(skew_fig,use_container_width=True,config={"displaylogo":False})

        section_header("STRIKE OI PROFILE","Gamma 引力位 · Open Interest by Strike","OI 仅作为 Gamma 磁吸代理；未包含做市商净头寸方向与合约 Gamma。")
        profile=chain[chain["strike"].between(spot*.70,spot*1.30)].copy()
        profile=profile.groupby(["strike","Type"],as_index=False)["openInterest"].sum()
        oi_fig=go.Figure()
        for option_type,color,sign in (("Call","#31d6a0",1),("Put","#ff5874",-1)):
            part=profile[profile["Type"].eq(option_type)]
            oi_fig.add_trace(go.Bar(x=part["strike"],y=part["openInterest"]*sign,name=f"{option_type} OI",marker_color=color,
                hovertemplate=f"{option_type} $%{{x:.2f}}<br>OI %{{customdata:,.0f}}<extra></extra>",customdata=part["openInterest"]))
        base_layout(oi_fig,430); oi_fig.update_layout(barmode="relative")
        oi_fig.add_vline(x=spot,line_dash="dash",line_color="#ffffff",line_width=2,annotation_text=f"SPOT ${spot:.2f}")
        oi_fig.update_xaxes(title="Strike"); oi_fig.update_yaxes(title="Call OI (+) / Put OI (−)")
        st.plotly_chart(oi_fig,use_container_width=True,config={"displaylogo":False})
        section_header("FULL OPTION CHAIN","完整近月 Call / Put 期权链","选择到期日和方向查看全部可用合约；快照数据明确标注采集时间。")
        chain_controls=st.columns([1,1,3])
        with chain_controls[0]:
            chosen_expiry=st.selectbox("到期日",sorted(chain["Expiration"].astype(str).unique()),key="full_chain_expiry")
        with chain_controls[1]:
            chosen_type=st.selectbox("方向",["Call","Put","All"],key="full_chain_type")
        shown=chain[chain["Expiration"].astype(str).eq(chosen_expiry)].copy()
        if chosen_type!="All": shown=shown[shown["Type"].eq(chosen_type)]
        shown=shown[shown["strike"].between(spot*.70,spot*1.30)] if np.isfinite(spot) else shown
        columns={"contractSymbol":"Contract","Type":"Type","strike":"Strike","bid":"Bid","ask":"Ask","lastPrice":"Last","volume":"Vol","openInterest":"OI","impliedVolatility":"IV"}
        for column in columns:
            if column not in shown: shown[column]=np.nan
        shown=shown[list(columns)].rename(columns=columns).sort_values("Strike")
        shown["IV"]=shown["IV"]*100
        st.dataframe(shown.style.format({"Strike":"${:,.2f}","Bid":"${:,.2f}","Ask":"${:,.2f}","Last":"${:,.2f}","Vol":"{:,.0f}","OI":"{:,.0f}","IV":"{:.1f}%"},na_rep="—"),use_container_width=True,hide_index=True,height=470)
        st.caption("方法限制：Yahoo 链不提供 Delta 与逐笔买卖方向，因此本页使用 ±4% OTM IV 作为 25-Delta Skew 近似；Volume/OI 不能证明主动买入或新开仓。")

with tab_flow:
    flow_head,flow_control=st.columns([5,1.2],vertical_alignment="bottom")
    with flow_head:
        section_header("PRIMARY MARKET FLOW","08 ETF 一级市场份额追踪","TQQQ / SOXL 杠杆资金与 QQQ / SPY 基石资本；Daily Flow = ΔShares × Prior NAV。")
    with flow_control:
        flow_symbol=st.selectbox("ETF 选择器",list(PRIMARY_FLOW_ETFS),key="leveraged_flow_symbol",
            format_func=lambda value:PRIMARY_FLOW_ETFS[value]["label"])
    flow_frame=flow_snapshots.get(flow_symbol,pd.DataFrame())
    if flow_symbol not in flow_snapshots:
        try: flow_frame=load_primary_flow(flow_symbol)
        except Exception: flow_frame=pd.DataFrame()
    if flow_frame.empty:
        st.warning(f"{flow_symbol} 价格序列暂时不可用，稍后刷新即可；系统不会以成交量估算申赎。")
    else:
        flow_meta=PRIMARY_FLOW_ETFS[flow_symbol]; extreme_threshold=float(flow_meta["threshold"])
        valid_flow=flow_frame.dropna(subset=["DailyFlow"]); latest_flow=float(valid_flow["DailyFlow"].iloc[-1])
        flow_source=str(flow_frame["Source"].iloc[-1]) if "Source" in flow_frame else "UNKNOWN"
        verified_shares=bool(flow_frame["HasVerifiedShares"].iloc[-1]) if "HasVerifiedShares" in flow_frame else False
        official_asof=pd.to_datetime(flow_frame["OfficialAsOf"].iloc[-1],errors="coerce") if "OfficialAsOf" in flow_frame else pd.NaT
        logger_status=str(flow_frame["LoggerStatus"].iloc[-1]) if "LoggerStatus" in flow_frame else "LOGGER UNKNOWN"
        record_count=int(flow_frame["RecordCount"].iloc[-1]) if "RecordCount" in flow_frame else 0
        window=valid_flow.tail(60); close_low=float(window["Close"].min()); close_high=float(window["Close"].max())
        price_low_zone=float(window["Close"].iloc[-1])<=close_low+.20*max(close_high-close_low,0)
        latest_is_official=bool(window["HasOfficialRecord"].iloc[-1]) if "HasOfficialRecord" in window else False
        flow_new_high=latest_flow>0 and latest_flow>=float(window["DailyFlow"].max())
        divergence=verified_shares and latest_is_official and price_low_zone and flow_new_high
        def compact_dollar(value: float) -> str:
            if not np.isfinite(value): return "N/A"
            return f"${value/1e9:+,.2f}B" if abs(value)>=1e9 else f"${value/1e6:+,.1f}M"
        flow_cards=st.columns(4)
        flow_cards[0].metric("LATEST VERIFIED FLOW",compact_dollar(latest_flow) if verified_shares else "N/A")
        flow_cards[1].metric("60D MAX INFLOW",compact_dollar(float(window["DailyFlow"].max())) if verified_shares else "N/A")
        flow_cards[2].metric("PRICE · 60D POSITION",f"${window['Close'].iloc[-1]:,.2f}","LOW ZONE" if price_low_zone else "MID / HIGH RANGE",delta_color="off")
        flow_cards[3].metric("DIVERGENCE","🔥 极端底背离·吸筹确认" if divergence else "NO CONFIRMATION",delta_color="off")
        if verified_shares:
            asof_text=official_asof.strftime("%Y-%m-%d") if pd.notna(official_asof) else "N/A"
            st.success(f"数据层：{flow_source} · 份额/NAV 截至 {asof_text} · {record_count:,} 条有效记录 · {logger_status}。未发布日期固定为 $0。")
        else:
            st.info(f"{flow_symbol} 尚无可验证的 Shares Outstanding 记录（{logger_status}）；流量柱严格保持 $0，仅展示市场价格，不进行任何成交量代理。")
        flow_fig=make_subplots(specs=[[{"secondary_y":True}]])
        scale=1e9 if max(float(flow_frame["DailyFlow"].abs().max()),extreme_threshold)>=1e9 else 1e6
        unit="B" if scale==1e9 else "M"; flow_scaled=flow_frame["DailyFlow"]/scale; threshold_scaled=extreme_threshold/scale
        bar_colors=np.where(flow_frame["DailyFlow"]>=extreme_threshold,"#f6c453",
            np.where(flow_frame["DailyFlow"]<=-extreme_threshold,"#ff365f",
                     np.where(flow_frame["DailyFlow"]>=0,"#31d6a0","#b9435a")))
        flow_fig.add_trace(go.Bar(x=flow_frame.index,y=flow_scaled,name="Verified Daily Primary Flow",marker_color=bar_colors,
            hovertemplate=f"%{{x|%Y-%m-%d}}<br>Flow $%{{y:+,.2f}}{unit}<extra></extra>"),secondary_y=False)
        flow_fig.add_trace(go.Scatter(x=flow_frame.index,y=flow_frame["Close"],name=f"{flow_symbol} Close",
            line=dict(color="#5aa2ff",width=2.2),hovertemplate="%{x|%Y-%m-%d}<br>Close $%{y:.2f}<extra></extra>"),secondary_y=True)
        if "NAV" in flow_frame and flow_frame["NAV"].notna().any():
            flow_fig.add_trace(go.Scatter(x=flow_frame.index,y=flow_frame["NAV"],name="Official NAV",
                line=dict(color="#f6c453",width=1.5,dash="dot"),hovertemplate="%{x|%Y-%m-%d}<br>NAV $%{y:.4f}<extra></extra>"),secondary_y=True)
        base_layout(flow_fig,600,"x unified")
        threshold_label=compact_dollar(extreme_threshold).replace("+","")
        flow_fig.add_hline(y=threshold_scaled,line_dash="dash",line_color="#f6c453",annotation_text=f"+{threshold_label} EXTREME")
        flow_fig.add_hline(y=-threshold_scaled,line_dash="dash",line_color="#ff5874",annotation_text=f"-{threshold_label} EXTREME")
        positive_events=flow_frame.loc[flow_frame["DailyFlow"].ge(extreme_threshold),"DailyFlow"]/scale
        negative_events=flow_frame.loc[flow_frame["DailyFlow"].le(-extreme_threshold),"DailyFlow"]/scale
        positive_text="🔥 主权级战略托底" if flow_symbol in ("QQQ","SPY") else "🔥 极端抄底流入"
        negative_text="⚠️ 机构级巨量撤资" if flow_symbol in ("QQQ","SPY") else "⚠️ 极端净赎回"
        for event_date,event_value in positive_events.tail(5).items():
            flow_fig.add_annotation(x=event_date,y=event_value,text=positive_text,
                showarrow=True,arrowhead=2,arrowcolor="#f6c453",font=dict(color="#f6c453",size=10),ax=0,ay=-32)
        for event_date,event_value in negative_events.tail(5).items():
            flow_fig.add_annotation(x=event_date,y=event_value,text=negative_text,
                showarrow=True,arrowhead=2,arrowcolor="#ff5874",font=dict(color="#ff7187",size=10),ax=0,ay=32)
        flow_fig.update_yaxes(title=f"Verified Creation / Redemption · ${unit}",secondary_y=False)
        flow_fig.update_yaxes(title="NAV / Adjusted Close",secondary_y=True)
        st.plotly_chart(flow_fig,use_container_width=True,config={"displaylogo":False,"scrollZoom":True})
        st.caption(f"严格口径：仅使用已记录的 Shares Outstanding 与 NAV；无记录或接口失败日期流量为 0。{flow_meta['class']} 极端阈值 {threshold_label}。成交量、涨跌幅与 signed-dollar-volume 均不参与计算。")

with tab_circuit:
    section_header("SYSTEMIC RISK LOCKS","Circuit Breakers · 宏观与系统风控","三把安全锁：指数200SMA、信用风险偏好、VIX期限结构。")
    risk_cards=st.columns(3)
    risk_cards[0].metric("200 SMA TREND LOCK","🚨 LOCKED" if breakers["broken"] else "🟢 OPEN",
                         "破位："+("、".join(breakers["broken"]) if breakers["broken"] else "无"),delta_color="off")
    risk_cards[1].metric("CREDIT LIQUIDITY","⚠️ 收紧" if breakers["credit_warning"] else "🟢 正常",
                         format_num(float(breakers["credit_change"]))+" · HYG/LQD 20D",delta_color="off")
    risk_cards[2].metric("VIX TERM STRUCTURE","🚨 倒挂" if breakers["vix_inverted"] else "🟢 正向",
                         "N/A" if not np.isfinite(float(breakers["vix_ratio"])) else f"VIX/VIX3M {breakers['vix_ratio']:.3f}",delta_color="off")
    if breakers["credit_warning"]: st.warning("⚠️ 信用市场流动性收紧：HYG/LQD 跌破50日均线且20日动量为负。")
    if breakers["vix_inverted"]: st.error("🚨 波动率倒挂：VIX / VIX3M >= 1.0，全市场防范无差别踩踏。")
    risk_left,risk_right=st.columns(2,gap="medium")
    with risk_left:
        section_header("TREND & CREDIT","Index Trend Lock / Credit Ratio","指数归一化趋势与 HYG/LQD 信用风险偏好。")
        risk_fig=make_subplots(rows=2,cols=1,shared_xaxes=True,vertical_spacing=.10)
        for ticker,color in (("SPY","#31d6a0"),("QQQ","#4f86d9")):
            s=prices[ticker].dropna().tail(504); rebased=s/s.iloc[0]*100; sma=s.rolling(200,min_periods=200).mean()/s.iloc[0]*100
            risk_fig.add_trace(go.Scatter(x=s.index,y=rebased,name=ticker,line=dict(color=color,width=2)),row=1,col=1)
            risk_fig.add_trace(go.Scatter(x=s.index,y=sma,name=f"{ticker} 200SMA",line=dict(color=color,width=1,dash="dash")),row=1,col=1)
        credit=prices[["HYG","LQD"]].dropna(); credit_ratio=credit["HYG"].div(credit["LQD"]).tail(504)
        risk_fig.add_trace(go.Scatter(x=credit_ratio.index,y=credit_ratio,name="HYG/LQD",line=dict(color="#f0a13a",width=2)),row=2,col=1)
        risk_fig.add_trace(go.Scatter(x=credit_ratio.index,y=credit_ratio.rolling(50).mean(),name="50D",line=dict(color="#a8adb5",width=1.3,dash="dash")),row=2,col=1)
        base_layout(risk_fig,600,"x unified"); risk_fig.update_yaxes(title="Rebased 100",row=1,col=1); risk_fig.update_yaxes(title="HYG/LQD",row=2,col=1)
        st.plotly_chart(risk_fig,use_container_width=True,config={"displaylogo":False})
    with risk_right:
        section_header("VOLATILITY CURVE","VIX / VIX3M Term Structure","比率 >= 1 表示现货波动率高于三个月期限波动率。")
        vix_pair=prices[["^VIX","^VIX3M"]].dropna().tail(504) if {"^VIX","^VIX3M"}.issubset(prices.columns) else pd.DataFrame()
        if vix_pair.empty:
            st.warning("VIX3M 数据暂不可用。")
        else:
            vol_fig=make_subplots(rows=2,cols=1,shared_xaxes=True,vertical_spacing=.10)
            vol_fig.add_trace(go.Scatter(x=vix_pair.index,y=vix_pair["^VIX"],name="VIX",line=dict(color="#ff5874",width=2)),row=1,col=1)
            vol_fig.add_trace(go.Scatter(x=vix_pair.index,y=vix_pair["^VIX3M"],name="VIX3M",line=dict(color="#4f86d9",width=2)),row=1,col=1)
            term_ratio=vix_pair["^VIX"].div(vix_pair["^VIX3M"])
            vol_fig.add_trace(go.Scatter(x=term_ratio.index,y=term_ratio,name="VIX/VIX3M",fill="tozeroy",line=dict(color="#f0a13a",width=2)),row=2,col=1)
            vol_fig.add_hline(y=1,line_dash="dash",line_color="#ff5874",annotation_text="INVERSION",row=2,col=1)
            base_layout(vol_fig,600,"x unified"); vol_fig.update_yaxes(title="Vol Index",row=1,col=1); vol_fig.update_yaxes(title="Ratio",row=2,col=1,range=[max(.5,float(term_ratio.min())*.95),max(1.15,float(term_ratio.max())*1.05)])
            st.plotly_chart(vol_fig,use_container_width=True,config={"displaylogo":False})

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

with tab_xray:
    section_header("LOOK-THROUGH RISK","ETF X-RAY · 底层真实杠杆敞口穿透器",
                   "发行商持仓优先；输入为组合资金权重，名义权重不含杠杆，有效 Beta 敞口按 ETF 倍数放大。")
    allocator=st.columns(4)
    allocation={
        "TQQQ":allocator[0].number_input("TQQQ · 3x 纳指 (%)",0.0,100.0,30.0,1.0,key="xray_tqqq"),
        "SOXL":allocator[1].number_input("SOXL · 3x 半导体 (%)",0.0,100.0,20.0,1.0,key="xray_soxl"),
        "QQQ":allocator[2].number_input("QQQ · 纳指基准 (%)",0.0,100.0,30.0,1.0,key="xray_qqq"),
        "CASH":allocator[3].number_input("现金 (%)",0.0,100.0,20.0,1.0,key="xray_cash"),
    }
    allocation_sum=sum(allocation.values())
    if abs(allocation_sum-100)>.01:
        st.warning(f"当前权重合计 {allocation_sum:.1f}%，请调整至 100%；下方仍按输入原值计算，不进行隐式归一化。")
    qqq_holdings,qqq_source=load_etf_holdings("QQQ"); soxx_holdings,soxx_source=load_etf_holdings("SOXX")
    exposure_rows=[]
    for portfolio_etf,lookthrough,leverage in (("TQQQ",qqq_holdings,3.0),("SOXL",soxx_holdings,3.0),("QQQ",qqq_holdings,1.0)):
        portfolio_weight=allocation[portfolio_etf]/100
        for _,holding in lookthrough.iterrows():
            constituent_weight=float(holding["Weight"])/100
            exposure_rows.append({"Ticker":holding["Ticker"],"Name":holding["Name"],
                "Nominal":portfolio_weight*constituent_weight,"Effective":portfolio_weight*leverage*constituent_weight,
                "Source ETF":portfolio_etf})
    exposure=pd.DataFrame(exposure_rows)
    if exposure.empty:
        st.warning("底层持仓暂不可用。")
    else:
        aggregate=exposure.groupby(["Ticker","Name"],as_index=False)[["Nominal","Effective"]].sum()
        aggregate["实际名义权重 (%)"]=aggregate["Nominal"]*100
        aggregate["有效 Beta 敞口 (%)"]=aggregate["Effective"]*100
        aggregate["集中度风险"]=np.where(aggregate["有效 Beta 敞口 (%)"]>25,"⚠️ 单一个股杠杆集中度过高","🟢 可控")
        aggregate=aggregate.sort_values("有效 Beta 敞口 (%)",ascending=False)
        gross_beta=(allocation["TQQQ"]*3+allocation["SOXL"]*3+allocation["QQQ"])/100
        top_effective=float(aggregate["有效 Beta 敞口 (%)"].iloc[0]); top_name=str(aggregate["Ticker"].iloc[0])
        xray_cards=st.columns(4)
        xray_cards[0].metric("PORTFOLIO ALLOCATION",f"{allocation_sum:.1f}%",delta_color="off")
        xray_cards[1].metric("GROSS BETA EXPOSURE",f"{gross_beta:.2f}x",delta_color="off")
        xray_cards[2].metric("TOP LOOK-THROUGH",top_name,f"{top_effective:.2f}% effective",delta_color="off")
        xray_cards[3].metric("CONCENTRATION LOCK","🚨 HIGH" if top_effective>25 else "🟢 CONTROLLED",delta_color="off")
        table_col,chart_col=st.columns([1.0,1.15],gap="medium")
        with table_col:
            section_header("CORE HOLDINGS","组合穿透前十大核心重仓股","同一股票在 QQQ 与半导体篮子中的敞口合并计算。")
            output=aggregate.head(10)[["Ticker","Name","实际名义权重 (%)","有效 Beta 敞口 (%)","集中度风险"]]
            style=output.style.format({"实际名义权重 (%)":"{:.2f}%","有效 Beta 敞口 (%)":"{:.2f}%"}).map(
                lambda value:"color:#ff5874;font-weight:700" if str(value).startswith("⚠️") else "color:#31d6a0",subset=["集中度风险"])
            st.dataframe(style,use_container_width=True,hide_index=True,height=430)
        with chart_col:
            section_header("LEVERAGE MAP","Nominal vs Effective Exposure","橙色为投入资本穿透，青色为考虑 3 倍杠杆后的有效 Beta 冲击。")
            top=aggregate.head(10).sort_values("有效 Beta 敞口 (%)")
            xray_fig=go.Figure()
            xray_fig.add_trace(go.Bar(y=top["Ticker"],x=top["实际名义权重 (%)"],orientation="h",name="Nominal Weight",marker_color="#f0a13a"))
            xray_fig.add_trace(go.Bar(y=top["Ticker"],x=top["有效 Beta 敞口 (%)"],orientation="h",name="Effective Beta",marker_color="#35d5ff"))
            xray_fig.add_vline(x=25,line_dash="dash",line_color="#ff5874",annotation_text="25% CONCENTRATION")
            base_layout(xray_fig,430,"y unified"); xray_fig.update_layout(barmode="group"); xray_fig.update_xaxes(title="Portfolio Exposure (%)")
            st.plotly_chart(xray_fig,use_container_width=True,config={"displaylogo":False})
        st.caption(f"QQQ 底层来源：{qqq_source} · SOXL 使用 SOXX 穿透，来源：{soxx_source}。发行商接口失败时会明确标记为内置参考基准；不会伪装成实时持仓。")

with tab_deep:
    section_header("MACRO FINANCIAL CONDITIONS","Macro Deep Dive · FRED 宏观金融压力与真实通胀",
                   "免 API Key 直连 FRED / OFR 官方 CSV；失败时回退至随应用发布的注明日期的历史快照。")
    fred_ids=("NFCI","OFRFSI","PCETRIM12M159SFRBDAL","PCETRIM1M158SFRBDAL","PCEPILFE","PCEPI","PI","PCE")
    fred,fred_status=load_fred_series(fred_ids)
    offline_ids=[series_id for series_id,source in fred_status.items() if source=="offline"]
    unavailable_ids=[series_id for series_id,source in fred_status.items() if source=="unavailable"]
    if offline_ids:
        offline_dates=[f"{series_id} {fred[series_id].dropna().index[-1]:%Y-%m-%d}" for series_id in offline_ids]
        st.caption("离线基准（非实时）："+" · ".join(offline_dates)+"。网络恢复后将优先使用官方新值。")
    if unavailable_ids:
        st.info("以下序列本次不可用："+", ".join(unavailable_ids)+"。")
    macro_left,macro_right=st.columns(2,gap="medium")
    with macro_left:
        nfci=fred["NFCI"].dropna() if "NFCI" in fred else pd.Series(dtype=float)
        latest_nfci=float(nfci.iloc[-1]) if not nfci.empty else np.nan
        section_header("FINANCIAL CONDITIONS",f"NFCI · Current {'N/A' if not np.isfinite(latest_nfci) else f'{latest_nfci:+.3f}'}",
                       "0 为历史中性；负值表示金融条件偏宽松，正值表示偏收紧。")
        if nfci.empty: st.info("NFCI 暂不可用。")
        else:
            view=nfci[nfci.index>=nfci.index[-1]-pd.Timedelta(days=365)]
            nfci_fig=go.Figure(go.Scatter(x=view.index,y=view,mode="lines",name="NFCI",fill="tozeroy",
                line=dict(color="#31d6a0" if latest_nfci<0 else "#ff5874",width=2.2)))
            nfci_fig.add_hline(y=0,line_dash="dash",line_color="#9aa8b9",annotation_text="NEUTRAL")
            base_layout(nfci_fig,420,"x unified"); nfci_fig.update_yaxes(title="NFCI")
            st.plotly_chart(nfci_fig,use_container_width=True,config={"displaylogo":False})
    with macro_right:
        ofr=fred["OFRFSI"].dropna() if "OFRFSI" in fred else pd.Series(dtype=float)
        latest_ofr=float(ofr.iloc[-1]) if not ofr.empty else np.nan
        section_header("SYSTEMIC STRESS",f"OFR Financial Stress Index · Current {'N/A' if not np.isfinite(latest_ofr) else f'{latest_ofr:+.2f}'}",
                       "0 为中性压力；+2 为本面板的战术高压警戒线。")
        if ofr.empty: st.info("OFR FSI 暂不可用。")
        else:
            view=ofr[ofr.index>=ofr.index[-1]-pd.Timedelta(days=365)]
            ofr_fig=go.Figure(go.Scatter(x=view.index,y=view,mode="lines",name="OFR FSI",fill="tozeroy",line=dict(color="#f0a13a",width=2.2)))
            ofr_fig.add_hline(y=0,line_dash="dash",line_color="#9aa8b9",annotation_text="NEUTRAL")
            ofr_fig.add_hline(y=2,line_dash="dot",line_color="#ff5874",annotation_text="EXTREME STRESS")
            base_layout(ofr_fig,420,"x unified"); ofr_fig.update_yaxes(title="OFR FSI")
            st.plotly_chart(ofr_fig,use_container_width=True,config={"displaylogo":False})
    section_header("INFLATION TAPE","Inflation · Last 12 Monthly Releases",
                   "Headline/Core 为价格指数同比；Trimmed Mean 采用 Dallas Fed 官方序列；收入与支出为环比。每行独立着色，绿色为该行低位、红色为高位。")
    inflation=inflation_release_table(fred)
    if inflation.empty:
        st.info("通胀与收支月度序列暂不可用。")
    else:
        st.dataframe(heat_style_table(inflation),use_container_width=True,height=285)
        st.caption("单位：% · 6M Trimmed Mean 由官方 1M 年化序列按复合方式计算。FRED 数据发布存在月度/周度时滞，标题中的当前值指各自最后有效发布日期。")

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

st.caption(f"DATA {latest_date:%Y-%m-%d} · SOURCE YAHOO FINANCE · LIVE PULSE CACHE 45S · RESEARCH CACHE 15M · STATIC SECTOR / CONSTITUENT WEIGHTS ARE VISUAL PROXIES · FOR RESEARCH ONLY, NOT INVESTMENT ADVICE")
