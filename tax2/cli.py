from __future__ import annotations
import typer, pandas as pd, os
from taxkit.tablegen import generate_table
from taxkit.utils import get_available_years, resolve_year, get_rule_path

app = typer.Typer(add_completion=False)

@app.command()
def tablegen(rules: str = None, filing_status: str = "single", year: int = None,
             inc_min: int = 0, inc_max: int = 500000, step: int = 50,
             period: str = "monthly", out: str = "tables/out.parquet"):
    """
    Generate tax tables. 
    If '--rules' is a specific file, it is used.
    If '--rules' is a directory or None, we attempt to find the best rule file based on --year.
    """
    if rules is None:
        # Default to federal rules dir relative to here
        rules = os.path.join(os.path.dirname(__file__), "rules", "federal")
    
    if os.path.isdir(rules):
        # Resolve year
        avail = get_available_years(rules)
        target = year if year else pd.Timestamp.now().year
        
        resolved_year, is_fallback = resolve_year(target, avail)
        if is_fallback and resolved_year != target:
            typer.echo(f"Warning: Rules for {target} not found. Using {resolved_year}.", err=True)
            
        rules = get_rule_path(rules, resolved_year)
        typer.echo(f"Using rules: {rules}")

    df = generate_table(rules, filing_status, inc_min, inc_max, step, period)
    os.makedirs(os.path.dirname(out), exist_ok=True)
    if out.lower().endswith(".csv"):
        df.to_csv(out, index=False)
    else:
        df.to_parquet(out, index=False)
    typer.echo(f"Saved {len(df)} rows to {out}")

if __name__ == "__main__":
    app()
