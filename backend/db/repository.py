"""Data access for the persistent layer. Persistence only: no credit, GPS, time-window,
image-quality or duplicate rules live here (those are later tasks)."""

from __future__ import annotations

import re
import uuid
from datetime import date, datetime
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from db.models import FieldSubmission, User, WaterBody, WaterBodyAnalysis

_GEOMETRY_RANK = {"none": 0, "approximate": 1, "osm": 2}


def gis_key(name: str) -> str:
    """The existing water-body identity (its name), normalised so case/spacing variants match."""
    key = re.sub(r"\s+", " ", (name or "").strip()).casefold()
    if not key:
        raise ValueError("water body name is empty")
    return key


def _features(geojson: dict | None) -> list[dict]:
    if not isinstance(geojson, dict):
        return []
    if geojson.get("type") == "FeatureCollection":
        return [f for f in geojson.get("features") or [] if isinstance(f, dict) and f.get("geometry")]
    if geojson.get("type") == "Feature" and geojson.get("geometry"):
        return [geojson]
    return []


def classify_geometry(geojson: dict | None) -> tuple[str, str | None]:
    """(geometry_source, osm_ref). The existing backend tags OSM outlines with ``osm_id``;
    everything else it returns is its generated approximation (a circle)."""
    features = _features(geojson)
    if not features:
        return "none", None
    for feature in features:
        props = feature.get("properties") or {}
        if props.get("osm_id") is not None:
            return "osm", str(props["osm_id"])
        if props.get("contour"):  # outline traced from the OSM basemap tile at the detected point
            return "osm", None
    return "approximate", None


def geometry_centroid(geojson: dict | None) -> tuple[float, float] | None:
    """(lat, lon): vertex mean of the first outer ring, the same method as the existing
    ``_polygon_centroid`` in main.py."""
    for feature in _features(geojson):
        geometry = feature["geometry"]
        coords = geometry.get("coordinates") or []
        if geometry.get("type") == "MultiPolygon":
            coords = coords[0] if coords else []
        if geometry.get("type") in ("Polygon", "MultiPolygon") and coords and coords[0]:
            ring = coords[0]
            return sum(p[1] for p in ring) / len(ring), sum(p[0] for p in ring) / len(ring)
    return None


def upsert_water_body(session: Session, name: str, geojson: dict | None = None) -> WaterBody:
    """Find the water body by its existing identity, creating it if new.

    Geometry is replaced only by one of equal or better provenance (an OSM outline is never
    downgraded to a generated circle)."""
    key = gis_key(name)
    body = session.scalars(select(WaterBody).where(WaterBody.gis_key == key)).one_or_none()
    if body is None:
        body = WaterBody(gis_key=key, name=name.strip(), geometry_source="none")
        session.add(body)
    source, osm_ref = classify_geometry(geojson)
    if source != "none" and _GEOMETRY_RANK[source] >= _GEOMETRY_RANK[body.geometry_source or "none"]:
        body.geometry = geojson
        body.geometry_source = source
        body.osm_ref = osm_ref or body.osm_ref
        centre = geometry_centroid(geojson)
        if centre:
            body.centroid_lat, body.centroid_lon = centre
    session.flush()
    return body


def _parse_date(value: Any) -> date | None:
    if isinstance(value, date):
        return value
    try:
        return datetime.strptime(str(value)[:10], "%Y-%m-%d").date()
    except (TypeError, ValueError):
        return None


def _num(value: Any, cast=float):
    try:
        return None if value is None else cast(value)
    except (TypeError, ValueError):
        return None


def record_analysis(
    session: Session,
    result: dict,
    *,
    analysis_type: str,
    engine: str,
    is_synthetic: bool,
    request_lat: float | None = None,
    request_lon: float | None = None,
    scene_ref: str | None = None,
    scene_date: date | None = None,
    report_ref: str | None = None,
) -> WaterBodyAnalysis:
    """Append one analysis row built from the existing ``AnalysisResponse`` dict. Never updates."""
    body = upsert_water_body(session, result["water_body"], result.get("geojson"))
    indicators = result.get("indicators") or {}
    anomaly = result.get("anomaly") or {}
    priority = result.get("priority") or {}
    row = WaterBodyAnalysis(
        water_body_id=body.id,
        legacy_analysis_id=str(result["analysis_id"]),
        analysis_type=analysis_type,
        requested_date=_parse_date(result.get("date")),
        status=str(anomaly.get("status") or "UNKNOWN"),
        anomaly_score=_num(anomaly.get("score"), int),
        anomaly_confidence=_num(anomaly.get("confidence")),
        deviation_sigma=_num(anomaly.get("deviation_sigma")),
        priority_score=_num(priority.get("score"), int),
        ndwi=_num(indicators.get("ndwi")),
        ndti=_num(indicators.get("ndti")),
        ndci=_num(indicators.get("ndci")),
        engine=engine,
        is_synthetic=is_synthetic,
        request_lat=request_lat,
        request_lon=request_lon,
        scene_ref=scene_ref,
        scene_date=scene_date,
        report_ref=report_ref,
    )
    session.add(row)
    session.flush()
    return row


def analysis_status(session: Session, name: str) -> dict | None:
    """Facts the backend needs to answer "has this water body been analyzed?".

    Returns None for a water body AquaSafe has never analyzed. Deciding what counts as
    *flagged* for credits is deliberately left to the credit task; the facts it needs
    (latest status, and whether the evidence is synthetic) are all here.
    """
    row = session.execute(
        text("SELECT * FROM water_body_analysis_status WHERE gis_key = :key"),
        {"key": gis_key(name)},
    ).mappings().one_or_none()
    return dict(row) if row else None


def analysis_history(session: Session, name: str) -> list[WaterBodyAnalysis]:
    return list(
        session.scalars(
            select(WaterBodyAnalysis)
            .join(WaterBody)
            .where(WaterBody.gis_key == gis_key(name))
            .order_by(WaterBodyAnalysis.analyzed_at, WaterBodyAnalysis.created_at)
        )
    )


def get_or_create_user(session: Session, external_id: str, display_name: str | None = None, email: str | None = None) -> User:
    user = session.scalars(select(User).where(User.external_id == external_id)).one_or_none()
    if user is None:
        user = User(external_id=external_id, display_name=display_name, email=email)
        session.add(user)
        session.flush()
    return user


def create_submission(
    session: Session,
    *,
    user_id: uuid.UUID,
    image_key: str,
    image_sha256: str,
    image_content_type: str | None = None,
    image_size_bytes: int | None = None,
    gps_lat: float | None = None,
    gps_lon: float | None = None,
    gps_accuracy_m: float | None = None,
    captured_at: datetime | None = None,
    water_body_id: uuid.UUID | None = None,
) -> FieldSubmission:
    """Store a received submission in its initial state (received / pending). No checks run."""
    submission = FieldSubmission(
        user_id=user_id,
        water_body_id=water_body_id,
        image_key=image_key,
        image_sha256=image_sha256,
        image_content_type=image_content_type,
        image_size_bytes=image_size_bytes,
        gps_lat=gps_lat,
        gps_lon=gps_lon,
        gps_accuracy_m=gps_accuracy_m,
        captured_at=captured_at,
    )
    session.add(submission)
    session.flush()
    return submission
