# AquaSafe Backend Implementation Plan (Role 1)

As **Person 1 (Backend & Remote-Sensing Intelligence)**, you own "What is happening?". This means data ingestion, AI-driven segmentation, temporal analysis, and serving the processed intelligence via a FastAPI contract to the Frontend and RAG components.

Following the strategy to **build one vertical slice first**, we phase the implementation to get a working end-to-end API as fast as possible.

---

## Phase 1: The Contract (FastAPI Skeleton) 🚀
**Goal:** Unblock Person 2 (Frontend) and Person 3 (RAG) immediately.
- [x] Initialize project structure and Python environment inside `AquaSafe/backend`.
- [x] Create `main.py` with FastAPI endpoints.
- [x] Implement JSON contract responses matching the agreed-upon system contract (Analysis ID, Indicators, Anomaly Score, GeoJSON).
- [x] Install dependencies (`fastapi`, `torch`, `rasterio`, `transformers`, `geopandas`, etc.).

---

## Phase 2: Remote Sensing Fundamentals 🛰️
**Goal:** Implement the spectral indicators and synthetic data generator.
- [x] Implement synthetic/mock Sentinel-2 data generator (`generate_mock_sentinel_scene`).
- [x] Build spectral indicator calculators (`NDWI`, `NDTI`, `NDCI`) using NumPy in `core/remote_sensing.py`.
- [x] Structure the spectral data processing pipeline.

---

## Phase 3: AI Water Detection Pipeline 🤖
**Goal:** Integrate the HuggingFace model for water body masks.
- [x] Create AI segmentation loader structure in `models/water_segmentation.py` targeting `giswqs/s2-water-unetplusplus-efficientnet-b4`.
- [x] Write tensor conversion and mask prediction logic (with mock toggle for rapid dev).
- [x] Wire water mask output to calculate average spectral indicators strictly within water boundaries.

---

## Phase 4: Temporal & Anomaly Engine 📊
**Goal:** Establish historical baselines and flag statistical anomalies.
- [x] Create statistical anomaly detection module (`core/anomaly.py`) measuring standard deviations ($\sigma$).
- [x] Implement Priority Scoring logic combining Severity, Persistence, and Proximity.
- [x] Connect historical time-series database (SQLite/JSON caching) for historical date comparisons.

---

## Phase 5: End-to-End Vertical Slice & Live Integration ⚡
**Goal:** Fully integrate Phase 2, 3, and 4 logic into the live FastAPI endpoints.
- [x] Wire `POST /api/analyze` to use dynamic spectral indices and AI segmentation.
- [x] Add the "Stress Test" API endpoint for Person 3 to inject synthetic changes for demo mode.
- [x] Verify live server response across all endpoints.
