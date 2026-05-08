import sqlite3
import pandas as pd
import os
from datetime import datetime

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(BASE_DIR, "data")
DB_PATH = os.path.join(DATA_DIR, "app.db")

def _get_conn():
    return sqlite3.connect(DB_PATH)

def init_db():
    os.makedirs(DATA_DIR, exist_ok=True)
    conn = _get_conn()
    cursor = conn.cursor()

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS schools (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE NOT NULL,
            academic_year TEXT
        )
    ''')

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS global_size_charts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            item_type TEXT,
            size_label TEXT,
            measurement_value REAL
        )
    ''')

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS allowances (
            item_type TEXT PRIMARY KEY,
            value REAL
        )
    ''')

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL
        )
    ''')

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            school_id INTEGER,
            school_name TEXT,
            processed_at TEXT,
            total_count INTEGER,
            success_count INTEGER,
            error_count INTEGER,
            file_path TEXT
        )
    ''')

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS students (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            school_id INTEGER NOT NULL,
            enrollment_code TEXT NOT NULL,
            student_name TEXT,
            class_number TEXT,
            class_name TEXT,
            gender TEXT,
            admission_type TEXT,
            house_colour TEXT,
            chest REAL,
            waist REAL,
            length REAL,
            shirt_size TEXT,
            bottom_type TEXT,
            bottom_size TEXT,
            sports_tee_size TEXT,
            school_tee_size TEXT,
            sports_pant_size TEXT,
            status TEXT,
            created_at TEXT,
            updated_at TEXT,
            UNIQUE(school_id, enrollment_code)
        )
    ''')

    defaults = {
        "Shirt": 3.0, "Pant": 1.0, "Skirt": 1.0, "Shorts": 1.0,
        "PP Shorts": 1.0, "PP Skirts": 1.0,
        "Sports T-Shirt": 3.0, "School T-Shirt": 3.0, "Sports Track Pant": 1.0
    }

    for item, val in defaults.items():
        cursor.execute(
            "INSERT OR IGNORE INTO allowances (item_type, value) VALUES (?, ?)",
            (item, val)
        )

    cursor.execute("SELECT * FROM users WHERE username = 'admin'")
    if not cursor.fetchone():
        cursor.execute(
            "INSERT INTO users (username, password) VALUES (?, ?)",
            ('admin', 'admin123')
        )

    conn.commit()
    conn.close()

def verify_user(u, p):
    conn = _get_conn()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM users WHERE username = ? AND password = ?", (u, p))
    res = cursor.fetchone()
    conn.close()
    return res is not None

# Schools
def save_school(n, y):
    conn = _get_conn()
    try:
        conn.execute("INSERT INTO schools (name, academic_year) VALUES (?, ?)", (n, y))
        conn.commit()
        return True
    except sqlite3.IntegrityError:
        return False
    finally:
        conn.close()

def update_school(sid, n, y):
    conn = _get_conn()
    conn.execute("UPDATE schools SET name = ?, academic_year = ? WHERE id = ?", (n, y, sid))
    conn.commit()
    conn.close()

def delete_school(sid):
    conn = _get_conn()
    conn.execute("DELETE FROM schools WHERE id = ?", (sid,))
    conn.commit()
    conn.close()

def get_all_schools():
    conn = _get_conn()
    df = pd.read_sql_query("SELECT * FROM schools", conn)
    conn.close()
    return df

def get_school_by_id(sid):
    conn = _get_conn()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM schools WHERE id = ?", (sid,))
    row = cursor.fetchone()
    conn.close()
    return row

# Charts
def save_global_chart(item_type, chart_df):
    conn = _get_conn()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM global_size_charts WHERE item_type = ?", (item_type,))
    for _, row in chart_df.iterrows():
        size_label = row.get('Size') or row.get('size_label')
        measurement_value = row.get('Value') or row.get('measurement_value')
        if size_label and str(size_label).strip() and measurement_value is not None and str(measurement_value).strip() != '':
            try:
                cursor.execute(
                    "INSERT INTO global_size_charts (item_type, size_label, measurement_value) VALUES (?, ?, ?)",
                    (item_type, str(size_label), float(measurement_value))
                )
            except (ValueError, TypeError):
                continue
    conn.commit()
    conn.close()

def get_global_chart(item_type):
    conn = _get_conn()
    query = "SELECT size_label as Size, measurement_value as Value FROM global_size_charts WHERE item_type = ?"
    df = pd.read_sql_query(query, conn, params=(item_type,))
    conn.close()
    return df

# Allowances
def get_allowance(item_type):
    conn = _get_conn()
    cursor = conn.cursor()
    cursor.execute("SELECT value FROM allowances WHERE item_type = ?", (item_type,))
    res = cursor.fetchone()
    conn.close()
    return res[0] if res else 1.0

def update_allowance(item_type, value):
    conn = _get_conn()
    conn.execute("UPDATE allowances SET value = ? WHERE item_type = ?", (float(value), item_type))
    conn.commit()
    conn.close()

def get_all_allowances():
    conn = _get_conn()
    df = pd.read_sql_query("SELECT * FROM allowances", conn)
    conn.close()
    return df

# History
def add_history(school_id, school_name, total, success, errors, file_path):
    conn = _get_conn()
    cursor = conn.cursor()
    now = datetime.now().isoformat()
    cursor.execute(
        "INSERT INTO history (school_id, school_name, processed_at, total_count, success_count, error_count, file_path) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (school_id, school_name, now, total, success, errors, file_path)
    )
    conn.commit()
    conn.close()

def get_history():
    conn = _get_conn()
    df = pd.read_sql_query(
        "SELECT * FROM history ORDER BY processed_at DESC", conn
    )
    conn.close()
    return df

# Students
def upsert_student(school_id, data):
    conn = _get_conn()
    cursor = conn.cursor()
    now = datetime.now().isoformat()
    
    cursor.execute(
        "SELECT id FROM students WHERE school_id = ? AND enrollment_code = ?",
        (school_id, data['enrollment_code'])
    )
    row = cursor.fetchone()
    
    if row:
        cursor.execute('''
            UPDATE students SET
                student_name = ?, class_number = ?, class_name = ?, gender = ?,
                admission_type = ?, house_colour = ?, chest = ?, waist = ?,
                length = ?, shirt_size = ?, bottom_type = ?, bottom_size = ?,
                sports_tee_size = ?, school_tee_size = ?, sports_pant_size = ?,
                status = ?, updated_at = ?
            WHERE school_id = ? AND enrollment_code = ?
        ''', (
            data.get('student_name'), data.get('class_number'), data.get('class_name'),
            data.get('gender'), data.get('admission_type'), data.get('house_colour'),
            data.get('chest'), data.get('waist'), data.get('length'),
            data.get('shirt_size'), data.get('bottom_type'), data.get('bottom_size'),
            data.get('sports_tee_size'), data.get('school_tee_size'), data.get('sports_pant_size'),
            data.get('status'), now, school_id, data['enrollment_code']
        ))
    else:
        cursor.execute('''
            INSERT INTO students (
                school_id, enrollment_code, student_name, class_number, class_name,
                gender, admission_type, house_colour, chest, waist, length,
                shirt_size, bottom_type, bottom_size, sports_tee_size,
                school_tee_size, sports_pant_size, status, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            school_id, data['enrollment_code'], data.get('student_name'),
            data.get('class_number'), data.get('class_name'), data.get('gender'),
            data.get('admission_type'), data.get('house_colour'), data.get('chest'),
            data.get('waist'), data.get('length'), data.get('shirt_size'),
            data.get('bottom_type'), data.get('bottom_size'), data.get('sports_tee_size'),
            data.get('school_tee_size'), data.get('sports_pant_size'), data.get('status'),
            now, now
        ))
    
    conn.commit()
    conn.close()

def get_students_by_school(school_id, search=None):
    conn = _get_conn()
    query = "SELECT * FROM students WHERE school_id = ?"
    params = [school_id]
    if search:
        query += " AND (student_name LIKE ? OR enrollment_code LIKE ? OR class_name LIKE ?)"
        like = f"%{search}%"
        params.extend([like, like, like])
    query += " ORDER BY student_name"
    df = pd.read_sql_query(query, conn, params=params)
    conn.close()
    return df

def get_student_by_id(student_id, school_id):
    conn = _get_conn()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM students WHERE id = ? AND school_id = ?", (student_id, school_id))
    row = cursor.fetchone()
    conn.close()
    return row

def update_student_data(student_id, school_id, data):
    conn = _get_conn()
    cursor = conn.cursor()
    now = datetime.now().isoformat()
    cursor.execute('''
        UPDATE students SET
            student_name = ?, class_number = ?, class_name = ?, gender = ?,
            admission_type = ?, house_colour = ?, chest = ?, waist = ?,
            length = ?, shirt_size = ?, bottom_type = ?, bottom_size = ?,
            sports_tee_size = ?, school_tee_size = ?, sports_pant_size = ?,
            status = ?, updated_at = ?
        WHERE id = ? AND school_id = ?
    ''', (
        data.get('student_name'), data.get('class_number'), data.get('class_name'),
        data.get('gender'), data.get('admission_type'), data.get('house_colour'),
        data.get('chest'), data.get('waist'), data.get('length'),
        data.get('shirt_size'), data.get('bottom_type'), data.get('bottom_size'),
        data.get('sports_tee_size'), data.get('school_tee_size'), data.get('sports_pant_size'),
        data.get('status'), now, student_id, school_id
    ))
    conn.commit()
    conn.close()

def delete_student(student_id, school_id):
    conn = _get_conn()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM students WHERE id = ? AND school_id = ?", (student_id, school_id))
    conn.commit()
    conn.close()
