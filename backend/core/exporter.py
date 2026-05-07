import pandas as pd
import io

def generate_vendor_excel(res_df):
    error_df = res_df[res_df['Status'] == "Error"].copy()
    if error_df.empty:
        error_df = pd.DataFrame(columns=res_df.columns)
        
    summary_data = {
        "Metric": ["Total Processed", "Success", "Errors"],
        "Count": [
            len(res_df),
            len(res_df[res_df['Status'] == "OK"]),
            len(res_df[res_df['Status'] == "Error"])
        ]
    }
    summary_df = pd.DataFrame(summary_data)
    
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        res_df.to_excel(writer, sheet_name='Processed Data', index=False)
        error_df.to_excel(writer, sheet_name='Errors', index=False)
        summary_df.to_excel(writer, sheet_name='Summary', index=False)
    return output.getvalue()
