from __future__ import annotations

from ytcore.models import DegerlemeFaktorleri, IndexKaydi
from ytcore.output.sunum_yaz import _ts, _typ_kaynak


def _kayit() -> IndexKaydi:
    return IndexKaydi(
        video_url="https://youtu.be/x",
        video_id="x",
        baslik="MY trillion $Dollar Project!",  # $ → Typst math tuzağı (kod-string'de literal)
        anadil="en",
        kanal="PewDiePie",
        konu="teknoloji",
        uretici_slug="p",
        video_slug="x",
        analiz_tarihi="2026-06-10",
        sure_sn=1026,
        degerleme_puani=75.1,
    )


def test_ts_typst_string_kacis():
    assert _ts('a"b\\c') == 'a\\"b\\\\c'  # tırnak + ters-bölü kaçışlı
    assert _ts("a\nb") == "a\\nb"  # newline → \n (Typst string tek-satır)


def test_typ_kaynak_tum_bolumler_ve_dolar_literal():
    k = _kayit()
    fakt = DegerlemeFaktorleri(novelty=100.0, rarity=50.0, nis=50.0, recency=92.6, length=74.2)
    src = _typ_kaynak(
        k, {"kisa": "k", "orta": "o", "detay": "d1\n\nd2"}, 0.70, "kişisel metin", 75.1, fakt
    )
    for bolum in ("TL;DR", "Özet", "Detaylı Özet", "Kişisel Analiz", "Değerleme", "BilgiDeğeri"):
        assert bolum in src
    # $ içeren başlık KOD-MODU string'inde (#let v_baslik = "...$...") → Typst math tetiklemez.
    assert '#let v_baslik = "MY trillion $Dollar Project!"' in src
    # faktör tablosu satırları (5 faktör)
    for ad in ("Novelty", "Rarity", "Niş", "Recency", "Length"):
        assert ad in src


def test_typ_kaynak_kisisel_bos_placeholder():
    k = _kayit()
    src = _typ_kaynak(k, {"kisa": "k", "detay": "d"}, None, "", None, DegerlemeFaktorleri())
    assert "kişisel analiz üretilmedi" in src  # boş kişisel → görünür placeholder


def test_generic_web_export_brand_source_url_and_full_signature(tmp_path):
    from docx import Document
    from ytcore.content.dokum import DokumBolum
    from ytcore.output.dokum_yaz import dokum_yaz
    from ytcore.output.klasor import analiz_klasoru_yaz

    record = _kayit().model_copy(
        update={
            "baslik": "Resmî düzenleme",
            "kaynak_turu": "web",
            "kaynak_url": "https://www.resmigazete.gov.tr/",
            "kaynak_sahibi": "Resmî Gazete",
        }
    )
    source = _typ_kaynak(
        record, {"kisa": "Özet", "detay": "Düzenleme"}, None, "Analiz", None, DegerlemeFaktorleri()
    )
    assert "RASATHANE · KAYNAK ANALİZİ" in source
    assert "youtube" not in source.casefold() and record.video_url not in source
    assert '#let v_url = "https://www.resmigazete.gov.tr/"' in source
    assert '#let v_kanal = "Resmî Gazete"' in source
    assert "Av. Mehmet Arın Gülüm" in source
    folder = analiz_klasoru_yaz(record, tmp_path)
    dokum_yaz(folder, record, [DokumBolum(None, "Düzenleme", "Kaynak metni", [])], pdf=False)
    texts = [(folder / name).read_text(encoding="utf-8") for name in ("00_kapak.md", "03_dokum.md")]
    texts.append(
        "\n".join(paragraph.text for paragraph in Document(folder / "03_dokum.docx").paragraphs)
    )
    for text in texts:
        assert "Rasathane" in text and "Av. Mehmet Arın Gülüm" in text
        assert "youtube" not in text.casefold()
