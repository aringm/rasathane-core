from __future__ import annotations

import pytest
from ytcore.infra.index import FakeIndexStore, LanceFtsRrfStore
from ytcore.models import IndexKaydi

# Gerçek LanceDB + SQLite FTS5 (dosya I/O, ağsız/torch'suz/Ollama'sız → default suite'te koşar;
# review MED: üretim retrieval/komsular/terim_df yolu yalnız fixture'da değil GERÇEK store'da test).


def _kayit(vid, kw=None):
    return IndexKaydi(
        video_url=f"https://youtu.be/{vid}",
        video_id=vid,
        baslik="Test",
        anadil="tr",
        kanal="K",
        konu="hukuk",
        uretici_slug="k",
        video_slug=vid,
        analiz_tarihi="2026-06-08",
        keywords=kw or [],
    )


def test_lance_komsular_kosinus_olcegi(tmp_path):
    # Aynı yön → kosinüs ~1; dik → ~0 (LanceDB cosine metric + 1-_distance).
    s = LanceFtsRrfStore(taban=tmp_path / "_idx")
    s.ekle(_kayit("v0"), "metin", [1.0, 0.0, 0.0])
    ayni = s.komsular([1.0, 0.0, 0.0], k=5, haric_id="q")
    assert ayni and ayni[0] > 0.99
    s2 = LanceFtsRrfStore(taban=tmp_path / "_idx2")
    s2.ekle(_kayit("v0"), "metin", [1.0, 0.0, 0.0])
    dik = s2.komsular([0.0, 1.0, 0.0], k=5, haric_id="q")
    assert dik and abs(dik[0]) < 0.01


def test_lance_boyut_kilidi_net_hata(tmp_path):
    # review HIGH: boyut uyuşmazlığı SESSİZ değil NET ValueError (fake-embed→gerçek-index tuzağı).
    s = LanceFtsRrfStore(taban=tmp_path / "_idx")
    s.ekle(_kayit("v0"), "metin", [1.0, 0.0])  # tablo 2-dim'e kilitlenir
    with pytest.raises(ValueError, match="boyut"):
        s.ekle(_kayit("v1"), "metin", [1.0, 0.0, 0.0])  # 3-dim → net hata


def test_iki_store_kosinus_esdeger(tmp_path):
    # review HIGH: FakeIndexStore (kosinüs) ve LanceFtsRrfStore (cosine metric) AYNI ölçek
    # → aynı içerik aynı novelty/niş (üretim ≠ fixture sapması yok).
    vek_a = [0.6, 0.8]  # norm 1
    sorgu = [1.0, 0.0]  # kosinüs(vek_a, sorgu) = 0.6
    fake = FakeIndexStore()
    fake.ekle(_kayit("v0"), "metin", vek_a)
    lance = LanceFtsRrfStore(taban=tmp_path / "_idx")
    lance.ekle(_kayit("v0"), "metin", vek_a)
    f = fake.komsular(sorgu, k=1, haric_id="q")[0]
    lc = lance.komsular(sorgu, k=1, haric_id="q")[0]
    assert abs(f - 0.6) < 0.02  # Fake gerçekten kosinüs
    assert abs(f - lc) < 0.05  # iki store yakın kosinüs (ölçek tutarlı)


def test_lance_terim_df_token_eslesme(tmp_path):
    # review MED: terim_df TOKEN eşleşmesi (FTS5) — substring değil; iki store tutarlı.
    s = LanceFtsRrfStore(taban=tmp_path / "_idx")
    s.ekle(_kayit("v0", ["sözleşme"]), "sözleşme hukuku temeldir", [1.0, 0.0])
    assert s.terim_df("sözleşme") == 1
    assert s.terim_df("hukuku") == 1
    assert s.terim_df("yok") == 0
    # FakeIndexStore ile AYNI token semantiği (substring değil)
    fake = FakeIndexStore()
    fake.ekle(_kayit("v0", ["sözleşme"]), "sözleşme hukuku temeldir", [1.0, 0.0])
    assert fake.terim_df("huk") == 0  # 'hukuku' içinde substring ama TOKEN değil → 0
    assert fake.terim_df("hukuku") == 1


def test_terim_df_bigram_iki_store_esdeger(tmp_path):
    # review HIGH (token-fix bigram regresyonu): YAKE n=2 BIGRAM keyword ('sözleşme hukuku').
    # FakeIndexStore phrase-match (ardışık token) ile LanceFtsRrfStore FTS5 phrase MATCH AYNI df
    # vermeli → eval(Fake) ≠ üretim(Lance) rarity sapması olmasın.
    govde = "sözleşme hukuku temel ilkedir"
    kw = ["sözleşme hukuku"]  # bigram
    fake = FakeIndexStore()
    fake.ekle(_kayit("v0", kw), govde, [1.0, 0.0])
    lance = LanceFtsRrfStore(taban=tmp_path / "_idx")
    lance.ekle(_kayit("v0", kw), govde, [1.0, 0.0])
    assert fake.terim_df("sözleşme hukuku") == 1  # bigram ardışık → bulunur (eski .split() 0)
    assert lance.terim_df("sözleşme hukuku") == 1
    assert fake.terim_df("sözleşme hukuku") == lance.terim_df("sözleşme hukuku")
    # ardışık-olmayan bigram → bulunmaz (her iki store)
    assert fake.terim_df("hukuku sözleşme") == 0
    assert lance.terim_df("hukuku sözleşme") == 0


def test_terim_df_noktalama_iki_store_esdeger(tmp_path):
    # review HIGH: noktalama sınırı (virgül) — FTS5 unicode61 böler; Fake \w+ ile hizalı.
    govde = "sözleşme, hukuku."  # virgüllü
    fake = FakeIndexStore()
    fake.ekle(_kayit("v0"), govde, [1.0, 0.0])
    lance = LanceFtsRrfStore(taban=tmp_path / "_idx")
    lance.ekle(_kayit("v0"), govde, [1.0, 0.0])
    assert fake.terim_df("sözleşme") == 1  # virgüle rağmen token bulunur (eski .split() 0)
    assert lance.terim_df("sözleşme") == 1
    assert fake.terim_df("sözleşme") == lance.terim_df("sözleşme")


def test_terim_df_turkce_I_case_iki_store_esdeger(tmp_path):
    # review tur-3 MED: Türkçe İ/I büyük-harf + diakritik — FakeIndexStore (_fold: NFD+combining
    # sök) ile LanceFtsRrfStore (FTS5 unicode61 remove_diacritics 2) AYNI df (rarity tutarlı).
    govde = "İSTANBUL Büyükşehir Belediyesi kararı"  # büyük İ + ş/ü
    fake = FakeIndexStore()
    fake.ekle(_kayit("v0"), govde, [1.0, 0.0])
    lance = LanceFtsRrfStore(taban=tmp_path / "_idx")
    lance.ekle(_kayit("v0"), govde, [1.0, 0.0])
    for terim in ["istanbul", "İstanbul", "büyükşehir", "BÜYÜKŞEHİR", "belediyesi"]:
        assert fake.terim_df(terim) == lance.terim_df(terim), f"{terim!r} df sapması"
        assert fake.terim_df(terim) == 1  # hepsi case-fold ile bulunmalı


def test_terim_df_compat_char_iki_store_esdeger(tmp_path):
    # review tur-4 MED: NFD (NFKD DEĞİL) → compatibility-char (ﬁ ligature) GENİŞLEMEZ; FTS5
    # remove_diacritics 2 de genişletmez → iki store tutarlı (NFKD 'ﬁ'→'fi' yapıp saptırırdı).
    govde = "ﬁnans raporu yayınlandı"  # ﬁ = U+FB01 ligature
    fake = FakeIndexStore()
    fake.ekle(_kayit("v0"), govde, [1.0, 0.0])
    lance = LanceFtsRrfStore(taban=tmp_path / "_idx")
    lance.ekle(_kayit("v0"), govde, [1.0, 0.0])
    # 'finans' (genişletilmiş) İKİ store'da da AYNI sonucu vermeli (NFD ile ikisi de eşleşmez).
    assert fake.terim_df("finans") == lance.terim_df("finans")
    assert fake.terim_df("raporu") == lance.terim_df("raporu") == 1


def test_lance_reupdate_fts_fail_desync_olmaz(tmp_path, monkeypatch):
    # review MED (re-update desync): mevcut video_id güncellenirken FTS yazımı patlarsa
    # belge_sayisi() ↔ terim_df desync OLMAMALI; eski kayıt TAM korunmalı (snapshot rollback).
    s = LanceFtsRrfStore(taban=tmp_path / "_idx")
    s.ekle(_kayit("v0", ["eski"]), "eski sürüm metin", [1.0, 0.0])
    assert s.belge_sayisi() == 1

    def _patlak():
        raise RuntimeError("FTS açılamadı")

    monkeypatch.setattr(s, "_fts", _patlak)  # re-update sırasında FTS yazımı patlar
    with pytest.raises(RuntimeError):
        s.ekle(_kayit("v0", ["yeni"]), "yeni sürüm metin", [0.0, 1.0])
    monkeypatch.undo()  # gerçek _fts geri (assert için)
    # Desync YOK: eski kayıt TAM korundu (yarım/boş değil), belge_sayisi↔terim_df tutarlı.
    assert s.belge_sayisi() == 1  # Lance: eski v0 snapshot'tan geri yüklendi
    assert s.terim_df("eski") == 1  # FTS: commit edilmemiş DELETE otomatik geri alındı
    assert s.terim_df("yeni") == 0  # yeni hiç girmedi


def test_lance_ara_rezerve_kelime_patlamaz(tmp_path):
    # review LOW: FTS5 rezerve kelime (AND/OR) içeren sorgu keyword kolunu patlatmaz.
    # ara() sorguyu embedding_al() (conftest FakeEmbedding 64-dim) ile embed eder → tablo da
    # FakeEmbedding vektörüyle kurulmalı (boyut uyumu).
    from ytcore.infra.embedding import embedding_al

    e = embedding_al()
    s = LanceFtsRrfStore(taban=tmp_path / "_idx")
    s.ekle(_kayit("v0", ["hukuk"]), "hukuk ve dava süreci", e.embed(["hukuk ve dava süreci"])[0])
    sonuc = s.ara("hukuk AND dava", k=5)  # 'AND' rezerve — tırnaklanmazsa syntax error
    assert any(r.video_id == "v0" for r in sonuc)


def test_lance_ara_generic_kaynak_url_metadata_korur(tmp_path):
    from ytcore.infra.embedding import embedding_al

    kayit = _kayit("github:openai/openai-python", ["python"]).model_copy(
        update={
            "video_url": "https://github.com/openai/openai-python",
            "kaynak_turu": "github",
            "kaynak_url": "https://github.com/openai/openai-python",
            "kaynak_id": "openai/openai-python",
            "kaynak_sahibi": "openai",
        }
    )
    e = embedding_al()
    s = LanceFtsRrfStore(taban=tmp_path / "_idx")
    s.ekle(kayit, "Python istemci repository", e.embed(["Python istemci repository"])[0])

    sonuc = s.ara("Python istemci", k=5)

    assert sonuc
    assert sonuc[0].kaynak_turu == "github"
    assert sonuc[0].kaynak_url == "https://github.com/openai/openai-python"
