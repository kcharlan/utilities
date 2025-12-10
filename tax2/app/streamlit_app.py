import streamlit as st
import pandas as pd
from datetime import date
from taxkit.rules_loader import load_rules
from taxkit.engine import compute_tax
from taxkit.models import TaxInput, FilingStatus
from taxkit.qif import build_qif_entries, QIFConfig
import io, os

import re
import pandas as pd

def _clean_numeric_series(s: pd.Series) -> pd.Series:
    # Accept $, commas, spaces; blanks -> NaN
    s = s.astype(str).str.strip()
    s = s.str.replace(r"[,$\s]", "", regex=True)
    return pd.to_numeric(s, errors="coerce")

def _normalized_rename_map(df: pd.DataFrame) -> dict:
    """Create a header map without producing duplicate targets."""
    used = set()
    mapping = {}
    for c in df.columns:
        k = c.strip()
        kl = k.lower().replace(" ", "")

        target = None
        if "income" in kl and "month" in kl:
            target = "MonthlyIncome"
        elif "federal" in kl and "tax" in kl:
            target = "FederalMonthlyTax"
        elif "state" in kl and "tax" in kl:
            target = "StateMonthlyTax"
        elif kl in ("monthlytax","taxmonthly"):
            target = "MonthlyTax"

        if target and target not in used:
            mapping[c] = target
            used.add(target)
        # If target already used, skip to avoid duplicates
    return mapping

def _normalize_table(df: pd.DataFrame) -> pd.DataFrame:
    # 1) Rename with a dedup-safe map
    mapping = _normalized_rename_map(df)
    df = df.rename(columns=mapping)

    # 2) If any dupes slipped through (e.g., original file already had exact same names), drop later ones
    df = df.loc[:, ~df.columns.duplicated(keep="first")]

    # 3) Coerce numeric columns if present (handle Series vs “accidental” DataFrame)
    for col in ("MonthlyIncome", "FederalMonthlyTax", "StateMonthlyTax", "MonthlyTax"):
        if col in df.columns:
            obj = df[col]
            if isinstance(obj, pd.DataFrame):
                # If duplicate names still present, take the first
                obj = obj.iloc[:, 0]
            df[col] = _clean_numeric_series(obj)

    # 4) Drop rows without income and make income an int if reasonable
    if "MonthlyIncome" in df.columns:
        df = df.dropna(subset=["MonthlyIncome"])
        try:
            df["MonthlyIncome"] = df["MonthlyIncome"].round().astype(int)
        except Exception:
            pass

    return df

    # Flexible header mapping
    rename = {}
    for c in df.columns:
        k = c.strip()
        kl = k.lower().replace(" ", "")
        if "income" in kl and "month" in kl:
            rename[c] = "MonthlyIncome"
        elif "federal" in kl and "tax" in kl:
            rename[c] = "FederalMonthlyTax"
        elif "state" in kl and "tax" in kl:
            rename[c] = "StateMonthlyTax"
        elif kl in ("monthlytax","taxmonthly"):
            rename[c] = "MonthlyTax"
    df = df.rename(columns=rename)

    # Coerce numeric columns if present
    for col in ("MonthlyIncome", "FederalMonthlyTax", "StateMonthlyTax", "MonthlyTax"):
        if col in df.columns:
            df[col] = _clean_numeric_series(df[col])

    # Drop rows with no income value
    if "MonthlyIncome" in df.columns:
        df = df.dropna(subset=["MonthlyIncome"])
        # keep integer income steps if they were whole numbers
        try:
            df["MonthlyIncome"] = df["MonthlyIncome"].round().astype(int)
        except Exception:
            pass
    return df


st.set_page_config(page_title="Tax Calculator + QIF", layout="wide")

st.title("Tax Calculator (Rules-Based) + QIF Export")

with st.sidebar:
    st.header("Mode")
    mode = st.radio("Computation source", ["Pregenerated table", "Compute from rules"])
    filing_status = st.selectbox("Filing status", [e.value for e in FilingStatus])
    st.caption("Tip: Compute annually; monthly is derived.")

col1, col2 = st.columns([1,1])

with col1:
    monthly_income = st.number_input("Monthly income ($)", min_value=0, value=5000, step=50)
    tx_date = st.date_input("Transaction date", value=date.today())
with col2:
    st.subheader("QIF Settings")
    payee = st.text_input("Payee", "Estimated Taxes Withholding")
    fed_exp = st.text_input("Federal expense category", "Tax:Federal Income Tax Estimated Paid")
    fed_tr = st.text_input("Federal transfer account", "[Federal Income Taxes]")
    state_exp = st.text_input("State expense category", "Tax:State Income Tax Estimated Paid")
    state_tr = st.text_input("State transfer account", "[GA State Income Taxes]")

cfg = QIFConfig(payee=payee, federal_expense=fed_exp, federal_transfer=fed_tr,
                state_expense=state_exp, state_transfer=state_tr)

st.divider()

def compute_from_rules_ui():
    from taxkit.utils import get_available_years, resolve_year, get_rule_path
    
    st.subheader("Rules files")

    # Resolve paths/years
    base_fed = os.path.join(os.path.dirname(__file__), "..", "rules", "federal")
    base_state = os.path.join(os.path.dirname(__file__), "..", "rules", "states", "GA") # Defaulting to GA for now as per original code

    avail_years = get_available_years(base_fed)
    target_year = date.today().year
    
    # Selection UI
    col_sel1, col_sel2 = st.columns(2)
    with col_sel1:
        # If no years found, just let them pick current year, we will warn later or fail
        if not avail_years:
            avail_years = [target_year]
        
        # If target year not in list but we have others, let's just default to the best match logic
        # But for the UI, we want to show all available options plus the current year if it's missing (maybe?)
        # Actually, let's just show available years. If current year is missing, we select the fallback.
        
        # Logic: 
        # 1. Calculate best year to show as default
        default_y, is_fallback = resolve_year(target_year, avail_years)
        
        # 2. Add current year to list if missing? No, user can only pick what exists.
        # But user wants to be able to "select which rule set to use".
        
        selected_year = st.selectbox("Tax Year", avail_years, index=avail_years.index(default_y) if default_y in avail_years else 0)

        if is_fallback and selected_year == default_y and target_year != default_y:
            st.warning(f"Rules for {target_year} not found. Defaulting to {default_y}.")

    colr1, colr2 = st.columns(2)
    with colr1:
        fed_file = st.file_uploader("Federal rules (YAML)", type=["yml","yaml"], key="fed_rules")
        if fed_file is None:
            fed_path = get_rule_path(base_fed, selected_year)
            st.caption(f"Using: {os.path.basename(fed_path)}")
        else:
            fed_path = os.path.join(st.session_state.get("tmp_dir","/tmp"), "federal.yaml")
            os.makedirs(st.session_state.get("tmp_dir","/tmp"), exist_ok=True)
            with open(fed_path, "wb") as f: f.write(fed_file.getvalue())
    with colr2:
        st.caption("Pick a state rules file (YAML). Default: GA.")
        state_file = st.file_uploader("State rules (YAML)", type=["yml","yaml"], key="state_rules")
        if state_file is None:
            state_path = get_rule_path(base_state, selected_year)
            st.caption(f"Using: {os.path.basename(state_path)}")
        else:
            state_path = os.path.join(st.session_state.get("tmp_dir","/tmp"), "state.yaml")
            with open(state_path, "wb") as f: f.write(state_file.getvalue())

    try:
        fed_rules = load_rules(fed_path)
        state_rules = load_rules(state_path)
        fs = FilingStatus(filing_status)
        annual_income = monthly_income * 12.0
        federal = compute_tax(TaxInput(annual_income=annual_income, filing_status=fs), fed_rules) / 12.0
        state = compute_tax(TaxInput(annual_income=annual_income, filing_status=fs), state_rules) / 12.0
        return round(federal, 2), round(state, 2)
    except Exception as e:
        st.error(f"Error loading rules or computing: {e}")
        return None, None

def from_table_ui():
    st.subheader("Load table(s)")
    uploaded = st.file_uploader(
        "Combined table (CSV/Parquet) with columns MonthlyIncome, FederalMonthlyTax, StateMonthlyTax "
        "OR a single-table with MonthlyIncome, MonthlyTax",
        type=["csv","parquet"], key="combo_table"
    )
    sep_federal = st.file_uploader("Alternatively: Federal table (CSV/Parquet)", type=["csv","parquet"], key="fed_table")
    sep_state = st.file_uploader("Alternatively: State table (CSV/Parquet)", type=["csv","parquet"], key="state_table")

    def read_table(file):
        if file is None:
            return None
        name = file.name.lower()
        if name.endswith(".csv"):
            # Read as strings to avoid dtype surprises; we’ll coerce explicitly
            df = pd.read_csv(file, dtype=str)
        else:
            df = pd.read_parquet(file)
            # Parquet usually preserves numeric dtypes, but normalize anyway
        return _normalize_table(df)

    df_combo = read_table(uploaded) if uploaded is not None else None
    df_fed   = read_table(sep_federal) if sep_federal is not None else None
    df_state = read_table(sep_state) if sep_state is not None else None

    # Fallback sample bundled with the app
    if df_combo is None and df_fed is None and df_state is None:
        sample_path_csv = os.path.join(os.path.dirname(__file__), "..", "tables", "sample_combined.csv")
        if os.path.exists(sample_path_csv):
            df_combo = _normalize_table(pd.read_csv(sample_path_csv, dtype=str))

    if df_combo is not None:
        # Combined table path
        if "MonthlyIncome" not in df_combo.columns:
            st.error("Combined table is missing a MonthlyIncome column.")
            return None, None, None

        # pick exact or nearest income
        series = df_combo["MonthlyIncome"]
        idx = (series - monthly_income).abs().idxmin()
        row = df_combo.loc[idx]

        # Prefer explicit federal/state cols; fall back to single MonthlyTax
        federal = row["FederalMonthlyTax"] if "FederalMonthlyTax" in df_combo.columns else row.get("MonthlyTax", 0.0)
        state   = row["StateMonthlyTax"]   if "StateMonthlyTax"   in df_combo.columns else 0.0

        return float(federal), float(state), df_combo

    elif df_fed is not None and df_state is not None:
        if "MonthlyIncome" not in df_fed.columns or "MonthlyIncome" not in df_state.columns:
            st.error("Separate tables must include MonthlyIncome.")
            return None, None, None

        rf = df_fed.rename(columns={"MonthlyTax":"FederalMonthlyTax"})
        rs = df_state.rename(columns={"MonthlyTax":"StateMonthlyTax"})
        merged = pd.merge(rf, rs, on="MonthlyIncome", how="outer", validate="one_to_one").sort_values("MonthlyIncome")

        series = merged["MonthlyIncome"]
        idx = (series - monthly_income).abs().idxmin()
        row = merged.loc[idx]

        return float(row["FederalMonthlyTax"]), float(row["StateMonthlyTax"]), merged

    else:
        st.info("Upload a table (or use the sample).")
        return None, None, None


# Compute taxes depending on mode
if mode == "Compute from rules":
    federal_tax, state_tax = compute_from_rules_ui()
    table_df = None
else:
    federal_tax, state_tax, table_df = from_table_ui()

st.divider()

if federal_tax is not None and state_tax is not None:
    total_tax = round(federal_tax + state_tax, 2)
    c1, c2, c3 = st.columns(3)
    c1.metric("Federal (monthly)", f"${federal_tax:,.2f}")
    c2.metric("State (monthly)", f"${state_tax:,.2f}")
    c3.metric("Total (monthly)", f"${total_tax:,.2f}")

    qif_text = build_qif_entries(tx_date, federal_tax, state_tax, cfg)
    st.download_button("Download QIF", data=qif_text.encode("utf-8"), file_name="tax_transactions.qif", mime="application/qif")

    if table_df is not None and mode == "Compute from rules":
        st.subheader("Cross-check vs table")
        if st.button("Compare with uploaded/sample table"):
            # Simple diff at the chosen income (nearest row in table)
            row = table_df[table_df["MonthlyIncome"] == monthly_income]
            if row.empty:
                row = table_df.iloc[(table_df["MonthlyIncome"] - monthly_income).abs().argsort()[:1]]
            t_fed = float(row.iloc[0].get("FederalMonthlyTax", row.iloc[0].get("MonthlyTax", 0.0)))
            t_state = float(row.iloc[0].get("StateMonthlyTax", 0.0))
            st.write({
                "engine_federal": federal_tax, "table_federal": t_fed, "delta_federal": round(federal_tax - t_fed, 2),
                "engine_state": state_tax, "table_state": t_state, "delta_state": round(state_tax - t_state, 2),
            })
else:
    st.warning("Provide inputs/files to compute taxes.")

st.caption("Rounding: computed annually, divided to monthly, then rounded to cents.")
