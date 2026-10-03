"""SQLAlchemy 2.0 models for Rasathane.

Telif compliance: Article.summary is capped at ~200 words; full article
text is never stored. This keeps the system on the right side of FSEK
(Turkish copyright law) limits on derivative works.
"""

from __future__ import annotations

import uuid
from datetime import date as date_type
from datetime import datetime
from typing import Any

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from store.database import Base

EMBEDDING_DIM = 1024  # bge-m3 native dimension


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    name: Mapped[str | None] = mapped_column(String(255))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Source(Base):
    __tablename__ = "sources"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(255))
    # turk_hukuku, dunya_ai, turkiye_ai, legaltech, muhakeme_stack
    category: Mapped[str] = mapped_column(String(64), index=True)
    # rss, twitter, reddit, youtube, github, arxiv, scraper
    type: Mapped[str] = mapped_column(String(32))
    url: Mapped[str] = mapped_column(String(2048))
    # ``enabled`` reflects feeds.yaml (base config); ``is_user_disabled`` is
    # the dashboard's runtime override. Effective state = enabled AND NOT
    # is_user_disabled. Splitting them keeps feeds.yaml git-friendly while
    # letting users mute a source without editing the YAML.
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    is_user_disabled: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    fetch_interval_minutes: Mapped[int] = mapped_column(Integer, default=60)
    last_fetched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    metadata_: Mapped[dict[str, Any]] = mapped_column("metadata", JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    articles: Mapped[list[Article]] = relationship(back_populates="source")


class Article(Base):
    __tablename__ = "articles"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    source_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("sources.id"), index=True
    )
    url: Mapped[str] = mapped_column(String(2048))
    url_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)  # sha256
    title: Mapped[str] = mapped_column(String(1024))
    # FSEK iktibas sınırı: max ~200 kelime, asla tam metin.
    summary: Mapped[str | None] = mapped_column(Text)
    # Phase 12-i: Türkçe kısa özet (sync-time) — gemini ile üretilir, ~110 kelime
    summary_tr_short: Mapped[str | None] = mapped_column(Text)
    # Phase 12-iii: Uzun analiz (on-click) — gemini ile üretilir,
    # FSEK iktibas sınırı: max ~200 kelime
    summary_tr_long: Mapped[str | None] = mapped_column(Text)
    author: Mapped[str | None] = mapped_column(String(255))
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    embedding: Mapped[list[float] | None] = mapped_column(Vector(EMBEDDING_DIM))
    importance_score: Mapped[float | None] = mapped_column(Float)
    cluster_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("clusters.id"), index=True
    )
    metadata_: Mapped[dict[str, Any]] = mapped_column("metadata", JSON, default=dict)

    source: Mapped[Source] = relationship(back_populates="articles")
    cluster: Mapped[Cluster | None] = relationship(back_populates="articles")


class Cluster(Base):
    __tablename__ = "clusters"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    brief_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("briefs.id"), index=True
    )
    label: Mapped[str] = mapped_column(String(255))
    summary: Mapped[str] = mapped_column(Text)
    importance_score: Mapped[float] = mapped_column(Float)
    centroid_embedding: Mapped[list[float] | None] = mapped_column(Vector(EMBEDDING_DIM))

    brief: Mapped[Brief] = relationship(back_populates="clusters")
    articles: Mapped[list[Article]] = relationship(back_populates="cluster")


class Brief(Base):
    __tablename__ = "briefs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    date: Mapped[date_type] = mapped_column(Date, index=True)
    # all, turk_hukuku, dunya_ai, turkiye_ai, legaltech, muhakeme_stack
    category: Mapped[str] = mapped_column(String(64))
    title: Mapped[str] = mapped_column(String(255))
    markdown_path: Mapped[str | None] = mapped_column(String(512))
    audio_path: Mapped[str | None] = mapped_column(String(512))
    mindmap_path: Mapped[str | None] = mapped_column(String(512))
    article_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    clusters: Mapped[list[Cluster]] = relationship(back_populates="brief")
    assets: Mapped[list[Asset]] = relationship(back_populates="brief")


class Asset(Base):
    __tablename__ = "assets"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    brief_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("briefs.id"), index=True
    )
    kind: Mapped[str] = mapped_column(String(32))  # markdown, audio, mindmap, image
    path: Mapped[str] = mapped_column(String(512))
    size_bytes: Mapped[int] = mapped_column(Integer)
    mime_type: Mapped[str] = mapped_column(String(128))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    brief: Mapped[Brief | None] = relationship(back_populates="assets")


class LibraryItem(Base):
    """Phase 12-iii: kullanıcının kaydettiği makale/brief'ler.

    Polymorphic: article_id veya brief_date doldurulur (CheckConstraint XOR).
    snapshot_md/snapshot_meta kayıt anındaki içeriği dondurur — article
    DB'den silinse bile kütüphane okunabilir kalır.
    """

    __tablename__ = "library_items"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    # "article" | "brief" | "deep_analysis"
    item_type: Mapped[str] = mapped_column(String(16))
    article_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("articles.id", ondelete="SET NULL"),
        nullable=True,
    )
    brief_date: Mapped[date_type | None] = mapped_column(Date, nullable=True)
    # Phase 17-v: deep_analyze job_id (16-hex string)
    deep_analysis_job_id: Mapped[str | None] = mapped_column(String(16), nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Kayıt anındaki içerik dondurulur (article silinse bile okunabilir)
    snapshot_md: Mapped[str] = mapped_column(Text)
    snapshot_meta: Mapped[dict[str, Any]] = mapped_column(JSON)
    saved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    article: Mapped[Article | None] = relationship()
