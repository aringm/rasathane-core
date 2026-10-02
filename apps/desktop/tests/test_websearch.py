from __future__ import annotations

from ytcore.intel.websearch import (
    AramaSonuc,
    FakeWebSearch,
    SerperSearch,
    websearch_al,
)


def test_fake_websearch(monkeypatch):
    monkeypatch.setenv("YT_WEBSEARCH_FIXTURE", "1")
    w = websearch_al()
    assert isinstance(w, FakeWebSearch)
    sonuc = w.ara("enflasyon 2025", n=3)
    assert sonuc and isinstance(sonuc[0], AramaSonuc)
    assert sonuc[0].url and sonuc[0].ozet


def test_fake_websearch_durumlu(monkeypatch):
    monkeypatch.setenv("YT_WEBSEARCH_FIXTURE", "1")
    w = websearch_al()
    sonuc, durum = w.ara_durumlu("enflasyon", 2)
    assert durum == "fixture"
    assert sonuc


def test_serper_anahtarsiz_inert(monkeypatch):
    monkeypatch.delenv("YT_WEBSEARCH_FIXTURE", raising=False)
    monkeypatch.delenv("SERPER_API_KEY", raising=False)
    w = websearch_al()
    assert isinstance(w, SerperSearch)
    sonuc, durum = w.ara_durumlu("enflasyon")
    assert sonuc == []  # anahtar yok → inert (egress fiilen yok)
    assert durum == "anahtar_yok"  # dürüst durum (sessiz başarı değil)


def test_serper_ara_anahtarsiz_bos(monkeypatch):
    monkeypatch.delenv("SERPER_API_KEY", raising=False)
    w = SerperSearch()
    assert w.ara("enflasyon") == []
