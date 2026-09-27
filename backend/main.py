from fastapi import FastAPI, HTTPException, Query, Response
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Dict, Any, List, Optional
from contextlib import asynccontextmanager
import datetime
import sys
import os
try:
    import httpx
except ImportError:
    httpx = None
import math

# Import backend core modules
from core.remote_sensing import (
    generate_mock_sentinel_scene,
    generate_realistic_sentinel_scene,
    render_satellite_image_png,
    render_thematic_layer_image,
    get_thematic_layers_metadata,
    process_scene_indices
)
from models.water_segmentation import generate_water_mask
from core.database import init_db, save_analysis, get_history, get_baseline, get_analysis
from core.anomaly import calculate_anomaly_score, calculate_priority

from fastapi.staticfiles import StaticFiles

# Import AI Assistant logic from the sibling directory
AI_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "ai_assistant")
FRONTEND_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "frontend")
if AI_DIR not in sys.path:
    sys.path.append(AI_DIR)
from rag.assistant import generate_explanation, generate_explanation_with_sources, generate_dynamic_questions  # noqa: E402

@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield

app = FastAPI(title="AquaWatch Backend API", description="Intelligence pipeline for AquaWatch", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---- Models ----
class AnalysisRequest(BaseModel):
    water_body: str
    date: str
    lat: Optional[float] = None
    lon: Optional[float] = None

class AnalysisResponse(BaseModel):
    analysis_id: str
    water_body: str
    date: str
    indicators: Dict[str, float]
    anomaly: Dict[str, Any]
    priority: Dict[str, int]
    geojson: Dict[str, Any]
    centroid: Optional[Dict[str, float]] = None

# ---- Locality Points Database ----
# ---- Locality Points Database (India-wide representation) ----
LOCALITY_POINTS = [
    {"id": "hussain_sagar", "name": "Hussain Sagar", "water_body": "Hussain Sagar", "lat": 17.4239, "lng": 78.4738, "district": "Hyderabad, Telangana"},
    {"id": "chilika_lake", "name": "Chilika Lake", "water_body": "Chilika Lake", "lat": 19.7200, "lng": 85.3200, "district": "Puri/Ganjam, Odisha"},
    {"id": "dal_lake", "name": "Dal Lake", "water_body": "Dal Lake", "lat": 34.1100, "lng": 74.8700, "district": "Srinagar, Jammu & Kashmir"},
    {"id": "sardar_sarovar", "name": "Sardar Sarovar Dam", "water_body": "Sardar Sarovar Dam", "lat": 21.8310, "lng": 73.7480, "district": "Narmada, Gujarat"},
    {"id": "powai_lake", "name": "Powai Lake", "water_body": "Powai Lake", "lat": 19.1250, "lng": 72.9050, "district": "Mumbai, Maharashtra"},
    {"id": "vembanad_lake", "name": "Vembanad Lake", "water_body": "Vembanad Lake", "lat": 9.6000, "lng": 76.4000, "district": "Kottayam/Alappuzha, Kerala"},
    {"id": "loktak_lake", "name": "Loktak Lake", "water_body": "Loktak Lake", "lat": 24.5500, "lng": 93.8000, "district": "Bishnupur, Manipur"},
    {"id": "bhojtal_lake", "name": "Bhojtal (Upper Lake)", "water_body": "Bhojtal", "lat": 23.2500, "lng": 77.3500, "district": "Bhopal, Madhya Pradesh"},
    {"id": "sambhar_lake", "name": "Sambhar Salt Lake", "water_body": "Sambhar Lake", "lat": 26.9000, "lng": 75.2000, "district": "Jaipur, Rajasthan"},
    {"id": "pichola_lake", "name": "Lake Pichola", "water_body": "Lake Pichola", "lat": 24.5750, "lng": 73.6780, "district": "Udaipur, Rajasthan"},
    {"id": "nagarjuna_sagar", "name": "Nagarjuna Sagar Reservoir", "water_body": "Nagarjuna Sagar", "lat": 16.5700, "lng": 79.3100, "district": "Nalgonda/Guntur, AP/TS"},
    {"id": "hirakud_reservoir", "name": "Hirakud Reservoir", "water_body": "Hirakud Reservoir", "lat": 21.5700, "lng": 83.8700, "district": "Sambalpur, Odisha"},
    {"id": "ambazari_lake", "name": "Ambazari Lake", "water_body": "Ambazari Lake", "lat": 21.1292, "lng": 79.0394, "district": "Nagpur West, Maharashtra"},
    {"id": "futala_lake", "name": "Futala Lake", "water_body": "Futala Lake", "lat": 21.1558, "lng": 79.0478, "district": "Nagpur North, Maharashtra"},
    {"id": "gorewada_lake", "name": "Gorewada Reservoir", "water_body": "Gorewada Lake", "lat": 21.1891, "lng": 79.0321, "district": "Nagpur NW, Maharashtra"},
]

# ─────────────────────────────────────────────────────────────────────────────
# DYNAMIC OSM / OVERPASS LAYER
# No hardcoded lake polygons — everything is fetched live from OpenStreetMap.
# ─────────────────────────────────────────────────────────────────────────────

# Overpass API mirrors — tried in order if one fails/504s
OVERPASS_URLS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
    "https://maps.mail.ru/osm/tools/overpass/api/interpreter",
]
OVERPASS_URL = OVERPASS_URLS[0]  # kept for backward compat

# In-memory cache so we don't hammer Overpass on every request
_osm_cache: Dict[str, Any] = {}

# ─────────────────────────────────────────────────────────────────────────────
# KNOWN LAKES FALLBACK — used when Overpass is down/504
# Covers major lakes, dams, and reservoirs across all regions of India
# ─────────────────────────────────────────────────────────────────────────────
_KNOWN_LAKES = [
    {"name": "Hussain Sagar",           "lat": 17.4239, "lon": 78.4738, "radius_km": 4.0},
    {"name": "Chilika Lake",            "lat": 19.7200, "lon": 85.3200, "radius_km": 25.0},
    {"name": "Dal Lake",                 "lat": 34.1100, "lon": 74.8700, "radius_km": 6.0},
    {"name": "Sardar Sarovar Dam",      "lat": 21.8310, "lon": 73.7480, "radius_km": 15.0},
    {"name": "Powai Lake",              "lat": 19.1250, "lon": 72.9050, "radius_km": 2.5},
    {"name": "Vembanad Lake",           "lat": 9.6000,  "lon": 76.4000, "radius_km": 20.0},
    {"name": "Loktak Lake",             "lat": 24.5500, "lon": 93.8000, "radius_km": 10.0},
    {"name": "Bhojtal (Upper Lake)",    "lat": 23.2500, "lon": 77.3500, "radius_km": 7.0},
    {"name": "Sambhar Salt Lake",       "lat": 26.9000, "lon": 75.2000, "radius_km": 18.0},
    {"name": "Lake Pichola",            "lat": 24.5750, "lon": 73.6780, "radius_km": 3.5},
    {"name": "Nagarjuna Sagar",         "lat": 16.5700, "lon": 79.3100, "radius_km": 12.0},
    {"name": "Hirakud Reservoir",       "lat": 21.5700, "lon": 83.8700, "radius_km": 20.0},
    {"name": "Wular Lake",              "lat": 34.3300, "lon": 74.5500, "radius_km": 10.0},
    {"name": "Shivsagar Lake (Koyna)",  "lat": 17.4000, "lon": 73.7500, "radius_km": 14.0},
    {"name": "Gobind Sagar (Bhakra)",   "lat": 31.4100, "lon": 76.4500, "radius_km": 15.0},
    {"name": "Pulicat Lake",            "lat": 13.6700, "lon": 80.2000, "radius_km": 16.0},
    {"name": "Futala Lake",             "lat": 21.1540, "lon": 79.0417, "radius_km": 1.2},
    {"name": "Ambazari Lake",           "lat": 21.1280, "lon": 79.0430, "radius_km": 1.5},
    {"name": "Gorewada Lake",           "lat": 21.1972, "lon": 79.0375, "radius_km": 2.5},
    {"name": "Sonegaon Lake",           "lat": 21.1330, "lon": 79.0660, "radius_km": 0.8},
    {"name": "Gandhisagar Lake",        "lat": 21.1444, "lon": 79.1070, "radius_km": 0.6},
]

def _nearest_known_lake(lat: float, lon: float, max_km: float = 2.0) -> Optional[Dict[str, Any]]:
    """Return the nearest known lake within max_km, or None."""
    best = None
    best_dist = max_km
    for lake in _KNOWN_LAKES:
        d = _haversine_km(lat, lon, lake["lat"], lake["lon"])
        if d < best_dist and d <= lake["radius_km"]:
            best_dist = d
            best = lake
    return best


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Approximate distance in km between two lat/lon points."""
    R = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat / 2) ** 2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon / 2) ** 2
    return R * 2 * math.asin(math.sqrt(a))


def _overpass_ways_to_geojson(elements: list, name: str) -> Dict[str, Any]:
    """Convert Overpass way/relation elements (from 'out body geom') into a GeoJSON FeatureCollection.

    With 'out body geom', Overpass inlines the geometry directly into each way element
    as a list of {lat, lon} dicts. No separate node elements are returned.
    For relations, member ways also carry inline geometry under members[].geometry.
    """
    features = []
    seen_coords = set()  # deduplicate identical rings

    def _make_feature(coords_raw, osm_id):
        """coords_raw: list of {lat, lon} dicts. Returns a Feature or None."""
        if len(coords_raw) < 3:
            return None
        coords = [(g["lon"], g["lat"]) for g in coords_raw]
        if coords[0] != coords[-1]:
            coords.append(coords[0])  # close the ring
        key = tuple(coords[:3])  # dedup key from first 3 pts
        if key in seen_coords:
            return None
        seen_coords.add(key)
        return {
            "type": "Feature",
            "geometry": {"type": "Polygon", "coordinates": [coords]},
            "properties": {"name": name, "osm_id": osm_id}
        }

    for el in elements:
        el_type = el.get("type")

        if el_type == "way":
            # Inline geometry is present in el["geometry"]
            geom = el.get("geometry", [])
            feat = _make_feature(geom, el["id"])
            if feat:
                features.append(feat)

        elif el_type == "relation":
            # Iterate through member ways — prefer outer ring, then inner/default
            for member in el.get("members", []):
                if member.get("type") != "way":
                    continue
                geom = member.get("geometry", [])
                if not geom:
                    continue
                feat = _make_feature(geom, member.get("ref", el["id"]))
                if feat:
                    features.append(feat)

    return {"type": "FeatureCollection", "features": features}


def _polygon_centroid(geojson: Dict) -> Optional[tuple]:
    """Return (lat, lon) centroid of the first polygon feature."""
    for feat in geojson.get("features", []):
        coords = feat.get("geometry", {}).get("coordinates", [[]])
        if coords and coords[0]:
            ring = coords[0]
            lat = sum(c[1] for c in ring) / len(ring)
            lon = sum(c[0] for c in ring) / len(ring)
            return (lat, lon)
    return None


async def _fetch_lake_by_name(name: str) -> Optional[Dict[str, Any]]:
    """Query Overpass for a named natural=water body and return GeoJSON."""
    cache_key = f"name:{name}"
    if cache_key in _osm_cache:
        return _osm_cache[cache_key]

    query = f"""
[out:json][timeout:25];
(
  way["natural"="water"]["name"~"{name}",i];
  relation["natural"="water"]["name"~"{name}",i];
  way["water"]["name"~"{name}",i];
  way["landuse"="reservoir"]["name"~"{name}",i];
  relation["water"]["name"~"{name}",i];
  relation["landuse"="reservoir"]["name"~"{name}",i];
);
out body geom;
"""
    async with httpx.AsyncClient(timeout=3.0, headers={"User-Agent": "AquaWatch/1.0"}) as client:
        for url in OVERPASS_URLS:
            try:
                resp = await client.post(url, data={"data": query})
                if resp.status_code in (502, 503, 504):
                    continue
                resp.raise_for_status()
                elements = resp.json().get("elements", [])
                if not elements:
                    break
                # Use the first matching element's name tag (may differ by case)
                actual_name = next(
                    (el.get("tags", {}).get("name", name) for el in elements if "tags" in el),
                    name
                )
                geojson = _overpass_ways_to_geojson(elements, actual_name)
                if geojson["features"]:
                    _osm_cache[cache_key] = geojson
                    return geojson
            except Exception:
                continue

    # All mirrors failed — check if it's a known lake
    for lake in _KNOWN_LAKES:
        if lake["name"].lower() == name.lower():
            # Return empty geojson for known lake if it hasn't been cached
            return _empty_geojson(lake["name"])
            
    return None


def _generate_circle_polygon(lat: float, lon: float, name: str, radius_km: float = 1.0, points: int = 36) -> Dict[str, Any]:
    """Generates a smooth GeoJSON polygon around lat/lon for water bodies without OSM boundary ways."""
    coords = []
    r_lat = radius_km / 111.0
    r_lon = radius_km / (111.0 * max(0.1, math.cos(math.radians(lat))))
    for i in range(points):
        angle = 2 * math.pi * i / points
        c_lat = lat + r_lat * math.sin(angle)
        c_lon = lon + r_lon * math.cos(angle)
        coords.append([round(c_lon, 6), round(c_lat, 6)])
    coords.append(coords[0])
    return {
        "type": "FeatureCollection",
        "features": [{
            "type": "Feature",
            "geometry": {"type": "Polygon", "coordinates": [coords]},
            "properties": {"name": name}
        }]
    }

async def _fetch_lake_at_point(lat: float, lon: float) -> Optional[Dict[str, Any]]:
    """Query Overpass for a water body at the clicked lat/lon point across India.
    Falls back to Nominatim reverse-geocoding, _KNOWN_LAKES, or dynamic coordinate descriptor.
    """
    query = f"""
[out:json][timeout:20];
(
  way["natural"="water"](around:1500,{lat},{lon});
  way["water"](around:1500,{lat},{lon});
  way["landuse"="reservoir"](around:1500,{lat},{lon});
  way["landuse"="basin"](around:1500,{lat},{lon});
  way["natural"="wetland"](around:1500,{lat},{lon});
  relation["natural"="water"](around:1500,{lat},{lon});
  relation["water"](around:1500,{lat},{lon});
  relation["landuse"="reservoir"](around:1500,{lat},{lon});
  relation["landuse"="basin"](around:1500,{lat},{lon});
);
out body geom;
"""
    if httpx:
        async with httpx.AsyncClient(timeout=3.5, headers={"User-Agent": "AquaSafe-Water-Detection/2.0"}) as client:
            for url in OVERPASS_URLS:
                try:
                    resp = await client.post(url, data={"data": query})
                    if resp.status_code in (502, 503, 504):
                        continue  # try next mirror
                    resp.raise_for_status()
                    elements = resp.json().get("elements", [])
                    if not elements:
                        break
                    best = None
                    best_name = "Unknown Water Body"
                    for el in elements:
                        n = el.get("tags", {}).get("name", "")
                        if n:
                            best = el
                            best_name = n
                            break
                    if best is None:
                        best = elements[0]
                    geojson = _overpass_ways_to_geojson(elements, best_name)
                    if geojson["features"]:
                        _osm_cache[f"name:{best_name}"] = geojson
                        return {"name": best_name, "geojson": geojson}
                except Exception:
                    continue  # try next mirror

    # Overpass mirrors did not find polygon — check known lakes in India only if click is within 500m
    known = _nearest_known_lake(lat, lon, max_km=0.5)
    if known:
        geojson = _generate_circle_polygon(lat, lon, known["name"], radius_km=known.get("radius_km", 1.0))
        return {"name": known["name"], "geojson": geojson}

    # Try Nominatim reverse-geocoding — extract REAL place name (never coordinates)
    if httpx:
        try:
            async with httpx.AsyncClient(timeout=3.5, headers={"User-Agent": "AquaSafe-India-Water-Detection/2.0"}) as client:
                rev_url = f"https://nominatim.openstreetmap.org/reverse?lat={lat}&lon={lon}&format=json"
                r = await client.get(rev_url)
                if r.status_code == 200:
                    data = r.json()
                    raw_name = (data.get("name") or "").strip()
                    addr = data.get("address", {})

                    # 1. Explicit water address tags (highest priority)
                    water_tag = (
                        addr.get("water") or addr.get("reservoir") or
                        addr.get("lake") or addr.get("pond") or
                        addr.get("waterway")
                    )
                    if water_tag and water_tag.lower() not in ("water", "yes", "stream", "river", "bay"):
                        place_name = water_tag.title()
                        circle = _generate_circle_polygon(lat, lon, place_name, radius_km=1.0)
                        _osm_cache[f"name:{place_name}"] = circle
                        return {"name": place_name, "geojson": circle}

                    # 2. Raw name explicitly contains water keywords
                    water_kw = ["lake", "dam", "sagar", "talao", "reservoir", "talav",
                                "sarovar", "wetland", "canal", "ghat", "basin", "pond"]
                    if raw_name and any(w in raw_name.lower() for w in water_kw):
                        circle = _generate_circle_polygon(lat, lon, raw_name, radius_km=1.0)
                        _osm_cache[f"name:{raw_name}"] = circle
                        return {"name": raw_name, "geojson": circle}

                    # 3. Raw name is a meaningful POI/place (not a road/highway)
                    road_indicators = ["road", "street", "marg", "lane", "path",
                                       "highway", "expressway", "bridge", "flyover"]
                    is_highway_class = (
                        data.get("class") == "highway" or
                        data.get("addresstype") in ("road", "highway")
                    )
                    is_road_name = any(ri in raw_name.lower() for ri in road_indicators) if raw_name else True

                    # Build locality hierarchy: most specific → broadest
                    locality = (
                        addr.get("suburb") or
                        addr.get("neighbourhood") or
                        addr.get("village") or
                        addr.get("town") or
                        addr.get("city") or
                        addr.get("municipality") or
                        addr.get("county")
                    )
                    context = (
                        addr.get("city") or
                        addr.get("state_district") or
                        addr.get("county") or
                        addr.get("state")
                    )

                    if raw_name and not is_road_name and not is_highway_class:
                        # Clean POI/place name
                        if context and context.lower() not in raw_name.lower():
                            place_name = f"{raw_name}, {context}"
                        else:
                            place_name = raw_name
                    elif locality:
                        if context and context.lower() != locality.lower():
                            place_name = f"{locality}, {context}"
                        else:
                            place_name = locality
                    else:
                        # Last resort: first meaningful segment of display_name
                        display = data.get("display_name", "")
                        parts = [p.strip() for p in display.split(",")
                                 if p.strip() and not p.strip().isdigit()
                                 and p.strip().lower() not in ("india",)]
                        place_name = ", ".join(parts[:2]) if parts else None

                    if place_name:
                        circle = _generate_circle_polygon(lat, lon, place_name, radius_km=1.0)
                        _osm_cache[f"name:{place_name}"] = circle
                        return {"name": place_name, "geojson": circle}
        except Exception:
            pass

    # Final fallback — check known lakes with generous radius, then use state/district name
    known_wide = _nearest_known_lake(lat, lon, max_km=15.0)
    if known_wide:
        geojson = _generate_circle_polygon(lat, lon, known_wide["name"], radius_km=known_wide.get("radius_km", 1.0))
        return {"name": known_wide["name"], "geojson": geojson}

    # Absolute last resort — still a real place name from a generic region label
    generic_name = "Selected Location"
    circle = _generate_circle_polygon(lat, lon, generic_name, radius_km=1.0)
    return {"name": generic_name, "geojson": circle}


async def _fetch_nearby_lakes(lat: float, lon: float, radius_km: float = 10.0) -> List[Dict[str, Any]]:
    """Return a list of named lakes within radius_km of a point."""
    # Convert km radius to Overpass radius in meters
    radius_m = int(radius_km * 1000)
    query = f"""
[out:json][timeout:30];
(
  way["natural"="water"]["name"](around:{radius_m},{lat},{lon});
  way["landuse"="reservoir"]["name"](around:{radius_m},{lat},{lon});
  relation["natural"="water"]["name"](around:{radius_m},{lat},{lon});
  relation["water"]["name"](around:{radius_m},{lat},{lon});
  relation["landuse"="reservoir"]["name"](around:{radius_m},{lat},{lon});
);
out body geom;
"""
    results = []
    async with httpx.AsyncClient(timeout=2.0, headers={"User-Agent": "AquaWatch/1.0"}) as client:
        for url in OVERPASS_URLS:
            try:
                resp = await client.post(url, data={"data": query})
                if resp.status_code in (502, 503, 504):
                    continue
                resp.raise_for_status()
                elements = resp.json().get("elements", [])
                seen = set()
                for el in elements:
                    name = el.get("tags", {}).get("name", "")
                    if name and name not in seen:
                        seen.add(name)
                        geom = el.get("geometry", [])
                        if geom:
                            c_lat = sum(g["lat"] for g in geom) / len(geom)
                            c_lon = sum(g["lon"] for g in geom) / len(geom)
                            dist = _haversine_km(lat, lon, c_lat, c_lon)
                            results.append({"name": name, "distance_km": round(dist, 2), "lat": c_lat, "lon": c_lon})
                results.sort(key=lambda x: x["distance_km"])
                return results[:10]  # success — return early
            except Exception:
                continue

    # All mirrors failed — fall back to known lakes sorted by distance
    for lake in _KNOWN_LAKES:
        d = _haversine_km(lat, lon, lake["lat"], lake["lon"])
        if d <= radius_km:
            results.append({"name": lake["name"], "distance_km": round(d, 2),
                            "lat": lake["lat"], "lon": lake["lon"]})
    results.sort(key=lambda x: x["distance_km"])
    return results[:10]


# Fallback GeoJSON for when Overpass is unreachable
def _empty_geojson(name: str = "Unknown") -> Dict[str, Any]:
    return {"type": "FeatureCollection", "features": [], "properties": {"name": name}}

# ---- Endpoints ----


@app.post("/api/analyze", response_model=AnalysisResponse)
async def analyze_scene(request: AnalysisRequest):
    """
    Trigger the pipeline for a water body and date.
    Uses synthetic data to test the end-to-end intelligence pipeline.
    """
    # 1. Ingestion (Mock)
    # Generate a dynamic seed based on location so different lakes get different readings
    if request.lat is not None and request.lon is not None:
        seed = int(abs(request.lat * 10000 + request.lon * 1000)) % 1000000
    else:
        seed = sum(ord(c) for c in request.water_body) * 42
    
    scene = generate_mock_sentinel_scene((256, 256), seed=seed)
    
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
        # Use the correct GeoJSON polygon for the requested water body
        "geojson": (
            (_osm_cache.get(f"name:{request.water_body}") or _generate_circle_polygon(request.lat, request.lon, request.water_body))
            if request.lat is not None and request.lon is not None
            else (await _fetch_lake_by_name(request.water_body) or _empty_geojson(request.water_body))
        ),
        "centroid": {"lat": request.lat, "lon": request.lon} if request.lat is not None and request.lon is not None else None
    }
    
    # 5. Save to database
    save_analysis(response_data)
    
    return response_data

@app.get("/api/water-bodies")
async def get_water_bodies(
    lat: Optional[float] = Query(None, description="Latitude to search near"),
    lon: Optional[float] = Query(None, description="Longitude to search near"),
    radius_km: float = Query(15.0, description="Search radius in km")
):
    """
    Dynamic water bodies list from OpenStreetMap Overpass API.
    If lat/lon provided, returns lakes near that point.
    Otherwise defaults to Nagpur region (21.15, 79.09).
    """
    search_lat = lat if lat is not None else 21.15
    search_lon = lon if lon is not None else 79.09

    nearby = await _fetch_nearby_lakes(search_lat, search_lon, radius_km)

    if not nearby:
        # Overpass unreachable — return minimal fallback
        return {
            "water_bodies": [],
            "nearby": {},
            "error": "OSM Overpass API unreachable. Map click to detect lake."
        }

    # Build water_bodies list and nearby map
    bodies = [item["name"] for item in nearby]
    nearby_map: Dict[str, List[str]] = {}
    for i, item in enumerate(nearby):
        # Each lake's nearby = all others sorted by distance, excluding itself
        others = [x["name"] for j, x in enumerate(nearby) if j != i]
        nearby_map[item["name"]] = others[:4]  # top 4 nearby

    return {
        "water_bodies": bodies,
        "nearby": nearby_map,
        "lakes_meta": nearby  # includes lat/lon for map auto-zoom
    }


@app.get("/api/detect-lake")
async def detect_lake(
    lat: float = Query(..., description="Latitude of click point"),
    lon: float = Query(..., description="Longitude of click point")
):
    """
    Detect the water body at the given lat/lon click point using OSM Overpass.
    Returns lake name, GeoJSON polygon, centroid, and nearby lakes.
    """
    result = await _fetch_lake_at_point(lat, lon)
    if not result:
        # _fetch_lake_at_point always returns a result now, but keep a safety net
        circle = _generate_circle_polygon(lat, lon, "Selected Location", radius_km=1.0)
        result = {"name": "Selected Location", "geojson": circle}

    name = result["name"]
    geojson = result["geojson"]
    centroid = _polygon_centroid(geojson)
    nearby = await _fetch_nearby_lakes(
        centroid[0] if centroid else lat,
        centroid[1] if centroid else lon,
        radius_km=15.0
    )
    # Exclude the detected lake itself from nearby
    nearby_filtered = [n for n in nearby if n["name"].lower() != name.lower()]

    return {
        "is_water": True,
        "name": name,
        "geojson": geojson,
        "centroid": {"lat": lat, "lon": lon},
        "lat": lat,
        "lon": lon,
        "polygon_centroid": {"lat": centroid[0], "lon": centroid[1]} if centroid else {"lat": lat, "lon": lon},
        "nearby": nearby_filtered[:5]
    }


@app.get("/api/lake-geojson")
async def get_lake_geojson(name: str = Query(..., description="Lake name to fetch polygon for")):
    """
    Fetch the real OSM GeoJSON polygon for a named lake.
    Used by frontend to draw the lake outline on map selection from dropdown.
    """
    cache_key = f"name:{name}"
    if cache_key in _osm_cache:
        return _osm_cache[cache_key]

    geojson = await _fetch_lake_by_name(name)
    if not geojson or not geojson["features"]:
        raise HTTPException(status_code=404, detail=f"No OSM polygon found for '{name}'")
    return geojson

@app.get("/api/analysis/{analysis_id}", response_model=AnalysisResponse)
async def get_analysis_endpoint(analysis_id: str):
    """Fetch the full analysis payload by ID."""
    analysis_data = get_analysis(analysis_id)
    if not analysis_data:
        raise HTTPException(status_code=404, detail="Analysis not found")
    
    # Add geojson to match model
    analysis_data["geojson"] = _osm_cache.get(f"name:{analysis_data['water_body']}", _empty_geojson(analysis_data['water_body']))
    return analysis_data

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
    analysis_data = get_analysis(analysis_id)
    if not analysis_data:
        return {"score": 50}
    return analysis_data["priority"]

# ---- AI Integration Endpoint ----
class ExplainRequest(BaseModel):
    user_question: str

@app.post("/api/analysis/{analysis_id}/explain")
async def explain_analysis(analysis_id: str, request: ExplainRequest):
    """
    Connects the Backend data directly to the RAG AI Assistant.
    Fetches the specific analysis data and asks the AI to dynamically explain it.
    """
    analysis_data = get_analysis(analysis_id)
    if not analysis_data:
        # Check if there's any recent analysis in the database
        recent = get_history(limit=1)
        if recent:
            analysis_data = {
                "analysis_id": recent[0].get("analysis_id", analysis_id),
                "water_body": recent[0].get("water_body", "Ambazari Lake"),
                "date": recent[0].get("date", "2026-09-26"),
                "indicators": {
                    "ndwi": recent[0].get("ndwi", 0.58),
                    "ndti": recent[0].get("ndti", 0.28),
                    "ndci": recent[0].get("ndci", 0.15)
                },
                "anomaly": {
                    "status": recent[0].get("anomaly_status", "NORMAL"),
                    "score": recent[0].get("anomaly_score", 45)
                },
                "priority": {"score": recent[0].get("priority_score", 50)}
            }
        else:
            analysis_data = {
                "analysis_id": analysis_id,
                "water_body": "Ambazari Lake",
                "date": "2026-09-26",
                "indicators": {"ndwi": 0.58, "ndti": 0.28, "ndci": 0.15},
                "anomaly": {"status": "NORMAL", "score": 45},
                "priority": {"score": 50}
            }

    try:
        explanation, sources = generate_explanation_with_sources(
            live_json_data=analysis_data,
            scientific_context="",
            user_question=request.user_question
        )
        citations = [s.get("citation", s.get("topic", "")) for s in sources if s.get("citation") or s.get("topic")]
        return {
            "analysis_id": analysis_id,
            "water_body": analysis_data.get("water_body", "Water Body"),
            "question": request.user_question,
            "explanation": explanation,
            "citations": citations
        }
    except Exception as e:
        # Graceful fallback explanation
        wb = analysis_data.get("water_body", "this water body")
        return {
            "analysis_id": analysis_id,
            "water_body": wb,
            "question": request.user_question,
            "explanation": f"### ⚠️ Live Hydrological Guidance: {wb}\n\nRegarding your question: *\"{request.user_question}\"*\n\n- **Chlorophyll-a / NDCI Status:** Current optical telemetry shows active baseline tracking for {wb}.\n- **Turbidity / NDTI Status:** Suspended matter proxy indicates monitored conditions.\n- **Recreational Safety:** Always exercise caution if surface algal scums or abnormal green coloration are visible, per WHO recreational water criteria.\n\n*(Note: Cloud synthesis fallback engaged: {str(e)[:80]})*",
            "citations": ["WHO & EPA Guidelines for Safe Recreational Water Environments"]
        }

@app.get("/api/analysis/{analysis_id}/suggested-questions")
async def get_suggested_questions(analysis_id: str):
    """
    Dynamically generates 4 contextual suggested questions using Gemini based on live lake readings.
    """
    analysis_data = get_analysis(analysis_id)
    if not analysis_data:
        recent = get_history(limit=1)
        if recent:
            analysis_data = {
                "water_body": recent[0].get("water_body", "Ambazari Lake"),
                "indicators": {"ndwi": recent[0].get("ndwi", 0.58), "ndti": recent[0].get("ndti", 0.28), "ndci": recent[0].get("ndci", 0.15)},
                "anomaly": {"status": recent[0].get("anomaly_status", "NORMAL"), "score": recent[0].get("anomaly_score", 45)}
            }
        else:
            analysis_data = {
                "water_body": "Ambazari Lake",
                "indicators": {"ndwi": 0.58, "ndti": 0.28, "ndci": 0.15},
                "anomaly": {"status": "NORMAL", "score": 45}
            }
    try:
        questions = generate_dynamic_questions(analysis_data)
    except Exception:
        wb = analysis_data.get("water_body", "Ambazari Lake")
        questions = [
            f"What does the current NDCI reading mean for {wb}?",
            f"What drives turbidity and SPM levels in {wb}?",
            f"Is it safe for swimming or recreation in {wb} right now?",
            f"How does the current reading compare to historical baseline?"
        ]
    return {
        "analysis_id": analysis_id,
        "water_body": analysis_data.get("water_body", "Water Body"),
        "questions": questions
    }


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
        "geojson": _osm_cache.get(f"name:{request.water_body}", _empty_geojson(request.water_body))
    }
    
    save_analysis(response_data)
    
    return response_data

@app.get("/api/analysis/{analysis_id}/geojson")
async def get_geojson(analysis_id: str):
    """Return just the GeoJSON boundaries for Leaflet."""
    analysis_data = get_analysis(analysis_id)
    if not analysis_data:
        raise HTTPException(status_code=404, detail="Analysis not found")
    return _osm_cache.get(f"name:{analysis_data['water_body']}", _empty_geojson(analysis_data['water_body']))


# ─────────────────────────────────────────────────────────────────────────────
# SATELLITE PROOF & THEMATIC API GATEWAY ENDPOINTS
# ─────────────────────────────────────────────────────────────────────────────

@app.get("/api/locality-points")
async def get_locality_points():
    """List of monitored locality points with coordinates for manual selection or dropdown."""
    return LOCALITY_POINTS


@app.get("/api/satellite-layers")
async def get_satellite_layers(
    lat: float = 21.1292,
    lng: float = 79.0394,
    date: str = "2026-09-25",
    water_body: Optional[str] = Query(default="", description="Water body name")
):
    """
    API Gateway: Computes and returns all 6 thematic satellite analysis layer definitions
    for ANY detected water body across India or worldwide without hardcoded frontend data.
    """
    return get_thematic_layers_metadata(lat=lat, lng=lng, date_str=date, water_body=water_body)


@app.get("/api/satellite-image")
async def get_thematic_satellite_image(
    layer: str = "algal",
    lat: float = 21.1292,
    lng: float = 79.0394,
    date: str = "2026-09-25",
    water_body: Optional[str] = Query(default="", description="Water body name")
):
    """
    API Gateway: Streams the high-definition satellite imagery map with the
    specific requested thematic analysis layer overlay for any lake/pond/dam across India:
      - algal (Chlorophyll-a / NDCI Algal Bloom)
      - erosion (Turbidity & Shoreline Cut/Fill NDTI)
      - thermal (Industrial Discharge Thermal Plume)
      - runoff (Topographical Flow Accumulation)
      - sewage (Hypoxia & Dissolved Oxygen Depletion)
      - change (Multi-temporal Change Detection CVA)
    """
    img_bytes = render_thematic_layer_image(layer, lat=lat, lng=lng, date_str=date, water_body=water_body)
    return Response(content=img_bytes, media_type="image/jpeg")


@app.get("/api/search-water-body")
async def search_water_body(
    q: str = Query(..., description="Name of lake, pond, dam, reservoir across India"),
    country: str = Query("in", description="Country code filter")
):
    """
    Search any lake, pond, dam, reservoir or wetland across India via OpenStreetMap Nominatim.
    Returns matched water bodies with exact coordinates, bounding boxes, and display names.
    """
    import urllib.request
    import urllib.parse
    import json
    
    encoded_query = urllib.parse.quote(q)
    url = f"https://nominatim.openstreetmap.org/search?q={encoded_query}&format=json&polygon_geojson=1&countrycodes={country}&limit=8"
    req = urllib.request.Request(url, headers={"User-Agent": "AquaSafe-Water-Detection/2.0"})
    try:
        with urllib.request.urlopen(req, timeout=4.0) as resp:
            data = json.loads(resp.read().decode())
            results = []
            for item in data:
                name = item.get("name") or item.get("display_name", "").split(",")[0]
                results.append({
                    "name": name,
                    "display_name": item.get("display_name"),
                    "lat": float(item.get("lat")),
                    "lon": float(item.get("lon")),
                    "type": item.get("type"),
                    "class": item.get("class"),
                    "boundingbox": item.get("boundingbox")
                })
            if results:
                return results
    except Exception:
        pass
        
    # Fallback to search in local database
    results = [
        {"name": k["name"], "display_name": f"{k['name']}, India", "lat": k["lat"], "lon": k["lon"]}
        for k in _KNOWN_LAKES if q.lower() in k["name"].lower()
    ]
    return results


@app.get("/api/analysis/{analysis_id}/satellite-image")
async def get_satellite_image_endpoint(
    analysis_id: str,
    mode: str = "rgb",
    lat: float = 21.1292,
    lng: float = 79.0394,
    date: str = "2026-09-25",
    water_body: Optional[str] = Query(default="", description="Water body name")
):
    img_bytes = render_thematic_layer_image(mode, lat=lat, lng=lng, date_str=date, water_body=water_body)
    return Response(content=img_bytes, media_type="image/jpeg")


# Mount frontend directory for direct single-port access (placed AFTER all API routes)
if os.path.isdir(FRONTEND_DIR):
    app.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
