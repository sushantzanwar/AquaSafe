import sqlite3
import json
import os
from typing import List, Dict, Any

DB_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "historical_data.db")

def init_db():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS history (
            analysis_id TEXT PRIMARY KEY,
            water_body TEXT,
            date TEXT,
            ndwi REAL,
            ndti REAL,
            ndci REAL,
            anomaly_status TEXT,
            anomaly_score INTEGER,
            priority_score INTEGER
        )
    """)
    # Pre-populate with some mock historical data for Ambazari Lake if empty
    cursor.execute("SELECT COUNT(*) FROM history")
    if cursor.fetchone()[0] == 0:
        mock_data = [
            ("A_20260625", "Ambazari Lake", "2026-06-25", 0.65, 0.12, 0.05, "NORMAL", 10, 15),
            ("A_20260725", "Ambazari Lake", "2026-07-25", 0.64, 0.14, 0.07, "NORMAL", 12, 18),
            ("A_20260825", "Ambazari Lake", "2026-08-25", 0.63, 0.13, 0.06, "NORMAL", 11, 16),
            ("A_20260925", "Ambazari Lake", "2026-09-25", 0.61, 0.32, 0.18, "HIGH", 86, 91),
        ]
        cursor.executemany("""
            INSERT INTO history (analysis_id, water_body, date, ndwi, ndti, ndci, anomaly_status, anomaly_score, priority_score)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, mock_data)
    conn.commit()
    conn.close()

def save_analysis(analysis_data: Dict[str, Any]):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("""
        INSERT OR REPLACE INTO history (analysis_id, water_body, date, ndwi, ndti, ndci, anomaly_status, anomaly_score, priority_score)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        analysis_data["analysis_id"],
        analysis_data["water_body"],
        analysis_data["date"],
        analysis_data["indicators"]["ndwi"],
        analysis_data["indicators"]["ndti"],
        analysis_data["indicators"]["ndci"],
        analysis_data["anomaly"]["status"],
        analysis_data["anomaly"]["score"],
        analysis_data["priority"]["score"]
    ))
    conn.commit()
    conn.close()

def get_history(water_body: str) -> List[Dict[str, Any]]:
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("""
        SELECT analysis_id, date, ndwi, ndti, ndci, anomaly_status, anomaly_score, priority_score
        FROM history WHERE water_body = ? ORDER BY date ASC
    """, (water_body,))
    rows = cursor.fetchall()
    conn.close()
    
    history = []
    for row in rows:
        history.append({
            "analysis_id": row[0],
            "date": row[1],
            "ndwi": row[2],
            "ndti": row[3],
            "ndci": row[4],
            "anomaly_status": row[5],
            "anomaly_score": row[6],
            "priority_score": row[7]
        })
    return history

def get_analysis(analysis_id: str) -> Dict[str, Any]:
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("""
        SELECT analysis_id, water_body, date, ndwi, ndti, ndci, anomaly_status, anomaly_score, priority_score
        FROM history WHERE analysis_id = ?
    """, (analysis_id,))
    row = cursor.fetchone()
    conn.close()
    if not row:
        return None
    return {
        "analysis_id": row[0],
        "water_body": row[1],
        "date": row[2],
        "indicators": {"ndwi": row[3], "ndti": row[4], "ndci": row[5]},
        "anomaly": {"status": row[6], "score": row[7]},
        "priority": {"score": row[8]}
    }

def get_baseline(water_body: str, limit: int = 5) -> Dict[str, float]:
    """Calculate mean and std dev of historical data to establish a baseline."""
    history = get_history(water_body)
    if not history:
        return {"ndti_mean": 0, "ndti_std": 0, "ndci_mean": 0, "ndci_std": 0}
        
    # Exclude recent high anomalies from baseline if possible, or just take the last 'limit' normal readings
    normal_history = [h for h in history if h["anomaly_status"] == "NORMAL"]
    if not normal_history:
        normal_history = history
        
    normal_history = normal_history[-limit:]
    
    ndti_vals = [h["ndti"] for h in normal_history]
    ndci_vals = [h["ndci"] for h in normal_history]
    
    import numpy as np
    return {
        "ndti_mean": float(np.mean(ndti_vals)) if ndti_vals else 0,
        "ndti_std": float(np.std(ndti_vals)) if len(ndti_vals) > 1 else 0.01, # small default std
        "ndci_mean": float(np.mean(ndci_vals)) if ndci_vals else 0,
        "ndci_std": float(np.std(ndci_vals)) if len(ndci_vals) > 1 else 0.01
    }
