"""Akıştaki haberlerden değişmez, kaynak bağlantılı yerel bülten oluşturur."""

from __future__ import annotations

import uuid
from copy import deepcopy
from typing import Any

from rasathane.product.news import (
    _extract,
    _plain_text,
    looks_turkish,
    speak_text,
    summarize_article,
)
from rasathane.product.store import ProductStore, digest, json_text, now

MAX_ARTICLES = 20
MAX_ITEM_CHARS = 300
MAX_AUDIO_BYTES = 32 * 1024 * 1024
NOTICE = (
    "Bu bülten kayıtlı kaynak metinlerinden cümle seçilerek oluşturuldu. "
    "Tam metinler okunmadı; kaynakları açarak doğrulayın."
)


def present_bulletin(store: ProductStore, bulletin_id: str) -> dict[str, Any]:
    """Eski yabancı/teknik özetleri gösterim için yeniler; kayıtlı tarihçeyi değiştirmez."""
    saved = store.get_bulletin(bulletin_id)
    projected = deepcopy(saved)
    changed = False
    for item in projected["items"]:
        summary = str(item.get("summary") or "")
        if (not summary and item.get("status") not in {"pending", "not_prepared"}) or (
            summary and looks_turkish(summary) and "Article URL:" not in summary
        ):
            continue
        try:
            current = summarize_article(store, item["article_id"])
        except ValueError:
            current = {
                "summary": "",
                "status": "unavailable",
                "method": "pending",
                "notice": "Türkçe özet bulunmuyor. Kaynak kaydını açarak doğrulayın.",
            }
        for key in (
            "summary",
            "status",
            "method",
            "notice",
            "title",
            "url",
            "text_scope",
            "source_hash",
            "source_excerpt",
            "evidence_quote",
            "job_id",
        ):
            if key in current:
                if projected.get("agenda") and key in {
                    "evidence_quote",
                    "source_excerpt",
                    "source_hash",
                }:
                    item["summary_" + key] = current[key]
                    continue
                item[key] = current[key]
        item["summary"] = _extract(item["summary"], item["title"], MAX_ITEM_CHARS)
        item["summary_chars"] = len(item["summary"])
        changed = True
    if not changed:
        return saved
    methods = {i["method"] for i in projected["items"] if i["status"] == "ready"}
    summary_method = "mixed" if len(methods) > 1 else next(iter(methods), "pending")
    if projected.get("agenda"):
        projected["summary_method"] = summary_method
    else:
        projected["method"] = summary_method
    projected["notice"] = (
        "Bu görünüm kayıtlı bültenin Türkçe haber özetlerini gösterir. "
        "Hazırlanmayan özetler açıkça belirtilir; kaynakları açarak doğrulayın."
    )
    projected["ready_count"] = sum(i["status"] == "ready" for i in projected["items"])
    projected["summary"] = "\n\n".join(
        [projected["title"], projected["notice"]]
        + [f"{i['title']}\n{i['summary'] or i['notice']}\n{i['url']}" for i in projected["items"]]
    )
    projected["source_content_hash"] = saved["content_hash"]
    projected["content_hash"] = digest(
        json_text({k: v for k, v in projected.items() if k != "content_hash"})
    )
    return projected


def create_bulletin(
    store: ProductStore,
    article_ids: list[str],
    title: str = "Akış bülteni",
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
    methods = {item["method"] for item in items if item["status"] == "ready"}
    method = "mixed" if len(methods) > 1 else next(iter(methods), "extractive")
    notice = (
        NOTICE
        if method == "extractive"
        else (
            "Bu bülten Türkçe haber özetlerinden oluşturuldu. Modelle hazırlanan özetler "
            "ve kayıtlı metinden alınan özetler her haberin yönteminde ayrıca belirtilir. "
            "Kaynakları açarak doğrulayın."
        )
    )
    paragraphs[1] = notice
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
        "items": items,
        "summary": "\n\n".join(paragraphs),
        "notice": notice,
        "article_count": len(items),
        "ready_count": sum(item["status"] == "ready" for item in items),
        "method": method,
    }
    snapshot["content_hash"] = digest(json_text(snapshot))
    return store.save_bulletin(snapshot)


def speak_bulletin(store: ProductStore, bulletin_id: str) -> bytes:
    """Kaynaklar sonradan değişse de ekranda açılan kayıtlı bülteni okur."""
    bulletin = present_bulletin(store, bulletin_id)
    paragraphs = [bulletin["title"], bulletin["notice"]]
    for number, item in enumerate(bulletin["items"], 1):
        paragraphs.append(f"{number}. {item['title']}. {item['summary'] or item['notice']}")
        if bulletin.get("agenda"):
            paragraphs.append(
                f"İlgi nedeni: {item['relevance_reason']}. "
                f"Proje etkisi: {item['project_impact']}. Öneri: {item['suggested_action']}."
            )
        if item["status"] == "ready" and item["text_scope"] == "managed_summary":
            paragraphs.append(item["notice"])
        elif "AI tarafından" in item["notice"] or item["method"] == "local_model":
            paragraphs.append(item["notice"])
    return speak_text("\n\n".join(paragraphs), max_audio_bytes=MAX_AUDIO_BYTES)
