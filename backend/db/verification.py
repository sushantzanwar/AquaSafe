"""Verified field contributions: the only place credits are decided and awarded.

Principle: credits = verified new environmental intelligence, not photo uploads.

Pipeline (all server-side, driven by the uploaded image bytes; client-typed coordinates, dates,
water-body ids and amounts are never consulted):

    EXIF GPS + capture time -> age <= max_photo_age_days -> water body resolved from the GPS point
    -> water body not already flagged/analyzed -> image validation -> duplicate check
    -> decision (VERIFIED | REJECTED) -> credit computed here -> ledger row

Verification is fully automatic; there is no human review step. States: PENDING (received) ->
VALIDATING (processing) -> VERIFIED | REJECTED, stored in the existing columns as
submission_status/verification_status = received/pending, processing/pending, accepted/passed,
rejected/failed. Anything the platform cannot verify with confidence is REJECTED (UNABLE_TO_VERIFY),
never left for a person to decide.

"Flagged/analyzed" (one definition, ``flag_status``): the water body has a completed standard
analysis (PostgreSQL ``water_body_analysis_status`` or the legacy SQLite history the Analyze flow
still writes), or a field submission for it was already VERIFIED. Stress tests never count.
It is evaluated at verification time: a body analyzed after a valid submission but before it is
verified earns nothing (deterministic, last check wins).

Credits are awarded exactly once: the ledger has UNIQUE(submission_id), advisory locks serialize
concurrent work on the same image and water body, and finalisation is idempotent.
"""

from __future__ import annotations

import hashlib
import math
import secrets
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Callable

from shapely.errors import GEOSException
from shapely.geometry import Point, shape
from shapely.ops import transform, unary_union
from sqlalchemy import func, select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from db import imagecheck, repository as repo
from db.credit_rules import CreditRules, load_rules
from db.models import CreditTransaction, FieldSubmission, User, WaterBody
from db.storage import LocalImageStorage

ExternalLookup = Callable[[float, float], "dict | None"]
LegacyHistory = Callable[[str], list]

AWARD_REASON = "field_submission_verified"

CHECK_LABELS = {
    "gps": "Photo contains GPS location",
    "captured": "Photo was taken within the last 7 days",
    "location": "Location matches a recognized water body",
    "new_water_body": "Water body is not already analyzed",
    "image": "Photo clearly shows the water body",
    "duplicate": "Photo is original and non-duplicate",
}


@dataclass
class Check:
    id: str
    status: str  # pass | fail | skip
    code: str | None = None
    message: str = ""

    @property
    def label(self) -> str:
        return CHECK_LABELS[self.id]


@dataclass
class Outcome:
    decision: str  # VERIFIED | REJECTED
    code: str
    message: str
    checks: list[Check]
    credits: int = 0
    tier: str | None = None
    body: WaterBody | None = None
    duplicate_of: uuid.UUID | None = None
    duplicate_details: dict | None = None


# --- geography ----------------------------------------------------------------------------------

def valid_coordinates(lat, lon) -> bool:
    try:
        lat, lon = float(lat), float(lon)
    except (TypeError, ValueError):
        return False
    if math.isnan(lat) or math.isnan(lon) or not (-90 <= lat <= 90 and -180 <= lon <= 180):
        return False
    return not (lat == 0 and lon == 0)  # (0, 0) is what broken cameras write


def distance_m(lat1, lon1, lat2, lon2) -> float:
    dlat, dlon = math.radians(lat2 - lat1), math.radians(lon2 - lon1)
    a = math.sin(dlat / 2) ** 2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon / 2) ** 2
    return 6371000.0 * 2 * math.asin(math.sqrt(a))


def distance_to_outline_m(geojson: dict | None, lat: float, lon: float) -> float | None:
    """Metres from the point to the nearest OSM polygon in the GeoJSON (0 when inside)."""
    k = math.cos(math.radians(lat))
    project = lambda x, y, z=None: ((x - lon) * 111320.0 * k, (y - lat) * 110540.0)  # noqa: E731
    shapes = []
    for feature in repo._features(geojson):
        props = feature.get("properties") or {}
        if props.get("osm_id") is None and not props.get("contour"):
            continue  # only real outlines are authoritative, never the generated circle
        try:
            geom = shape(feature["geometry"])
            shapes.append(transform(project, geom if geom.is_valid else geom.buffer(0)))
        except (GEOSException, ValueError, KeyError, TypeError):
            continue
    if not shapes:
        return None
    return float(Point(0, 0).distance(unary_union(shapes)))


def resolve_water_body(
    session: Session, lat: float, lon: float, external_lookup: ExternalLookup | None, rules: CreditRules
) -> tuple[str, WaterBody | None]:
    """('resolved', body) | ('far', None) | ('unknown', None).

    Authoritative sources, in order: outlines already stored in ``water_bodies``, then the same
    OSM lookup the map's click-to-detect uses. Only real OSM outlines count; a generated circle is
    an approximation, so it yields 'unknown' (rejected as unverifiable) rather than a guess.
    """
    for body in session.scalars(select(WaterBody).where(WaterBody.geometry_source == "osm")):
        d = distance_to_outline_m(body.geometry, lat, lon)
        if d is not None and d <= rules.max_location_distance_m:
            return "resolved", body
    found = None
    if external_lookup is not None:
        try:
            found = external_lookup(lat, lon)
        except Exception:
            found = None
    if found and found.get("is_water") is False:
        return "far", None  # the detector positively identified land: not a water body
    if not found or not found.get("geojson"):
        return "unknown", None
    source, osm_ref = repo.classify_geometry(found["geojson"])
    if source != "osm":
        return "unknown", None
    d = distance_to_outline_m(found["geojson"], lat, lon)
    if d is None or d > rules.max_location_distance_m:
        return "far", None
    name = (found.get("name") or "").strip()
    if not name or name.lower().startswith("unknown water body"):
        name = f"OSM water body {osm_ref or f'{lat:.4f},{lon:.4f}'}"  # unnamed bodies must not collapse into one identity
    return "resolved", repo.upsert_water_body(session, name, found["geojson"])


def flag_status(
    session: Session, body: WaterBody, legacy_history: LegacyHistory | None, exclude_submission_id: uuid.UUID | None = None
) -> dict:
    reasons = []
    row = repo.analysis_status(session, body.name)
    if row and (row.get("analysis_count") or 0) > 0:
        reasons.append("analysis")
    query = select(func.count()).select_from(FieldSubmission).where(
        FieldSubmission.water_body_id == body.id, FieldSubmission.verification_status == "passed"
    )
    if exclude_submission_id:
        query = query.where(FieldSubmission.id != exclude_submission_id)
    if session.scalar(query):
        reasons.append("field_verification")
    if legacy_history is not None:
        try:
            if legacy_history(body.name):
                reasons.append("legacy_analysis")
        except Exception:
            pass
    return {"flagged": bool(reasons), "reasons": reasons}


def find_duplicate(
    session: Session, *, sha256: str, phash: int, lat: float | None, lon: float | None,
    captured_at: datetime | None, exclude_id: uuid.UUID | None, rules: CreditRules,
) -> tuple[FieldSubmission, dict] | None:
    """Exact, perceptual (any user) and same-observation (same place and time) matches against every
    submission that has not itself been rejected."""
    query = select(FieldSubmission).where(FieldSubmission.verification_status != "failed")
    if exclude_id:
        query = query.where(FieldSubmission.id != exclude_id)
    others = list(session.scalars(query))
    if exclude_id is not None:
        # Only an EARLIER submission can make this one a duplicate; otherwise two concurrent
        # copies of the same photo would each see the other and both be rejected.
        mine = session.get(FieldSubmission, exclude_id)
        if mine is not None:
            others = [o for o in others if (o.uploaded_at, str(o.id)) < (mine.uploaded_at, str(mine.id))]
    for other in others:
        if other.image_sha256 == sha256:
            return other, {"kind": "exact"}
    for other in others:
        if other.perceptual_hash is not None:
            dist = imagecheck.hamming(phash, imagecheck.from_signed64(other.perceptual_hash))
            if dist <= rules.phash_max_distance:
                return other, {"kind": "perceptual", "hamming": dist}
    if lat is not None and lon is not None and captured_at is not None:
        for other in others:
            if other.gps_lat is None or other.gps_lon is None or other.captured_at is None:
                continue
            if (
                distance_m(lat, lon, other.gps_lat, other.gps_lon) <= rules.duplicate_distance_m
                and abs((captured_at - other.captured_at).total_seconds()) <= rules.duplicate_seconds
            ):
                return other, {"kind": "same_observation"}
    return None


# --- evaluation ---------------------------------------------------------------------------------

def _image_check(facts: imagecheck.ImageFacts, rules: CreditRules) -> tuple[Check, str | None]:
    """Returns the check and the credit tier ('high'/'acceptable') when it passes."""
    def fail(code, msg):
        return Check("image", "fail", code, msg), None

    if min(facts.width, facts.height) < rules.min_side_px:
        return fail("LOW_QUALITY", "Image resolution is too low.")
    if facts.document_like or facts.luma_std < 8:
        return fail("INVALID_IMAGE", "The image looks blank, like a screenshot or document, not a water body.")
    if facts.mean_luma < 25 or facts.mean_luma > 245:
        return fail("LOW_QUALITY", "Image is too dark or overexposed.")
    if facts.sharpness < 25:
        return fail("LOW_QUALITY", "Image is too blurry.")
    if facts.water_like < rules.min_water_like or facts.row_std > rules.max_row_std:
        return fail("INVALID_IMAGE", "No water surface was detected: the image does not look like a water body.")
    if facts.quality_score < rules.acceptable_quality_score:
        return fail("LOW_QUALITY", "Image quality is insufficient for verification.")
    return Check("image", "pass"), ("high" if facts.quality_score >= rules.high_quality_score else "acceptable")


def evaluate(
    session: Session,
    facts: imagecheck.ImageFacts,
    *,
    sha256: str,
    external_lookup: ExternalLookup | None,
    legacy_history: LegacyHistory | None,
    rules: CreditRules,
    now: datetime | None = None,
    exclude_submission_id: uuid.UUID | None = None,
    lock: bool = False,
) -> Outcome:
    now = now or datetime.now(timezone.utc)
    checks: dict[str, Check] = {k: Check(k, "skip") for k in CHECK_LABELS}

    # 1. GPS from the photo's own EXIF.
    gps_ok = valid_coordinates(facts.gps_lat, facts.gps_lon)
    if gps_ok:
        checks["gps"] = Check("gps", "pass")
    elif rules.require_metadata:
        checks["gps"] = Check("gps", "fail", "NO_GPS", rules.message("NO_GPS"))
    else:
        checks["gps"] = Check("gps", "skip", None, "No GPS in this photo, so its location and novelty could not be checked.")

    # 2. Original capture time (never upload time or a typed date).
    if facts.captured_at is None:
        if rules.require_metadata:
            checks["captured"] = Check("captured", "fail", "UNABLE_TO_VERIFY", "The photo has no original capture time.")
        else:
            checks["captured"] = Check("captured", "skip", None, "No capture time in this photo, so its age could not be checked.")
    elif facts.time_inconsistent:
        checks["captured"] = Check("captured", "fail", "UNABLE_TO_VERIFY", "The photo's time metadata is inconsistent.")
    elif facts.captured_at > now + timedelta(seconds=rules.future_tolerance_seconds):
        checks["captured"] = Check("captured", "fail", "UNABLE_TO_VERIFY", "The photo's capture time is in the future.")
    elif now - facts.captured_at > timedelta(days=rules.max_photo_age_days):
        checks["captured"] = Check("captured", "fail", "TOO_OLD", rules.message("TOO_OLD"))
    else:
        checks["captured"] = Check("captured", "pass")

    if lock:
        session.execute(text("SELECT pg_advisory_xact_lock(hashtext(:k))"), {"k": f"img:{sha256}"})

    # 3-4. Which water body is this, and is it already flagged/analyzed?
    body = None
    if gps_ok:
        state, body = resolve_water_body(session, facts.gps_lat, facts.gps_lon, external_lookup, rules)
        if state == "resolved":
            checks["location"] = Check("location", "pass")
            if lock:
                session.execute(text("SELECT pg_advisory_xact_lock(hashtext(:k))"), {"k": f"wb:{body.id}"})
            flag = flag_status(session, body, legacy_history, exclude_submission_id)
            checks["new_water_body"] = (
                Check("new_water_body", "fail", "ALREADY_ANALYZED", rules.message("ALREADY_ANALYZED"))
                if flag["flagged"] else Check("new_water_body", "pass")
            )
        elif state == "far":
            checks["location"] = Check("location", "fail", "INVALID_LOCATION", rules.message("INVALID_LOCATION"))
        else:
            checks["location"] = Check("location", "fail", "UNABLE_TO_VERIFY", "The water body at this location could not be identified reliably.")

    # 5. Image validation.
    image_check, tier = _image_check(facts, rules)
    checks["image"] = image_check

    # 6. Duplicates.
    dup = find_duplicate(
        session, sha256=sha256, phash=facts.phash,
        lat=facts.gps_lat if gps_ok else None, lon=facts.gps_lon if gps_ok else None,
        captured_at=facts.captured_at, exclude_id=exclude_submission_id, rules=rules,
    )
    duplicate_of, duplicate_details = (dup[0].id, dup[1]) if dup else (None, None)
    checks["duplicate"] = Check("duplicate", "fail", "DUPLICATE", rules.message("DUPLICATE")) if dup else Check("duplicate", "pass")

    ordered = [checks[k] for k in CHECK_LABELS]
    # Which failure is reported first. A re-sent photo is a DUPLICATE before it is "already analyzed".
    precedence = ("gps", "captured", "location", "duplicate", "new_water_body", "image")
    failed = next((checks[k] for k in precedence if checks[k].status == "fail"), None)
    if failed:
        return Outcome("REJECTED", failed.code, failed.message or rules.message(failed.code), ordered, body=body,
                       duplicate_of=duplicate_of, duplicate_details=duplicate_details)
    credits = rules.award_high_quality if tier == "high" else rules.award_acceptable_quality
    return Outcome("VERIFIED", "VERIFIED", rules.message("VERIFIED"), ordered, credits=credits, tier=tier, body=body)


# --- persistence --------------------------------------------------------------------------------

def _apply(session: Session, sub: FieldSubmission, outcome: Outcome, facts: imagecheck.ImageFacts, rules: CreditRules) -> None:
    """Write the decision. Credits are inserted at most once (UNIQUE(submission_id) + ON CONFLICT)."""
    sub.water_body_id = outcome.body.id if outcome.body else None
    sub.quality_score = facts.quality_score
    sub.quality_details = {
        "sharpness": round(facts.sharpness, 1), "mean_luma": round(facts.mean_luma, 1),
        "water_like": round(facts.water_like, 3), "row_std": round(facts.row_std, 1),
        "width": facts.width, "height": facts.height, "tier": outcome.tier,
    }
    sub.verification_result = {
        "decision": outcome.decision, "code": outcome.code, "message": outcome.message,
        "capture_source": facts.capture_source,
        "checks": [{"id": c.id, "status": c.status, "code": c.code, "message": c.message} for c in outcome.checks],
    }
    sub.reason_code = outcome.code
    sub.duplicate_of_submission_id = outcome.duplicate_of
    sub.duplicate_details = outcome.duplicate_details
    if outcome.decision == "VERIFIED":
        sub.submission_status, sub.verification_status, sub.rejection_reason = "accepted", "passed", None
        session.execute(
            pg_insert(CreditTransaction)
            .values(user_id=sub.user_id, amount=outcome.credits, reason=AWARD_REASON, submission_id=sub.id)
            .on_conflict_do_nothing(constraint="uq_credit_transactions_submission_id")
        )
    elif outcome.decision == "REJECTED":
        sub.submission_status, sub.verification_status, sub.rejection_reason = "rejected", "failed", outcome.message
    session.flush()


def status_label(sub: FieldSubmission) -> str:
    return {
        ("received", "pending"): "PENDING",
        ("processing", "pending"): "VALIDATING",
        ("accepted", "passed"): "VERIFIED",
        ("rejected", "failed"): "REJECTED",
    }.get((sub.submission_status, sub.verification_status), "PENDING")


def credits_for(session: Session, submission_id: uuid.UUID) -> int:
    return int(session.scalar(select(func.coalesce(func.sum(CreditTransaction.amount), 0)).where(
        CreditTransaction.submission_id == submission_id)) or 0)


def submission_view(session: Session, sub: FieldSubmission) -> dict:
    """What the client may see. Raw GPS and EXIF are deliberately not included."""
    result = sub.verification_result or {}
    label = status_label(sub)
    body = session.get(WaterBody, sub.water_body_id) if sub.water_body_id else None
    return {
        "id": str(sub.id),
        "status": label,
        "reason_code": sub.reason_code,
        "message": {
            "PENDING": "Submission received.",
            "VALIDATING": "Verification in progress.",
        }.get(label, sub.rejection_reason or result.get("message")),
        "credits_awarded": credits_for(session, sub.id),
        "water_body": body.name if body else None,
        "captured_at": sub.captured_at.isoformat() if sub.captured_at else None,
        "submitted_at": sub.uploaded_at.isoformat() if sub.uploaded_at else None,
        "checks": [
            {"id": c["id"], "label": CHECK_LABELS[c["id"]], "status": c["status"], "message": c.get("message") or ""}
            for c in result.get("checks", [])
        ],
    }


def outcome_view(outcome: Outcome) -> dict:
    """Preview of the checks for the UI before submitting; never awards or stores anything."""
    return {
        "eligible": outcome.decision == "VERIFIED",
        "decision": outcome.decision,
        "reason_code": None if outcome.decision == "VERIFIED" else outcome.code,
        "message": outcome.message,
        "water_body": outcome.body.name if outcome.body else None,
        "checks": [{"id": c.id, "label": c.label, "status": c.status, "message": c.message} for c in outcome.checks],
        "note": "Preview only. Credits are decided by the server when you submit, and again at verification time.",
    }


def legacy_analysis_exists(water_body: str) -> bool:
    """Has the Analyze flow ever run for this water body, per the legacy SQLite history?

    Read-only on purpose: core.database.get_history() invents (and INSERTS) mock history for any
    name it has not seen, so it cannot answer this question. A real standard analysis is stored as
    ``A_<yyyymmdd>_<name without spaces>``; stress tests (``STRESS_...``) and the auto-generated demo
    passes (``A_<yyyymmdd>_<number>``) are ignored.
    """
    import sqlite3
    from pathlib import Path

    from core import database as legacy

    path = Path(legacy.DB_PATH)
    if not path.is_file():
        return False
    suffix = "_" + water_body.replace(" ", "")
    conn = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
    try:
        rows = conn.execute("SELECT analysis_id FROM history WHERE water_body = ?", (water_body,)).fetchall()
    finally:
        conn.close()
    return any(r[0].startswith("A_") and r[0].endswith(suffix) for r in rows)


def default_legacy_history() -> LegacyHistory | None:
    """Callable returning a truthy list when the legacy history shows a real analysis."""
    try:
        import core.database  # noqa: F401
    except Exception:
        return None
    return lambda name: [name] if legacy_analysis_exists(name) else []


def submit_photo(
    session_factory,
    *,
    user_id: uuid.UUID,
    data: bytes,
    content_type: str | None,
    external_lookup: ExternalLookup | None,
    legacy_history: LegacyHistory | None = None,
    rules: CreditRules | None = None,
    now: datetime | None = None,
    storage: LocalImageStorage | None = None,
) -> dict:
    """Receive, validate and (if eligible) credit one photo. ``session_factory`` is a context manager
    yielding a Session that commits on success (db.session.session_scope)."""
    rules = rules or load_rules()
    storage = storage or LocalImageStorage()
    sha = hashlib.sha256(data).hexdigest()
    try:
        facts = imagecheck.analyze(data, rules)
    except imagecheck.ImageDecodeError:
        return {"id": None, "status": "REJECTED", "reason_code": "INVALID_IMAGE", "message": rules.message("INVALID_IMAGE"),
                "credits_awarded": 0, "water_body": None, "captured_at": None, "submitted_at": None, "checks": []}

    # Transaction A: PENDING. The row exists (and is auditable) before any decision is taken.
    stored = storage.save(data, content_type)
    with session_factory() as session:
        sub = repo.create_submission(
            session, user_id=user_id, image_key=stored.key, image_sha256=sha, image_content_type=content_type,
            image_size_bytes=stored.size_bytes,
            gps_lat=facts.gps_lat if valid_coordinates(facts.gps_lat, facts.gps_lon) else None,
            gps_lon=facts.gps_lon if valid_coordinates(facts.gps_lat, facts.gps_lon) else None,
            captured_at=facts.captured_at,
        )
        sub.perceptual_hash = imagecheck.to_signed64(facts.phash)
        sub_id = sub.id

    # Transaction B: VALIDATING -> final state, under advisory locks.
    with session_factory() as session:
        # Lock order matters (deadlock otherwise): image lock first, then this row.
        session.execute(text("SELECT pg_advisory_xact_lock(hashtext(:k))"), {"k": f"img:{sha}"})
        sub = session.scalars(select(FieldSubmission).where(FieldSubmission.id == sub_id).with_for_update()).one()
        sub.submission_status = "processing"
        session.flush()
        outcome = evaluate(
            session, facts, sha256=sha, external_lookup=external_lookup, legacy_history=legacy_history,
            rules=rules, now=now, exclude_submission_id=sub_id, lock=True,
        )
        _apply(session, sub, outcome, facts, rules)
        if outcome.duplicate_of and (dup := session.get(FieldSubmission, outcome.duplicate_of)) and dup.image_key != sub.image_key \
                and dup.image_sha256 == sha:
            storage.delete(sub.image_key)  # exact duplicate: keep a single stored copy
            sub.image_key = dup.image_key
        return submission_view(session, sub)


# --- users, balance, leaderboard, rewards -------------------------------------------------------

def _token_id(token: str) -> str:
    return "anon:" + hashlib.sha256(token.encode()).hexdigest()


def register_user(session: Session, display_name: str | None) -> tuple[User, str]:
    """Anonymous contributor. AquaSafe has no login yet, so the server issues a secret token; only its
    hash is stored, and every credit/balance call must present it (nobody can act as someone else)."""
    token = secrets.token_urlsafe(32)
    name = " ".join((display_name or "").split())[:40] or f"Contributor-{secrets.token_hex(2).upper()}"
    user = repo.get_or_create_user(session, _token_id(token), display_name=name)
    return user, token


def user_for_token(session: Session, token: str | None) -> User | None:
    if not token or len(token) < 20:
        return None
    return session.scalars(select(User).where(User.external_id == _token_id(token))).one_or_none()


def balance(session: Session, user_id: uuid.UUID) -> dict:
    total = session.scalar(select(func.coalesce(func.sum(CreditTransaction.amount), 0)).where(CreditTransaction.user_id == user_id))
    counts = dict(session.execute(
        select(FieldSubmission.verification_status, func.count()).where(FieldSubmission.user_id == user_id)
        .group_by(FieldSubmission.verification_status)
    ).all())
    return {
        "credits": int(total or 0),
        "verified_contributions": counts.get("passed", 0),
        "pending": counts.get("pending", 0),
        "rejected": counts.get("failed", 0),
    }


def transactions(session: Session, user_id: uuid.UUID, limit: int = 50) -> list[dict]:
    rows = session.scalars(select(CreditTransaction).where(CreditTransaction.user_id == user_id)
                           .order_by(CreditTransaction.created_at.desc()).limit(limit))
    return [{"id": str(t.id), "amount": t.amount, "reason": t.reason,
             "submission_id": str(t.submission_id) if t.submission_id else None,
             "status": "posted", "created_at": t.created_at.isoformat()} for t in rows]


def leaderboard(session: Session, limit: int = 20) -> list[dict]:
    """Ranked by credits actually awarded, then verified contributions. Pending and rejected
    submissions contribute nothing to rank or credits; they only lower the verification rate once decided."""
    rows = session.execute(text("""
        SELECT u.display_name,
               left(replace(u.id::text, '-', ''), 6) AS handle,
               coalesce(e.credits, 0)  AS credits,
               coalesce(s.verified, 0) AS verified,
               coalesce(s.decided, 0)  AS decided
        FROM users u
        JOIN (SELECT user_id, sum(amount) AS credits FROM credit_transactions WHERE amount > 0 GROUP BY user_id) e
             ON e.user_id = u.id
        LEFT JOIN (SELECT user_id,
                          count(*) FILTER (WHERE verification_status = 'passed') AS verified,
                          count(*) FILTER (WHERE verification_status IN ('passed', 'failed')) AS decided
                   FROM field_submissions GROUP BY user_id) s ON s.user_id = u.id
        ORDER BY e.credits DESC, s.verified DESC, u.created_at ASC
        LIMIT :limit
    """), {"limit": limit}).mappings().all()
    return [
        {"rank": i + 1, "user": r["display_name"] or f"Contributor-{r['handle']}", "handle": r["handle"],
         "verified_contributions": int(r["verified"]), "credits": int(r["credits"]),
         "verification_rate": round(r["verified"] / r["decided"], 3) if r["decided"] else None}
        for i, r in enumerate(rows)
    ]


def rewards_catalogue(credits: int | None, rules: CreditRules | None = None) -> list[dict]:
    from db.credit_rules import REWARD_LABELS
    rules = rules or load_rules()
    out = []
    for key, cfg in sorted(rules.rewards.items(), key=lambda kv: kv[1]["cost"]):
        title, desc = REWARD_LABELS[key]
        out.append({
            "key": key, "title": title, "description": desc, "cost": cfg["cost"],
            "available": bool(cfg["available"]),
            "status": "available" if cfg["available"] else "coming_soon",
            "affordable": None if credits is None else credits >= cfg["cost"],
        })
    return out
