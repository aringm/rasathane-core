"""Phase 32-ii: find_pending_title_tr + set_article_title_tr testleri.

Mock-based — real DB değil. Pure logic + filter behavior.
"""

from __future__ import annotations

import uuid
from typing import Any
from unittest.mock import MagicMock

import pytest

# ── set_article_title_tr — flag_modified pattern ─────────────────────────


@pytest.mark.asyncio
async def test_set_article_title_tr_writes_to_metadata_json(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """metadata.title_tr alanını yazar + flag_modified çağırır."""
    from store.repository import set_article_title_tr

    article_id = uuid.uuid4()
    fake_article = MagicMock()
    fake_article.id = article_id
    fake_article.metadata_ = {"existing_key": "value"}

    fake_result = MagicMock()
    fake_result.scalar_one_or_none.return_value = fake_article

    fake_session = MagicMock()

    async def fake_execute(*_args, **_kwargs):
        return fake_result

    fake_session.execute = fake_execute

    flag_modified_calls: list[tuple[Any, str]] = []

    def fake_flag(obj, attr):
        flag_modified_calls.append((obj, attr))

    monkeypatch.setattr("sqlalchemy.orm.attributes.flag_modified", fake_flag)

    await set_article_title_tr(fake_session, article_id, "Türkçe başlık")

    # Metadata güncellendi (existing key korundu + title_tr eklendi)
    assert fake_article.metadata_ == {"existing_key": "value", "title_tr": "Türkçe başlık"}
    # flag_modified çağrıldı
    assert len(flag_modified_calls) == 1
    assert flag_modified_calls[0][1] == "metadata_"


@pytest.mark.asyncio
async def test_set_article_title_tr_creates_metadata_if_none() -> None:
    """metadata_ None ise boş dict oluşturup title_tr ekler."""
    from store.repository import set_article_title_tr

    article_id = uuid.uuid4()
    fake_article = MagicMock()
    fake_article.id = article_id
    fake_article.metadata_ = None

    fake_result = MagicMock()
    fake_result.scalar_one_or_none.return_value = fake_article

    fake_session = MagicMock()

    async def fake_execute(*_args, **_kwargs):
        return fake_result

    fake_session.execute = fake_execute

    await set_article_title_tr(fake_session, article_id, "Yeni başlık")

    assert fake_article.metadata_ == {"title_tr": "Yeni başlık"}


@pytest.mark.asyncio
async def test_set_article_title_tr_raises_for_unknown_id() -> None:
    """Bilinmeyen article_id → LookupError."""
    from store.repository import set_article_title_tr

    fake_result = MagicMock()
    fake_result.scalar_one_or_none.return_value = None

    fake_session = MagicMock()

    async def fake_execute(*_args, **_kwargs):
        return fake_result

    fake_session.execute = fake_execute

    with pytest.raises(LookupError, match=r"article .* not found"):
        await set_article_title_tr(fake_session, uuid.uuid4(), "x")


# ── find_pending_title_tr — Python-side filter ───────────────────────────


@pytest.mark.asyncio
async def test_find_pending_title_tr_filters_tr_sources() -> None:
    """Source lang=tr olan makaleler skip — zaten Türkçe."""
    from store.repository import find_pending_title_tr

    en_article = MagicMock()
    en_article.metadata_ = {}  # title_tr yok
    en_article.source = MagicMock()
    en_article.source.metadata_ = {"lang": "en"}

    tr_article = MagicMock()
    tr_article.metadata_ = {}
    tr_article.source = MagicMock()
    tr_article.source.metadata_ = {"lang": "tr"}

    no_lang = MagicMock()
    no_lang.metadata_ = {}
    no_lang.source = MagicMock()
    no_lang.source.metadata_ = {}  # lang belirtilmemiş → EN sayılır

    fake_scalars = MagicMock()
    fake_scalars.all.return_value = [en_article, tr_article, no_lang]
    fake_result = MagicMock()
    fake_result.scalars.return_value = fake_scalars

    fake_session = MagicMock()

    async def fake_execute(*_args, **_kwargs):
        return fake_result

    fake_session.execute = fake_execute

    out = await find_pending_title_tr(fake_session, limit=10)

    # tr_article filtrelendi, en + no_lang döndü
    assert len(out) == 2
    assert tr_article not in out


@pytest.mark.asyncio
async def test_find_pending_title_tr_filters_existing_title_tr() -> None:
    """metadata.title_tr varsa o article skip — idempotent."""
    from store.repository import find_pending_title_tr

    already_translated = MagicMock()
    already_translated.metadata_ = {"title_tr": "Zaten çevrilmiş"}
    already_translated.source = MagicMock()
    already_translated.source.metadata_ = {"lang": "en"}

    pending = MagicMock()
    pending.metadata_ = {}
    pending.source = MagicMock()
    pending.source.metadata_ = {"lang": "en"}

    fake_scalars = MagicMock()
    fake_scalars.all.return_value = [already_translated, pending]
    fake_result = MagicMock()
    fake_result.scalars.return_value = fake_scalars

    fake_session = MagicMock()

    async def fake_execute(*_args, **_kwargs):
        return fake_result

    fake_session.execute = fake_execute

    out = await find_pending_title_tr(fake_session, limit=10)
    assert len(out) == 1
    assert out[0] is pending


@pytest.mark.asyncio
async def test_find_pending_title_tr_respects_limit() -> None:
    """Limit'i aşan article filter sonrası kesilir."""
    from store.repository import find_pending_title_tr

    articles = []
    for _ in range(20):
        a = MagicMock()
        a.metadata_ = {}
        a.source = MagicMock()
        a.source.metadata_ = {"lang": "en"}
        articles.append(a)

    fake_scalars = MagicMock()
    fake_scalars.all.return_value = articles
    fake_result = MagicMock()
    fake_result.scalars.return_value = fake_scalars

    fake_session = MagicMock()

    async def fake_execute(*_args, **_kwargs):
        return fake_result

    fake_session.execute = fake_execute

    out = await find_pending_title_tr(fake_session, limit=5)
    assert len(out) == 5  # Limit respected
