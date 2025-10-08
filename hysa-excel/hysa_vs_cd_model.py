import pandas as pd
import xlsxwriter

inputs = pd.read_csv('inputs.csv')
wb = xlsxwriter.Workbook('CD_vs_HYSA_Model_TEMPLATE_MATCH.xlsx')

percent_format = wb.add_format({'num_format': '0.00%'})
number_format = wb.add_format({'num_format': '0.00'})
header_format = wb.add_format({'bold': True})
checkmark_format = wb.add_format({'align': 'center', 'font_color': 'green', 'bold': True, 'font_size': 16})

ws_inputs = wb.add_worksheet('Inputs')
ws_mb = wb.add_worksheet('Monthly Balances')
ws_simple = wb.add_worksheet('Simple')
ws_output = wb.add_worksheet('Output')

percent_params = [
    "Starting HYSA Rate", "Starting CD Rate",
    "Rate Step (per period)", "CD Sensitivity"
]

param_row = {}
for col_idx, col in enumerate(inputs.columns):
    ws_inputs.write(0, col_idx, col, header_format)
for row_idx, row in enumerate(inputs.itertuples(index=False), 1):
    param = str(row[0]).strip()
    value = row[1]
    param_row[param] = row_idx + 1
    ws_inputs.write(row_idx, 0, param)
    if param in percent_params:
        try:
            ws_inputs.write_number(row_idx, 1, float(value), percent_format)
        except Exception:
            ws_inputs.write(row_idx, 1, value)
    else:
        try:
            ws_inputs.write_number(row_idx, 1, float(value), number_format)
        except Exception:
            ws_inputs.write(row_idx, 1, value)

def get_cell(param_name):
    row = param_row[param_name]
    return f"$B${row}"

principal_cell = get_cell('Initial Principal')
hysa_rate_cell = get_cell('Starting HYSA Rate')
cd_rate_cell = get_cell('Starting CD Rate')
rate_step_cell = get_cell('Rate Step (per period)')
rate_freq_cell = get_cell('Rate Change Frequency (months)')
cd_sens_cell = get_cell('CD Sensitivity')
duration_cell = get_cell('Total Duration (months)')

cd_terms = [
    ("CD 3mo Rate", "CD 3mo", 3),
    ("CD 6mo Rate", "CD 6mo", 6),
    ("CD 12mo Rate", "CD 12mo", 12),
    ("CD 18mo Rate", "CD 18mo", 18),
    ("CD 24mo Rate", "CD 24mo", 24),
    ("CD 36mo Rate", "CD 36mo", 36),
    ("CD 60mo Rate", "CD 60mo", 60)
]

# Monthly Balances headers
mb_headers = ["Month", "HYSA Rate", "HYSA"]
for term in cd_terms:
    mb_headers.extend([term[0], term[1]])
ws_mb.write_row(0, 0, mb_headers, header_format)

# Month sequence (dynamic array)
ws_mb.write_formula(1, 0, f'=SEQUENCE(Inputs!{duration_cell},1,1,1)')
duration = int(float(inputs.loc[inputs['Parameter'] == 'Total Duration (months)', 'Value'].values[0]))

# HYSA Rate stepping (clamped to >=0)
for i in range(2, duration+2):
    ws_mb.write_formula(
        i-1, 1,
        f'=MAX(Inputs!{hysa_rate_cell} + INT((A{i}-1)/Inputs!{rate_freq_cell})*Inputs!{rate_step_cell}, 0)'
    )

# HYSA Balance
ws_mb.write_formula(1, 2, f'=Inputs!{principal_cell}')
for i in range(2, duration+1):
    ws_mb.write_formula(i, 2, f'=C{i}*(1+B{i+1}/12)')

# All CD rates and balances
for cd_idx, (rate_col, bal_col, cd_term) in enumerate(cd_terms):
    rate_col_idx = 3 + cd_idx*2
    bal_col_idx = rate_col_idx + 1

    for i in range(2, duration+2):
        if i == 2:
            ws_mb.write_formula(
                i-1, rate_col_idx,
                f'=MAX(Inputs!{cd_rate_cell} + INT((A{i}-1)/Inputs!{rate_freq_cell})*Inputs!{rate_step_cell}*Inputs!{cd_sens_cell}, 0)'
            )
        else:
            ws_mb.write_formula(
                i-1, rate_col_idx,
                f'=IF(MOD(A{i}-1,{cd_term})=0,'
                f'MAX(Inputs!{cd_rate_cell} + INT((A{i}-1)/Inputs!{rate_freq_cell})*Inputs!{rate_step_cell}*Inputs!{cd_sens_cell}, 0),'
                f'{chr(65+rate_col_idx)}{i-1})'
            )

    ws_mb.write_formula(1, bal_col_idx, f'=Inputs!{principal_cell}')
    for i in range(2, duration+1):
        rate_col_letter = chr(65+rate_col_idx)
        bal_col_letter = chr(65+bal_col_idx)
        ws_mb.write_formula(i, bal_col_idx, f'={bal_col_letter}{i}*(1+{rate_col_letter}{i+1}/12)')

# Simple tab headers (for your own expansion)
simple_headers = ["Month", "HYSA", "CD"]
ws_simple.write_row(0, 0, simple_headers, header_format)

# --- Output Tab ---
output_headers = ["Strategy", "Final Balance", "Best Performer", "Notes"]
ws_output.write_row(0, 0, output_headers, header_format)

# Output strategies and formulas
strategies = ["HYSA"] + [bal_col for _, bal_col, _ in cd_terms]
for idx, strat in enumerate(strategies):
    # Strategy name
    ws_output.write(idx+1, 0, strat)
    # Final Balance: link to last row in Monthly Balances for this strategy
    col_letter = chr(67 + (idx*2) if idx > 0 else 67)  # C for HYSA, then E, G, ... for CDs
    ws_output.write_formula(idx+1, 1, f"='Monthly Balances'!{col_letter}{duration+1}")
    # Best Performer: checkmark if this is max
    range_letter_start = "B2"
    range_letter_end = f"B{len(strategies)+1}"
    ws_output.write_formula(idx+1, 2, f'=IF(B{idx+2}=MAX($B$2:$B${len(strategies)+1}),"✓","")', checkmark_format)
    # Notes left blank

wb.close()
