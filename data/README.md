# ETF primary-market data

The files in this directory are the verified baseline and append-only local observations for the **08 PRIMARY ETF FLOW** module.

- `tqqq_historical_shares.csv` contains one year of daily NAV and shares outstanding from the ProShares official historical NAV download. ProShares reports shares in thousands; the checked-in file stores actual shares.
- `spy_shares_baseline.csv` contains the latest 270 official daily observations from State Street's public SPY NAV-history workbook.
- `soxl_shares_baseline.json` is the guarded SOXL baseline patch. Direxion's public product page currently exposes NAV but not a historical daily Shares Outstanding field, so its record list intentionally remains empty until issuer-verifiable values are available.
- `{ticker}_flow_history.csv` is initialized automatically and receives a new row only when the issuer endpoint supplies both NAV and Shares Outstanding for a date not already present.
- QQQ uses Invesco's official public prices API (`CUSIP 46090E103`), which reports the effective date, NAV and Shares Outstanding. The local logger builds its daily history forward from each valid response.
- `soxx_shares_history.csv` starts with the issuer-verified 2026-10-09 SOXX observation and accepts future dated iShares observations. The iShares product page currently exposes a latest-day snapshot, not a downloadable one-year daily shares history.
- `smh_shares_history.csv` is schema-initialized but intentionally contains no observations: VanEck's accessible SMH product page publishes NAV/assets/holdings, not a verified daily shares-outstanding history. Do not derive shares from rounded AUM/NAV or insert synthetic rows. Until a verified source is available, the app shows the SMH price chart and explicitly marks its primary-market flow as unavailable.

Required columns are `date`, `shares_outstanding`, and `nav`. Optional provenance columns are `source_url` and `source_note`.

Primary-market flow is calculated only as:

`(shares_outstanding[t] - shares_outstanding[t-1]) * nav[t-1]`

A trading date without an issuer shares record is explicitly assigned zero flow. Sparse observations more than five calendar days apart are not treated as a one-day flow. Secondary-market volume, price direction, signed-dollar-volume and AUM/NAV-derived share estimates are never used.

Local CSV persistence is durable on a normal local checkout, but Streamlit Community Cloud's runtime filesystem is ephemeral. The scheduled GitHub Actions workflow `.github/workflows/update-market-snapshots.yml` now runs `scripts/update_market_snapshots.py` after US trading days and commits verified issuer observations back to this directory. It also saves dated Yahoo option-chain snapshots (`options_chain_latest.csv`) when available. The app always tries the live chain first and labels a saved snapshot with its UTC capture time; snapshots older than seven days are rejected. GitHub scheduling and public Yahoo data can be delayed or unavailable, so these snapshots are not a guaranteed live feed. SOXL remains unpopulated unless Direxion actually publishes both shares outstanding and NAV; no synthetic history is inserted.
