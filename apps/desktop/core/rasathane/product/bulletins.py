"""Akıştaki haberlerden değişmez, kaynak bağlantılı yerel bülten oluşturur."""

from __future__ import annotations

import uuid
from typing import Any

from rasathane.product.news import _extract, _plain_text, speak_text, summarize_article
from rasathane.product.store import ProductStore, digest, json_text, now

MAX_ARTICLES = 20
MAX_ITEM_CHARS = 300
MAX_AUDIO_BYTES = 32 * 1024 * 1024
NOTICE = (
    "Bu bülten kayıtlı kaynak metinlerinden cümle seçilerek oluşturuldu. "
    "Tam metinler okunmadı; kaynakları açarak doğrulayın."
)


def create_bulletin(
    store: ProductStore,
    article_ids: list[str],
    title: str = "Akış bülteni",
    workspace_id: str | None = None,
) -> dict[str, Any]:
    if not 1 <= len(article_ids) <= MAX_ARTICLES:
        raise ValueError("Bülten için 1–20 haber seçin.")
    if len(set(article_ids)) != len(article_ids):
        raise ValueError("Aynı haber bir bültene iki kez eklenemez.")
    title = _plain_text(title).strip()
    if not title or len(title) > 120:
        raise ValueError("Bülten başlığı 1–120 karakter olmalı.")
    items: list[dict[str, Any]] = []
    for article_id in article_ids:
        result = summarize_article(store, article_id)
        metadata = store.rows(
            "SELECT a.published_at,f.name AS source_name FROM articles a "
            "LEFT JOIN feeds f ON f.id=a.source_id WHERE a.id=?",
            (article_id,),
        )[0]
        result["title"] = _extract(result["title"], "", 180)
        result["summary"] = _extract(result["summary"], result["title"], MAX_ITEM_CHARS)
        result["summary_chars"] = len(result["summary"])
        result["source_name"] = _plain_text(str(metadata["source_name"] or "Kayıtlı kaynak"))
        result["published_at"] = metadata["published_at"]
        items.append(result)
    paragraphs = [title, NOTICE]
    for number, item in enumerate(items, 1):
        paragraphs.append(
            f"{number}. {item['title']}\n{item['summary'] or item['notice']}\n"
            f"{item['source_name']} · {item['published_at'] or 'Yayın tarihi belirtilmemiş'}\n"
            f"{item['url']}\n{item['notice']}"
        )
    snapshot: dict[str, Any] = {
        "id": uuid.uuid4().hex,
        "title": title,
        "created_at": now(),
        "workspace_id": workspace_id,
        "items": items,
        "summary": "\n\n".join(paragraphs),
        "notice": NOTICE,
        "article_count": len(items),
        "ready_count": sum(item["status"] == "ready" for item in items),
        "method": "extractive",
    }
    snapshot["content_hash"] = digest(json_text(snapshot))
    return store.save_bulletin(snapshot)


def speak_bulletin(store: ProductStore, bulletin_id: str) -> bytes:
    """Kaynaklar sonradan değişse de ekranda açılan kayıtlı bülteni okur."""
    bulletin = store.get_bulletin(bulletin_id)
    paragraphs = [bulletin["title"], bulletin["notice"]]
    for number, item in enumerate(bulletin["items"], 1):
        paragraphs.append(f"{number}. {item['title']}. {item['summary'] or item['notice']}")
        if item["status"] == "ready" and item["text_scope"] == "managed_summary":
            paragraphs.append(item["notice"])
        elif "AI tarafından" in item["notice"]:
            paragraphs.append(item["notice"])
    return speak_text("\n\n".join(paragraphs), max_audio_bytes=MAX_AUDIO_BYTES)
