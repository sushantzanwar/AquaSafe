"""Persistent data foundation: users, water bodies, analysis history, field submissions,
credit ledger and reward schema.

Also creates:
  * water_body_analysis_status: per-water-body facts for "has this been analyzed?"
  * updated_at triggers, so raw-SQL updates keep timestamps right as well as ORM updates
  * append-only guards on water_body_analyses and credit_transactions (history is never rewritten)

Revision ID: 0001
Revises:
Create Date: 2026-09-27 08:38:53.012777
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = '0001'
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_UPDATED_AT_TABLES = ("users", "water_bodies", "field_submissions", "rewards", "reward_redemptions")
_APPEND_ONLY_TABLES = ("water_body_analyses", "credit_transactions")

_EXTRA_UP = [
    """
    CREATE FUNCTION aquasafe_set_updated_at() RETURNS trigger AS $$
    BEGIN
        NEW.updated_at := now();
        RETURN NEW;
    END;
    $$ LANGUAGE plpgsql
    """,
    *[
        f"CREATE TRIGGER trg_{t}_updated_at BEFORE UPDATE ON {t} "
        f"FOR EACH ROW EXECUTE FUNCTION aquasafe_set_updated_at()"
        for t in _UPDATED_AT_TABLES
    ],
    """
    CREATE FUNCTION aquasafe_append_only() RETURNS trigger AS $$
    BEGIN
        RAISE EXCEPTION '% is append-only: % is not allowed', TG_TABLE_NAME, TG_OP
            USING ERRCODE = 'restrict_violation';
    END;
    $$ LANGUAGE plpgsql
    """,
    *[
        f"CREATE TRIGGER trg_{t}_append_only BEFORE UPDATE OR DELETE ON {t} "
        f"FOR EACH ROW EXECUTE FUNCTION aquasafe_append_only()"
        for t in _APPEND_ONLY_TABLES
    ],
    # Facts only. What counts as "flagged" for credits is decided by the credit task; the latest
    # status and whether any evidence came from measured (non-synthetic) data are both here.
    # Stress tests inject fake anomalies, so they are counted separately and never set a status.
    """
    CREATE VIEW water_body_analysis_status AS
    SELECT
        wb.id   AS water_body_id,
        wb.gis_key,
        wb.name,
        count(a.id) FILTER (WHERE a.analysis_type = 'standard')                       AS analysis_count,
        count(a.id) FILTER (WHERE a.analysis_type = 'standard' AND NOT a.is_synthetic) AS measured_analysis_count,
        count(a.id) FILTER (WHERE a.analysis_type = 'stress_test')                    AS stress_test_count,
        max(a.analyzed_at) FILTER (WHERE a.analysis_type = 'standard')                AS last_analyzed_at,
        latest.status        AS last_status,
        latest.is_synthetic  AS last_is_synthetic,
        latest.id            AS last_analysis_id,
        measured.analyzed_at AS last_measured_at,
        measured.status      AS last_measured_status,
        measured.id          AS last_measured_analysis_id
    FROM water_bodies wb
    LEFT JOIN water_body_analyses a ON a.water_body_id = wb.id
    LEFT JOIN LATERAL (
        SELECT x.id, x.status, x.is_synthetic FROM water_body_analyses x
        WHERE x.water_body_id = wb.id AND x.analysis_type = 'standard'
        ORDER BY x.analyzed_at DESC, x.created_at DESC LIMIT 1
    ) latest ON true
    LEFT JOIN LATERAL (
        SELECT x.id, x.status, x.analyzed_at FROM water_body_analyses x
        WHERE x.water_body_id = wb.id AND x.analysis_type = 'standard' AND NOT x.is_synthetic
        ORDER BY x.analyzed_at DESC, x.created_at DESC LIMIT 1
    ) measured ON true
    GROUP BY wb.id, wb.gis_key, wb.name, latest.status, latest.is_synthetic, latest.id,
             measured.analyzed_at, measured.status, measured.id
    """,
]

_EXTRA_DOWN = [
    "DROP VIEW IF EXISTS water_body_analysis_status",
    *[f"DROP TRIGGER IF EXISTS trg_{t}_append_only ON {t}" for t in _APPEND_ONLY_TABLES],
    "DROP FUNCTION IF EXISTS aquasafe_append_only()",
    *[f"DROP TRIGGER IF EXISTS trg_{t}_updated_at ON {t}" for t in _UPDATED_AT_TABLES],
    "DROP FUNCTION IF EXISTS aquasafe_set_updated_at()",
]


def upgrade() -> None:
    op.create_table('rewards',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('name', sa.String(length=200), nullable=False),
    sa.Column('description', sa.Text(), nullable=True),
    sa.Column('cost_credits', sa.Integer(), nullable=False),
    sa.Column('is_active', sa.Boolean(), server_default='true', nullable=False),
    sa.Column('quantity_available', sa.Integer(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint('cost_credits > 0', name=op.f('ck_rewards_cost_positive')),
    sa.CheckConstraint('quantity_available IS NULL OR quantity_available >= 0', name=op.f('ck_rewards_quantity_non_negative')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_rewards'))
    )
    op.create_table('users',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('external_id', sa.String(length=255), nullable=False),
    sa.Column('display_name', sa.String(length=120), nullable=True),
    sa.Column('email', sa.String(length=320), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_users')),
    sa.UniqueConstraint('email', name=op.f('uq_users_email')),
    sa.UniqueConstraint('external_id', name=op.f('uq_users_external_id'))
    )
    op.create_table('water_bodies',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('gis_key', sa.String(length=255), nullable=False),
    sa.Column('name', sa.String(length=255), nullable=False),
    sa.Column('geometry', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('geometry_source', sa.String(length=20), server_default='none', nullable=False),
    sa.Column('osm_ref', sa.String(length=64), nullable=True),
    sa.Column('centroid_lat', sa.Float(), nullable=True),
    sa.Column('centroid_lon', sa.Float(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("geometry_source IN ('osm', 'approximate', 'none')", name=op.f('ck_water_bodies_geometry_source')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_water_bodies')),
    sa.UniqueConstraint('gis_key', name=op.f('uq_water_bodies_gis_key'))
    )
    op.create_table('field_submissions',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('user_id', sa.UUID(), nullable=False),
    sa.Column('water_body_id', sa.UUID(), nullable=True),
    sa.Column('image_key', sa.String(length=1024), nullable=False),
    sa.Column('image_sha256', sa.String(length=64), nullable=False),
    sa.Column('image_content_type', sa.String(length=100), nullable=True),
    sa.Column('image_size_bytes', sa.Integer(), nullable=True),
    sa.Column('gps_lat', sa.Float(), nullable=True),
    sa.Column('gps_lon', sa.Float(), nullable=True),
    sa.Column('gps_accuracy_m', sa.Float(), nullable=True),
    sa.Column('captured_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('uploaded_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('submission_status', sa.String(length=20), server_default='received', nullable=False),
    sa.Column('verification_status', sa.String(length=20), server_default='pending', nullable=False),
    sa.Column('verification_result', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('rejection_reason', sa.Text(), nullable=True),
    sa.Column('quality_score', sa.Float(), nullable=True),
    sa.Column('quality_details', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('duplicate_of_submission_id', sa.UUID(), nullable=True),
    sa.Column('duplicate_details', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("submission_status IN ('received', 'processing', 'accepted', 'rejected', 'withdrawn')", name=op.f('ck_field_submissions_submission_status')),
    sa.CheckConstraint("verification_status IN ('pending', 'passed', 'failed', 'needs_review')", name=op.f('ck_field_submissions_verification_status')),
    sa.CheckConstraint('duplicate_of_submission_id IS NULL OR duplicate_of_submission_id <> id', name=op.f('ck_field_submissions_not_self_duplicate')),
    sa.CheckConstraint('gps_lat IS NULL OR gps_lat BETWEEN -90 AND 90', name=op.f('ck_field_submissions_gps_lat_range')),
    sa.CheckConstraint('gps_lon IS NULL OR gps_lon BETWEEN -180 AND 180', name=op.f('ck_field_submissions_gps_lon_range')),
    sa.ForeignKeyConstraint(['duplicate_of_submission_id'], ['field_submissions.id'], name=op.f('fk_field_submissions_duplicate_of_submission_id_field_submissions'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_field_submissions_user_id_users'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['water_body_id'], ['water_bodies.id'], name=op.f('fk_field_submissions_water_body_id_water_bodies'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_field_submissions'))
    )
    op.create_index(op.f('ix_field_submissions_image_sha256'), 'field_submissions', ['image_sha256'], unique=False)
    op.create_index(op.f('ix_field_submissions_user_id'), 'field_submissions', ['user_id'], unique=False)
    op.create_index(op.f('ix_field_submissions_water_body_id'), 'field_submissions', ['water_body_id'], unique=False)
    op.create_table('reward_redemptions',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('user_id', sa.UUID(), nullable=False),
    sa.Column('reward_id', sa.UUID(), nullable=False),
    sa.Column('status', sa.String(length=20), server_default='pending', nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("status IN ('pending', 'fulfilled', 'cancelled')", name=op.f('ck_reward_redemptions_status')),
    sa.ForeignKeyConstraint(['reward_id'], ['rewards.id'], name=op.f('fk_reward_redemptions_reward_id_rewards'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_reward_redemptions_user_id_users'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_reward_redemptions'))
    )
    op.create_index(op.f('ix_reward_redemptions_user_id'), 'reward_redemptions', ['user_id'], unique=False)
    op.create_table('water_body_analyses',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('water_body_id', sa.UUID(), nullable=False),
    sa.Column('legacy_analysis_id', sa.String(length=255), nullable=False),
    sa.Column('analysis_type', sa.String(length=20), nullable=False),
    sa.Column('requested_date', sa.Date(), nullable=True),
    sa.Column('analyzed_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('status', sa.String(length=32), nullable=False),
    sa.Column('anomaly_score', sa.Integer(), nullable=True),
    sa.Column('anomaly_confidence', sa.Float(), nullable=True),
    sa.Column('deviation_sigma', sa.Float(), nullable=True),
    sa.Column('priority_score', sa.Integer(), nullable=True),
    sa.Column('ndwi', sa.Float(), nullable=True),
    sa.Column('ndti', sa.Float(), nullable=True),
    sa.Column('ndci', sa.Float(), nullable=True),
    sa.Column('engine', sa.String(length=64), nullable=False),
    sa.Column('is_synthetic', sa.Boolean(), nullable=False),
    sa.Column('request_lat', sa.Float(), nullable=True),
    sa.Column('request_lon', sa.Float(), nullable=True),
    sa.Column('scene_ref', sa.String(length=255), nullable=True),
    sa.Column('scene_date', sa.Date(), nullable=True),
    sa.Column('report_ref', sa.String(length=1024), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("analysis_type IN ('standard', 'stress_test')", name=op.f('ck_water_body_analyses_analysis_type')),
    sa.ForeignKeyConstraint(['water_body_id'], ['water_bodies.id'], name=op.f('fk_water_body_analyses_water_body_id_water_bodies'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_water_body_analyses'))
    )
    op.create_index('ix_water_body_analyses_body_time', 'water_body_analyses', ['water_body_id', 'analyzed_at'], unique=False)
    op.create_index(op.f('ix_water_body_analyses_legacy_analysis_id'), 'water_body_analyses', ['legacy_analysis_id'], unique=False)
    op.create_table('credit_transactions',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('user_id', sa.UUID(), nullable=False),
    sa.Column('amount', sa.Integer(), nullable=False),
    sa.Column('reason', sa.String(length=100), nullable=False),
    sa.Column('submission_id', sa.UUID(), nullable=True),
    sa.Column('redemption_id', sa.UUID(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint('NOT (submission_id IS NOT NULL AND redemption_id IS NOT NULL)', name=op.f('ck_credit_transactions_single_source')),
    sa.CheckConstraint('amount <> 0', name=op.f('ck_credit_transactions_amount_non_zero')),
    sa.ForeignKeyConstraint(['redemption_id'], ['reward_redemptions.id'], name=op.f('fk_credit_transactions_redemption_id_reward_redemptions'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['submission_id'], ['field_submissions.id'], name=op.f('fk_credit_transactions_submission_id_field_submissions'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_credit_transactions_user_id_users'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_credit_transactions'))
    )
    op.create_index(op.f('ix_credit_transactions_redemption_id'), 'credit_transactions', ['redemption_id'], unique=False)
    op.create_index(op.f('ix_credit_transactions_submission_id'), 'credit_transactions', ['submission_id'], unique=False)
    op.create_index('ix_credit_transactions_user_time', 'credit_transactions', ['user_id', 'created_at'], unique=False)

    for statement in _EXTRA_UP:
        op.execute(statement)


def downgrade() -> None:
    for statement in _EXTRA_DOWN:
        op.execute(statement)
    op.drop_index('ix_credit_transactions_user_time', table_name='credit_transactions')
    op.drop_index(op.f('ix_credit_transactions_submission_id'), table_name='credit_transactions')
    op.drop_index(op.f('ix_credit_transactions_redemption_id'), table_name='credit_transactions')
    op.drop_table('credit_transactions')
    op.drop_index(op.f('ix_water_body_analyses_legacy_analysis_id'), table_name='water_body_analyses')
    op.drop_index('ix_water_body_analyses_body_time', table_name='water_body_analyses')
    op.drop_table('water_body_analyses')
    op.drop_index(op.f('ix_reward_redemptions_user_id'), table_name='reward_redemptions')
    op.drop_table('reward_redemptions')
    op.drop_index(op.f('ix_field_submissions_water_body_id'), table_name='field_submissions')
    op.drop_index(op.f('ix_field_submissions_user_id'), table_name='field_submissions')
    op.drop_index(op.f('ix_field_submissions_image_sha256'), table_name='field_submissions')
    op.drop_table('field_submissions')
    op.drop_table('water_bodies')
    op.drop_table('users')
    op.drop_table('rewards')
