import pandas as pd
import re

def normalize_measurement(value):
    if pd.isna(value) or str(value).strip() == "":
        return None
    match = re.search(r"(\d+\.?\d*)", str(value))
    return float(match.group(1)) if match else None

def calculate_garment_measure(body_measure, allowance):
    val = normalize_measurement(body_measure)
    return val + allowance if (val is not None and val >= 5) else None

def match_size(garment_value, chart_df, measure_col='Value'):
    if garment_value is None:
        return None, None  # No measurement = not an error
    if chart_df is None or chart_df.empty:
        return None, "Chart Missing"
    
    chart_sorted = chart_df.sort_values(by=measure_col).reset_index(drop=True)
    for _, row in chart_sorted.iterrows():
        chart_val = normalize_measurement(row[measure_col])
        if chart_val is not None and chart_val >= garment_value:
            return row['Size'], None
    return None, "Above Range"
