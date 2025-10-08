
import pandas as pd
from datetime import datetime
from pathlib import Path
import argparse
import sys

def parse_currency(val):
    if isinstance(val, str):
        return float(val.replace("$", "").replace(",", "").strip())
    return float(val)

def load_tax_table(csv_path):
    df = pd.read_csv(csv_path)
    df = df.rename(columns={
        'Monthly Gross\n Income': 'MonthlyIncome',
        'Federal Monthly\n Tax': 'FederalTax',
        'State Monthly\nTax': 'StateTax'
    })
    df['MonthlyIncome'] = df['MonthlyIncome'].apply(parse_currency)
    df['FederalTax'] = df['FederalTax'].apply(parse_currency)
    df['StateTax'] = df['StateTax'].apply(parse_currency)
    return df

def generate_qif(income, date_str, tax_df, output_path):
    try:
        date_obj = datetime.strptime(date_str, "%m/%d/%Y")
    except ValueError:
        print("Error: Date must be in MM/DD/YYYY format.")
        sys.exit(1)

    match = tax_df[tax_df['MonthlyIncome'] == income]
    if match.empty:
        print(f"Error: Monthly income ${income:,.2f} not found in tax table.")
        sys.exit(1)

    fed_tax = match.iloc[0]['FederalTax']
    state_tax = match.iloc[0]['StateTax']
    qif_date = date_obj.strftime("%m/%d/%y")
    memo_date = date_obj.strftime("%m/%d/%Y")

    lines = [
        "!Type:Bank",
        # Federal Expense
        f"D{qif_date}",
        f"T{-fed_tax:.2f}",
        "PEstimated Federal Taxes Withholding",
        f"MEstimated Federal taxes - {memo_date}",
        "LTax:Federal Income Tax Estimated Paid",
        "^",
        # Federal Transfer
        f"D{qif_date}",
        f"T{fed_tax:.2f}",
        "PEstimated Federal Taxes Withholding",
        f"MEstimated Federal taxes - {memo_date}",
        "L[Federal Income Taxes]",
        "^",
        # State Expense
        f"D{qif_date}",
        f"T{-state_tax:.2f}",
        "PEstimated GA State Taxes Withholding",
        f"MEstimated State taxes - {memo_date}",
        "LTax:State Income Tax Estimated Paid",
        "^",
        # State Transfer
        f"D{qif_date}",
        f"T{state_tax:.2f}",
        "PEstimated GA State Taxes Withholding",
        f"MEstimated State taxes - {memo_date}",
        "L[GA State Income Taxes]",
        "^"
    ]

    out_file = Path(output_path) / f"tax_entries_{date_obj.strftime('%Y-%m-%d')}.qif"
    with open(out_file, "w") as f:
        f.write("\n".join(lines))
    print(f"QIF file generated: {out_file}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generate QIF for estimated taxes.")
    parser.add_argument("--income", type=float, required=True, help="Monthly income (e.g., 10000)")
    parser.add_argument("--date", type=str, required=True, help="Target date (MM/DD/YYYY)")
    parser.add_argument("--tax-table", type=str, required=True, help="Path to tax table CSV")
    parser.add_argument("--output-dir", type=str, default=".", help="Output directory for QIF file")

    args = parser.parse_args()
    tax_df = load_tax_table(args.tax_table)
    generate_qif(args.income, args.date, tax_df, args.output_dir)
