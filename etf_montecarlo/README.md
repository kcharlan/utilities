# ETF Dividend Monte Carlo
Bootstrap historical Yahoo Finance dividend data to forecast the distribution of income for a basket of ETFs. Two variants are provided:

- `etf-montecarlo.py` – Per-share forecasts with optional share counts supplied at runtime.
- `etf2-montecarlo.py` – Same engine pre-filled with portfolio share counts for a quick personal run.

## Environment

```bash
python3 -m venv venv
source venv/bin/activate
pip install yfinance pandas numpy tqdm
```

Yahoo Finance requests quickly, so no API keys are needed. The scripts assume network access.

## Inputs

Edit the configuration block at the top of the script:

```python
tickers = ["JEPI", "ITWO", "SDIV", "ULTY", "XDTE", "SPYI"]
years_of_history = 5          # lookback window
runs_per_ticker = 10_000      # Monte-Carlo paths
target_horizon = "1Y"         # informational, not yet enforced
share_counts = {"JEPI": 1800, ...}  # optional
```

## How It Works

1. Pulls dividend history for each ticker via `yfinance.Ticker.dividends`.
2. Restricts to the trailing `years_of_history`.
3. Estimates typical payment frequency by median dividend count per year.
4. Runs an empirical bootstrap:
   - Draws `freq_per_year` dividends with replacement for each path.
   - Sums to annual income.
5. Reports percentile bands (P10–P90) both per share and scaled by supplied share counts.

The output is a formatted DataFrame printed to stdout.

## Running

```bash
python etf-montecarlo.py
# or
python etf2-montecarlo.py
```

## Extending

- Adjust `target_horizon` logic if you want to support horizons other than 12 months.
- Persist results to CSV/Parquet by calling `df.to_csv("forecast.csv")`.
- Swap in log-returns or price-based simulations by modifying the main loop—most scaffolding (progress, percentile reporting) is reusable.
