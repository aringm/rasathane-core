"""phase12i summary_tr columns

Revision ID: 48b7e827a42c
Revises: b2f117c4a8e1
Create Date: 2026-05-07 02:18:20.742570

Adds Article.summary_tr_short / summary_tr_long. Both nullable so the
migration is safe on the existing ~3977 rows; ``pulse translate-pending``
backfills lazily.

FSEK iktibas sınırı (models.py:81): summary_tr_long oluşturulurken ~200
kelimeyi geçmemeli. Bu kural prompt template'lerinde uygulanır, kolon
sınırı serbest (Text).
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "48b7e827a42c"
down_revision: str | None = "b2f117c4a8e1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("articles", sa.Column("summary_tr_short", sa.Text(), nullable=True))
    op.add_column("articles", sa.Column("summary_tr_long", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("articles", "summary_tr_long")
    op.drop_column("articles", "summary_tr_short")
