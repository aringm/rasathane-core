from __future__ import annotations

import wave

import httpx
import pytest
from rasathane.product import api, bulletins, news
from rasathane.product.service import ProductService
from rasathane.product.store import ProductStore, digest, json_text
from ytcore.uretim.tts import SesSonuc
from ytmcp.server import gui_http_app


@pytest.fixture
def store(tmp_path):
    store = ProductStore(tmp_path)
    store.add_articles(
        None,
        [
            {
                "id": "haber",
                "url": "https://example.org/haber",
                "title": "Yönetmelik yayımlandı",
                "summary": "Başvuru süresi otuz gündür. Yetkili merci açıklama yaptı.",
                "published_at": "2026-10-03T09:00:00Z",
                "provenance": {"text_scope": "feed_excerpt"},
            },
            {
                "id": "karar",
                "url": "https://example.org/karar",
                "title": "Karar listesi",
                "summary": "Karar: 10, Daire: 1",
                "provenance": {"text_scope": "official_metadata"},
            },
        ],
    )
    return store


def test_bulletin_snapshot_preserves_sources_scope_and_export_after_source_changes(store):
    result = bulletins.create_bulletin(store, ["haber", "karar"])
    assert result["article_count"] == 2 and result["ready_count"] == 1
    assert (
        result["items"][0]["summary"] == "Başvuru süresi otuz gündür. Yetkili merci açıklama yaptı."
    )
    assert result["items"][0]["published_at"] == "2026-10-03T09:00:00Z"
    assert result["items"][1]["status"] == "unavailable"
    assert "Karar: 10" not in result["summary"]
    assert "https://example.org/haber" in result["summary"]
    assert result["content_hash"] == digest(
        json_text({k: v for k, v in result.items() if k != "content_hash"})
    )
    with store.connection() as conn:
        conn.execute("UPDATE articles SET summary='Değişen haber' WHERE id='haber'")
    assert ProductStore(store.directory).get_bulletin(result["id"]) == result
    exported = store.export()
    saved_document = next(row for row in exported["documents"] if row["kind"] == "bulletin")
    assert saved_document["provenance"]["bulletin"] == result
    assert any(row["kind"] == "bulletin" for row in store.search("başvuru"))
    assert store.list_bulletins()[0]["article_count"] == 2


@pytest.mark.parametrize("ids", [[], ["haber"] * 21, ["haber", "haber"], ["haber", "olmayan"]])
def test_invalid_selection_is_atomic(store, ids):
    with pytest.raises(ValueError):
        bulletins.create_bulletin(store, ids)
    assert store.list_bulletins() == []


def test_retired_workspace_argument_does_not_save_bulletin(store):
    with pytest.raises(TypeError):
        bulletins.create_bulletin(store, ["haber"], workspace_id="olmayan")
    assert store.list_bulletins() == []


def test_long_items_remain_bounded_and_source_based(store):
    with store.connection() as conn:
        conn.execute(
            "UPDATE articles SET title=?,summary=? WHERE id='haber'",
            ("Başlık " * 80, "Kaynak cümlesi burada. " * 200),
        )
    result = bulletins.create_bulletin(store, ["haber"])
    assert len(result["items"][0]["summary"]) <= 300
    assert len(result["items"][0]["title"]) <= 180
    assert result["items"][0]["source_chars"] > 300


def test_bulletin_speech_reads_saved_summary_and_keeps_missing_text_notice(store, monkeypatch):
    result = bulletins.create_bulletin(store, ["haber", "karar"])
    observed = []

    def synthesize(self, text, path):
        observed.append((text, path))
        with wave.open(str(path), "wb") as output:
            output.setnchannels(1)
            output.setsampwidth(2)
            output.setframerate(22050)
            output.writeframes(b"\x01\x00" * 100)
        return SesSonuc("uretildi", "windows")

    monkeypatch.setattr(news.WindowsTTS, "seslendir", synthesize)
    with store.connection() as conn:
        conn.execute("UPDATE articles SET summary='Değişen haber' WHERE id='haber'")
    assert bulletins.speak_bulletin(store, result["id"])[:4] == b"RIFF"
    assert "Başvuru süresi otuz gündür." in observed[0][0]
    assert "Değişen haber" not in observed[0][0]
    assert "özetlenebilecek haber metni bulunmuyor" in observed[0][0]
    assert not observed[0][1].exists()


async def test_bulletin_create_restore_export_and_audio_api(store, monkeypatch):
    monkeypatch.setattr(api, "_service", ProductService(store, autostart=False))
    monkeypatch.delenv("RASATHANE_SESSION_TOKEN", raising=False)
    monkeypatch.setattr(bulletins, "speak_text", lambda text, **kwargs: b"RIFFfixture")
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=gui_http_app()),
        base_url="http://localhost",
        headers={"Origin": "rasathane://app"},
    ) as client:
        path = "/api/rasathane/bulletins"
        for body in (
            {"article_ids": []},
            {"article_ids": ["haber"] * 21},
            {"article_ids": ["haber"], "text": "arbitrary"},
        ):
            assert (await client.post(path, json=body)).status_code == 422
        created = await client.post(
            path, json={"article_ids": ["haber", "karar"], "title": "Günlük bülten"}
        )
        assert created.status_code == 201
        item = created.json()
        assert (await client.get(path)).json()["items"][0]["id"] == item["id"]
        assert (await client.get(path + "/" + item["id"])).json() == item
        assert (await client.get(path + "/olmayan")).status_code == 404
        audio = await client.post(path + "/" + item["id"] + "/speech", json={})
        assert audio.status_code == 200 and audio.content == b"RIFFfixture"
        assert audio.headers["cache-control"] == "no-store"
        assert audio.headers["content-type"] == "audio/wav"
        exported = (await client.get("/api/rasathane/export")).json()
        assert exported["documents"][-1]["provenance"]["bulletin"]["id"] == item["id"]
