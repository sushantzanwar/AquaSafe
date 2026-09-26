from fastapi import FastAPI
from datetime import datetime
import json
import os

app = FastAPI(title="AquaWatch Mock Backend API")

# This is a sample response that perfectly matches our analysis_contract.json
mock_data = {
    "analysis_id": "AW-2026-09-26-001",
    "timestamp": datetime.utcnow().isoformat() + "Z",
    "location": {
        "name": "Ambazari Lake",
        "coordinates": [79.0357, 21.1311]
    },
    "satellite_data": {
        "source": "Sentinel-2",
        "scene_date": "2026-09-25",
        "cloud_cover_percentage": 2.4
    },
    "water_detection": {
        "model_used": "giswqs/s2-water-unetplusplus-efficientnet-b4",
        "water_surface_area_sq_km": 15.2,
        "mask_geojson_url": "/api/mock/geojson/AW-2026-09-26-001"
    },
    "contamination_detection": {
        "model_used": "aquawatch-contamination-v1",
        "indicators": {
            "ndwi": 0.61,
            "ndti": 0.32,
            "ndci": 0.18,
            "turbidity": 45.5
        },
        "anomaly_status": "HIGH",
        "confidence_score": 0.89,
        "detected_contaminants": ["Algal Bloom", "High Suspended Sediment"]
    },
    "investigation_priority": {
        "score": 91,
        "recommendation": "Immediate field investigation required due to sudden spike in NDCI."
    }
}

@app.get("/api/analysis/{analysis_id}")
async def get_analysis(analysis_id: str):
    """
    Mock endpoint that Person 2 (Frontend) and Person 3 (AI Assistant) 
    can use to fetch 'live' data without waiting for the real backend.
    """
    # Overwrite the ID to match whatever was requested for demo purposes
    response = mock_data.copy()
    response["analysis_id"] = analysis_id
    return response

@app.get("/api/analysis/latest")
async def get_latest_analysis():
    """Returns the most recent analysis run."""
    return mock_data

if __name__ == "__main__":
    import uvicorn
    # Run using: python mock_server.py
    uvicorn.run(app, host="0.0.0.0", port=8000)
