"""Hook called by the existing analysis endpoints after they finish.

It records a summary of the result and never changes it. If DATABASE_URL is unset the hook does
nothing; if the database is unreachable it logs and returns, so the Analyze flow keeps working
exactly as before either way.
"""

from __future__ import annotations

import logging

from db.session import enabled, session_scope

log = logging.getLogger("aquasafe.db")

# The /api/analyze and /api/stress-test handlers build their input with
# core.remote_sensing.generate_mock_sentinel_scene (seeded random bands), so their results are
# recorded as synthetic. A future engine that reads satellite data records is_synthetic=False.
MOCK_ENGINE = "backend.mock_sentinel.v1"


def persist_analysis(
    result: dict,
    *,
    analysis_type: str,
    engine: str = MOCK_ENGINE,
    is_synthetic: bool = True,
    request_lat: float | None = None,
    request_lon: float | None = None,
) -> str | None:
    """Returns the new analysis row id, or None when persistence is off or failed."""
    if not enabled():
        return None
    try:
        from db.repository import record_analysis

        with session_scope() as session:
            row = record_analysis(
                session,
                result,
                analysis_type=analysis_type,
                engine=engine,
                is_synthetic=is_synthetic,
                request_lat=request_lat,
                request_lon=request_lon,
            )
            return str(row.id)
    except Exception as exc:  # persistence must never break the analysis response
        log.warning("analysis %s not persisted: %s: %s", result.get("analysis_id"), exc.__class__.__name__, str(exc)[:200])
        return None
