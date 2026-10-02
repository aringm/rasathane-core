from __future__ import annotations

from ytcore.transcript.metadata import info_to_index

INFO = {
    "id": "dQw4w9WgXcQ",
    "title": "Türkçe Hukuk Söyleşisi",
    "uploader": "Hukuk Kanalı",
    "channel": "Hukuk Kanalı",
    "upload_date": "20260115",
    "duration": 642,
    "webpage_url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
    "language": "tr",
}


def test_temel_alanlar():
    k = info_to_index(INFO, konu="hukuk", analiz_tarihi="2026-06-07")
    assert k.video_id == "dQw4w9WgXcQ"
    assert k.baslik == "Türkçe Hukuk Söyleşisi"
    assert k.kanal == "Hukuk Kanalı"
    assert k.sure_sn == 642
    assert k.konu == "hukuk"
    assert k.faz0_stub is False


def test_tarih_formatlanir():
    k = info_to_index(INFO, konu="x", analiz_tarihi="2026-06-07")
    assert k.yayin_tarihi == "2026-01-15"  # YYYYMMDD -> YYYY-MM-DD


def test_slug_turkce_karaktersiz():
    k = info_to_index(INFO, konu="hukuk", analiz_tarihi="2026-06-07")
    assert k.uretici_slug == "hukuk-kanali"  # ç/ı/ö... ASCII
    assert all(ord(c) < 128 for c in k.video_slug)


def test_eksik_alanlar_none_guvenli():
    k = info_to_index({"id": "x", "title": "T"}, konu="g", analiz_tarihi="2026-06-07")
    assert k.sure_sn is None and k.yayin_tarihi is None
    assert isinstance(k.kanal, str)


def test_anadil_yoksa_bos_string():
    k = info_to_index({"id": "x", "title": "T"}, konu="g", analiz_tarihi="2026-06-07")
    assert isinstance(k.anadil, str)  # bilinmiyorsa "" (ISO yok)


def test_gecersiz_tarih_none():
    k = info_to_index({"id": "x", "title": "T", "upload_date": "2026"}, "g", "2026-06-07")
    assert k.yayin_tarihi is None


def test_sayisal_olmayan_duration_cokmez():
    # Re-review R1: yt-dlp canlı/kısıtlı videoda duration='NA' → int('NA') ValueError
    # ATMAMAL I (başarılı transkripti 'hata' yapardı). None'a düşer.
    for d in ("NA", "", "bilinmiyor", None):
        k = info_to_index({"id": "x", "title": "T", "duration": d}, "g", "2026-06-07")
        assert k.sure_sn is None


def test_url_video_id_benzersiz_fallback():
    # Re-review R5: id çıkmayan farklı URL'ler AYNI klasöre düşüp birbirini EZMESİN.
    from ytcore.transcript.metadata import url_video_id

    assert url_video_id("https://youtu.be/dQw4w9WgXcQ") == "dQw4w9WgXcQ"
    assert url_video_id("???") != url_video_id("////")  # farklı junk → farklı id


def test_url_video_id_none_cokmez():
    # Re-review LOW: url_video_id(None) AttributeError ATMAMALI (iç tutarlılık).
    from ytcore.transcript.metadata import url_video_id

    assert url_video_id(None)  # type: ignore[arg-type]


def test_non_str_baslik_kanal_cokmez():
    # Re-review LOW: yt-dlp anomali (non-str title/channel) slugify'ı çökertmemeli.
    k = info_to_index({"id": "x", "title": 12345, "channel": 999}, "g", "2026-06-07")
    assert isinstance(k.baslik, str) and isinstance(k.uretici_slug, str)
    assert k.baslik == "12345"
