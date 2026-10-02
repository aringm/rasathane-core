"""phase17v deep_analysis library type

Revision ID: d8a2f15c7e91
Revises: ec405b1652ec
Create Date: 2026-05-07

LibraryItem polymorphic'ı 3. tip ile genişletir: ``deep_analysis``.
Yeni kolon ``deep_analysis_job_id`` (16-hex string, deep_analyze
job_id'siyle aynı) — partial unique index aynı job'un iki kere
kaydedilmemesini garanti eder. CheckConstraint XOR 3 dallı:
article_id XOR brief_date XOR deep_analysis_job_id.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "d8a2f15c7e91"
down_revision: str | None = "ec405b1652ec"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 1. Yeni kolon
    op.add_column(
        "library_items",
        sa.Column("deep_analysis_job_id", sa.String(16), nullable=True),
    )

    # 2. Eski 2-dal CheckConstraint'i drop edip 3-dal yenisini ekle
    op.drop_constraint("library_items_polymorphic", "library_items", type_="check")
    op.create_check_constraint(
        "library_items_polymorphic",
        "library_items",
        "(item_type='article' AND article_id IS NOT NULL AND brief_date IS NULL "
        "    AND deep_analysis_job_id IS NULL) "
        "OR (item_type='brief' AND brief_date IS NOT NULL AND article_id IS NULL "
        "    AND deep_analysis_job_id IS NULL) "
        "OR (item_type='deep_analysis' AND deep_analysis_job_id IS NOT NULL "
        "    AND article_id IS NULL AND brief_date IS NULL)",
    )

    # 3. Partial unique index — aynı deep job 2x kaydedilemez
    op.create_index(
        "ux_library_deep_analysis",
        "library_items",
        ["deep_analysis_job_id"],
        unique=True,
        postgresql_where=sa.text("deep_analysis_job_id IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("ux_library_deep_analysis", table_name="library_items")
    op.drop_constraint("library_items_polymorphic", "library_items", type_="check")
    op.create_check_constraint(
        "library_items_polymorphic",
        "library_items",
        "(item_type='article' AND article_id IS NOT NULL AND brief_date IS NULL) "
        "OR (item_type='brief' AND brief_date IS NOT NULL AND article_id IS NULL)",
    )
    op.drop_column("library_items", "deep_analysis_job_id")
