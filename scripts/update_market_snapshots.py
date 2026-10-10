"""Persist issuer-confirmed ETF shares and dated Yahoo option-chain snapshots.

Run from the repository root. Missing issuer fields never become synthetic flows.
Each source fails independently so a transient outage preserves the last good file.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from io import BytesIO, StringIO
from pathlib import Path
import html
import json
import re
import time
import zipfile
from xml.etree import ElementTree as ET

import pandas as pd
import requests
import yfinance as yf


ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
DATA.mkdir(exist_ok=True)
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; BuySideQuantPortal/1.0)"}
FLOW_COLUMNS = ["date", "shares_outstanding", "nav", "source_url", "source_note"]
OPTION_SYMBOLS = ("QQQ", "SPY", "SMH", "SOXX", "NVDA", "TSLA", "MU", "ITA", "XLE")
SECTOR_SHARE_SYMBOLS = ("XLK", "XLE", "XLF", "XLI", "XLY", "XLC", "XLV", "XLP", "XLU", "XLRE", "XLB")
OPTION_COLUMNS = ["Symbol", "SnapshotAtUTC", "SpotAtCapture", "Expiration", "Type",
                  "contractSymbol", "strike", "lastPrice", "bid", "ask", "volume",
                  "openInterest", "impliedVolatility", "inTheMoney"]


def normalize(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty:
        return pd.DataFrame(columns=FLOW_COLUMNS)
    frame = frame.copy()
    for column in FLOW_COLUMNS:
        if column not in frame:
            frame[column] = ""
    frame["date"] = pd.to_datetime(frame["date"], errors="coerce").dt.strftime("%Y-%m-%d")
    for column in ("shares_outstanding", "nav"):
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    frame = frame.dropna(subset=["date", "shares_outstanding", "nav"])
    frame = frame[frame["shares_outstanding"].gt(0) & frame["nav"].gt(0)]
    return frame[FLOW_COLUMNS].sort_values("date").drop_duplicates("date", keep="last").reset_index(drop=True)


def get(url: str, timeout: int = 25) -> bytes:
    response = requests.get(url, headers=HEADERS, timeout=timeout)
    response.raise_for_status()
    return response.content


def xlsx_rows(payload: bytes) -> list[list[object]]:
    """Read the first worksheet without an optional Excel engine dependency."""
    ns = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
    with zipfile.ZipFile(BytesIO(payload)) as book:
        strings = []
        if "xl/sharedStrings.xml" in book.namelist():
            strings_root = ET.fromstring(book.read("xl/sharedStrings.xml"))
            strings = ["".join(node.itertext()) for node in strings_root.findall("m:si", ns)]
        sheet = ET.fromstring(book.read("xl/worksheets/sheet1.xml"))
    rows = []
    for row in sheet.findall(".//m:sheetData/m:row", ns):
        values = []
        for cell in row.findall("m:c", ns):
            ref = cell.attrib.get("r", "A1")
            letters = re.match(r"[A-Z]+", ref)
            index = 0
            for letter in letters.group(0) if letters else "A":
                index = index * 26 + ord(letter) - 64
            while len(values) < index:
                values.append(None)
            value = cell.find("m:v", ns)
            inline = cell.find("m:is", ns)
            raw = value.text if value is not None else "".join(inline.itertext()) if inline is not None else None
            if cell.attrib.get("t") == "s" and raw is not None:
                raw = strings[int(raw)]
            values[index - 1] = raw
        rows.append(values)
    return rows


def issuer_records(symbol: str) -> pd.DataFrame:
    if symbol in SECTOR_SHARE_SYMBOLS:
        url = f"https://www.ssga.com/library-content/products/fund-data/etfs/us/navhist-us-en-{symbol.lower()}.xlsx"
        rows = xlsx_rows(get(url))
        index = next((i for i, row in enumerate(rows)
            if any(str(item).strip().lower() == "date" for item in row if item is not None)), None)
        if index is None:
            return pd.DataFrame(columns=FLOW_COLUMNS)
        header = [str(item).strip() if item is not None else "" for item in rows[index]]
        raw = pd.DataFrame(rows[index + 1:]).iloc[:, :len(header)]
        raw.columns = header[:len(raw.columns)]
        if not {"Date", "Shares Outstanding", "NAV"}.issubset(raw.columns):
            return pd.DataFrame(columns=FLOW_COLUMNS)
        return normalize(pd.DataFrame({"date": raw["Date"],
            "shares_outstanding": pd.to_numeric(raw["Shares Outstanding"], errors="coerce"),
            "nav": pd.to_numeric(raw["NAV"], errors="coerce"),
            "source_url": url, "source_note": "State Street official daily NAV/share history"})).tail(300)
    if symbol == "TQQQ":
        url = "https://accounts.profunds.com/etfdata/ByFund/TQQQ-historical_nav.csv"
        raw = pd.read_csv(StringIO(get(url).decode("utf-8-sig", errors="replace")))
        return normalize(pd.DataFrame({"date": raw.get("Date"),
            "shares_outstanding": pd.to_numeric(raw.get("Shares Outstanding (000)"), errors="coerce") * 1000,
            "nav": raw.get("NAV"), "source_url": url, "source_note": "ProShares official daily NAV file"}))
    if symbol == "SPY":
        url = "https://www.ssga.com/library-content/products/fund-data/etfs/us/navhist-us-en-spy.xlsx"
        rows = xlsx_rows(get(url))
        index = next(i for i, row in enumerate(rows) if row and str(row[0]).strip().lower() == "date")
        headers = [str(item).strip() if item is not None else "" for item in rows[index]]
        raw = pd.DataFrame(rows[index + 1:], columns=headers)
        dates = raw.get("Date")
        if dates is not None:
            numeric = pd.to_numeric(dates, errors="coerce")
            dates = dates.where(numeric.isna(), pd.to_datetime(numeric, unit="D", origin="1899-12-30", errors="coerce"))
        return normalize(pd.DataFrame({"date": dates, "shares_outstanding": raw.get("Shares Outstanding"),
            "nav": raw.get("NAV"), "source_url": url, "source_note": "State Street official SPY NAV history"}))
    if symbol == "QQQ":
        url = ("https://dng-api.invesco.com/cache/v1/accounts/en_US/shareclasses/46090E103/prices"
               "?idType=cusip&productType=ETF&variationType=priceListing&productSubType=ETF")
        payload = json.loads(get(url).decode("utf-8", errors="replace"))
        return normalize(pd.DataFrame([{"date": payload.get("effectiveDate"),
            "shares_outstanding": payload.get("sharesOutstanding"), "nav": payload.get("nav"),
            "source_url": url, "source_note": "Invesco official QQQ prices API"}]))
    if symbol == "SOXL":
        url = "https://www.direxion.com/product/daily-semiconductor-bull-bear-3x-etfs"
        page = get(url).decode("utf-8", errors="replace")
        match = re.search(r'<script[^>]+id=["\']__NEXT_DATA__["\'][^>]*>(.*?)</script>', page, re.S | re.I)
        payload = json.loads(html.unescape(match.group(1))) if match else {}
        candidates = []
        def collect(item: object) -> None:
            if isinstance(item, dict):
                if str(item.get("Ticker", item.get("ticker", ""))).upper() == "SOXL":
                    candidates.append(item)
                for value in item.values(): collect(value)
            elif isinstance(item, list):
                for value in item: collect(value)
        def number(item: object, keys: set[str]) -> float | None:
            if isinstance(item, dict):
                for key, value in item.items():
                    if re.sub(r"[^a-z]", "", key.lower()) in keys:
                        try: return float(str(value).replace(",", ""))
                        except (TypeError, ValueError): pass
                for value in item.values():
                    found = number(value, keys)
                    if found is not None: return found
            if isinstance(item, list):
                for value in item:
                    found = number(value, keys)
                    if found is not None: return found
            return None
        collect(payload)
        fund = candidates[0] if candidates else {}
        shares = number(fund, {"sharesoutstanding", "outstandingshares"})
        nav = number(fund, {"nav", "netassetvalue"})
        raw_date = str(fund.get("Pricing", {}).get("TradeDate", fund.get("TradeDate", ""))) if fund else ""
        observed = pd.to_datetime(raw_date, format="%m%d%Y", errors="coerce")
        return normalize(pd.DataFrame([{"date": observed, "shares_outstanding": shares, "nav": nav,
            "source_url": url, "source_note": "Direxion official product page"}]))
    return pd.DataFrame(columns=FLOW_COLUMNS)


def save_issuer_history(symbol: str) -> None:
    path = DATA / f"{symbol.lower()}_flow_history.csv"
    existing = pd.read_csv(path) if path.exists() and path.stat().st_size else pd.DataFrame(columns=FLOW_COLUMNS)
    incoming = issuer_records(symbol)
    if incoming.empty:
        print(f"{symbol}: no issuer-confirmed shares+NAV; preserving history")
        return
    prior = normalize(existing)
    combined = normalize(pd.concat([prior, incoming], ignore_index=True))
    if symbol in SECTOR_SHARE_SYMBOLS:
        combined = combined.tail(300).reset_index(drop=True)
    if not combined.equals(prior):
        combined.to_csv(path, index=False)
    print(f"{symbol}: {len(incoming)} verified observations, {len(combined)} retained")


def option_snapshot(symbol: str) -> pd.DataFrame:
    ticker = yf.Ticker(symbol)
    try:
        spot = float(ticker.fast_info["last_price"])
    except Exception:
        spot = float(ticker.history(period="5d")["Close"].dropna().iloc[-1])
    if not 0 < spot < float("inf"):
        return pd.DataFrame(columns=OPTION_COLUMNS)
    today = datetime.now(timezone.utc).date()
    expiries = [expiry for expiry in ticker.options
                if 7 <= (pd.Timestamp(expiry).date() - today).days <= 30][:2]
    frames = []
    stamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
    for expiry in expiries:
        try:
            chain = ticker.option_chain(expiry)
            for kind, source in (("Call", chain.calls), ("Put", chain.puts)):
                frame = source.copy()
                frame["strike"] = pd.to_numeric(frame["strike"], errors="coerce")
                frame = frame[frame["strike"].between(spot * .70, spot * 1.30)]
                if frame.empty: continue
                frame["Symbol"] = symbol
                frame["SnapshotAtUTC"] = stamp
                frame["SpotAtCapture"] = spot
                frame["Expiration"] = expiry
                frame["Type"] = kind
                for column in OPTION_COLUMNS:
                    if column not in frame: frame[column] = pd.NA
                frames.append(frame[OPTION_COLUMNS])
        except Exception as exc:
            print(f"{symbol} {expiry}: option chain unavailable ({type(exc).__name__})")
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(columns=OPTION_COLUMNS)


def save_options() -> None:
    path = DATA / "options_chain_latest.csv"
    previous = pd.read_csv(path) if path.exists() and path.stat().st_size else pd.DataFrame(columns=OPTION_COLUMNS)
    fresh = []
    succeeded = set()
    for symbol in OPTION_SYMBOLS:
        try:
            frame = option_snapshot(symbol)
            if not frame.empty:
                fresh.append(frame)
                succeeded.add(symbol)
                print(f"{symbol}: {len(frame)} option contracts captured")
            else:
                print(f"{symbol}: no eligible chain; preserving prior snapshot")
        except Exception as exc:
            print(f"{symbol}: option source failed ({type(exc).__name__}); preserving prior snapshot")
        time.sleep(.4)
    if not fresh:
        return
    old = previous[~previous["Symbol"].isin(succeeded)] if not previous.empty else previous
    result = pd.concat([old, *fresh], ignore_index=True)
    result.to_csv(path, index=False)


if __name__ == "__main__":
    for ticker_symbol in (*SECTOR_SHARE_SYMBOLS, "TQQQ", "SOXL", "QQQ", "SPY"):
        try:
            save_issuer_history(ticker_symbol)
        except Exception as error:
            print(f"{ticker_symbol}: issuer source failed ({type(error).__name__}); preserving history")
    save_options()
