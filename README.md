# AquaWatch

Satellite water-quality and contamination intelligence prototype. It reads cached Sentinel-2 L2A scenes, estimates relative turbidity, chlorophyll-a, and transparency, and ranks zones for ground sampling.

Outputs are decision support, not laboratory results. Every API payload includes a confidence score and a lab-verification disclaimer. The demo does not call a live satellite API.

The directory layout and build order are in [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

## Run

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[geo,indicators]"
python scripts/seed_demo.py
uvicorn aquawatch.main:app --reload
```

```bash
cd frontend
npm install
npm run dev
```

Place scenes at `data/scenes/{water_body_id}/{YYYYMMDD}/` with `B02`, `B03`, `B04`, `B08`, `B11`, `B12`, and `SCL`. Optional `B05` and `B06` enable the Dall'Olmo / Gitelson chlorophyll index. Download the water-model weights before the demo; see `models/README.md`. With `LLM_PROVIDER=none` (the default), alerts stay on the template and the assistant quotes the corpus.

## Persistent database (PostgreSQL)

`backend/db/` holds AquaSafe's persistent application data: users, water bodies, the analysis history, field submissions, and the credit-ledger and reward schema. It records **what the existing pipeline produced**; it does not analyse anything itself. With no `DATABASE_URL` the backend runs exactly as before.

```powershell
docker compose up -d db                      # PostgreSQL 16; credentials from .env (see .env.example)
cd backend
..\.venv\Scripts\alembic upgrade head        # create/upgrade the schema
..\.venv\Scripts\uvicorn main:app --port 8000
..\.venv\Scripts\python -m pytest tests      # uses a throwaway database, dropped afterwards
```

- Every `/api/analyze` and `/api/stress-test` call appends a row to `water_body_analyses`; rows are never updated or deleted, so history accumulates.
- Water bodies are identified by their existing name (normalised) in `water_bodies.gis_key`; the GeoJSON outline is stored as the API returns it.
- The `water_body_analysis_status` view answers "has this water body been analyzed?", including whether the evidence was synthetic.
- `GET /api/health/db` reports connectivity and the applied migration revision.
- The existing SQLite `backend/historical_data.db` and the CSV/GeoJSON exports on the Analysis page are unchanged.

## Data layout

The offline loader in `aquawatch.data` reads a second, explicit cache. It does not call the network.

```
data/<water_body_id>/<YYYYMMDD>/
  B2.tif   B3.tif   B4.tif   B8.tif    # 10 m
  B11.tif  B12.tif                      # 20 m accepted; resampled to 10 m
  SCL.tif
```

`B02.tif`-style names are accepted as well. Monitored water bodies are declared in `config/data_catalog.yaml` with `id`, `name`, a GeoJSON boundary polygon, and the list of scene dates. `load_scene` stacks those bands into one xarray dataset (`stack` has dimensions `band`, `y`, `x`), resamples B11 and B12 onto the 10 m grid, and clips to the polygon.

A configured date with no folder still returns a dataset: reflectance is NaN, SCL is `0`, and `status` is `missing`. The API scene tree under `data/scenes/` is unchanged.

Water masks are a separate one-time step, not part of an API request:

```bash
python scripts/preprocess_water.py
```

That command reads `data/<water_body_id>/<YYYYMMDD>/`, drops cloud and cloud-shadow pixels using SCL, and skips a date when less than 60% of the AOI is valid. Otherwise it runs `giswqs/s2-water-unetplusplus-efficientnet-b4` locally (weights loaded once from `models/s2-water-unetplusplus-efficientnet-b4`; nothing is downloaded). NDWI from B3 and B8 is the cross-check: disagreement over more than 25% of the valid area is stored as `low_confidence`. Each kept date gets `water_mask.tif` plus extent in hectares (water pixels × 100 m²) in `data/products/water_extent.sqlite` and `.parquet`.

```bash
pytest
```

## Run with Docker

```bash
cp .env.example .env        # set POSTGRES_PASSWORD, and LLM_API_KEY for the AI assistant
docker compose up -d --build
```

Open <http://localhost:8000/dashboard.html> (API + frontend are served by the same container).
PostgreSQL runs as the `db` service; migrations run automatically when the app starts.
Uploaded photos and the legacy analysis history live in named volumes (`aquasafe_uploads`, `aquasafe_data`), and
the database in `aquasafe_pgdata`, so they survive `docker compose down` (add `-v` to erase them).

```bash
docker compose logs -f app   # logs
docker compose down          # stop
```
