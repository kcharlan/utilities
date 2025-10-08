import pandas as pd

fed = pd.read_parquet("tables/federal_2025.parquet").rename(columns={"MonthlyTax": "FederalMonthlyTax"})
ga = pd.read_parquet("tables/ga_2025.parquet").rename(columns={"MonthlyTax": "StateMonthlyTax"})
combined = pd.merge(fed, ga, on="MonthlyIncome", how="outer").sort_values("MonthlyIncome")
combined.to_csv("tables/combined_2025.csv", index=False)
