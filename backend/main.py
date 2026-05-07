import os
import json
import math
import pandas as pd
from fastapi import FastAPI, UploadFile, File, Form, HTTPException, Body
from typing import Any
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
    get_school_by_id, get_all_allowances,
    upsert_student, get_students_by_school, get_student_by_id,
    update_student_data, delete_student
)

app = FastAPI(title="Central Uniform Sizer API", version="2.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

init_db()

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
os.makedirs(DATA_DIR, exist_ok=True)

def clean_val(v):
    if pd.isna(v):
        return None
    if isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
        return None
    return v

def sanitize_records(records):
    for rec in records:
        for k, v in rec.items():
            if isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
                rec[k] = None
    return records

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
def update_chart(item_type: str, data: Any = Body(...)):
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
async def process_sizing(file: UploadFile = File(...), school_id: int = Form(...), mapping: str = Form(...), sheet_name: str = Form(None)):
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
        if sheet_name:
            df = pd.read_excel(io.BytesIO(contents), sheet_name=sheet_name)
        else:
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
            chest_raw = clean_val(row[mapping["chest"]])
            waist_raw = clean_val(row[mapping["waist"]])
            
            has_chest = chest_raw is not None
            has_waist = waist_raw is not None

            # Shirt
            if has_chest:
                g_chest = calculate_garment_measure(chest_raw, get_allowance("Shirt"))
                shirt_size, s_err = match_size(g_chest, get_global_chart("Shirt"), 'Value')
                if not shirt_size:
                    shirt_size = s_err if s_err else ""
            else:
                shirt_size = ""

            # Determine bottom type from gender/class
            grade_val = str(row[mapping["class_num"]]) if not pd.isna(row[mapping["class_num"]]) else ""
            gender_val = str(row[mapping["gender"]]).upper().strip() if not pd.isna(row[mapping["gender"]]) else ""

            if "GIRL" in gender_val or gender_val in ["F", "FEMALE"]:
                bottom_type, target_chart = "Skirt", get_global_chart("Skirt")
            elif "BOY" in gender_val or gender_val in ["M", "MALE"]:
                is_junior = any(grade_val.startswith(str(i)) for i in range(1, 6))
                bottom_type, target_chart = ("Shorts", get_global_chart("Shorts")) if is_junior else ("Pant", get_global_chart("Pant"))
            else:
                bottom_type, target_chart = "Shorts", get_global_chart("Shorts")

            # Bottom
            if has_waist:
                g_waist = calculate_garment_measure(waist_raw, get_allowance(bottom_type))
                bottom_size, b_err = match_size(g_waist, target_chart, 'Value')
                if not bottom_size:
                    bottom_size = b_err if b_err else ""
            else:
                bottom_type = ""
                bottom_size = ""

            # Sports T-Shirt
            if has_chest:
                sports_chest = calculate_garment_measure(chest_raw, get_allowance("Sports T-Shirt"))
                sports_t_size, st_err = match_size(sports_chest, get_global_chart("Sports T-Shirt"), 'Value')
                if not sports_t_size:
                    sports_t_size = st_err if st_err else ""
            else:
                sports_t_size = ""

            # School T-Shirt
            if has_chest:
                school_chest = calculate_garment_measure(chest_raw, get_allowance("School T-Shirt"))
                school_t_size, sc_err = match_size(school_chest, get_global_chart("School T-Shirt"), 'Value')
                if not school_t_size:
                    school_t_size = sc_err if sc_err else ""
            else:
                school_t_size = ""

            # Sports Track Pant
            if has_waist:
                sports_waist = calculate_garment_measure(waist_raw, get_allowance("Sports Track Pant"))
                sports_p_size, sp_err = match_size(sports_waist, get_global_chart("Sports Track Pant"), 'Value')
                if not sports_p_size:
                    sports_p_size = sp_err if sp_err else ""
            else:
                sports_p_size = ""

            # Status logic
            shirt_ok = has_chest and shirt_size and shirt_size not in ["Chart Missing", "Above Range", ""]
            bottom_ok = has_waist and bottom_size and bottom_size not in ["Chart Missing", "Above Range", ""]
            
            if shirt_ok and bottom_ok:
                status = "OK"
            elif shirt_ok or bottom_ok:
                status = "Partial"
            else:
                status = "Error"

            result_row = {
                "Enrollment Code": str(row[mapping["enr"]]) if not pd.isna(row[mapping["enr"]]) else "",
                "Student Name": str(row[mapping["name"]]) if not pd.isna(row[mapping["name"]]) else "",
                "Class Number": str(row[mapping["class_num"]]) if not pd.isna(row[mapping["class_num"]]) else "",
                "Class Name": str(row[mapping["class_name"]]) if not pd.isna(row[mapping["class_name"]]) else "",
                "Gender": str(row[mapping["gender"]]) if not pd.isna(row[mapping["gender"]]) else "",
                "Admission Type": str(row[mapping["adm_type"]]) if not pd.isna(row[mapping["adm_type"]]) else "",
                "House Colour": str(row[mapping["house"]]) if not pd.isna(row[mapping["house"]]) else "",
                "Chest": chest_raw if has_chest else "",
                "Waist": waist_raw if has_waist else "",
                "Shirt Size": shirt_size,
                "Bottom Type": bottom_type,
                "Bottom Size": bottom_size,
                "Sports T-Shirt": sports_t_size,
                "School T-Shirt": school_t_size,
                "Sports Track Pant": sports_p_size,
                "Status": status
            }
            if "length" in mapping and mapping["length"]:
                result_row["Length"] = clean_val(row.get(mapping["length"]))

            # Upsert to database with school isolation
            upsert_student(school_id, {
                "enrollment_code": result_row["Enrollment Code"],
                "student_name": result_row["Student Name"],
                "class_number": result_row["Class Number"],
                "class_name": result_row["Class Name"],
                "gender": result_row["Gender"],
                "admission_type": result_row["Admission Type"],
                "house_colour": result_row["House Colour"],
                "chest": result_row.get("Chest") if has_chest else None,
                "waist": result_row.get("Waist") if has_waist else None,
                "length": result_row.get("Length"),
                "shirt_size": str(result_row["Shirt Size"]) if result_row["Shirt Size"] != "" else None,
                "bottom_type": result_row["Bottom Type"] if result_row["Bottom Type"] != "" else None,
                "bottom_size": str(result_row["Bottom Size"]) if result_row["Bottom Size"] != "" else None,
                "sports_tee_size": str(result_row["Sports T-Shirt"]) if result_row["Sports T-Shirt"] != "" else None,
                "school_tee_size": str(result_row["School T-Shirt"]) if result_row["School T-Shirt"] != "" else None,
                "sports_pant_size": str(result_row["Sports Track Pant"]) if result_row["Sports Track Pant"] != "" else None,
                "status": result_row["Status"]
            })

            results.append(result_row)
        except Exception as e:
            err_row = {
                "Enrollment Code": str(row.get(mapping.get("enr", "Unknown"), "Unknown")) if not pd.isna(row.get(mapping.get("enr", "Unknown"), "Unknown")) else "Unknown",
                "Student Name": str(row.get(mapping.get("name", "Unknown"), "Unknown")) if not pd.isna(row.get(mapping.get("name", "Unknown"), "Unknown")) else "Unknown",
                "Class Number": str(row.get(mapping.get("class_num", "Unknown"), "Unknown")) if not pd.isna(row.get(mapping.get("class_num", "Unknown"), "Unknown")) else "Unknown",
                "Class Name": str(row.get(mapping.get("class_name", "Unknown"), "Unknown")) if not pd.isna(row.get(mapping.get("class_name", "Unknown"), "Unknown")) else "Unknown",
                "Gender": str(row.get(mapping.get("gender", "Unknown"), "Unknown")) if not pd.isna(row.get(mapping.get("gender", "Unknown"), "Unknown")) else "Unknown",
                "Admission Type": str(row.get(mapping.get("adm_type", "Unknown"), "Unknown")) if not pd.isna(row.get(mapping.get("adm_type", "Unknown"), "Unknown")) else "Unknown",
                "House Colour": str(row.get(mapping.get("house", "Unknown"), "Unknown")) if not pd.isna(row.get(mapping.get("house", "Unknown"), "Unknown")) else "Unknown",
                "Chest": None,
                "Waist": None,
                "Shirt Size": "Error",
                "Bottom Type": "Error",
                "Bottom Size": "Error",
                "Sports T-Shirt": "Error",
                "School T-Shirt": "Error",
                "Sports Track Pant": "Error",
                "Status": f"Error: {str(e)[:50]}"
            }
            results.append(err_row)

    results = sanitize_records(results)
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

# ============== STUDENT ENDPOINTS (School Isolated) ==============

@app.get("/students")
def list_students(school_id: int, search: str = None):
    school = get_school_by_id(school_id)
    if not school:
        raise HTTPException(status_code=404, detail="School not found")
    df = get_students_by_school(school_id, search)
    records = df.to_dict(orient="records")
    return sanitize_records(records)

@app.get("/students/{student_id}")
def get_student(student_id: int, school_id: int):
    school = get_school_by_id(school_id)
    if not school:
        raise HTTPException(status_code=404, detail="School not found")
    row = get_student_by_id(student_id, school_id)
    if not row:
        raise HTTPException(status_code=404, detail="Student not found")
    keys = [k[0] for k in row.cursor.description] if hasattr(row, 'cursor') else [
        "id", "school_id", "enrollment_code", "student_name", "class_number", "class_name",
        "gender", "admission_type", "house_colour", "chest", "waist", "length",
        "shirt_size", "bottom_type", "bottom_size", "sports_tee_size",
        "school_tee_size", "sports_pant_size", "status", "created_at", "updated_at"
    ]
    return dict(zip(keys, row))

@app.put("/students/{student_id}")
def edit_student(student_id: int, school_id: int, data: dict):
    school = get_school_by_id(school_id)
    if not school:
        raise HTTPException(status_code=404, detail="School not found")
    row = get_student_by_id(student_id, school_id)
    if not row:
        raise HTTPException(status_code=404, detail="Student not found")
    
    # Recalculate sizes if measurements changed
    if data.get("chest") is not None or data.get("waist") is not None:
        chest = data.get("chest")
        waist = data.get("waist")
        
        g_chest = calculate_garment_measure(chest, get_allowance("Shirt")) if chest is not None else None
        shirt_size, _ = match_size(g_chest, get_global_chart("Shirt"), 'Value')
        
        gender_val = str(data.get("gender", "")).upper().strip()
        class_num = str(data.get("class_number", ""))
        if "GIRL" in gender_val or gender_val in ["F", "FEMALE"]:
            bottom_type, target_chart = "Skirt", get_global_chart("Skirt")
        elif "BOY" in gender_val or gender_val in ["M", "MALE"]:
            is_junior = any(class_num.startswith(str(i)) for i in range(1, 6))
            bottom_type, target_chart = ("Shorts", get_global_chart("Shorts")) if is_junior else ("Pant", get_global_chart("Pant"))
        else:
            bottom_type, target_chart = "Shorts", get_global_chart("Shorts")
        
        g_waist = calculate_garment_measure(waist, get_allowance(bottom_type)) if waist is not None else None
        bottom_size, _ = match_size(g_waist, target_chart, 'Value')
        
        sports_chest = calculate_garment_measure(chest, get_allowance("Sports T-Shirt")) if chest is not None else None
        sports_t_size, _ = match_size(sports_chest, get_global_chart("Sports T-Shirt"), 'Value')
        
        school_chest = calculate_garment_measure(chest, get_allowance("School T-Shirt")) if chest is not None else None
        school_t_size, _ = match_size(school_chest, get_global_chart("School T-Shirt"), 'Value')
        
        sports_waist = calculate_garment_measure(waist, get_allowance("Sports Track Pant")) if waist is not None else None
        sports_p_size, _ = match_size(sports_waist, get_global_chart("Sports Track Pant"), 'Value')
        
        data["shirt_size"] = shirt_size if shirt_size else "Invalid"
        data["bottom_type"] = bottom_type
        data["bottom_size"] = bottom_size if bottom_size else "Invalid"
        data["sports_tee_size"] = sports_t_size if sports_t_size else "Invalid"
        data["school_tee_size"] = school_t_size if school_t_size else "Invalid"
        data["sports_pant_size"] = sports_p_size if sports_p_size else "Invalid"
        data["status"] = "OK" if (shirt_size and bottom_size) else "Error"
    
    update_student_data(student_id, school_id, data)
    return {"status": "updated"}

@app.delete("/students/{student_id}")
def remove_student(student_id: int, school_id: int):
    school = get_school_by_id(school_id)
    if not school:
        raise HTTPException(status_code=404, detail="School not found")
    row = get_student_by_id(student_id, school_id)
    if not row:
        raise HTTPException(status_code=404, detail="Student not found")
    delete_student(student_id, school_id)
    return {"status": "deleted"}

@app.get("/")
def root():
    return {"message": "Central Uniform Sizer API v2.1.0", "status": "running"}
