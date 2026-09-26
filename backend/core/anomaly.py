import numpy as np

def calculate_anomaly_score(current_value: float, historical_baseline: float, std_dev: float) -> dict:
    """
    Implements statistical anomaly logic based on historical standard deviation.
    """
    if std_dev == 0:
        return {"status": "NORMAL", "score": 0, "confidence": 0.0}

    deviation = (current_value - historical_baseline) / std_dev
    
    # Sigmoid-like scaling for anomaly score (0 to 100) based on deviation
    score = min(100, max(0, int((abs(deviation) / 4.0) * 100))) 
    confidence = min(1.0, abs(deviation) / 5.0)

    status = "NORMAL"
    if deviation > 3.2:
        status = "HIGH"
    elif deviation > 2.0:
        status = "WARNING"

    return {
        "status": status,
        "score": score,
        "confidence": round(confidence, 2),
        "deviation_sigma": round(deviation, 2)
    }

def calculate_priority(severity_score: int, persistence_days: int = 1, proximity_factor: float = 1.0) -> dict:
    """
    Calculates investigation priority using severity, persistence, and proximity.
    """
    priority = (severity_score * 0.5) + (persistence_days * 10) + (proximity_factor * 20)
    final_score = min(100, max(0, int(priority)))
    return {"score": final_score}
