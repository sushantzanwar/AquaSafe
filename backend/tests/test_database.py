"""PostgreSQL persistence layer: migrations, models, constraints, and the Analyze-flow hook."""

from __future__ import annotations

import time
import uuid

import pytest
from sqlalchemy import inspect, select, text
from sqlalchemy.exc import IntegrityError

from db import repository as repo
from db.models import CreditTransaction, FieldSubmission, WaterBodyAnalysis
from db.session import check_connection, session_scope
from db.storage import LocalImageStorage

EXPECTED_TABLES = {
    "users",
    "water_bodies",
    "water_body_analyses",
    "field_submissions",
    "credit_transactions",
    "rewards",
    "reward_redemptions",
}

CIRCLE = {  # shape of the backend's generated approximation (no osm_id)
    "type": "FeatureCollection",
    "features": [{"type": "Feature", "properties": {"name": "Futala Lake"},
                  "geometry": {"type": "Polygon", "coordinates": [[[79.04, 21.15], [79.05, 21.15], [79.05, 21.16], [79.04, 21.15]]]}}],
}
OSM = {  # shape of an Overpass outline (carries osm_id)
    "type": "FeatureCollection",
    "features": [{"type": "Feature", "properties": {"name": "Futala Lake", "osm_id": 123456},
                  "geometry": {"type": "Polygon", "coordinates": [[[79.039, 21.151], [79.045, 21.151], [79.045, 21.156], [79.039, 21.151]]]}}],
}


def analysis_result(name="Futala Lake", date="2026-06-15", status="NORMAL", geojson=CIRCLE, aid=None):
    """Same dict the existing /api/analyze builds."""
    return {
        "analysis_id": aid or f"A_{date.replace('-', '')}_{name.replace(' ', '')}",
        "water_body": name,
        "date": date,
        "indicators": {"ndwi": 0.61, "ndti": 0.12, "ndci": 0.05},
        "anomaly": {"status": status, "score": 12, "confidence": 0.4, "deviation_sigma": 0.5},
        "priority": {"score": 16},
        "geojson": geojson,
    }


# --- connection and migrations ----------------------------------------------------------------

def test_connection_and_revision(db):
    state = check_connection()
    assert state == {"enabled": True, "connected": True, "revision": "0003"}


def test_fresh_migration_creates_schema(db):
    inspector = inspect(db)
    assert EXPECTED_TABLES <= set(inspector.get_table_names())
    assert "water_body_analysis_status" in inspector.get_view_names()


def test_migration_downgrade_and_upgrade_round_trip(pg_url, alembic_config):
    from alembic import command
    from sqlalchemy import create_engine

    from db.session import reset_engine

    reset_engine()
    config = alembic_config(pg_url)
    command.downgrade(config, "base")
    engine = create_engine(pg_url)
    assert not (EXPECTED_TABLES & set(inspect(engine).get_table_names()))
    command.upgrade(config, "head")
    assert EXPECTED_TABLES <= set(inspect(engine).get_table_names())
    engine.dispose()


# --- users and water bodies -------------------------------------------------------------------

def test_user_creation_is_idempotent_and_unique(db):
    with session_scope() as s:
        first = repo.get_or_create_user(s, "demo-user", display_name="Demo")
        again = repo.get_or_create_user(s, "demo-user")
        assert first.id == again.id
    with pytest.raises(IntegrityError):
        with session_scope() as s:
            from db.models import User

            s.add(User(external_id="demo-user"))


def test_water_body_identity_matches_existing_name_key(db):
    with session_scope() as s:
        a = repo.upsert_water_body(s, "Futala Lake", CIRCLE)
        b = repo.upsert_water_body(s, "  futala   LAKE ", None)
        assert a.id == b.id and a.gis_key == "futala lake" and a.name == "Futala Lake"
        assert a.geometry_source == "approximate" and a.geometry == CIRCLE


def test_osm_outline_is_never_downgraded_to_generated_circle(db):
    with session_scope() as s:
        body = repo.upsert_water_body(s, "Futala Lake", OSM)
        repo.upsert_water_body(s, "Futala Lake", CIRCLE)
        assert body.geometry_source == "osm" and body.osm_ref == "123456" and body.geometry == OSM
        assert body.centroid_lat == pytest.approx(21.15225) and body.centroid_lon == pytest.approx(79.042)


# --- analysis history -------------------------------------------------------------------------

def test_multiple_analyses_are_kept_as_history(db):
    with session_scope() as s:
        for date, status in [("2026-06-15", "NORMAL"), ("2026-07-15", "WARNING"), ("2026-08-15", "HIGH")]:
            repo.record_analysis(s, analysis_result(date=date, status=status), analysis_type="standard",
                                 engine="backend.mock_sentinel.v1", is_synthetic=True)
        # The existing system reuses analysis_id for same-day reruns; both rows must survive.
        repo.record_analysis(s, analysis_result(date="2026-08-15", status="NORMAL"), analysis_type="standard",
                             engine="backend.mock_sentinel.v1", is_synthetic=True)
    with session_scope() as s:
        history = repo.analysis_history(s, "Futala Lake")
        assert [h.status for h in history] == ["NORMAL", "WARNING", "HIGH", "NORMAL"]
        assert len({h.id for h in history}) == 4
        assert sum(h.legacy_analysis_id == "A_20260815_FutalaLake" for h in history) == 2
        assert s.scalar(text("SELECT count(*) FROM water_bodies")) == 1


def test_analysis_rows_are_append_only(db):
    with session_scope() as s:
        row = repo.record_analysis(s, analysis_result(), analysis_type="standard", engine="e", is_synthetic=True)
        row_id = row.id
    with pytest.raises(IntegrityError, match="append-only"):
        with session_scope() as s:
            s.execute(text("UPDATE water_body_analyses SET status = 'HIGH' WHERE id = :id"), {"id": row_id})
    with pytest.raises(IntegrityError, match="append-only"):
        with session_scope() as s:
            s.execute(text("DELETE FROM water_body_analyses WHERE id = :id"), {"id": row_id})


def test_analysis_status_answers_has_this_been_analyzed(db):
    with session_scope() as s:
        assert repo.analysis_status(s, "Futala Lake") is None  # never analyzed
        repo.record_analysis(s, analysis_result(status="NORMAL"), analysis_type="standard", engine="mock", is_synthetic=True)
        repo.record_analysis(s, analysis_result(date="2026-07-01", status="HIGH"), analysis_type="stress_test",
                             engine="mock", is_synthetic=True)
    with session_scope() as s:
        status = repo.analysis_status(s, "futala lake")
        assert status["analysis_count"] == 1 and status["stress_test_count"] == 1
        assert status["last_status"] == "NORMAL"  # a stress test never becomes the lake's status
        assert status["last_is_synthetic"] is True
        assert status["measured_analysis_count"] == 0 and status["last_measured_status"] is None
        repo.record_analysis(s, analysis_result(date="2026-09-01", status="WARNING"), analysis_type="standard",
                             engine="satellite-engine", is_synthetic=False)
    with session_scope() as s:
        status = repo.analysis_status(s, "Futala Lake")
        assert status["measured_analysis_count"] == 1 and status["last_measured_status"] == "WARNING"


# --- field submissions, storage, credits ------------------------------------------------------

def test_field_submission_persistence_with_local_storage(db, tmp_path):
    storage = LocalImageStorage(tmp_path)
    stored = storage.save(b"\xff\xd8fake-jpeg", "image/jpeg")
    assert storage.read(stored.key) == b"\xff\xd8fake-jpeg" and stored.key.endswith(".jpg")
    with session_scope() as s:
        user = repo.get_or_create_user(s, "field-user")
        body = repo.upsert_water_body(s, "Futala Lake", CIRCLE)
        sub = repo.create_submission(
            s, user_id=user.id, water_body_id=body.id, image_key=stored.key, image_sha256=stored.sha256,
            image_content_type=stored.content_type, image_size_bytes=stored.size_bytes, gps_lat=21.153, gps_lon=79.042,
        )
        sub_id = sub.id
    with session_scope() as s:
        saved = s.get(FieldSubmission, sub_id)
        assert (saved.submission_status, saved.verification_status) == ("received", "pending")
        assert saved.uploaded_at is not None and saved.image_key == stored.key
        assert saved.user.external_id == "field-user" and saved.water_body.name == "Futala Lake"
    with pytest.raises(ValueError):
        storage.path("../../etc/passwd")


def test_foreign_keys_and_checks_are_enforced(db):
    with pytest.raises(IntegrityError):  # unknown user
        with session_scope() as s:
            repo.create_submission(s, user_id=uuid.uuid4(), image_key="k", image_sha256="0" * 64)
    with pytest.raises(IntegrityError):  # GPS out of range
        with session_scope() as s:
            user = repo.get_or_create_user(s, "u1")
            repo.create_submission(s, user_id=user.id, image_key="k", image_sha256="0" * 64, gps_lat=123.0)
    with pytest.raises(IntegrityError):  # unknown water body
        with session_scope() as s:
            s.add(WaterBodyAnalysis(water_body_id=uuid.uuid4(), legacy_analysis_id="x", analysis_type="standard",
                                    status="NORMAL", engine="e", is_synthetic=True))
    with pytest.raises(IntegrityError):  # water body with history cannot be deleted
        with session_scope() as s:
            repo.record_analysis(s, analysis_result(), analysis_type="standard", engine="e", is_synthetic=True)
        with session_scope() as s:
            s.execute(text("DELETE FROM water_bodies"))
    with pytest.raises(IntegrityError):  # zero-amount credit rows are rejected
        with session_scope() as s:
            user = repo.get_or_create_user(s, "u2")
            s.add(CreditTransaction(user_id=user.id, amount=0, reason="test"))
    with session_scope() as s:  # ledger rows link to a user and a submission
        user = repo.get_or_create_user(s, "u3")
        sub = repo.create_submission(s, user_id=user.id, image_key="k", image_sha256="1" * 64)
        s.add(CreditTransaction(user_id=user.id, amount=5, reason="schema-test", submission_id=sub.id))
    with session_scope() as s:
        assert s.scalar(select(CreditTransaction.amount)) == 5


# --- existing Analyze flow --------------------------------------------------------------------

@pytest.fixture
def api(monkeypatch, tmp_path):
    """The real backend app, with its SQLite history redirected to a temp file."""
    pytest.importorskip("httpx")
    from fastapi.testclient import TestClient

    import core.database as legacy
    import main

    monkeypatch.setattr(legacy, "DB_PATH", str(tmp_path / "historical_data.db"))
    with TestClient(main.app) as client:
        yield client, legacy


RESPONSE_KEYS = {"analysis_id", "water_body", "date", "indicators", "anomaly", "priority", "geojson", "centroid", "spectral_profile"}


def test_existing_analyze_flow_records_history_without_changing_response(db, api):
    client, legacy = api
    payload = {"water_body": "Ambazari Lake", "date": "2026-09-27", "lat": 21.1292, "lon": 79.0394}
    first = client.post("/api/analyze", json=payload)
    second = client.post("/api/analyze", json=payload)
    assert first.status_code == second.status_code == 200
    assert set(first.json()) == RESPONSE_KEYS  # contract unchanged
    assert first.json()["analysis_id"] == "A_20260927_AmbazariLake"
    # Existing SQLite store still written (and still overwrites same-day reruns, as before).
    assert [r["analysis_id"] for r in legacy.get_history("Ambazari Lake")].count("A_20260927_AmbazariLake") == 1
    # PostgreSQL keeps both runs.
    with session_scope() as s:
        rows = repo.analysis_history(s, "Ambazari Lake")
        assert len(rows) == 2 and {r.analysis_type for r in rows} == {"standard"}
        assert all(r.is_synthetic and r.engine == "backend.mock_sentinel.v1" for r in rows)
        assert rows[0].ndti == first.json()["indicators"]["ndti"]
        assert rows[0].status == first.json()["anomaly"]["status"]
        assert rows[0].request_lat == pytest.approx(21.1292)
    stress = client.post("/api/stress-test", json={"water_body": "Ambazari Lake", "date": "2026-09-27"})
    assert stress.status_code == 200
    with session_scope() as s:
        status = repo.analysis_status(s, "Ambazari Lake")
        assert status["analysis_count"] == 2 and status["stress_test_count"] == 1
    assert client.get("/api/health/db").json()["connected"] is True


def test_analyze_still_works_without_database(api, monkeypatch):
    client, _ = api
    from db.session import reset_engine

    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setattr("db.config.database_url", lambda: None)
    monkeypatch.setattr("db.session.database_url", lambda: None)
    reset_engine()
    response = client.post("/api/analyze", json={"water_body": "Futala Lake", "date": "2026-09-27", "lat": 21.154, "lon": 79.042})
    assert response.status_code == 200 and set(response.json()) == RESPONSE_KEYS
    assert client.get("/api/health/db").json() == {"enabled": False, "connected": False, "revision": None}


def test_analyze_still_works_when_database_is_down(api, monkeypatch):
    client, _ = api
    from db.session import reset_engine

    monkeypatch.setattr("db.session.database_url", lambda: "postgresql+psycopg://nobody:x@127.0.0.1:1/none")
    reset_engine()
    started = time.monotonic()
    response = client.post("/api/analyze", json={"water_body": "Futala Lake", "date": "2026-09-27", "lat": 21.154, "lon": 79.042})
    assert response.status_code == 200 and set(response.json()) == RESPONSE_KEYS
    assert time.monotonic() - started < 15  # bounded by DATABASE_CONNECT_TIMEOUT, not the OS TCP timeout
    reset_engine()
