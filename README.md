# AquaWatch

AquaWatch is an intelligent remote-sensing application designed to monitor water bodies, detect anomalies, and prioritize investigations using satellite imagery (Sentinel-2) and AI.

## Architecture

The project is divided into three main responsibilities:

### 1. Backend & Remote-Sensing Intelligence (`/backend`)
Builds the entire data-processing and intelligence pipeline behind the application.
* **Responsibilities:** Sentinel-2 ingestion, Preprocessing, Water-body detection (using U-Net++), Spectral analysis (NDWI, NDTI, NDCI), Temporal analysis, Anomaly detection, Priority scoring, and FastAPI backend.

### 2. Frontend & GIS Visualization (`/frontend`)
Builds everything the user interacts with and sees.
* **Responsibilities:** React Dashboard, Leaflet Map integration, Temporal sliders, Trend charts, Alerts, and Evidence cards.

### 3. AI Assistant & Integration (`/ai_assistant`)
Handles RAG, System Integration, and Demo Orchestration.
* **Responsibilities:** RAG Scientific Assistant, API Syncing (JSON Contracts), Live Data Injection, Stress Testing / Demo orchestration, and AquaCredits integration.

## Project Structure

```text
AquaWatch/
├── backend/                  # Person 1 (FastAPI, Remote Sensing, Models)
├── frontend/                 # Person 2 (React, Leaflet, Dashboard)
├── ai_assistant/             # Person 3 (RAG, Integration, Demo Orchestration)
└── docs/                     # General Documentation
```

## Getting Started

*(Instructions for setup will be added here as the components are developed.)*
