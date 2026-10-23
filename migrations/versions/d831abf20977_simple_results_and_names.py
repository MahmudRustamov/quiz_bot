"""Add structured names and independent simple-result release state; retain history."""

import sqlalchemy as sa
from alembic import op

revision = "d831abf20977"
down_revision = "c72a1483b921"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("users", sa.Column("first_name", sa.String(75), nullable=True))
    op.add_column("users", sa.Column("last_name", sa.String(75), nullable=True))
    # Legacy display names remain unchanged; users explicitly confirm missing names.
    op.add_column("exams", sa.Column("subject", sa.String(200), nullable=True))
    op.add_column("exams", sa.Column("simple_release_policy", sa.String(20), nullable=True))
    op.add_column(
        "exams",
        sa.Column(
            "simple_results_released", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
    )
    op.add_column(
        "exams",
        sa.Column("answer_review_enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
    )
    op.add_column(
        "attempts", sa.Column("simple_released_at", sa.DateTime(timezone=True), nullable=True)
    )


def downgrade():
    op.drop_column("attempts", "simple_released_at")
    for column in (
        "answer_review_enabled",
        "simple_results_released",
        "simple_release_policy",
        "subject",
    ):
        op.drop_column("exams", column)
    op.drop_column("users", "last_name")
    op.drop_column("users", "first_name")
