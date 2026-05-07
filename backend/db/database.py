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

    defaults = {
        "Shirt": 3.0, "Pant": 1.0, "Skirt": 1.0, "Shorts": 1.0,
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

def save_global_chart(item_type, chart_df):
    conn = _get_conn()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM global_size_charts WHERE item_type = ?", (item_type,))
    for _, row in chart_df.iterrows():
        size_label = row.get('Size') or row.get('size_label')
        measurement_value = row.get('Value') or row.get('measurement_value')
        if size_label is not None and measurement_value is not None:
            cursor.execute(
                "INSERT INTO global_size_charts (item_type, size_label, measurement_value) VALUES (?, ?, ?)",
                (item_type, str(size_label), float(measurement_value))
            )
    conn.commit()
    conn.close()

def get_global_chart(item_type):
    conn = _get_conn()
    query = "SELECT size_label as Size, measurement_value as Value FROM global_size_charts WHERE item_type = ?"
    df = pd.read_sql_query(query, conn, params=(item_type,))
    conn.close()
    return df

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
