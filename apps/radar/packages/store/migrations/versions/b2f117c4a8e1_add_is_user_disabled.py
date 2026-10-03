"""add Source.is_user_disabled override flag

Revision ID: b2f117c4a8e1
Revises: d41c05dba5af
Create Date: 2026-05-07 12:00:00.000000

The dashboard's enable/disable toggle writes to this column rather than
mutating feeds.yaml. Effective enabled state is ``enabled AND NOT
is_user_disabled``. Default ``false`` so existing rows behave the same
post-migration as pre-migration.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "b2f117c4a8e1"
down_revision: str | None = "d41c05dba5af"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "sources",
        sa.Column(
            "is_user_disabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )


def downgrade() -> None:
    op.drop_column("sources", "is_user_disabled")
