"""phase12iii library_items

Revision ID: ec405b1652ec
Revises: 48b7e827a42c
Create Date: 2026-05-07 10:35:19.653978

Polymorphic kütüphane tablosu. Bir kayıt ya bir makaleye (``article_id``)
ya da bir brief tarihine (``brief_date``) bağlanır — CheckConstraint XOR
garanti eder. ``snapshot_md`` kayıt anındaki içerik dondurulur (article
DB'den silinse bile kütüphane okunabilir kalır).

Partial unique index'ler PostgreSQL spesifik (rasathane zaten Postgres'e
bağımlı — pgvector). Aynı makale veya aynı tarihteki brief 2 kere
kaydedilemez (idempotent save).
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

# revision identifiers, used by Alembic.
revision: str = "ec405b1652ec"
down_revision: str | None = "48b7e827a42c"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "library_items",
        sa.Column(
            "id",
            UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("item_type", sa.String(16), nullable=False),
        sa.Column(
            "article_id",
            UUID(as_uuid=True),
            sa.ForeignKey("articles.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("brief_date", sa.Date, nullable=True),
        sa.Column("note", sa.Text, nullable=True),
        sa.Column("snapshot_md", sa.Text, nullable=False),
        sa.Column("snapshot_meta", JSONB, nullable=False),
        sa.Column(
            "saved_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "(item_type='article' AND article_id IS NOT NULL AND brief_date IS NULL) "
            "OR (item_type='brief' AND brief_date IS NOT NULL AND article_id IS NULL)",
            name="library_items_polymorphic",
        ),
    )
    op.create_index(
        "ux_library_article",
        "library_items",
        ["article_id"],
        unique=True,
        postgresql_where=sa.text("article_id IS NOT NULL"),
    )
    op.create_index(
        "ux_library_brief",
        "library_items",
        ["brief_date"],
        unique=True,
        postgresql_where=sa.text("brief_date IS NOT NULL"),
    )
    op.create_index("ix_library_saved_at", "library_items", ["saved_at"])


def downgrade() -> None:
    op.drop_index("ix_library_saved_at", table_name="library_items")
    op.drop_index("ux_library_brief", table_name="library_items")
    op.drop_index("ux_library_article", table_name="library_items")
    op.drop_table("library_items")
