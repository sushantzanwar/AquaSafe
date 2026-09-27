"""Verified field contributions: rejection code, perceptual hash, once-only credit awards.

Adds to field_submissions:
  * reason_code      machine-readable outcome (VERIFIED, NO_GPS, TOO_OLD, ALREADY_ANALYZED, ...)
  * perceptual_hash  64-bit dHash (stored signed) for near-duplicate detection
And to credit_transactions:
  * unique(submission_id)   a submission can be credited at most once (spend rows have NULL submission_id)
  * amount > 0 for submission-sourced rows (a submission can only ever earn credits)

Existing rows are untouched.

Revision ID: 0002
Revises: 0001
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0002"
down_revision: Union[str, Sequence[str], None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("field_submissions", sa.Column("reason_code", sa.String(length=32), nullable=True))
    op.add_column("field_submissions", sa.Column("perceptual_hash", sa.BigInteger(), nullable=True))
    op.create_index(op.f("ix_field_submissions_perceptual_hash"), "field_submissions", ["perceptual_hash"])
    op.create_unique_constraint(op.f("uq_credit_transactions_submission_id"), "credit_transactions", ["submission_id"])
    op.create_check_constraint(
        op.f("ck_credit_transactions_submission_earns"), "credit_transactions", "submission_id IS NULL OR amount > 0"
    )


def downgrade() -> None:
    op.drop_constraint(op.f("ck_credit_transactions_submission_earns"), "credit_transactions", type_="check")
    op.drop_constraint(op.f("uq_credit_transactions_submission_id"), "credit_transactions", type_="unique")
    op.drop_index(op.f("ix_field_submissions_perceptual_hash"), table_name="field_submissions")
    op.drop_column("field_submissions", "perceptual_hash")
    op.drop_column("field_submissions", "reason_code")
