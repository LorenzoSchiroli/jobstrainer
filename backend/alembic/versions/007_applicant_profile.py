"""add applicant_profile table

Revision ID: 007
Revises: 006
Create Date: 2026-05-28
"""
from typing import Sequence, Union
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from alembic import op

revision: str = "007"
down_revision: Union[str, None] = "006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "applicant_profile",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("first_name", sa.Text(), nullable=True),
        sa.Column("last_name", sa.Text(), nullable=True),
        sa.Column("email", sa.Text(), nullable=True),
        sa.Column("phone", sa.Text(), nullable=True),
        sa.Column("city", sa.Text(), nullable=True),
        sa.Column("country", sa.Text(), nullable=True),
        sa.Column("work_auth", sa.Text(), nullable=True),
        sa.Column("urls", postgresql.JSONB(), nullable=True),
        sa.Column("extra_qa", postgresql.JSONB(), nullable=True),
        sa.Column("cv_text", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True),
                  server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", name="uq_applicant_profile_user_id"),
    )
    # Migrate existing cv_text from users
    op.execute("""
        INSERT INTO applicant_profile (user_id, cv_text, created_at, updated_at)
        SELECT id, cv_text, now(), now()
        FROM users
        WHERE cv_text IS NOT NULL
    """)
    op.drop_column("users", "cv_text")


def downgrade() -> None:
    op.add_column("users", sa.Column("cv_text", sa.Text(), nullable=True))
    op.execute("""
        UPDATE users u
        SET cv_text = ap.cv_text
        FROM applicant_profile ap
        WHERE ap.user_id = u.id
    """)
    op.drop_table("applicant_profile")
