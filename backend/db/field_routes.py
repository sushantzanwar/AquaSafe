"""HTTP API for verified field contributions. All decisions live in db/verification.py; these
handlers only parse input, authenticate the contributor and shape responses.

Client input that is deliberately IGNORED for credit purposes: latitude, longitude, capture date,
water-body id, credit amount. Only the uploaded image bytes are trusted (via its own EXIF).
"""

from __future__ import annotations

import asyncio
import time
import uuid

import hashlib

from fastapi import APIRouter, File, Form, Header, HTTPException, UploadFile
from pydantic import BaseModel

from db import imagecheck, verification as ver
from db.credit_rules import load_rules
from db.session import enabled, session_scope

router = APIRouter()

# main.py installs the async OSM point lookup it already uses for click-to-detect.
_async_lookup = None
_lookup_cache: dict[tuple[float, float], tuple[float, dict | None]] = {}


def set_point_lookup(fn) -> None:
    global _async_lookup
    _async_lookup = fn


def external_lookup(lat: float, lon: float):
    """Sync wrapper (handlers run in the threadpool) with a short cache so preview + submit share one lookup."""
    if _async_lookup is None:
        return None
    key = (round(lat, 4), round(lon, 4))
    hit = _lookup_cache.get(key)
    if hit and time.time() - hit[0] < 300:
        return hit[1]
    result = asyncio.run(_async_lookup(lat, lon))
    if result is not None:
        _lookup_cache[key] = (time.time(), result)
    return result


def _require_db() -> None:
    if not enabled():
        raise HTTPException(503, "Credits are unavailable: the database is not configured.")


def _user(session, token: str | None):
    user = ver.user_for_token(session, token)
    if user is None:
        raise HTTPException(401, "Missing or invalid contributor token.")
    return user


class RegisterBody(BaseModel):
    display_name: str | None = None


@router.post("/api/users/anonymous", status_code=201)
def register(body: RegisterBody):
    """Create an anonymous contributor; the secret token is returned once and only its hash is stored."""
    _require_db()
    with session_scope() as session:
        user, token = ver.register_user(session, body.display_name)
        return {"token": token, "display_name": user.display_name}


@router.post("/api/field/precheck")
def precheck(file: UploadFile = File(...)):
    """Run every check on a photo and report the result WITHOUT storing it or awarding anything."""
    _require_db()
    rules = load_rules()
    data = file.file.read(rules.max_upload_bytes + 1)
    if not data or len(data) > rules.max_upload_bytes:
        raise HTTPException(400, "Empty or oversized upload.")
    try:
        facts = imagecheck.analyze(data, rules)
    except imagecheck.ImageDecodeError:
        return {"eligible": False, "decision": "REJECTED", "reason_code": "INVALID_IMAGE",
                "message": rules.message("INVALID_IMAGE"), "water_body": None, "checks": [],
                "note": "Preview only."}
    with session_scope() as session:
        outcome = ver.evaluate(
            session, facts, sha256=hashlib.sha256(data).hexdigest(), external_lookup=external_lookup,
            legacy_history=ver.default_legacy_history(), rules=rules,
        )
        return ver.outcome_view(outcome)


@router.post("/api/field/submissions", status_code=201)
def submit(
    file: UploadFile = File(...),
    water_body_id: str | None = Form(None),  # accepted for display only; never used to decide anything
    x_aquasafe_token: str | None = Header(None),
):
    """Store the photo as PENDING, validate it, and return the authoritative result."""
    _require_db()
    rules = load_rules()
    data = file.file.read(rules.max_upload_bytes + 1)
    if not data:
        raise HTTPException(400, "Empty upload.")
    if len(data) > rules.max_upload_bytes:
        raise HTTPException(413, f"Image is larger than {rules.max_upload_bytes // (1024 * 1024)} MB.")
    with session_scope() as session:
        user_id = _user(session, x_aquasafe_token).id
    return ver.submit_photo(
        session_scope, user_id=user_id, data=data, content_type=file.content_type,
        external_lookup=external_lookup, legacy_history=ver.default_legacy_history(), rules=rules,
    )


def _parse_id(value: str) -> uuid.UUID:
    try:
        return uuid.UUID(value)
    except ValueError:
        raise HTTPException(404, "Submission not found.")


@router.get("/api/field/submissions/{submission_id}")
def submission_status(submission_id: str, x_aquasafe_token: str | None = Header(None)):
    _require_db()
    with session_scope() as session:
        user = _user(session, x_aquasafe_token)
        sub = session.get(ver.FieldSubmission, _parse_id(submission_id))
        if sub is None or sub.user_id != user.id:
            raise HTTPException(404, "Submission not found.")
        return ver.submission_view(session, sub)


@router.get("/api/field/submissions")
def my_submissions(x_aquasafe_token: str | None = Header(None)):
    _require_db()
    with session_scope() as session:
        user = _user(session, x_aquasafe_token)
        subs = session.scalars(
            ver.select(ver.FieldSubmission).where(ver.FieldSubmission.user_id == user.id)
            .order_by(ver.FieldSubmission.uploaded_at.desc()).limit(50)
        )
        return [ver.submission_view(session, s) for s in subs]


@router.get("/api/credits/me")
def credits_me(x_aquasafe_token: str | None = Header(None)):
    _require_db()
    with session_scope() as session:
        user = _user(session, x_aquasafe_token)
        return {"display_name": user.display_name, **ver.balance(session, user.id)}


@router.get("/api/credits/transactions")
def credits_transactions(x_aquasafe_token: str | None = Header(None)):
    _require_db()
    with session_scope() as session:
        return ver.transactions(session, _user(session, x_aquasafe_token).id)


@router.get("/api/credits/leaderboard")
def credits_leaderboard():
    _require_db()
    with session_scope() as session:
        return ver.leaderboard(session)


@router.get("/api/credits/rewards")
def credits_rewards(x_aquasafe_token: str | None = Header(None)):
    """Reward catalogue. Credits unlock AquaRadar capabilities; they have no monetary value.
    Rewards whose feature is not built yet are listed as coming_soon and cannot be redeemed."""
    rules = load_rules()
    credits = None
    if enabled() and x_aquasafe_token:
        with session_scope() as session:
            user = ver.user_for_token(session, x_aquasafe_token)
            credits = ver.balance(session, user.id)["credits"] if user else None
    return {
        "rewards": ver.rewards_catalogue(credits, rules),
        "disclaimer": "Credits unlock AquaRadar features. They have no monetary value and cannot be exchanged for cash.",
    }
