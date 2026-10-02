from __future__ import annotations

from datetime import date, timedelta

from ytcore.infra.embedding import FakeEmbedding
from ytcore.infra.index import FakeIndexStore
from ytcore.intel.degerleme import bilgi_degeri
from ytcore.models import IndexKaydi


def _kayit(vid, tarih=None):
    return IndexKaydi(
        video_url=f"https://youtu.be/{vid}",
        video_id=vid,
        baslik="Sözleşme hukuku",
        anadil="tr",
        kanal="K",
        konu="hukuk",
        uretici_slug="k",
        video_slug=vid,
        analiz_tarihi="2026-06-08",
        yayin_tarihi=tarih,
        keywords=["sözleşme", "irade"],
    )


def test_degerleme_bos_korpus_soguk_baslangic():
    # İlk belge: korpus yok → novelty/niş nötr-yüksek + gerekçede "korpus yok".
    s = FakeIndexStore()
    embed = FakeEmbedding()
    puan, fakt = bilgi_degeri(_kayit("v1"), "Sözleşme hukuku temeldir.", embed, s)
    assert 0.0 <= puan <= 100.0
    assert fakt.novelty == 100.0  # korpus boş → en yüksek novelty
    assert fakt.rarity == 50.0  # korpus boş → nötr


def test_degerleme_novelty_ayirt_edici():
    # review (totoloji): 'novelty<100' alakasız belge için de geçer (yalnız korpus-dolu
    # sinyali). Ayırt-edicilik: BİREBİR-AYNI string (özdeşlik, cos=1.0), ALAKASIZ'dan KESİN
    # düşük novelty almalı. degerleme.py 1-max_benzerlik mantığı bozulsa (novelty=50 sabiti)
    # KIRMIZI döner — Faz 2 pk_self dersi. NOT: FakeEmbedding (SHA256-hash) string-yakınlığı
    # semantiğe TAŞIMAZ → bu yalnız özdeşlik-vakası; DERECE-bazlı novelty kalibrasyonu (cos~0.7
    # ara-benzerlik) bge-m3 + held-out TR korpus bekler (değişmez #3).
    s = FakeIndexStore()
    embed = FakeEmbedding()
    s.ekle(_kayit("v0"), "Sözleşme hukuku temeldir.", embed.embed(["Sözleşme hukuku temeldir."])[0])
    _, benzer = bilgi_degeri(_kayit("v1"), "Sözleşme hukuku temeldir.", embed, s)
    _, alakasiz = bilgi_degeri(_kayit("v2"), "Tamamen başka bir konu uzay roket.", embed, s)
    assert benzer.novelty is not None and alakasiz.novelty is not None
    assert benzer.novelty < alakasiz.novelty  # benzerlik sinyali (totoloji DEĞİL)
    assert benzer.novelty < 100.0  # korpusta neredeyse-aynı var → düşük


def test_degerleme_recency_eski_dusuk():
    s = FakeIndexStore()
    embed = FakeEmbedding()
    eski = (date.today() - timedelta(days=180)).isoformat()  # 2 yarı-ömür
    _, fakt = bilgi_degeri(_kayit("v1", tarih=eski), "metin", embed, s)
    assert fakt.recency is not None and fakt.recency < 30.0  # 0.5^2=0.25 → 25


def test_degerleme_recency_tarih_yok_none():
    s = FakeIndexStore()
    _, fakt = bilgi_degeri(_kayit("v1", tarih=None), "metin", FakeEmbedding(), s)
    assert fakt.recency is None  # tarih yok → None (sahte skor değil), puan nötr-50 ile sürer


def test_degerleme_agirlikli_toplam_0_100():
    s = FakeIndexStore()
    puan, fakt = bilgi_degeri(_kayit("v1"), "metin", FakeEmbedding(), s)
    for v in (fakt.novelty, fakt.rarity, fakt.nis, fakt.recency, fakt.length):
        assert v is None or 0.0 <= v <= 100.0
    assert 0.0 <= puan <= 100.0


def test_degerleme_bos_govde():
    s = FakeIndexStore()
    puan, fakt = bilgi_degeri(_kayit("v1"), "", FakeEmbedding(), s)
    assert fakt.length == 0.0
    assert 0.0 <= puan <= 100.0


def test_degerleme_ozel_agirlik_clamp():
    # review LOW: ağırlık toplamı!=1 / eksik anahtar → puan 0-100 clamp, KeyError yok.
    s = FakeIndexStore()
    # novelty=100 (soğuk-başlangıç) * 2.0 = 200 → clamp 100. 'eksik' anahtar deger'de yok → 0.
    puan, _ = bilgi_degeri(
        _kayit("v1"), "metin", FakeEmbedding(), s, agirliklar={"novelty": 2.0, "eksik": 1.0}
    )
    assert 0.0 <= puan <= 100.0
    assert puan == 100.0  # 2.0*100 clamp + 1.0*0(eksik) = 100
