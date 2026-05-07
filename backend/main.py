import os
import json
import pandas as pd
from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
import io
import uuid

from core.size_engine import calculate_garment_measure, match_size
from core.exporter import generate_vendor_excel
from db.database import (
    init_db, get_all_schools, get_global_chart, save_school,
    update_school, delete_school, save_global_chart, verify_user,
    get_allowance, update_allowance, add_history, get_history,
    get_school_by_id, get_all_allowances
)

app = FastAPI(title="Central Uniform Sizer API", version="2.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

init_db()

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
os.makedirs(DATA_DIR, exist_ok=True)

@app.post("/login")
def login(data: dict):
    if verify_user(data.get("username"), data.get("password")):
        return {"status": "success", "token": "cuni-static-token-v1"}
    raise HTTPException(status_code=401, detail="Invalid credentials")

@app.get("/schools")
def list_schools():
    df = get_all_schools()
    return df.to_dict(orient="records")

@app.post("/schools")
def add_school(data: dict):
    if save_school(data.get("name"), data.get("year")):
        return {"status": "success"}
    raise HTTPException(status_code=400, detail="School already exists")

@app.put("/schools/{school_id}")
def edit_school(school_id: int, data: dict):
    update_school(school_id, data.get("name"), data.get("year"))
    return {"status": "updated"}

@app.delete("/schools/{school_id}")
def remove_school(school_id: int):
    delete_school(school_id)
    return {"status": "deleted"}

@app.get("/charts")
def get_charts():
    items = ["Shirt", "Pant", "Skirt", "Shorts", "Sports T-Shirt", "School T-Shirt", "Sports Track Pant"]
    return {item: get_global_chart(item).to_dict(orient="records") for item in items}

@app.post("/charts/{item_type}")
def update_chart(item_type: str, data: list):
    df = pd.DataFrame(data)
    save_global_chart(item_type, df)
    return {"status": "updated"}

@app.get("/allowances")
def list_allowances():
    df = get_all_allowances()
    return {row["item_type"]: row["value"] for _, row in df.iterrows()}

@app.post("/allowances/{item_type}")
def edit_allowance(item_type: str, data: dict):
    val = data.get("value")
    if val is None:
        raise HTTPException(status_code=400, detail="Value required")
    update_allowance(item_type, float(val))
    return {"status": "updated"}

@app.get("/template")
def download_template():
    cols = [
        "Enrollment Code", "Student Name", "Gender", "Admission Type",
        "House Colour", "Class Number", "Class Name",
        "Chest", "Waist", "Length"
    ]

    df = pd.DataFrame(columns=cols)
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        df.to_excel(writer, index=False, sheet_name='Template')
    output.seek(0)
    return StreamingResponse(
        output,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": "attachment; filename=Student_Template.xlsx"}
    )

@app.post("/process")
async def process_sizing(file: UploadFile = File(...), school_id: int = Form(...), mapping: str = Form(...)):
    try:
        mapping = json.loads(mapping)
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid mapping JSON")

    if not mapping:
        raise HTTPException(status_code=400, detail="Mapping required")

    school = get_school_by_id(school_id)
    if not school:
        raise HTTPException(status_code=404, detail="School not found")

    contents = await file.read()
    if not contents:
        raise HTTPException(status_code=400, detail="Empty file")

    try:
        df = pd.read_excel(io.BytesIO(contents))
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Cannot read Excel: {str(e)}")

    required_keys = ["enr", "name", "class_num", "class_name", "gender", "adm_type", "house", "chest", "waist"]
    missing = [k for k in required_keys if k not in mapping]
    if missing:
        raise HTTPException(status_code=400, detail=f"Missing mapping keys: {missing}")

    results = []
    for _, row in df.iterrows():
        try:
            g_chest = calculate_garment_measure(row[mapping["chest"]], get_allowance("Shirt"))
            shirt_size, s_err = match_size(g_chest, get_global_chart("Shirt"), 'Value')

            grade_val = str(row[mapping["class_num"]])
            gender_val = str(row[mapping["gender"]]).upper().strip()

            if "GIRL" in gender_val or gender_val in ["F", "FEMALE"]:
                bottom_type, target_chart = "Skirt", get_global_chart("Skirt")
            elif "BOY" in gender_val or gender_val in ["M", "MALE"]:
                is_junior = any(grade_val.startswith(str(i)) for i in range(1, 6))
                bottom_type, target_chart = ("Shorts", get_global_chart("Shorts")) if is_junior else ("Pant", get_global_chart("Pant"))
            else:
                bottom_type, target_chart = "Shorts", get_global_chart("Shorts")

            g_waist = calculate_garment_measure(row[mapping["waist"]], get_allowance(bottom_type))
            bottom_size, b_err = match_size(g_waist, target_chart, 'Value')

            sports_chest = calculate_garment_measure(row[mapping["chest"]], get_allowance("Sports T-Shirt"))
            sports_t_size, st_err = match_size(sports_chest, get_global_chart("Sports T-Shirt"), 'Value')

            school_chest = calculate_garment_measure(row[mapping["chest"]], get_allowance("School T-Shirt"))
            school_t_size, sc_err = match_size(school_chest, get_global_chart("School T-Shirt"), 'Value')

            sports_waist = calculate_garment_measure(row[mapping["waist"]], get_allowance("Sports Track Pant"))
            sports_p_size, sp_err = match_size(sports_waist, get_global_chart("Sports Track Pant"), 'Value')

            status = "OK" if (shirt_size and bottom_size) else "Error"

            result_row = {
                "Enrollment Code": row[mapping["enr"]],
                "Student Name": row[mapping["name"]],
                "Class Number": row[mapping["class_num"]],
                "Class Name": row[mapping["class_name"]],
                "Gender": row[mapping["gender"]],
                "Admission Type": row[mapping["adm_type"]],
                "House Colour": row[mapping["house"]],
                "Chest": row.get(mapping.get("chest", ""), ""),
                "Waist": row.get(mapping.get("waist", ""), ""),
                "Shirt Size": shirt_size if shirt_size else s_err,
                "Bottom Type": bottom_type,
                "Bottom Size": bottom_size if bottom_size else b_err,
                "Sports T-Shirt": sports_t_size if sports_t_size else st_err,
                "School T-Shirt": school_t_size if school_t_size else sc_err,
                "Sports Track Pant": sports_p_size if sports_p_size else sp_err,
                "Status": status
            }
            if "length" in mapping and mapping["length"]:
                result_row["Length"] = row.get(mapping["length"], "")
            results.append(result_row)

        except Exception as e:
            err_row = {
                "Enrollment Code": row.get(mapping.get("enr", "Unknown"), "Unknown"),
                "Student Name": row.get(mapping.get("name", "Unknown"), "Unknown"),
                "Class Number": row.get(mapping.get("class_num", "Unknown"), "Unknown"),
                "Class Name": row.get(mapping.get("class_name", "Unknown"), "Unknown"),
                "Gender": row.get(mapping.get("gender", "Unknown"), "Unknown"),
                "Admission Type": row.get(mapping.get("adm_type", "Unknown"), "Unknown"),
                "House Colour": row.get(mapping.get("house", "Unknown"), "Unknown"),
                "Chest": "",
                "Waist": "",
                "Shirt Size": "Error",
                "Bottom Type": "Error",
                "Bottom Size": "Error",
                "Sports T-Shirt": "Error",
                "School T-Shirt": "Error",
                "Sports Track Pant": "Error",
                "Status": f"Error: {str(e)[:50]}"
            }
            results.append(err_row)


    res_df = pd.DataFrame(results)

    try:
        excel_bytes = generate_vendor_excel(res_df)
        file_id = str(uuid.uuid4())[:8]
        out_path = os.path.join(DATA_DIR, f"output_{file_id}.xlsx")
        with open(out_path, "wb") as f:
            f.write(excel_bytes)

        add_history(
            school_id=school_id,
            school_name=school[1],
            total=len(res_df),
            success=len(res_df[res_df['Status'] == "OK"]),
            errors=len(res_df[res_df['Status'] == "Error"]),
            file_path=out_path
        )

        temp_path = os.path.join(DATA_DIR, "temp_out.xlsx")
        with open(temp_path, "wb") as f:
            f.write(excel_bytes)

        return {"status": "success", "data": results, "file_id": file_id}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Export failed: {str(e)}")

@app.get("/download")
def download():
    temp_path = os.path.join(DATA_DIR, "temp_out.xlsx")
    if not os.path.exists(temp_path):
        raise HTTPException(status_code=404, detail="No processed file available. Run process first.")
    return FileResponse(temp_path, filename="Vendor_Final.xlsx")

@app.get("/history")
def list_history():
    df = get_history()
    return df.to_dict(orient="records")

@app.get("/")
def root():
    return {"message": "Central Uniform Sizer API v2.0.0", "status": "running"}
