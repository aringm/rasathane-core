"""Shared test fixtures and fake helpers for the Rasathane test suite.

The fakes here replace SQLAlchemy ``Result``/``Session``/``session_factory``
at the module-attribute level (via ``monkeypatch.setattr``) so we can
exercise tool/route bodies without provisioning a real Postgres+pgvector
container. Real DB behaviour is covered by the integration suite in
``tests/test_repository.py``.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any
from unittest.mock import MagicMock


class FakeScalars:
    def __init__(self, items: list[Any]) -> None:
        self._items = items

    def all(self) -> list[Any]:
        return list(self._items)


class FakeResult:
    """Subset of SQLAlchemy ``Result`` we use across MCP tools and dashboard routes."""

    def __init__(
        self,
        *,
        scalars: list[Any] | None = None,
        rows: list[Any] | None = None,
        scalar_value: Any = None,
    ) -> None:
        self._scalars = scalars or []
        self._rows = rows or []
        self._scalar = scalar_value

    def scalars(self) -> FakeScalars:
        return FakeScalars(self._scalars)

    def all(self) -> list[Any]:
        return list(self._rows)

    def scalar_one(self) -> Any:
        return self._scalar

    def scalar_one_or_none(self) -> Any:
        return self._scalar


class FakeSession:
    def __init__(self, results: list[FakeResult]) -> None:
        self._results = list(results)
        self.executed_statements: list[Any] = []
        self.commits = 0

    async def execute(self, stmt: Any) -> FakeResult:
        self.executed_statements.append(stmt)
        if not self._results:
            raise AssertionError("FakeSession exhausted — under-mocked test")
        return self._results.pop(0)

    async def commit(self) -> None:
        self.commits += 1


class FakeSessionFactory:
    """Replacement for ``store.database.session_factory``."""

    def __init__(self, results: list[FakeResult]) -> None:
        self._session = FakeSession(results)
        self.entered = 0

    def __call__(self) -> FakeSessionFactory:
        return self

    async def __aenter__(self) -> FakeSession:
        self.entered += 1
        return self._session

    async def __aexit__(self, *args: object) -> None:
        return None


def make_fake_source(
    *,
    name: str = "Sample Source",
    category: str = "dunya_ai",
    type_: str = "rss",
    url: str = "https://example.com/feed",
    enabled: bool = True,
    is_user_disabled: bool = False,
    source_id: uuid.UUID | None = None,
) -> Any:
    s = MagicMock()
    s.id = source_id or uuid.uuid4()
    s.name = name
    s.category = category
    s.type = type_
    s.url = url
    s.enabled = enabled
    s.is_user_disabled = is_user_disabled
    s.fetch_interval_minutes = 60
    s.last_fetched_at = datetime(2026, 5, 6, 12, 0, 0, tzinfo=UTC)
    s.metadata_ = {"lang": "en"}
    return s


def make_fake_article(
    *,
    title: str = "Sample article",
    summary: str = "Short summary",
    url: str = "https://example.com/article",
    source: Any = None,
    has_embedding: bool = False,
) -> Any:
    a = MagicMock()
    a.url = url
    a.title = title
    a.summary = summary
    a.summary_tr_short = None
    a.summary_tr_long = None
    a.author = "anon"
    a.published_at = datetime(2026, 5, 6, 14, 0, 0, tzinfo=UTC)
    a.fetched_at = datetime(2026, 5, 6, 15, 0, 0, tzinfo=UTC)
    a.metadata_ = {"feed_url": url}
    a.embedding = [0.1] * 1024 if has_embedding else None
    a.source = source or make_fake_source()
    return a
