import yfinance as yf
import numpy as np
import pandas as pd
from datetime import datetime
from tqdm import tqdm

# ------------ user inputs ------------
tickers = ["JEPI", "ITWO", "SDIV", "ULTY", "XDTE", "SPYI"]
years_of_history = 5           # look‑back window
runs_per_ticker  = 10_000      # Monte‑Carlo paths per ETF

# 🆕  Your share counts
share_counts = {
    "JEPI": 1800,
    "ITWO": 2450,
    "SDIV": 5755,
    "ULTY": 4510,
    "XDTE": 640,
    "SPYI": 5060,
}
# -------------------------------------

today = pd.Timestamp.today(tz="UTC")

def empirical_bootstrap(series, n_draws):
    """Draw from the empirical distribution with replacement."""
    return np.random.choice(series, size=n_draws, replace=True)

results = []

for tkr in tqdm(tickers):
    # 1 Grab dividend history
    etf = yf.Ticker(tkr)
    divs = etf.dividends

    if divs.empty:
        print(f"{tkr}: no dividend data found, skipping")
        continue

    # 2 Restrict to the last N years
    cutoff = today - pd.DateOffset(years=years_of_history)
    divs = divs[divs.index >= cutoff]

    # 3 Infer payment frequency
    counts_per_year = divs.groupby(divs.index.year).size().median().round()
    freq_per_year   = int(counts_per_year) or 1

    # 4 Monte‑Carlo
    annual_totals = []
    for _ in range(runs_per_ticker):
        path = empirical_bootstrap(divs.values, freq_per_year).sum()
        annual_totals.append(path)

    annual_totals = np.array(annual_totals)
    q10, q25, q50, q75, q90 = np.percentile(annual_totals, [10, 25, 50, 75, 90])

    shares = share_counts.get(tkr, 1)  # defaults to 1 if you forget a ticker
    results.append({
        "ETF": tkr,
        "P10 $/share":  q10,
        "P25 $/share":  q25,
        "P50 $/share":  q50,
        "P75 $/share":  q75,
        "P90 $/share":  q90,
        "Shares":       shares,
        "P10 $ total":  q10 * shares,
        "P25 $ total":  q25 * shares,
        "P50 $ total":  q50 * shares,
        "P75 $ total":  q75 * shares,
        "P90 $ total":  q90 * shares,
        "Observations": len(divs),
    })

df = pd.DataFrame(results).set_index("ETF")
pd.options.display.float_format = "${:,.2f}".format
print(df)
