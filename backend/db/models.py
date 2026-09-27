"""Persistent application data for AquaSafe (PostgreSQL).

Scope: identity and history that the application must query later. Detailed analysis output
(the CSV/GeoJSON exports, satellite imagery, rasters) stays where the existing system produces it;
rows here only summarise an analysis and can reference an artifact by path/key.

Enumerated text columns use CHECK constraints instead of native ENUM types so later tasks can
add states with a plain migration.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    MetaData,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

NAMING = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}

GEOMETRY_SOURCES = ("osm", "approximate", "none")
ANALYSIS_TYPES = ("standard", "stress_test")
SUBMISSION_STATUSES = ("received", "processing", "accepted", "rejected", "withdrawn")
VERIFICATION_STATUSES = ("pending", "passed", "failed", "needs_review")
REDEMPTION_STATUSES = ("pending", "fulfilled", "cancelled")


def _in(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN ({', '.join(repr(v) for v in values)})"


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING)


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


def _uuid_pk() -> Mapped[uuid.UUID]:
    return mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)


class User(TimestampMixin, Base):
    """A person who submits field photos and holds credits.

    AquaSafe has no authentication yet. ``external_id`` is the stable identifier issued by
    whatever identity provider is added later (e.g. an OIDC subject); no auth logic lives here.
    """

    __tablename__ = "users"

    id: Mapped[uuid.UUID] = _uuid_pk()
    external_id: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    display_name: Mapped[str | None] = mapped_column(String(120))
    email: Mapped[str | None] = mapped_column(String(320), unique=True)

    submissions: Mapped[list[FieldSubmission]] = relationship(back_populates="user")
    credit_transactions: Mapped[list[CreditTransaction]] = relationship(back_populates="user")


class WaterBody(TimestampMixin, Base):
    """One monitored water body.

    Identity follows the existing system, which keys every analysis, the SQLite history table and
    the frontend's sessionStorage on the water-body *name*. ``gis_key`` is that name normalised
    (trimmed, whitespace collapsed, case-folded), so it cannot drift from the existing identity.
    ``geometry`` is the GeoJSON FeatureCollection exactly as the existing API returns it.
    """

    __tablename__ = "water_bodies"
    __table_args__ = (CheckConstraint(_in("geometry_source", GEOMETRY_SOURCES), name="geometry_source"),)

    id: Mapped[uuid.UUID] = _uuid_pk()
    gis_key: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    geometry: Mapped[dict | None] = mapped_column(JSONB)
    # osm = OpenStreetMap outline; approximate = the backend's generated circle; none = no geometry.
    geometry_source: Mapped[str] = mapped_column(String(20), nullable=False, server_default="none")
    osm_ref: Mapped[str | None] = mapped_column(String(64))
    centroid_lat: Mapped[float | None] = mapped_column(Float)
    centroid_lon: Mapped[float | None] = mapped_column(Float)

    analyses: Mapped[list[WaterBodyAnalysis]] = relationship(back_populates="water_body")


class WaterBodyAnalysis(Base):
    """Append-only summary of one run of the existing analysis pipeline. Never overwritten.

    Mirrors the existing ``AnalysisResponse`` (indicators, anomaly, priority) plus provenance.
    ``legacy_analysis_id`` is the existing ``analysis_id``; it is NOT unique because the existing
    system reuses it for every run of the same water body on the same day.
    """

    __tablename__ = "water_body_analyses"
    __table_args__ = (
        CheckConstraint(_in("analysis_type", ANALYSIS_TYPES), name="analysis_type"),
        Index("ix_water_body_analyses_body_time", "water_body_id", "analyzed_at"),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()
    water_body_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("water_bodies.id", ondelete="RESTRICT"), nullable=False
    )
    legacy_analysis_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    analysis_type: Mapped[str] = mapped_column(String(20), nullable=False)
    requested_date: Mapped[date | None] = mapped_column(Date)
    analyzed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    # Existing anomaly block: status is the pipeline's own label (e.g. HIGH / WARNING / NORMAL).
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    anomaly_score: Mapped[int | None] = mapped_column(Integer)
    anomaly_confidence: Mapped[float | None] = mapped_column(Float)
    deviation_sigma: Mapped[float | None] = mapped_column(Float)
    priority_score: Mapped[int | None] = mapped_column(Integer)
    ndwi: Mapped[float | None] = mapped_column(Float)
    ndti: Mapped[float | None] = mapped_column(Float)
    ndci: Mapped[float | None] = mapped_column(Float)

    # Provenance. is_synthetic is true when the engine generated the input instead of reading
    # satellite data, so later features can tell measured results from demo output.
    engine: Mapped[str] = mapped_column(String(64), nullable=False)
    is_synthetic: Mapped[bool] = mapped_column(Boolean, nullable=False)
    request_lat: Mapped[float | None] = mapped_column(Float)
    request_lon: Mapped[float | None] = mapped_column(Float)
    scene_ref: Mapped[str | None] = mapped_column(String(255))  # satellite scene/product id, when there is one
    scene_date: Mapped[date | None] = mapped_column(Date)
    report_ref: Mapped[str | None] = mapped_column(String(1024))  # path/key of a server-side report, when there is one
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    water_body: Mapped[WaterBody] = relationship(back_populates="analyses")


class FieldSubmission(TimestampMixin, Base):
    """A user's field photo. The image lives in file/object storage; ``image_key`` points to it.

    Holds the current verification state. The individual checks (GPS, time window, quality,
    duplicates) are later tasks; their detailed output goes in the JSONB columns.
    """

    __tablename__ = "field_submissions"
    __table_args__ = (
        CheckConstraint(_in("submission_status", SUBMISSION_STATUSES), name="submission_status"),
        CheckConstraint(_in("verification_status", VERIFICATION_STATUSES), name="verification_status"),
        CheckConstraint("gps_lat IS NULL OR gps_lat BETWEEN -90 AND 90", name="gps_lat_range"),
        CheckConstraint("gps_lon IS NULL OR gps_lon BETWEEN -180 AND 180", name="gps_lon_range"),
        CheckConstraint("duplicate_of_submission_id IS NULL OR duplicate_of_submission_id <> id", name="not_self_duplicate"),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True)
    water_body_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("water_bodies.id", ondelete="RESTRICT"), index=True
    )
    image_key: Mapped[str] = mapped_column(String(1024), nullable=False)
    image_sha256: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    image_content_type: Mapped[str | None] = mapped_column(String(100))
    image_size_bytes: Mapped[int | None] = mapped_column(Integer)
    gps_lat: Mapped[float | None] = mapped_column(Float)
    gps_lon: Mapped[float | None] = mapped_column(Float)
    gps_accuracy_m: Mapped[float | None] = mapped_column(Float)
    captured_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    uploaded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    submission_status: Mapped[str] = mapped_column(String(20), nullable=False, server_default="received")
    verification_status: Mapped[str] = mapped_column(String(20), nullable=False, server_default="pending")
    verification_result: Mapped[dict | None] = mapped_column(JSONB)
    rejection_reason: Mapped[str | None] = mapped_column(Text)
    quality_score: Mapped[float | None] = mapped_column(Float)
    quality_details: Mapped[dict | None] = mapped_column(JSONB)
    duplicate_of_submission_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("field_submissions.id", ondelete="SET NULL")
    )
    duplicate_details: Mapped[dict | None] = mapped_column(JSONB)
    # Machine-readable outcome (see db/credit_rules.REASONS); rejection_reason holds the message.
    reason_code: Mapped[str | None] = mapped_column(String(32))
    # 64-bit dHash stored as signed BIGINT, for near-duplicate detection.
    perceptual_hash: Mapped[int | None] = mapped_column(BigInteger, index=True)

    user: Mapped[User] = relationship(back_populates="submissions")
    water_body: Mapped[WaterBody | None] = relationship()


class Reward(TimestampMixin, Base):
    """Catalogue entry a user could redeem credits for. Schema only; no redemption logic yet."""

    __tablename__ = "rewards"
    __table_args__ = (
        CheckConstraint("cost_credits > 0", name="cost_positive"),
        CheckConstraint("quantity_available IS NULL OR quantity_available >= 0", name="quantity_non_negative"),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    cost_credits: Mapped[int] = mapped_column(Integer, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    quantity_available: Mapped[int | None] = mapped_column(Integer)  # NULL = unlimited


class RewardRedemption(TimestampMixin, Base):
    __tablename__ = "reward_redemptions"
    __table_args__ = (CheckConstraint(_in("status", REDEMPTION_STATUSES), name="status"),)

    id: Mapped[uuid.UUID] = _uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True)
    reward_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("rewards.id", ondelete="RESTRICT"), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, server_default="pending")


class CreditTransaction(Base):
    """Append-only credit ledger. A balance is SUM(amount) per user; there is no balance column,
    and amounts are only ever written by the server. Earning/spending rules are a later task."""

    __tablename__ = "credit_transactions"
    __table_args__ = (
        CheckConstraint("amount <> 0", name="amount_non_zero"),
        CheckConstraint("NOT (submission_id IS NOT NULL AND redemption_id IS NOT NULL)", name="single_source"),
        CheckConstraint("submission_id IS NULL OR amount > 0", name="submission_earns"),
        UniqueConstraint("submission_id"),  # a submission is credited at most once
        Index("ix_credit_transactions_user_time", "user_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    amount: Mapped[int] = mapped_column(Integer, nullable=False)
    reason: Mapped[str] = mapped_column(String(100), nullable=False)
    submission_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("field_submissions.id", ondelete="RESTRICT"), index=True
    )
    redemption_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("reward_redemptions.id", ondelete="RESTRICT"), index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    user: Mapped[User] = relationship(back_populates="credit_transactions")
