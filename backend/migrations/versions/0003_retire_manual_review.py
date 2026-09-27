"""Retire manual review: verification is fully automatic.

Any submission left in the old needs_review state can never be resolved by a person now, so it is
closed as REJECTED (UNABLE_TO_VERIFY). No credits were ever awarded for these rows, and a rejected
submission does not block the contributor from submitting the photo again.

Revision ID: 0003
Revises: 0002
"""
from typing import Sequence, Union

from alembic import op

revision: str = "0003"
down_revision: Union[str, Sequence[str], None] = "0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        UPDATE field_submissions
        SET submission_status = 'rejected',
            verification_status = 'failed',
            reason_code = 'UNABLE_TO_VERIFY',
            rejection_reason = 'Manual review has been retired; this submission could not be verified automatically. Please submit the photo again.'
        WHERE verification_status = 'needs_review'
        """
    )


def downgrade() -> None:
    pass  # the previous state cannot be reconstructed, and nothing depends on it
