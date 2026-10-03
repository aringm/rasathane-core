from __future__ import annotations

import wave

import pytest
from rasathane.product import news
from rasathane.product.store import ProductStore
from ytcore.uretim.tts import SesSonuc


@pytest.fixture
def store(tmp_path):
    return ProductStore(tmp_path)


def article(store, summary, **provenance):
    store.add_articles(
        None,
        [
            {
                "id": "haber",
                "url": "https://example.org/haber",
                "title": "Yeni haber",
                "summary": summary,
                "provenance": provenance,
            }
        ],
    )


def test_summary_uses_only_saved_text_and_preserves_source(store):
    article(store, "<p>Yönetmelik yayımlandı.</p><p>Başvuru süresi otuz gündür.</p>")
    result = news.summarize_article(store, "haber")
    assert result["summary"] == "Yönetmelik yayımlandı. Başvuru süresi otuz gündür."
    assert result["method"] == "extractive"
    assert result["url"] == "https://example.org/haber"
    assert len(result["source_hash"]) == 64
    assert "tam metin okunmadı" in result["notice"]
    assert store.list_articles()[0]["summary"].startswith("<p>")


def test_long_summary_is_bounded_without_new_claims(store):
    sentences = [f"Haberin {i} numaralı konusu için açıklama yapıldı." for i in range(100)]
    article(store, " ".join(sentences))
    result = news.summarize_article(store, "haber")
    assert len(result["summary"]) <= news.MAX_SUMMARY_CHARS
    for sentence in result["summary"].split(". "):
        assert sentence.rstrip(".") + "." in sentences


@pytest.mark.parametrize(
    "text,scope",
    [
        ("", "feed_excerpt"),
        ("Yeni haber", "feed_excerpt"),
        ("Daire: 1, karar: 4", "official_metadata"),
    ],
)
def test_metadata_and_missing_text_do_not_become_fabricated_summaries(store, text, scope):
    article(store, text, text_scope=scope)
    result = news.summarize_article(store, "haber")
    assert result["status"] == "unavailable"
    assert result["summary"] == ""
    with pytest.raises(ValueError, match="metni bulunmuyor"):
        news.speak_article(store, "haber")


def test_managed_ai_summary_keeps_origin_disclosure(store):
    article(
        store, "İtiraz kabul edildi.", text_scope="managed_summary", summary_kind="ai_generated"
    )
    result = news.summarize_article(store, "haber")
    assert "tam karar metni okunmadı" in result["notice"]
    assert "AI tarafından" in result["notice"]


def test_script_content_is_not_read_aloud(store):
    article(store, "<script>Kötü içerik</script><style>CSS</style><p>Gerçek &amp; kaynak.</p>")
    assert news.summarize_article(store, "haber")["summary"] == "Gerçek & kaynak."


def test_missing_article_and_sql_input_are_rejected(store):
    with pytest.raises(ValueError, match="Haber bulunamadı"):
        news.summarize_article(store, "' OR 1=1 --")


def test_speech_returns_valid_wav_and_cleans_temporary_file(store, monkeypatch):
    article(store, "Yönetmelik yayımlandı.")
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
    result = news.speak_article(store, "haber")
    assert result[:4] == b"RIFF"
    assert observed[0][0] == "Yönetmelik yayımlandı."
    assert not observed[0][1].exists()


@pytest.mark.parametrize(
    "status,data", [("ses_modeli_yok", b""), ("uretildi", b"invalid"), ("hata", b"")]
)
def test_speech_errors_are_truthful_and_unlock_next_attempt(store, monkeypatch, status, data):
    article(store, "Kaynak haberi.")

    def synthesize(self, text, path):
        path.write_bytes(data)
        return SesSonuc(status, "windows")

    monkeypatch.setattr(news.WindowsTTS, "seslendir", synthesize)
    for _ in range(2):
        with pytest.raises(ValueError):
            news.speak_article(store, "haber")
        assert not news._speech_lock.locked()


def test_concurrent_speech_is_bounded(store):
    article(store, "Kaynak haberi.")
    with news._speech_lock:
        with pytest.raises(ValueError, match="Bir sesli özet hazırlanıyor"):
            news.speak_article(store, "haber")
