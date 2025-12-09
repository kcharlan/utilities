# Product Requirements Document (PRD)

## Title: `qif_div_converter` — Fidelity CSV → Moneydance-Compatible QIF Dividend Conversion Utility

---

## 1. Overview

`qif_div_converter` is a command-line utility that ingests a Fidelity `Accounts_History.csv` file and outputs a properly formatted QIF file containing **dividend transactions only**, compatible with Moneydance. All processing rules, fund mappings, and account filters are defined and maintained in a colocated configuration JSON file (`qif_div_converter.json`).

The utility operates strictly within the current working directory—no fixed output paths—and supports shell wildcards for CSV input parameters.

---

## 2. Goals & Non‑Goals

### Goals

- Provide a deterministic, scriptable CLI tool for transforming Fidelity dividend data into Moneydance QIF format.
- Allow configuration-driven filtering (accounts, funds) without changing utility code.
- Validate output and warn on malformed or skipped records.
- Produce a summary table for reconciliation.

### Non‑Goals

- No GUI or interactive prompts.
- No automatic detection of fund mappings.
- No support for reinvestments or complex corporate actions.

---

## 3. Configuration (`qif_div_converter.json`)

Stored in the exact same directory as the utility executable/script. The utility must resolve its own path (similar to `$0` in bash) and load the JSON from that directory.

### 3.1 Required JSON Structure

```json
{
  "accounts": [
    "Individual - TOD"
  ],
  "fund_mappings": {
    "ITWO": "ITWO - PROSHARES TR RUSSELL 2000 HIG",
    "SPAXX": "FIDELITY GOVERNMENT MONEY MARKET"
  },
  "category": "Investment:Dividends"
}
```

### 3.2 Extendability

- Adding new accounts requires inserting another string under `accounts`.
- Adding fund mappings is as simple as extending the `fund_mappings` object.
- The utility must gracefully handle unknown tickers by skipping them **with a warning**.

---

## 4. CLI Specification

```
qif_div_converter <input_csv>
```

### Requirements

- Utility must accept relative or absolute paths.
- Wildcards must be supported via shell expansion (`*.csv`).
- If multiple files are provided via wildcard expansion, process them sequentially, generating one QIF per file.

---

## 5. Transaction Inclusion Rules

A row qualifies for processing only if:

1. `Account` matches one of the configured accounts.
2. `Symbol` exists in the `fund_mappings` dictionary.
3. Transaction type is **“DIVIDEND RECEIVED”**.
4. Transaction type is **not** “REINVESTMENT”.
5. `Amount` is a **positive** number.

If any condition fails, the utility must:

- **Skip the row**, and
- Emit a **warning** explaining why.

---

## 6. QIF Output Specification

### 6.1 File Header

```
!Type:Invst
```

### 6.2 Per‑Transaction QIF Block

```
D<M/D'YY>
NMiscInc
Y<Mapped Fund Name>
T<Amount rounded to 2 decimals>
MDividend <TICKER>
L<Category from config.json>
^
```

### Formatting Requirements

- Date must be rendered `M/D'YY` with **ASCII apostrophe**.
- Amount must always include two decimals.
- Action `N` is always `MiscInc`.

---

## 7. Output Behavior

### 7.1 Naming Convention

```
dividends_by_fund_<startYYYYMMDD>_<endYYYYMMDD>.qif
```

Generated **in the current working directory** of the running utility.

### 7.2 Validation Requirements

Before finalizing the file:

- Must begin with `!Type:Invst`.
- Must contain ≥1 transaction.
- All dates must contain apostrophe format.
- Amounts must be valid decimal numbers with two places.

If validation fails:

- Abort generation.
- Emit warnings.
- Exit with non‑zero status.

---

## 8. Summary Output

After generating the QIF file, print a summary table to stdout:

| Ticker | Count | Total Amount |
| ------ | ----- | ------------ |

Totals must match generated QIF entries.

---

## 9. Error Handling & Warnings

The utility must **never silently skip data**. Emit warnings for:

- Unknown tickers.
- Missing required CSV fields.
- Invalid numeric amounts.
- Invalid or unparsable dates.
- Rows excluded due to config filters.

Warnings should identify:

- Line number
- Cause of exclusion
- Relevant field values

---

## 10. Functional Flow

1. Resolve utility directory and load `qif_div_converter.json`.
2. Accept a CSV path argument (wildcard-expanded by shell).
3. For each CSV:
   - Parse rows.
   - Validate required fields.
   - Apply filters (account, ticker, amount, transaction type).
   - Log warnings for all exclusions.
   - Generate per-row QIF entries.
   - Accumulate stats.
4. Determine date range and generate final filename.
5. Validate file.
6. Write QIF file to current directory.
7. Print summary table.

---

## 11. Edge Cases & Required Behavior

- **Empty result set** → Print error and exit non-zero.
- **CSV with no valid account column or symbol column** → Fatal error.
- **Malformed CSV** → Fatal error with diagnostic output.
- **Large files** → Process streaming; no requirement for in‑memory entirety.

---

## 12. Example Transaction

This worked example uses the settings in the provided config JSON.

Input fields:

- Symbol: ITWO
- Run Date: 08/07/2025
- Amount: 358.57

Output:

```
D8/7'25
NMiscInc
YITWO - PROSHARES TR RUSSELL 2000 HIG
T358.57
MDividend ITWO
LInvestment:Dividends
^
```

---

## 13. Acceptance Criteria

- All filtering rules configurable and extendable.
- QIF loads cleanly into Moneydance.
- Summary output matches QIF totals.
- Utility warns on every skipped row.
- No hardcoded paths; all outputs local.

---

## 14. Future Enhancements

- Multiple output formats (OFX, JSON, etc.).
- Support for reinvested dividends with configurable action types.
- Automatic ticker→fund name inference.

---

End of PRD.
