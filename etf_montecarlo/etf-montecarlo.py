import yfinance as yf
import numpy as np
import pandas as pd
from datetime import datetime
from tqdm import tqdm

# ------------ user inputs ------------
tickers = ["JEPI", "ITWO", "SDIV", "ULTY", "XDTE", "SPYI"]
years_of_history = 5          # how much history to sample from
runs_per_ticker  = 10_000     # Monte‑Carlo paths
target_horizon   = "1Y"       # '1Y' = next 12 months of income
# (optional) share counts, e.g. {"JEPI": 1800, ...}
share_counts = {}
# -------------------------------------

today = pd.Timestamp.today(tz="UTC")

def empirical_bootstrap(series, n_draws):
    """Draw from the empirical distribution with replacement."""
    return np.random.choice(series, size=n_draws, replace=True)

results = []

for tkr in tqdm(tickers):
    # 2.1  Grab dividend history
    etf = yf.Ticker(tkr)
    divs = etf.dividends

    if divs.empty:
        print(f"{tkr}: no dividend data found, skipping")
        continue

    # 2.2  Restrict to the last N years
    cutoff = today - pd.DateOffset(years=years_of_history)
    divs = divs[divs.index >= cutoff]

    # 2.3  Determine *typical* frequency
    #      Yahoo records cash on the ex‑date, so we infer frequency by counting per year
    counts_per_year = divs.groupby(divs.index.year).size().median().round()
    freq_per_year   = int(counts_per_year) or 1        # avoid zero division

    # 2.4  Monte‑Carlo
    annual_totals = []
    for _ in range(runs_per_ticker):
        path = empirical_bootstrap(divs.values, freq_per_year).sum()
        annual_totals.append(path)

    annual_totals = np.array(annual_totals)
    q = np.percentile(annual_totals, [10, 25, 50, 75, 90])

    shares = share_counts.get(tkr, 1)      # default to *per‑share* if you’ve not supplied counts
    results.append({
        "ETF": tkr,
        "Per‑Share P10": q[0],
        "Per‑Share P25": q[1],
        "Per‑Share P50": q[2],
        "Per‑Share P75": q[3],
        "Per‑Share P90": q[4],
        "Shares (model)": shares,
        "Portfolio $ P10": q[0] * shares,
        "Portfolio $ P25": q[1] * shares,
        "Portfolio $ P50": q[2] * shares,
        "Portfolio $ P75": q[3] * shares,
        "Portfolio $ P90": q[4] * shares,
        "Hist. obs": len(divs)
    })

df = pd.DataFrame(results).set_index("ETF")
pd.options.display.float_format = "${:,.2f}".format
print(df)
