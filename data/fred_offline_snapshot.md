# Macro Deep Dive offline snapshot

This file accompanies `fred_offline_snapshot.csv`. It is a **dated, non-live fallback**, not a substitute for the current official releases. On each one-hour cache refresh the app first tries the official endpoints and merges newer observations over these rows.

Sources:

- NFCI, trimmed-mean PCE, PCE price indexes, personal income and spending: FRED series pages `https://fred.stlouisfed.org/series/{SERIES_ID}` and their observation tables.
- OFR Financial Stress Index: Office of Financial Research `https://www.financialresearch.gov/financial-stress-index/data/fsi.csv`. `OFRFSI` is an internal column key in the app, **not** a FRED series ID.

Snapshot coverage as packaged on 2026-10-09: NFCI through 2026-10-02 (five official weekly points); OFR FSI through 2026-10-06 (monthly samples plus the latest observation); monthly inflation and personal-income/spending series through 2026-08. Older NFCI weekly values were unavailable from the checked sources and have not been fabricated. The one-year chart shows the available portion when offline.

The PCE price-index rows start in 2024-08 so that twelve-month inflation changes can be computed for the last twelve monthly releases. Source series can be revised after this snapshot date; the app labels offline readings accordingly.
