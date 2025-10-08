from __future__ import annotations
import typer, pandas as pd, os
from taxkit.tablegen import generate_table

app = typer.Typer(add_completion=False)

@app.command()
def tablegen(rules: str, filing_status: str = "single",
             inc_min: int = 0, inc_max: int = 500000, step: int = 50,
             period: str = "monthly", out: str = "tables/out.parquet"):
    df = generate_table(rules, filing_status, inc_min, inc_max, step, period)
    os.makedirs(os.path.dirname(out), exist_ok=True)
    if out.lower().endswith(".csv"):
        df.to_csv(out, index=False)
    else:
        df.to_parquet(out, index=False)
    typer.echo(f"Saved {len(df)} rows to {out}")

if __name__ == "__main__":
    app()
