"""Phase 33-ii: HuggingFace model release adapter tests."""

import json
from datetime import UTC, datetime

import pytest
from ingestion.huggingface_models import fetch_hf_models, parse_hf_response

# Phase 35-xiv: SAMPLE_RESPONSE artık gerçek HF API schema'sı (canlı call ile
# doğrulandı). Önceki versiyon `lastModified` kullanıyordu — bu field API
# response'unda yok, sadece `createdAt` var. Bug: adapter `it.get("lastModified")`
# döndürüyordu → cache'e `posted_at: null` yazılıyor → time-filter'da elenir
# → UI'da sosyal medya feed boş görünüyordu.
SAMPLE_RESPONSE = [
    {
        "_id": "abc123",
        "id": "deepseek-ai/DeepSeek-V3-Base",
        "modelId": "deepseek-ai/DeepSeek-V3-Base",
        "createdAt": "2026-05-19T11:42:00.000Z",
        "downloads": 12345,
        "likes": 100,
        "private": False,
        "tags": ["text-generation", "pytorch", "transformers"],
        "pipeline_tag": "text-generation",
        "library_name": "transformers",
    },
    {
        "_id": "def456",
        "id": "deepseek-ai/DeepSeek-V3-Chat",
        "modelId": "deepseek-ai/DeepSeek-V3-Chat",
        "createdAt": "2026-05-18T09:00:00.000Z",
        "downloads": 5678,
        "likes": 50,
        "private": False,
        "tags": ["conversational"],
        "pipeline_tag": "conversational",
    },
]


def test_parse_hf_response_normalizes_posts():
    posts = parse_hf_response(SAMPLE_RESPONSE, author="deepseek-ai")
    assert len(posts) == 2
    p = posts[0]
    assert p["title"] == "DeepSeek-V3-Base"
    assert p["url"] == "https://huggingface.co/deepseek-ai/DeepSeek-V3-Base"
    assert p["handle"] == "deepseek-ai"
    assert p["platform"] == "huggingface"
    assert set(p["tags"]) >= {"acik_kaynak_ai", "dunya_ai"}


def test_parse_hf_response_maps_created_at_to_posted_at():
    """Phase 35-xiv: HF API `createdAt` field → post `posted_at` mapping.

    Önceki adapter `lastModified` field'ını okuyordu ama API response'da
    bu field yok (canlı `huggingface.co/api/models` ile doğrulandı).
    Sonuç: tüm HF post'larının `posted_at` null kayıt ediliyordu, sosyal
    medya time filter'ında (Phase 35-xii) tamamı eleniyordu → UI'da
    hiç post yoktu. Bu test gerçek HF API schema'sına uyumu pin'ler.
    """
    posts = parse_hf_response(SAMPLE_RESPONSE, author="deepseek-ai")
    assert posts[0]["posted_at"] == "2026-05-19T11:42:00.000Z"
    assert posts[1]["posted_at"] == "2026-05-18T09:00:00.000Z"
    # Hiç null/empty kalmamalı
    assert all(p["posted_at"] for p in posts)


def test_parse_hf_response_falls_back_to_last_modified_when_no_created_at():
    """Defansif fallback: API ileride `lastModified` field eklerse desteklenir.

    Mevcut canlı HF API sadece `createdAt` dönüyor; ama versiyonlar arası
    schema değişikliği olasılığına karşı `or` chain kuruldu. createdAt
    yoksa lastModified denenmeli (legacy fallback).
    """
    legacy_response = [
        {
            "id": "old/legacy-model",
            "lastModified": "2024-01-15T00:00:00.000Z",
            # createdAt YOK
            "downloads": 100,
            "pipeline_tag": "text-generation",
        }
    ]
    posts = parse_hf_response(legacy_response, author="old")
    assert posts[0]["posted_at"] == "2024-01-15T00:00:00.000Z"


@pytest.mark.asyncio
async def test_fetch_hf_models_uses_cache(tmp_path, monkeypatch):
    cache_root = tmp_path / "cache"
    cache_root.mkdir()
    author = "deepseek-ai"
    cache_file = cache_root / f"hf_{author}.json"
    cache_file.write_text(
        json.dumps(
            {
                "fetched_at": datetime.now(UTC).isoformat(),
                "posts": [
                    {
                        "title": "cached-model",
                        "url": "https://x",
                        "handle": author,
                        "platform": "huggingface",
                        "posted_at": "2026-05-19T00:00:00+00:00",
                        "tags": ["acik_kaynak_ai", "dunya_ai"],
                        "safe": True,
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    async def fail_fetch(*_a, **_k):
        raise AssertionError("Cache fresh — fetch should not run")

    monkeypatch.setattr("ingestion.huggingface_models._http_get_json", fail_fetch)
    posts = await fetch_hf_models([author], cache_root=cache_root, cache_ttl_sec=3600)
    assert posts[0]["title"] == "cached-model"
