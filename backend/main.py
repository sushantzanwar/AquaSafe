from fastapi import FastAPI, HTTPException, Response
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Dict, Any, List, Optional
import datetime

app = FastAPI(title="AquaWatch Backend API", description="Intelligence pipeline for AquaWatch")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---- Models ----
class AnalysisRequest(BaseModel):
    water_body: str
    date: str
    lat: Optional[float] = 21.129
    lng: Optional[float] = 79.039

class AnalysisResponse(BaseModel):
    analysis_id: str
    water_body: str
    date: str
    indicators: Dict[str, float]
    anomaly: Dict[str, Any]
    priority: Dict[str, int]
    geojson: Dict[str, Any]

# ---- Locality Points Database ----
LOCALITY_POINTS = [
    {"id": "ambazari_center", "name": "Ambazari Lake — Center Point", "water_body": "Ambazari Lake", "lat": 21.1292, "lng": 79.0394, "district": "Nagpur West"},
    {"id": "ambazari_spillway", "name": "Ambazari Lake — Spillway Intake", "water_body": "Ambazari Lake", "lat": 21.1325, "lng": 79.0431, "district": "Nagpur West"},
    {"id": "futala_north", "name": "Futala Lake — North Inlet", "water_body": "Futala Lake", "lat": 21.1558, "lng": 79.0478, "district": "Nagpur North"},
    {"id": "gorewada_intake", "name": "Gorewada Reservoir — Treatment Intake", "water_body": "Gorewada Lake", "lat": 21.1891, "lng": 79.0321, "district": "Nagpur NW"},
    {"id": "gandhisagar_east", "name": "Gandhisagar Lake — East Basin", "water_body": "Gandhisagar Lake", "lat": 21.1448, "lng": 79.0965, "district": "Central Nagpur"},
    {"id": "sonegaon_south", "name": "Sonegaon Lake — South Reach", "water_body": "Sonegaon Lake", "lat": 21.0934, "lng": 79.0562, "district": "Nagpur South"},
    {"id": "erie_maumee", "name": "Lake Erie — Maumee Bay Outlet", "water_body": "Lake Erie", "lat": 41.7450, "lng": -83.4100, "district": "West Basin"},
    {"id": "erie_sandusky", "name": "Lake Erie — Sandusky Bay Sector", "water_body": "Lake Erie", "lat": 41.4750, "lng": -82.8250, "district": "Central Shore"},
]

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

from core.remote_sensing import generate_mock_sentinel_scene, generate_realistic_sentinel_scene, render_satellite_image_png, process_scene_indices
from models.water_segmentation import generate_water_mask
from core.database import init_db, save_analysis, get_history, get_baseline
from core.anomaly import calculate_anomaly_score, calculate_priority
from contextlib import asynccontextmanager
import sys
import os

# Import AI Assistant logic from the sibling directory
AI_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "ai_assistant")
if AI_DIR not in sys.path:
    sys.path.append(AI_DIR)
# pyrefly: ignore [missing-import]
from rag.assistant import generate_explanation

@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield

app.router.lifespan_context = lifespan


@app.get("/api/locality-points")
async def get_locality_points():
    """List of monitored locality points with coordinates for manual selection or dropdown."""
    return LOCALITY_POINTS


# ---- Satellite Layer Definitions ----
SATELLITE_LAYERS = [
    {
        "key": "algal",
        "layer": "bloom",
        "title": "Algal Activity — Chlorophyll-a / NDCI Map",
        "short_title": "Algal Activity (NDCI / Chl-a)",
        "description": "Multispectral heat map overlay on the water body highlighting high photosynthetic activity to isolate algal blooms.",
        "image": "images/algal_bloom.jpg",
        "band": "S2 B5-B4 · NDCI",
        "summary_value": "NDCI: +0.41",
        "summary_color": "var(--green)",
        "dot_color": "var(--green)",
        "severity": "HIGH",
        "severity_class": "sh",
        "pulse": True,
        "status": "BLOOM CONFIRMED — HIGH",
        "status_color": "var(--red)",
        "source": "ESA Copernicus Sentinel-2\nL2A Surface Reflectance\n10m × 10m spatial resolution",
        "indicators": [
            {"name": "NDCI Index",      "value": "+0.41",       "color": "var(--red)",    "pct": 82},
            {"name": "Chl-a Estimate",  "value": "68.4 µg/L",  "color": "var(--yellow)", "pct": 68},
            {"name": "Bloom Coverage",  "value": "34% surface", "color": "var(--yellow)", "pct": 34},
            {"name": "Confidence",      "value": "0.89",        "color": "var(--green)",  "pct": 89}
        ],
        "science": "NDCI (Normalized Difference Chlorophyll Index) is computed as (B5−B4)/(B5+B4) from Sentinel-2. Values above 0.2 indicate significant phytoplankton concentration. Neon green-yellow zones correspond to algal bloom hotspots requiring immediate sample collection and public health advisories."
    },
    {
        "key": "erosion",
        "layer": "erosion",
        "title": "Soil Erosion — Total Suspended Solids (TSS) Map",
        "short_title": "Soil Erosion (TSS / Turbidity)",
        "description": "Zones of high water turbidity near the shoreline marking adjacent land areas showing topographical soil loss compared to the baseline map.",
        "image": "images/soil_erosion.jpg",
        "band": "S2 B4-B3 · NDTI",
        "summary_value": "TSS: 48 mg/L",
        "summary_color": "var(--yellow)",
        "dot_color": "var(--yellow)",
        "severity": "MODERATE",
        "severity_class": "sm",
        "pulse": False,
        "status": "TURBIDITY ANOMALY — MODERATE",
        "status_color": "var(--yellow)",
        "source": "ESA Copernicus Sentinel-2\nL2A Surface Reflectance\n10m × 10m spatial resolution",
        "indicators": [
            {"name": "NDTI Index",   "value": "+0.29",       "color": "var(--yellow)", "pct": 58},
            {"name": "TSS Estimate", "value": "48 mg/L",     "color": "var(--yellow)", "pct": 48},
            {"name": "Plume Area",   "value": "18% surface", "color": "var(--yellow)", "pct": 18},
            {"name": "Confidence",   "value": "0.81",        "color": "var(--green)",  "pct": 81}
        ],
        "science": "TSS is derived from the red-band reflectance and the NDTI index (Red−Green)/(Red+Green). Orange-brown plumes entering from the shoreline indicate active soil erosion and sediment transport. Adjacent land erosion scars are identified by comparing bare soil reflectance against vegetated baseline values using Landsat/Sentinel multi-date composites."
    },
    {
        "key": "thermal",
        "layer": "thermal",
        "title": "Industrial Discharge — Thermal Plume Map",
        "short_title": "Industrial Discharge (Thermal)",
        "description": "Thermal infrared color gradient over the water body to isolate temperature anomalies and trace the flow paths of industrial discharge.",
        "image": "images/thermal_discharge.jpg",
        "band": "Landsat B10 · LSWR",
        "summary_value": "ΔT: +6.2°C",
        "summary_color": "var(--red)",
        "dot_color": "var(--red)",
        "severity": "CRITICAL",
        "severity_class": "sh",
        "pulse": True,
        "status": "THERMAL ANOMALY — CRITICAL",
        "status_color": "var(--red)",
        "source": "Landsat-8/9 Band 10\nThermal Infrared (TIRS)\n100m resampled to 30m",
        "indicators": [
            {"name": "Temp. Anomaly",    "value": "+6.2°C",   "color": "var(--red)",    "pct": 90},
            {"name": "Plume Length",     "value": "2.4 km",   "color": "var(--red)",    "pct": 75},
            {"name": "Discharge Points", "value": "3 sources","color": "var(--yellow)", "pct": 60},
            {"name": "Confidence",       "value": "0.94",     "color": "var(--green)",  "pct": 94}
        ],
        "science": "Land Surface Water Temperature (LSWR) is retrieved from Landsat-8/9 Band 10 (thermal infrared). Industrial cooling water or waste discharge creates temperature plumes visible in TIR imagery. Critical threshold: anomaly >4°C above ambient temperature baseline indicates thermal pollution. Flow trajectories are computed using current vectors derived from multi-temporal TIR composites."
    },
    {
        "key": "runoff",
        "layer": "runoff",
        "title": "Agricultural Runoff — Flow Accumulation Map",
        "short_title": "Agricultural Runoff (Flow Acc.)",
        "description": "Directional flow vectors and accumulation zones across adjacent land to trace the exact topographical pathways where runoff enters the water.",
        "image": "images/agricultural_runoff.jpg",
        "band": "DEM + S2 · NDVI",
        "summary_value": "3 Entry Points",
        "summary_color": "var(--cyan)",
        "dot_color": "var(--cyan)",
        "severity": "MODERATE",
        "severity_class": "sm",
        "pulse": False,
        "status": "RUNOFF RISK — MODERATE",
        "status_color": "var(--cyan)",
        "source": "SRTM 10m DEM + Sentinel-2\nD-infinity flow accumulation\nNDVI seasonal composite",
        "indicators": [
            {"name": "Entry Points",      "value": "3 nodes",    "color": "var(--cyan)",   "pct": 60},
            {"name": "Flow Accumulation", "value": "High (N)",   "color": "var(--cyan)",   "pct": 72},
            {"name": "Nitrate Proxy",     "value": "NDVI −0.18", "color": "var(--yellow)", "pct": 45},
            {"name": "Confidence",        "value": "0.78",       "color": "var(--green)",  "pct": 78}
        ],
        "science": "Hydrological flow accumulation is modeled from a 10m DEM (SRTM/Copernicus) using the D-infinity algorithm. Directional flow vectors show topographic drainage concentration zones across agricultural land. Entry point nodes mark where cumulative flow reaches the lake boundary. Fertilizer/pesticide proxy is estimated via negative NDVI change relative to seasonal baseline."
    },
    {
        "key": "sewage",
        "layer": "sewage",
        "title": "Sewage — Dissolved Oxygen / BOD Depletion Map",
        "short_title": "Sewage (DO / BOD Depletion)",
        "description": "Specific zones of oxygen depletion within the water body using a color gradient to visualize the spread and impact of organic sewage.",
        "image": "images/sewage_do.jpg",
        "band": "S2 + ML · DO Model",
        "summary_value": "DO: 2.1 mg/L",
        "summary_color": "var(--purple)",
        "dot_color": "var(--purple)",
        "severity": "CRITICAL",
        "severity_class": "sh",
        "pulse": True,
        "status": "HYPOXIA DETECTED — CRITICAL",
        "status_color": "var(--purple)",
        "source": "ESA Copernicus Sentinel-2\nML DO Retrieval Model\nIn-situ calibrated",
        "indicators": [
            {"name": "DO Level",    "value": "2.1 mg/L",   "color": "var(--red)",    "pct": 21},
            {"name": "BOD Estimate","value": "18 mg/L",    "color": "var(--red)",    "pct": 72},
            {"name": "Anoxic Zone", "value": "28% surface","color": "var(--purple)", "pct": 28},
            {"name": "Confidence",  "value": "0.85",       "color": "var(--green)",  "pct": 85}
        ],
        "science": "Dissolved Oxygen (DO) is estimated from Sentinel-2 blue-green band ratios combined with machine learning models trained on in-situ DO measurements. Purple-red zones indicate DO < 3 mg/L (hypoxic) — life-threatening conditions for aquatic organisms. Sewage discharge plumes are traced via high BOD proxy, elevated CDOM (colored dissolved organic matter) retrievals from the shortwave-infrared bands."
    },
    {
        "key": "change",
        "layer": "change",
        "title": "Environmental Change — Multi-Temporal Change Detection Map",
        "short_title": "Environmental Change (Multi-Temporal)",
        "description": "Structural differences by overlaying a contrast layer that highlights areas of new shoreline expansion, habitat loss, or infrastructure changes against the original baseline.",
        "image": "images/change_detection.jpg",
        "band": "S2 2014–2026 · CVA",
        "summary_value": "Δ Shore: −4.2%",
        "summary_color": "var(--orange)",
        "dot_color": "var(--orange)",
        "severity": "DETECTED",
        "severity_class": "sm",
        "pulse": False,
        "status": "CHANGE DETECTED — 2014–2026",
        "status_color": "var(--orange)",
        "source": "ESA Copernicus Sentinel-2\nMulti-temporal CVA 2014–2026\n10m × 10m spatial resolution",
        "indicators": [
            {"name": "Shoreline Change", "value": "−4.2%",  "color": "var(--red)",    "pct": 42},
            {"name": "Habitat Loss",     "value": "−8.1 ha","color": "var(--orange)", "pct": 55},
            {"name": "Veg. Recovery",    "value": "+2.3 ha","color": "var(--green)",  "pct": 23},
            {"name": "Confidence",       "value": "0.91",   "color": "var(--green)",  "pct": 91}
        ],
        "science": "Change Vector Analysis (CVA) compares multi-temporal Sentinel-2 composites (2014 baseline vs 2026 current). Red pixels represent areas where land-cover changed to impervious surface or water edge recession exceeding the 2σ threshold. Magenta shows lake boundary retreat. Green indicates vegetation recovery. The composite uses bands B8A, B11, B4 for maximum spectral separability between change classes."
    }
]

# ---- Scene Metadata ----
SCENE_METADATA = {
    "constellation": "ESA Copernicus S2-L2A",
    "resolution": "10 m/pixel",
    "cloud_cover": "0.02%",
    "anomaly_score": "86 / 100",
    "api_gateway": "COPERNICUS"
}


@app.get("/api/satellite-layers")
async def get_satellite_layers():
    """
    Returns all 6 thematic satellite analysis layer definitions.
    Used by the Satellite Proof Gallery frontend to render cards,
    inspector modals, and metadata strips without any hardcoded data.
    """
    return {
        "layers": SATELLITE_LAYERS,
        "scene_meta": SCENE_METADATA
    }



@app.get("/api/analysis/{analysis_id}/satellite-image")
async def get_satellite_image(
    analysis_id: str,
    mode: str = "rgb",
    lat: float = 21.1292,
    lng: float = 79.0394,
    date: str = "2026-09-25"
):
    """
    Renders high-definition Sentinel-2 satellite image PNG streams.
    Modes:
      - 'rgb': True Color Sentinel-2 RGB (B4, B3, B2)
      - 'false_color': Infrared False Color Composite (B8, B4, B3)
      - 'ndwi': NDWI Water Index Heatmap
      - 'ndti': NDTI Turbidity Plume Heatmap
      - 'ndci': NDCI Chlorophyll-a Algal Bloom Heatmap
    """
    scene = generate_realistic_sentinel_scene(lat=lat, lng=lng, date_str=date)
    png_bytes = render_satellite_image_png(scene, mode=mode)
    return Response(content=png_bytes, media_type="image/png")



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

# ---- AI Integration Endpoint ----
class ExplainRequest(BaseModel):
    user_question: str

@app.post("/api/analysis/{analysis_id}/explain")
async def explain_analysis(analysis_id: str, request: ExplainRequest):
    """
    Connects the Backend data directly to the RAG AI Assistant.
    Fetches the specific analysis data and asks the AI to explain it.
    """
    if analysis_id not in MOCK_ANALYSIS:
        # In a real system, you would fetch the analysis from the DB here using analysis_id
        # For now, we will fallback to the mock data to ensure the demo works
        analysis_data = MOCK_ANALYSIS.get("A123")
    else:
        analysis_data = MOCK_ANALYSIS[analysis_id]

    try:
        # Placeholder for scientific context until ChromaDB is fully populated
        scientific_context = "NDCI measures chlorophyll. High values indicate algal blooms. NDTI measures turbidity."
        
        explanation = generate_explanation(
            live_json_data=analysis_data,
            scientific_context=scientific_context,
            user_question=request.user_question
        )
        return {
            "analysis_id": analysis_id,
            "question": request.user_question,
            "explanation": explanation
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"AI Assistant Error: {str(e)}")

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
