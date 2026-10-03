from __future__ import annotations

import pytest
from ytcore.infra.index import FakeIndexStore, index_al
from ytcore.models import IndexKaydi


def _kayit(vid, baslik, kw):
    return IndexKaydi(
        video_url=f"https://youtu.be/{vid}",
        video_id=vid,
        baslik=baslik,
        anadil="tr",
        kanal="K",
        konu="hukuk",
        uretici_slug="k",
        video_slug=vid,
        analiz_tarihi="2026-06-08",
        keywords=kw,
    )


def test_fake_index_ekle_ara(monkeypatch):
    monkeypatch.setenv("YT_INDEX_FIXTURE", "1")
    s = index_al()
    assert isinstance(s, FakeIndexStore)
    s.ekle(
        _kayit("v1", "Sözleşme hukuku", ["sözleşme", "irade"]),
        "Sözleşme hukuku temeldir.",
        [1.0, 0.0],
    )
    s.ekle(
        _kayit("v2", "Tazminat hukuku", ["tazminat", "mahkeme"]),
        "Tazminat haksız fiilden doğar.",
        [0.0, 1.0],
    )
    assert s.belge_sayisi() == 2
    sonuc = s.ara("sözleşme", k=2)  # keyword + vektör hibrit
    assert any(r.video_id == "v1" for r in sonuc)


def test_fake_index_komsular_self_haric(monkeypatch):
    monkeypatch.setenv("YT_INDEX_FIXTURE", "1")
    s = index_al()
    s.ekle(_kayit("v1", "A", ["a"]), "A metni", [1.0, 0.0])
    # v1 zaten korpusta; komşular self-hariç → boş (degerleme self-hariç okur)
    benzerlikler = s.komsular([1.0, 0.0], k=5, haric_id="v1")
    assert benzerlikler == []


def test_fake_index_komsular_baska_belge(monkeypatch):
    monkeypatch.setenv("YT_INDEX_FIXTURE", "1")
    s = index_al()
    s.ekle(_kayit("v0", "A", ["a"]), "A metni", [1.0, 0.0])
    s.ekle(_kayit("v1", "B", ["b"]), "B metni", [1.0, 0.0])  # v0'a aynı vektör
    benz = s.komsular([1.0, 0.0], k=5, haric_id="v1")  # v0 görünür (self=v1 hariç)
    assert len(benz) == 1
    assert benz[0] > 0.99  # aynı yön → benzerlik ~1


def test_fake_index_terim_df(monkeypatch):
    monkeypatch.setenv("YT_INDEX_FIXTURE", "1")
    s = index_al()
    s.ekle(_kayit("v1", "A", ["sözleşme"]), "sözleşme hukuku", [1.0, 0.0])
    s.ekle(_kayit("v2", "B", ["sözleşme"]), "sözleşme tazminat", [0.0, 1.0])
    s.ekle(_kayit("v3", "C", ["tazminat"]), "tazminat hukuku", [0.5, 0.5])
    assert s.terim_df("sözleşme") == 2  # 2 belgede geçiyor
    assert s.terim_df("tazminat") == 2
    assert s.terim_df("yok") == 0


def test_fake_index_bos():
    s = FakeIndexStore()
    assert s.belge_sayisi() == 0
    assert s.ara("herhangi", k=5) == []
    assert s.komsular([1.0, 0.0], k=5, haric_id="x") == []


@pytest.mark.ollama  # LanceDB gerçek dosya I/O gerektirir → default koşuda atla
def test_lance_store_gercek(tmp_path, monkeypatch):
    monkeypatch.delenv("YT_INDEX_FIXTURE", raising=False)
    monkeypatch.setenv("YT_EMBED_FIXTURE", "1")  # embed fake (LanceDB gerçek)
    from ytcore.infra.embedding import embedding_al
    from ytcore.infra.index import LanceFtsRrfStore

    s = LanceFtsRrfStore(taban=tmp_path / "_index")
    e = embedding_al()
    s.ekle(
        _kayit("v1", "Sözleşme hukuku", ["sözleşme"]),
        "Sözleşme temeldir",
        e.embed(["Sözleşme temeldir"])[0],
    )
    assert s.belge_sayisi() == 1
    assert s.terim_df("sözleşme") >= 1
    sonuc = s.ara("sözleşme", k=2)
    assert any(r.video_id == "v1" for r in sonuc)
