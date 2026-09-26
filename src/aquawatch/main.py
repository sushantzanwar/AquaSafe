"""FastAPI application factory."""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from aquawatch import __version__
from aquawatch.api.deps import build_state
from aquawatch.api.routes import alerts, anomalies, assistant, credits, explain, health, maps, priority, scenes, stress
from aquawatch.settings import load_settings


def create_app() -> FastAPI:
    settings = load_settings()
    app = FastAPI(title="AquaWatch", version=__version__)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.state.aquawatch = build_state(settings)
    for module in (health, scenes, maps, anomalies, alerts, explain, priority, assistant, credits, stress):
        app.include_router(module.router, prefix="/api")

    frontend_dir = Path(__file__).parent.parent.parent / "frontend" / "dist"
    if frontend_dir.exists():
        # Serve assets directory statically
        assets_dir = frontend_dir / "assets"
        if assets_dir.exists():
            app.mount("/assets", StaticFiles(directory=assets_dir), name="assets")
        
        # Catch-all route for SPA routing and other static files
        @app.get("/{full_path:path}")
        async def serve_frontend(full_path: str):
            path = frontend_dir / full_path
            if path.exists() and path.is_file():
                return FileResponse(path)
            return FileResponse(frontend_dir / "index.html")

    return app


app = create_app()


def main() -> None:
    import uvicorn

    uvicorn.run("aquawatch.main:app", host="0.0.0.0", port=8000, reload=False)
