"""Shared reading passages for imported exams."""

import sqlalchemy as sa
from alembic import op

revision = "c72a1483b921"
down_revision = "904d86bc2ccb"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "exam_materials",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "exam_id", sa.Integer(), sa.ForeignKey("exams.id", ondelete="RESTRICT"), nullable=False
        ),
        sa.Column("key", sa.String(60), nullable=False),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("source_pages", sa.JSON(), nullable=False),
        sa.UniqueConstraint("exam_id", "key"),
    )
    op.create_index("ix_exam_materials_exam_id", "exam_materials", ["exam_id"])
    op.create_table(
        "question_materials",
        sa.Column(
            "question_id",
            sa.Integer(),
            sa.ForeignKey("questions.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "material_id",
            sa.Integer(),
            sa.ForeignKey("exam_materials.id", ondelete="RESTRICT"),
            primary_key=True,
        ),
        sa.Column("position", sa.Integer(), nullable=False),
    )


def downgrade():
    op.drop_table("question_materials")
    op.drop_index("ix_exam_materials_exam_id", table_name="exam_materials")
    op.drop_table("exam_materials")
