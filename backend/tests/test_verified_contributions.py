"""Verified field contributions: end-to-end through the HTTP API against a real PostgreSQL database.

Photos are real JPEG files generated with Pillow (real EXIF GPS / DateTimeOriginal written into the
bytes). Nothing in the validation is weakened for the tests; the OSM lookup is the only stub, standing
in for the network call to Overpass.
"""

from __future__ import annotations

import io
import threading
import uuid
from datetime import datetime, timedelta, timezone

import numpy as np
import pytest
from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, IntegrityError

from db import field_routes, imagecheck, repository as repo, verification as ver
from db.session import session_scope

IST = timezone(timedelta(hours=5, minutes=30))
ALPHA = ("Test Lake Alpha", 17.4000, 78.4500)
BETA = ("Test Lake Beta", 18.5000, 79.5000)
LAKES = [ALPHA, BETA]


def outline(name, lat, lon, half=0.003):
    ring = [[lon - half, lat - half], [lon + half, lat - half], [lon + half, lat + half], [lon - half, lat + half], [lon - half, lat - half]]
    return {"type": "FeatureCollection", "features": [{"type": "Feature", "properties": {"name": name, "osm_id": abs(hash(name)) % 10**7},
                                                       "geometry": {"type": "Polygon", "coordinates": [ring]}}]}


async def fake_overpass(lat, lon):
    """Stands in for the Overpass call: returns a lake outline within ~1.5 km, else only an approximate circle."""
    for name, clat, clon in LAKES:
        if abs(lat - clat) < 0.0085 and abs(lon - clon) < 0.0085:
            return {"name": name, "geojson": outline(name, clat, clon)}
    circle = outline("Somewhere", lat, lon, 0.005)
    del circle["features"][0]["properties"]["osm_id"]
    return {"name": "Somewhere", "geojson": circle}


def _dms(value):
    value = abs(value)
    d = int(value)
    m = int((value - d) * 60)
    s = (value - d - m / 60) * 3600
    return (float(d), float(m), round(s, 3))


def make_photo(seed, *, lat=ALPHA[1], lon=ALPHA[2], taken=None, kind="water", size=(960, 720), gps=True,
               sigma=4.0, fmt="JPEG", exif_time=True):
    """A real image file. `seed` changes the picture's structure so different seeds are different photos."""
    rng = np.random.default_rng(seed)
    w, h = size
    y, x = np.linspace(0, 1, h)[:, None], np.linspace(0, 1, w)[None, :]
    if kind == "water":
        sky, water = np.array([150, 190, 230.0]), np.array([40, 110, 160.0])
    elif kind == "murky":  # smooth but brown: might be turbid water, might be mud -> human review
        sky, water = np.array([125, 105, 85.0]), np.array([120, 100, 80.0])
    elif kind == "indoor":  # cluttered scene: many differently coloured objects with hard edges
        sky = water = np.array([200.0, 190.0, 150.0])
    else:
        sky = water = np.array([0.0, 0.0, 0.0])
    horizon = rng.uniform(0.28, 0.5)
    img = np.where((y < horizon)[..., None], sky, water) * np.ones((h, w, 3))
    for _ in range(4):
        fx, fy, ph, amp = rng.uniform(0.5, 4), rng.uniform(0.5, 4), rng.uniform(0, 6.28), rng.uniform(6, 14)
        img += amp * np.sin(2 * np.pi * (fx * x + fy * y) + ph)[..., None]
    img += rng.normal(0, sigma, (h, w, 1))
    if kind == "indoor":
        for _ in range(60):
            x0, y0 = rng.integers(0, w - 60), rng.integers(0, h - 60)
            img[y0:y0 + rng.integers(30, 220), x0:x0 + rng.integers(30, 260)] = rng.integers(0, 256, 3)
    if kind == "noise":
        img = rng.integers(0, 256, (h, w, 3))
    image = Image.fromarray(np.clip(img, 0, 255).astype(np.uint8))

    exif = Image.Exif()
    sub = {}
    if exif_time:
        when = (taken or datetime.now(timezone.utc) - timedelta(days=2)).astimezone(IST)
        sub = {36867: when.strftime("%Y:%m:%d %H:%M:%S"), 36880: "+05:30"}
    if sub:
        exif[0x8769] = sub
    if gps:
        exif[0x8825] = {1: "N" if lat >= 0 else "S", 2: _dms(lat), 3: "E" if lon >= 0 else "W", 4: _dms(lon)}
    buf = io.BytesIO()
    image.save(buf, fmt, exif=exif, quality=92)
    return buf.getvalue()


def days_ago(n):
    return datetime.now(timezone.utc) - timedelta(days=n)


@pytest.fixture
def api(db, tmp_path, monkeypatch):
    monkeypatch.setenv("AQUASAFE_UPLOADS_DIR", str(tmp_path / "uploads"))
    monkeypatch.setenv("AQUASAFE_ADMIN_TOKEN", "reviewer-secret")
    monkeypatch.setattr(ver, "default_legacy_history", lambda: (lambda name: []))
    monkeypatch.setattr(field_routes, "_async_lookup", fake_overpass)
    field_routes._lookup_cache.clear()
    monkeypatch.setenv("AQUASAFE_REQUIRE_METADATA", "1")  # the ten spec scenarios test the full rules
    from db.credit_rules import load_rules
    load_rules.cache_clear()
    import main

    return TestClient(main.app)


class Who:
    def __init__(self, api, name="tester"):
        self.api = api
        r = api.post("/api/users/anonymous", json={"display_name": name})
        assert r.status_code == 201
        self.token = r.json()["token"]
        self.h = {"X-AquaSafe-Token": self.token}

    def submit(self, data, **form):
        return self.api.post("/api/field/submissions", headers=self.h, files={"file": ("p.jpg", data, "image/jpeg")}, data=form)

    def balance(self):
        return self.api.get("/api/credits/me", headers=self.h).json()["credits"]


def assert_rejected(resp, code):
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["status"] == "REJECTED", body
    assert body["reason_code"] == code, body
    assert body["credits_awarded"] == 0
    return body


def leaderboard(api):
    return api.get("/api/credits/leaderboard").json()


# --- the ten required scenarios ---------------------------------------------------------------------

def test_01_valid_new_water_body_is_verified_and_credited(api):
    user = Who(api)
    body = user.submit(make_photo(1, taken=days_ago(2))).json()
    assert body["status"] == "VERIFIED" and body["reason_code"] == "VERIFIED"
    assert body["credits_awarded"] == 100 and body["water_body"] == ALPHA[0]
    assert all(c["status"] == "pass" for c in body["checks"])
    assert user.balance() == 100
    tx = api.get("/api/credits/transactions", headers=user.h).json()
    assert len(tx) == 1 and tx[0]["amount"] == 100 and tx[0]["submission_id"] == body["id"]
    lb = leaderboard(api)
    assert lb[0]["credits"] == 100 and lb[0]["verified_contributions"] == 1 and lb[0]["verification_rate"] == 1.0
    # GPS/EXIF is not echoed back
    assert "gps" not in body and "lat" not in str(body).lower().replace("later", "")


def test_01b_acceptable_quality_earns_the_lower_award(api):
    body = Who(api).submit(make_photo(2, size=(500, 500), sigma=1.8, taken=days_ago(1))).json()
    assert body["status"] == "VERIFIED" and body["credits_awarded"] == 50


def test_02_no_gps_is_rejected(api):
    user = Who(api)
    body = assert_rejected(user.submit(make_photo(3, gps=False)), "NO_GPS")
    assert user.balance() == 0 and body["message"] == "Photo does not contain valid GPS metadata."


def test_03_photo_older_than_seven_days_is_rejected(api):
    user = Who(api)
    assert_rejected(user.submit(make_photo(4, taken=days_ago(8))), "TOO_OLD")
    assert user.balance() == 0
    # 6 days is fine
    assert Who(api, "b").submit(make_photo(5, taken=days_ago(6))).json()["status"] == "VERIFIED"


def test_03b_missing_and_future_capture_time_never_earn(api):
    assert_rejected(Who(api).submit(make_photo(6, exif_time=False)), "UNABLE_TO_VERIFY")
    assert_rejected(Who(api).submit(make_photo(7, taken=datetime.now(timezone.utc) + timedelta(days=3))), "UNABLE_TO_VERIFY")


def test_04_already_analyzed_water_body_is_rejected(api):
    with session_scope() as s:
        repo.record_analysis(s, {"analysis_id": "A_1", "water_body": ALPHA[0], "date": "2026-09-01", "geojson": outline(*ALPHA),
                                 "anomaly": {"status": "NORMAL"}}, analysis_type="standard", engine="x", is_synthetic=True)
    user = Who(api)
    body = assert_rejected(user.submit(make_photo(8, taken=days_ago(1))), "ALREADY_ANALYZED")
    assert body["message"] == "This water body has already been analyzed." and user.balance() == 0
    # a different, unanalyzed lake is still creditable
    assert user.submit(make_photo(9, lat=BETA[1], lon=BETA[2], taken=days_ago(1))).json()["credits_awarded"] == 100


def test_04b_stress_tests_do_not_count_as_analysis(api):
    with session_scope() as s:
        repo.record_analysis(s, {"analysis_id": "S_1", "water_body": ALPHA[0], "date": "2026-09-01", "geojson": outline(*ALPHA),
                                 "anomaly": {"status": "HIGH"}}, analysis_type="stress_test", engine="x", is_synthetic=True)
    assert Who(api).submit(make_photo(10, taken=days_ago(1))).json()["status"] == "VERIFIED"


def test_04c_legacy_sqlite_history_counts_as_analysis(api, monkeypatch):
    monkeypatch.setattr(ver, "default_legacy_history", lambda: (lambda name: [{"water_body": name}]))
    assert_rejected(Who(api).submit(make_photo(11, taken=days_ago(1))), "ALREADY_ANALYZED")


def test_04d_second_contributor_to_a_field_verified_body_earns_nothing(api):
    first, second = Who(api, "first"), Who(api, "second")
    assert first.submit(make_photo(12, taken=days_ago(1))).json()["credits_awarded"] == 100
    assert_rejected(second.submit(make_photo(13, lat=ALPHA[1] + 0.001, taken=days_ago(1.5))), "ALREADY_ANALYZED")
    assert second.balance() == 0


def test_05_duplicates_earn_nothing(api):
    first, second = Who(api, "first"), Who(api, "second")
    original = make_photo(14, taken=days_ago(1))
    assert first.submit(original).json()["credits_awarded"] == 100
    assert_rejected(second.submit(original), "DUPLICATE")  # exact copy, other user
    assert_rejected(first.submit(original), "DUPLICATE")  # replay by the same user
    # near-duplicate: same photo re-encoded smaller (different bytes, same picture)
    img = Image.open(io.BytesIO(original))
    buf = io.BytesIO()
    img.resize((720, 540)).save(buf, "JPEG", quality=70, exif=img.getexif())
    assert_rejected(second.submit(buf.getvalue()), "DUPLICATE")
    assert first.balance() == 100 and second.balance() == 0


def test_05b_same_place_and_time_is_a_duplicate_observation(db):
    rules = ver.load_rules()
    with session_scope() as s:
        user = repo.get_or_create_user(s, "u1")
        when = days_ago(1)
        first = repo.create_submission(s, user_id=user.id, image_key="submissions/2026/09/" + "a" * 32 + ".jpg", image_sha256="a" * 64,
                                       gps_lat=17.4, gps_lon=78.45, captured_at=when)
        first.perceptual_hash = 1
        near = ver.find_duplicate(s, sha256="b" * 64, phash=0x5555555555555555, lat=17.40005, lon=78.45005,
                                  captured_at=when + timedelta(minutes=5), exclude_id=None, rules=rules)
        assert near and near[1]["kind"] == "same_observation"
        far = ver.find_duplicate(s, sha256="b" * 64, phash=0x5555555555555555, lat=17.41, lon=78.45, captured_at=when, exclude_id=None, rules=rules)
        assert far is None  # ~1 km away: a legitimate separate observation
        later = ver.find_duplicate(s, sha256="b" * 64, phash=0x5555555555555555, lat=17.4, lon=78.45, captured_at=when + timedelta(hours=5),
                                   exclude_id=None, rules=rules)
        assert later is None


def test_06_invalid_or_unrelated_images_are_rejected(api):
    user = Who(api)
    assert_rejected(user.submit(make_photo(15, kind="noise", taken=days_ago(1))), "INVALID_IMAGE")
    assert_rejected(user.submit(make_photo(16, kind="dark", taken=days_ago(1))), "INVALID_IMAGE")
    # a screenshot/document: mostly white with a little text-like content
    doc = np.full((720, 960, 3), 250, np.uint8)
    doc[100:110, 50:900] = 20
    buf = io.BytesIO()
    exif = Image.Exif()
    exif[0x8769] = {36867: datetime.now(IST).strftime("%Y:%m:%d %H:%M:%S"), 36880: "+05:30"}
    exif[0x8825] = {1: "N", 2: _dms(17.4), 3: "E", 4: _dms(78.45)}
    Image.fromarray(doc).save(buf, "JPEG", exif=exif)
    assert_rejected(user.submit(buf.getvalue()), "INVALID_IMAGE")
    # not an image at all: rejected, nothing stored
    r = user.submit(b"this is not an image")
    assert r.json()["status"] == "REJECTED" and r.json()["reason_code"] == "INVALID_IMAGE" and r.json()["id"] is None
    # tiny and blurry images are LOW_QUALITY
    assert_rejected(user.submit(make_photo(17, size=(320, 240), taken=days_ago(1))), "LOW_QUALITY")
    assert_rejected(user.submit(make_photo(18, sigma=0.0, taken=days_ago(1))), "LOW_QUALITY")
    assert user.balance() == 0


def test_07_client_supplied_water_body_and_coordinates_are_ignored(api):
    user = Who(api)
    # Photo is at Alpha; the client claims Beta, an ID, and typed GPS/date. None of it matters.
    body = user.submit(make_photo(19, taken=days_ago(1)), water_body_id=BETA[0], latitude="18.5", longitude="79.5",
                       captured_at="2026-09-27").json()
    assert body["status"] == "VERIFIED" and body["water_body"] == ALPHA[0]
    # Typed coordinates cannot stand in for a missing geotag.
    assert_rejected(Who(api, "x").submit(make_photo(20, gps=False), water_body_id=ALPHA[0], latitude="17.4", longitude="78.45"), "NO_GPS")
    # Typed date cannot rescue an old photo.
    assert_rejected(Who(api, "y").submit(make_photo(21, lat=BETA[1], lon=BETA[2], taken=days_ago(30)), captured_at="2026-09-27"), "TOO_OLD")


def test_07b_location_far_from_any_water_or_unidentifiable(api):
    far = 0.0045  # ~165 m beyond the outline
    assert_rejected(Who(api).submit(make_photo(22, lat=ALPHA[1] + 0.003 + far - 0.003, lon=ALPHA[2], taken=days_ago(1))), "INVALID_LOCATION")
    # nowhere near a known outline: only an approximate circle is available -> human review, never credit
    body = Who(api, "z").submit(make_photo(23, lat=12.9, lon=77.6, taken=days_ago(1))).json()
    assert body["status"] == "REJECTED" and body["reason_code"] == "UNABLE_TO_VERIFY" and body["credits_awarded"] == 0


def test_08_same_submission_twice_pays_once(api):
    user = Who(api)
    data = make_photo(24, taken=days_ago(1))
    first, second = user.submit(data).json(), user.submit(data).json()
    assert first["credits_awarded"] == 100 and second["credits_awarded"] == 0 and second["reason_code"] == "DUPLICATE"
    assert user.balance() == 100
    with session_scope() as s:
        assert s.execute(text("SELECT count(*) FROM credit_transactions")).scalar() == 1


def test_08b_concurrent_identical_submissions_pay_once(api):
    with session_scope() as s:
        uid = ver.register_user(s, "racer")[0].id
    data = make_photo(25, taken=days_ago(1))
    barrier, results = threading.Barrier(4), []

    def go():
        barrier.wait()
        results.append(ver.submit_photo(session_scope, user_id=uid, data=data, content_type="image/jpeg",
                                        external_lookup=lambda lat, lon: {"name": ALPHA[0], "geojson": outline(*ALPHA)},
                                        legacy_history=lambda n: []))

    threads = [threading.Thread(target=go) for _ in range(4)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert sorted(r["status"] for r in results) == ["REJECTED", "REJECTED", "REJECTED", "VERIFIED"]
    with session_scope() as s:
        assert s.execute(text("SELECT coalesce(sum(amount),0) FROM credit_transactions")).scalar() == 100


def test_08c_database_refuses_a_second_award_for_one_submission(api):
    user = Who(api)
    sub_id = uuid.UUID(user.submit(make_photo(26, taken=days_ago(1))).json()["id"])
    with pytest.raises(IntegrityError):
        with session_scope() as s:
            uid = s.execute(text("SELECT user_id FROM field_submissions")).scalar()
            s.execute(text("INSERT INTO credit_transactions (id, user_id, amount, reason, submission_id) "
                           "VALUES (gen_random_uuid(), :u, 100, 'x', :s)"), {"u": uid, "s": sub_id})
    with pytest.raises(DBAPIError):  # the ledger is append-only
        with session_scope() as s:
            s.execute(text("UPDATE credit_transactions SET amount = 9999"))


def test_09_client_cannot_choose_the_credit_amount(api):
    user = Who(api)
    body = user.submit(make_photo(27, taken=days_ago(1)), credits="99999", credit_amount="99999", amount="99999", award="99999").json()
    assert body["credits_awarded"] == 100 and user.balance() == 100
    # No endpoint exists that awards credits directly.
    for method, path in (("post", "/api/credits/award"), ("post", "/api/credits"), ("put", "/api/credits/me"), ("post", "/api/credits/me")):
        assert getattr(api, method)(path, headers=user.h, json={"amount": 99999}).status_code in (404, 405)
    assert user.balance() == 100


def test_10_pending_and_rejected_do_not_move_the_leaderboard(api):
    user = Who(api)
    assert leaderboard(api) == []
    assert_rejected(user.submit(make_photo(29, gps=False)), "NO_GPS")
    assert_rejected(user.submit(make_photo(28, kind="indoor", taken=days_ago(1))), "INVALID_IMAGE")
    # a submission still in PENDING / VALIDATING (row exists, no decision yet) earns and ranks nothing
    with session_scope() as s:
        uid = s.execute(text("SELECT id FROM users")).scalar()
        sub = repo.create_submission(s, user_id=uid, image_key="submissions/2026/09/" + "b" * 32 + ".jpg", image_sha256="b" * 64)
        sub.submission_status = "processing"
    assert user.balance() == 0 and leaderboard(api) == []
    me = api.get("/api/credits/me", headers=user.h).json()
    assert me["pending"] == 1 and me["rejected"] == 2 and me["verified_contributions"] == 0
    # and there is no reviewer path: nobody can approve a submission by hand
    assert api.post(f"/api/field/submissions/{uuid.uuid4()}/review", json={"approve": True}, headers={"X-Admin-Token": "x"}).status_code in (404, 405)


def test_10b_verification_is_automatic_no_pending_review_state(api):
    for seed, kind in ((80, "water"), (81, "indoor"), (82, "noise")):
        body = Who(api, f"u{seed}").submit(make_photo(seed, kind=kind, taken=days_ago(1))).json()
        assert body["status"] in ("VERIFIED", "REJECTED")


# --- API surface ---------------------------------------------------------------------------------

def test_precheck_reports_checks_and_stores_nothing(api):
    data = make_photo(32, taken=days_ago(1))
    r = api.post("/api/field/precheck", files={"file": ("p.jpg", data, "image/jpeg")}).json()
    assert r["eligible"] is True and r["water_body"] == ALPHA[0] and len(r["checks"]) == 6
    bad = api.post("/api/field/precheck", files={"file": ("p.jpg", make_photo(33, taken=days_ago(9)), "image/jpeg")}).json()
    assert bad["eligible"] is False and bad["reason_code"] == "TOO_OLD"
    with session_scope() as s:
        assert s.execute(text("SELECT count(*) FROM field_submissions")).scalar() == 0
        assert s.execute(text("SELECT count(*) FROM credit_transactions")).scalar() == 0


def test_auth_and_ownership(api):
    assert api.post("/api/field/submissions", files={"file": ("p.jpg", make_photo(34), "image/jpeg")}).status_code == 401
    assert api.get("/api/credits/me", headers={"X-AquaSafe-Token": "x" * 40}).status_code == 401
    a, b = Who(api, "a"), Who(api, "b")
    sub = a.submit(make_photo(35, taken=days_ago(1))).json()
    assert api.get(f"/api/field/submissions/{sub['id']}", headers=a.h).json()["status"] == "VERIFIED"
    assert api.get(f"/api/field/submissions/{sub['id']}", headers=b.h).status_code == 404
    assert api.get("/api/field/submissions", headers=a.h).json()[0]["id"] == sub["id"]


def test_rewards_catalogue_is_configurable_honest_and_unredeemable(api):
    user = Who(api)
    user.submit(make_photo(36, taken=days_ago(1)))
    r = api.get("/api/credits/rewards", headers=user.h).json()
    assert [x["cost"] for x in r["rewards"]] == [500, 1000, 1500, 2000, 5000]
    assert all(x["status"] == "coming_soon" and x["available"] is False and x["affordable"] is False for x in r["rewards"])
    assert "no monetary value" in r["disclaimer"]
    assert api.post("/api/credits/rewards/detailed_analysis/redeem", headers=user.h).status_code in (404, 405)


def test_leaderboard_ranks_by_awarded_credits_not_submission_count(api):
    spammer, quiet = Who(api, "spammer"), Who(api, "quiet")
    for i in range(5):
        spammer.submit(make_photo(40 + i, gps=False))
    quiet.submit(make_photo(50, taken=days_ago(1)))
    lb = leaderboard(api)
    assert [r["user"] for r in lb] == ["quiet"]


def test_legacy_history_check_is_read_only_and_ignores_stress_and_demo_rows(tmp_path, monkeypatch):
    import sqlite3
    from core import database as legacy

    path = tmp_path / "legacy.db"
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE history (analysis_id TEXT PRIMARY KEY, water_body TEXT, date TEXT)")
    conn.executemany("INSERT INTO history VALUES (?,?,?)", [
        ("A_20260927_RealLake", "Real Lake", "2026-09-27"),      # a real Analyze run
        ("STRESS_20260927_StressLake", "Stress Lake", "2026-09-27"),  # stress test: never counts
        ("A_20260925_73", "Demo Lake", "2026-09-25"),           # auto-generated demo pass: never counts
    ])
    conn.commit()
    conn.close()
    monkeypatch.setattr(legacy, "DB_PATH", str(path))
    assert ver.legacy_analysis_exists("Real Lake") is True
    assert ver.legacy_analysis_exists("Stress Lake") is False
    assert ver.legacy_analysis_exists("Demo Lake") is False
    assert ver.legacy_analysis_exists("Never Seen") is False
    conn = sqlite3.connect(path)
    assert conn.execute("SELECT count(*) FROM history").fetchone()[0] == 3  # nothing was inserted
    conn.close()


def test_detector_land_result_is_invalid_location_and_contour_outline_is_accepted(api, monkeypatch):
    async def land(lat, lon):  # what the precision detector returns for terrestrial ground
        return {"is_water": False, "name": "Land Surface (Bharat Nagar)", "geojson": None, "water_type": "terrestrial_land"}

    monkeypatch.setattr(field_routes, "_async_lookup", land)
    field_routes._lookup_cache.clear()
    assert_rejected(Who(api).submit(make_photo(60, taken=days_ago(1))), "INVALID_LOCATION")

    async def water(lat, lon):  # confirmed water, outline traced from the tile (no osm_id)
        feat = outline("Contour Lake", lat, lon)["features"][0]
        feat["properties"] = {"contour": True, "name": "Contour Lake"}
        return {"is_water": True, "name": "Contour Lake", "geojson": {"type": "FeatureCollection", "features": [feat]}}

    monkeypatch.setattr(field_routes, "_async_lookup", water)
    field_routes._lookup_cache.clear()
    body = Who(api, "w").submit(make_photo(61, taken=days_ago(1))).json()
    assert body["status"] == "VERIFIED" and body["water_body"] == "Contour Lake"


def test_relaxed_mode_scans_photos_without_metadata(api, monkeypatch):
    monkeypatch.setenv("AQUASAFE_REQUIRE_METADATA", "0")
    from db.credit_rules import load_rules
    load_rules.cache_clear()
    user = Who(api)
    ok = user.submit(make_photo(70, gps=False, exif_time=False)).json()  # a "normal" picture
    assert ok["status"] == "VERIFIED" and ok["credits_awarded"] == 100
    by_id = {c["id"]: c["status"] for c in ok["checks"]}
    assert by_id["gps"] == by_id["captured"] == by_id["location"] == "skip" and by_id["image"] == "pass"
    # the image scan and duplicate protection still apply
    assert_rejected(user.submit(make_photo(71, kind="noise", gps=False, exif_time=False)), "INVALID_IMAGE")
    assert_rejected(user.submit(make_photo(73, kind="indoor", gps=False, exif_time=False)), "INVALID_IMAGE")
    assert_rejected(user.submit(make_photo(70, gps=False, exif_time=False)), "DUPLICATE")
    # metadata that IS present is still enforced
    assert_rejected(user.submit(make_photo(72, taken=days_ago(9))), "TOO_OLD")
    load_rules.cache_clear()
