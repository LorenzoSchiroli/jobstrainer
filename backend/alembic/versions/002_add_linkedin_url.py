"""add linkedin_url to companies

Revision ID: 002
Revises: 001
Create Date: 2026-05-16
"""
from typing import Sequence, Union
import sqlalchemy as sa
from alembic import op

revision: str = "002"
down_revision: Union[str, None] = "001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("companies", sa.Column("linkedin_url", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("companies", "linkedin_url")
