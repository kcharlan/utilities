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

@app.command("generate-combined")
def generate_combined(year: int = None, state: str = "GA", out_dir: str = "tables",
                      filing_status: str = "single", inc_max: int = 500000, step: int = 50):
    """
    Generate federal and state tables for a given year (or current year) and merge them.
    This replaces the old generate_tables.sh and merge_tables.py scripts.
    """
    # 1. Resolve Year
    # We look at federal rules to determine available years
    fed_rules_dir = os.path.join(os.path.dirname(__file__), "rules", "federal")
    avail = get_available_years(fed_rules_dir)
    target = year if year else pd.Timestamp.now().year
    
    resolved_year, is_fallback = resolve_year(target, avail)
    if is_fallback and resolved_year != target:
        typer.echo(f"Warning: Rules for {target} not found. Using {resolved_year}.", err=True)
    
    typer.echo(f"Generating tables for Tax Year: {resolved_year}")

    # 2. Resolve Paths
    fed_path = get_rule_path(fed_rules_dir, resolved_year)
    
    state_rules_dir = os.path.join(os.path.dirname(__file__), "rules", "states", state)
    state_path = get_rule_path(state_rules_dir, resolved_year)
    
    if not os.path.exists(fed_path):
        typer.echo(f"Error: Federal rules not found at {fed_path}", err=True)
        raise typer.Exit(code=1)
    if not os.path.exists(state_path):
        typer.echo(f"Error: State rules not found at {state_path}", err=True)
        raise typer.Exit(code=1)

    # 3. Generate DataFrames
    typer.echo(f"Processing Federal: {os.path.basename(fed_path)}")
    df_fed = generate_table(fed_path, filing_status, 0, inc_max, step, "monthly")
    
    typer.echo(f"Processing State ({state}): {os.path.basename(state_path)}")
    df_state = generate_table(state_path, filing_status, 0, inc_max, step, "monthly")

    # 4. Save individual files (Parquet)
    os.makedirs(out_dir, exist_ok=True)
    
    fed_out = os.path.join(out_dir, f"federal_{resolved_year}.parquet")
    df_fed.to_parquet(fed_out, index=False)
    
    state_out = os.path.join(out_dir, f"{state.lower()}_{resolved_year}.parquet")
    df_state.to_parquet(state_out, index=False)
    
    # 5. Merge
    # Rename columns for the combined CSV format
    # Expecting: MonthlyIncome, FederalMonthlyTax, StateMonthlyTax
    
    # generate_table returns [MonthlyIncome, MonthlyTax] (plus potentially others, but those are key)
    # Let's ensure we merge on MonthlyIncome
    
    rf = df_fed.rename(columns={"MonthlyTax": "FederalMonthlyTax"})
    rs = df_state.rename(columns={"MonthlyTax": "StateMonthlyTax"})
    
    # Select only relevant columns to avoid conflicts if other cols exist
    rf = rf[["MonthlyIncome", "FederalMonthlyTax"]]
    rs = rs[["MonthlyIncome", "StateMonthlyTax"]]
    
    combined = pd.merge(rf, rs, on="MonthlyIncome", how="outer").sort_values("MonthlyIncome")
    
    combined_out = os.path.join(out_dir, f"combined_{resolved_year}.csv")
    combined.to_csv(combined_out, index=False)
    
    typer.echo(f"Success! Generated {len(combined)} rows.")
    typer.echo(f"Outputs:\n  - {fed_out}\n  - {state_out}\n  - {combined_out}")


if __name__ == "__main__":
    app()
