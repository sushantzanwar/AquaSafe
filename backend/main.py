from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import Dict, Any, List
import datetime

app = FastAPI(title="AquaWatch Backend API", description="Intelligence pipeline for AquaWatch")

# ---- Models ----
class AnalysisRequest(BaseModel):
    water_body: str
    date: str

class AnalysisResponse(BaseModel):
    analysis_id: str
    water_body: str
    date: str
    indicators: Dict[str, float]
    anomaly: Dict[str, Any]
    priority: Dict[str, int]
    geojson: Dict[str, Any]

# ---- Mock Database ----
MOCK_ANALYSIS = {
    "A123": {
        "analysis_id": "A123",
        "water_body": "Ambazari Lake",
        "date": "2026-09-25",
        "indicators": {
            "ndwi": 0.61,
            "ndti": 0.32,
            "ndci": 0.18
        },
        "anomaly": {
            "status": "HIGH",
            "score": 86,
            "confidence": 0.87
        },
        "priority": {
            "score": 91
        },
        "geojson": {
            "type": "FeatureCollection",
            "features": [
                {
                    "type": "Feature",
                    "geometry": {
                        "type": "Polygon",
                        "coordinates": [[[79.033, 21.123], [79.033, 21.135], [79.045, 21.135], [79.045, 21.123], [79.033, 21.123]]]
                    },
                    "properties": {"name": "Ambazari Lake Segment"}
                }
            ]
        }
    }
}

# ---- Endpoints ----

from core.remote_sensing import generate_mock_sentinel_scene, process_scene_indices
from models.water_segmentation import generate_water_mask
from core.database import init_db, save_analysis, get_history, get_baseline
from core.anomaly import calculate_anomaly_score, calculate_priority
from contextlib import asynccontextmanager

@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield

app.router.lifespan_context = lifespan


@app.post("/api/analyze", response_model=AnalysisResponse)
async def analyze_scene(request: AnalysisRequest):
    """
    Trigger the pipeline for a water body and date.
    Uses synthetic data to test the end-to-end intelligence pipeline.
    """
    # 1. Ingestion (Mock)
    scene = generate_mock_sentinel_scene((256, 256))
    
    # 2. Spectral Analysis (Calculates NDWI, NDTI, NDCI)
    indices = process_scene_indices(scene)
    
    # 3. Water-body Detection (Mock AI model)
    water_mask = generate_water_mask(scene)
    
    # Average the indices over the water mask area to get single indicator values
    water_pixels = water_mask > 0
    ndwi_val = float(indices["ndwi"][water_pixels].mean()) if water_pixels.any() else 0.0
    ndti_val = float(indices["ndti"][water_pixels].mean()) if water_pixels.any() else 0.0
    ndci_val = float(indices["ndci"][water_pixels].mean()) if water_pixels.any() else 0.0

    # Calculate Anomaly against historical baseline
    baseline = get_baseline(request.water_body)
    anomaly_result = calculate_anomaly_score(ndti_val, baseline["ndti_mean"], baseline["ndti_std"])
    
    # Calculate Priority
    priority_result = calculate_priority(anomaly_result["score"], persistence_days=1, proximity_factor=1.0)

    # 4. Construct Response matching the agreed contract
    response_data = {
        "analysis_id": f"A_{request.date.replace('-','')}_{request.water_body.replace(' ','')}",
        "water_body": request.water_body,
        "date": request.date,
        "indicators": {
            "ndwi": round(ndwi_val, 3),
            "ndti": round(ndti_val, 3),
            "ndci": round(ndci_val, 3)
        },
        "anomaly": {
            "status": anomaly_result["status"],
            "score": anomaly_result["score"],
            "confidence": anomaly_result["confidence"],
            "deviation_sigma": anomaly_result.get("deviation_sigma", 0)
        },
        "priority": {
            "score": priority_result["score"]
        },
        "geojson": MOCK_ANALYSIS["A123"]["geojson"] # Keeping the static geojson for now
    }
    
    # 5. Save to database
    save_analysis(response_data)
    
    return response_data

@app.get("/api/water-bodies")
async def get_water_bodies():
    """List of currently monitored water bodies."""
    return ["Ambazari Lake", "Futala Lake", "Gorewada Lake"]

@app.get("/api/analysis/{analysis_id}", response_model=AnalysisResponse)
async def get_analysis(analysis_id: str):
    """Fetch the full analysis payload by ID."""
    if analysis_id not in MOCK_ANALYSIS:
        raise HTTPException(status_code=404, detail="Analysis not found")
    return MOCK_ANALYSIS[analysis_id]

@app.get("/api/analysis/{analysis_id}/history")
async def get_analysis_history(analysis_id: str, water_body: str = "Ambazari Lake"):
    """Fetch temporal history for the charts from database."""
    history_data = get_history(water_body)
    formatted_history = []
    for row in history_data:
        formatted_history.append({
            "date": row["date"],
            "ndti": row["ndti"],
            "ndci": row["ndci"],
            "status": row["anomaly_status"]
        })
    
    return {
        "analysis_id": analysis_id,
        "water_body": water_body,
        "history": formatted_history
    }

@app.get("/api/analysis/{analysis_id}/anomalies")
async def get_anomalies(analysis_id: str, water_body: str = "Ambazari Lake"):
    """Detailed anomaly explanation based on database baseline."""
    baseline = get_baseline(water_body)
    return {
        "analysis_id": analysis_id,
        "baseline": {"ndti_mean": round(baseline["ndti_mean"], 3), "ndci_mean": round(baseline["ndci_mean"], 3)},
        "deviation": {"ndti_std": round(baseline["ndti_std"], 3), "ndci_std": round(baseline["ndci_std"], 3)},
        "contributing_indicators": 3
    }

@app.get("/api/analysis/{analysis_id}/priority")
async def get_analysis_priority(analysis_id: str):
    """Return just the priority score block."""
    if analysis_id not in MOCK_ANALYSIS:
        # Fallback if not found in MOCK_ANALYSIS
        return {"score": 50}
    return MOCK_ANALYSIS[analysis_id]["priority"]

# ---- Stress Test Endpoint for Person 3 ----

class StressTestRequest(BaseModel):
    water_body: str
    date: str
    anomaly_multiplier: float = 3.0

@app.post("/api/stress-test", response_model=AnalysisResponse)
async def stress_test_pipeline(request: StressTestRequest):
    """
    Injects synthetic changes for demo mode.
    Forces extreme values to trigger HIGH anomaly and Priority scores.
    """
    # 1. Generate normal scene
    scene = generate_mock_sentinel_scene((256, 256))
    
    # Inject synthetic stress (e.g. increase red and nir bands to simulate high turbidity)
    scene["red"] = scene["red"] * request.anomaly_multiplier # Red
    scene["nir"] = scene["nir"] * request.anomaly_multiplier # NIR
    
    # 2. Spectral Analysis
    indices = process_scene_indices(scene)
    
    # 3. Water-body Detection
    water_mask = generate_water_mask(scene)
    
    water_pixels = water_mask > 0
    ndwi_val = float(indices["ndwi"][water_pixels].mean()) if water_pixels.any() else 0.0
    ndti_val = float(indices["ndti"][water_pixels].mean()) if water_pixels.any() else 0.0
    ndci_val = float(indices["ndci"][water_pixels].mean()) if water_pixels.any() else 0.0

    # Baseline & Anomaly
    baseline = get_baseline(request.water_body)
    anomaly_result = calculate_anomaly_score(ndti_val, baseline["ndti_mean"], baseline["ndti_std"])
    priority_result = calculate_priority(anomaly_result["score"], persistence_days=3, proximity_factor=1.5)

    response_data = {
        "analysis_id": f"STRESS_{request.date.replace('-','')}_{request.water_body.replace(' ','')}",
        "water_body": request.water_body,
        "date": request.date,
        "indicators": {
            "ndwi": round(ndwi_val, 3),
            "ndti": round(ndti_val, 3),
            "ndci": round(ndci_val, 3)
        },
        "anomaly": {
            "status": anomaly_result["status"],
            "score": anomaly_result["score"],
            "confidence": anomaly_result["confidence"],
            "deviation_sigma": anomaly_result.get("deviation_sigma", 0)
        },
        "priority": {
            "score": priority_result["score"]
        },
        "geojson": MOCK_ANALYSIS.get("A123", {}).get("geojson", {}) 
    }
    
    save_analysis(response_data)
    
    return response_data

@app.get("/api/analysis/{analysis_id}/geojson")
async def get_geojson(analysis_id: str):
    """Return just the GeoJSON boundaries for Leaflet."""
    if analysis_id not in MOCK_ANALYSIS:
        raise HTTPException(status_code=404, detail="Analysis not found")
    return MOCK_ANALYSIS[analysis_id]["geojson"]

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
