"""add embedding to jobs

Revision ID: 010
Revises: 009
Create Date: 2026-07-05
"""
from typing import Sequence, Union
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from alembic import op

revision: str = "010"
down_revision: Union[str, None] = "009"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("jobs", sa.Column("embedding", postgresql.ARRAY(sa.Float()), nullable=True))


def downgrade() -> None:
    op.drop_column("jobs", "embedding")
