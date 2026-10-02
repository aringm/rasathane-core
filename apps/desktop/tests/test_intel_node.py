from __future__ import annotations

import pytest
from ytcore.intel.node import degerleme_node, factcheck_node, kisisel_node

# Faz 3 node'ları için ortak state (içerik var → node'lar gerçek çağrı yapar).
_STATE = {
    "metadata": {
        "video_url": "u",
        "video_id": "v",
        "baslik": "b",
        "anadil": "tr",
        "kanal": "k",
        "konu": "h",
        "uretici_slug": "u",
        "video_slug": "v",
        "analiz_tarihi": "2026-06-08",
    },
    "keywords": ["sözleşme"],
    "ozet": {"detay": "Sözleşme hukuku temeldir.", "kisa": "x", "orta": "y"},
}


def test_degerleme_node_icerik_yok():
    s = degerleme_node({})
    assert s["degerleme_puani"] is None
    assert s["govde_index"] == ""


def test_kisisel_node_icerik_yok():
    s = kisisel_node({})
    assert s["kisisel_durum"] == "icerik_yok"


def test_factcheck_node_icerik_yok():
    s = factcheck_node({})
    assert s["factcheck_durum"] == "icerik_yok"


def test_degerleme_node_govde_ozetten(monkeypatch):
    monkeypatch.setenv("YT_INDEX_FIXTURE", "1")
    monkeypatch.setenv("YT_EMBED_FIXTURE", "1")
    state = {
        "metadata": {
            "video_url": "u",
            "video_id": "v",
            "baslik": "b",
            "anadil": "tr",
            "kanal": "k",
            "konu": "h",
            "uretici_slug": "u",
            "video_slug": "v",
            "analiz_tarihi": "2026-06-08",
        },
        "keywords": ["sözleşme"],
        "ozet": {"detay": "Sözleşme hukuku temeldir.", "kisa": "x", "orta": "y"},
    }
    s = degerleme_node(state)  # type: ignore[arg-type]
    assert s["degerleme_puani"] is not None
    assert s["govde_index"] == "Sözleşme hukuku temeldir."


# --- Hata yolları (review MED: graceful 'hata' + KOD_HATALARI re-raise testsizdi) ---


def test_degerleme_node_model_hata_graceful(monkeypatch):
    # bilgi_degeri RuntimeError (embed/index ham hata) → graceful: puan None, çökme yok.
    import ytcore.intel.node as nd

    def _patla(*a, **k):
        raise RuntimeError("ollama down")

    monkeypatch.setattr(nd, "bilgi_degeri", _patla)
    s = degerleme_node(_STATE)  # type: ignore[arg-type]
    assert s["degerleme_puani"] is None  # graceful (çökme yok)
    # Kök-neden YÜZEYDE (review tur-2 MED): 'hata' durumu + degerleme_hata; icerik_yok'tan ayrı.
    assert s["degerleme_durum"] == "hata"
    assert s["degerleme_hata"]


def test_degerleme_node_icerik_yok_durum():
    # govde boş → 'icerik_yok' (model 'hata'sından AYRI — ikisi de puan=None ama durum farklı).
    s = degerleme_node({})
    assert s["degerleme_puani"] is None
    assert s["degerleme_durum"] == "icerik_yok"


def test_degerleme_node_kod_bug_reraise(monkeypatch):
    # KeyError (kod-bug) → re-raise (maskeleme YOK — Faz 1/2 dersi).
    import ytcore.intel.node as nd

    def _bug(*a, **k):
        raise KeyError("şema değişti")

    monkeypatch.setattr(nd, "bilgi_degeri", _bug)
    with pytest.raises(KeyError):
        degerleme_node(_STATE)  # type: ignore[arg-type]


def test_kisisel_node_model_hata_graceful(monkeypatch):
    import ytcore.intel.node as nd

    def _patla(*a, **k):
        raise RuntimeError("ollama down")

    monkeypatch.setattr(nd, "kisisel_analiz", _patla)
    s = kisisel_node(_STATE)  # type: ignore[arg-type]
    assert s["kisisel_durum"] == "hata"
    assert s["kisisel_hata"]  # kök-neden yüzeyde (Faz 1/2 deseni)


def test_kisisel_node_kod_bug_reraise(monkeypatch):
    import ytcore.intel.node as nd

    def _bug(*a, **k):
        raise AttributeError("kontrat ihlali")

    monkeypatch.setattr(nd, "kisisel_analiz", _bug)
    with pytest.raises(AttributeError):
        kisisel_node(_STATE)  # type: ignore[arg-type]


def test_factcheck_node_model_hata_graceful(monkeypatch):
    import ytcore.intel.node as nd

    def _patla(*a, **k):
        raise RuntimeError("ollama down")

    monkeypatch.setattr(nd, "fact_check", _patla)
    s = factcheck_node(_STATE)  # type: ignore[arg-type]
    assert s["factcheck_durum"] == "hata"
    assert s["factcheck_hata"]


def test_factcheck_node_kod_bug_reraise(monkeypatch):
    import ytcore.intel.node as nd

    def _bug(*a, **k):
        raise TypeError("tip hatası")

    monkeypatch.setattr(nd, "fact_check", _bug)
    with pytest.raises(TypeError):
        factcheck_node(_STATE)  # type: ignore[arg-type]


def test_kisisel_node_model_bos(monkeypatch):
    # İçerik VAR ama model boş döndü → 'model_bos' (icerik_yok DEĞİL — review MED).
    import ytcore.intel.node as nd

    def _bos(*a, **k):
        return "", "model_bos"

    monkeypatch.setattr(nd, "kisisel_analiz", _bos)
    s = kisisel_node(_STATE)  # type: ignore[arg-type]
    assert s["kisisel_durum"] == "model_bos"


# --- Faz 5 Mod B arming + cloud sayaç (denetim HIGH: hermetik testte hiç koşmuyordu) ---


def test_factcheck_node_mod_b_arming_ve_sayac(monkeypatch):
    # hedef=cloud + opt-in (YT_CLOUD_VERDICT=1) + anahtar → CloudClient KURULUR ve gerçek
    # çağrı sayaçları state'e AKTARILIR. Bu yol hiçbir hermetik testte koşmuyordu (guard/sayaç
    # silinse 423 yeşil kalırdı). FakeCloud ile hermetik (HTTP yok). Mutasyon-kontrol.
    import ytcore.intel.node as nd
    import ytcore.router.cloud_client as cc

    monkeypatch.setenv("YT_CLOUD_VERDICT", "1")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")

    class _FakeCloud:
        def __init__(self, *a, **k):
            self.cagri_sayisi = 3
            self.toplam_girdi_token = 120
            self.toplam_cikti_token = 45

    monkeypatch.setattr(cc, "CloudClient", _FakeCloud)
    monkeypatch.setattr(nd, "fact_check", lambda *a, **k: ([], "uretildi"))
    state = {**_STATE, "hedef": "cloud", "cloud_cagrisi_sayisi": 0}
    out = nd.factcheck_node(state)  # type: ignore[arg-type]
    assert out["cloud_cagrisi_sayisi"] == 3  # gerçek çağrı sayacı aktarıldı
    assert out["cloud_girdi_token"] == 120 and out["cloud_cikti_token"] == 45


def test_factcheck_node_hedef_local_cloud_armanmaz(monkeypatch):
    # Kontrast/mutasyon: hedef=local iken CloudClient KURULMAMALI (arming koşulu sıkı kalmalı)
    # → cloud sayaç alanı çıktıda YOK. Arming gevşerse (örn. hedef kontrolü düşerse) KIRMIZI.
    import ytcore.intel.node as nd
    import ytcore.router.cloud_client as cc

    monkeypatch.setenv("YT_CLOUD_VERDICT", "1")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")

    def _patla(*a, **k):
        raise AssertionError("hedef=local iken CloudClient KURULMAMALI (Mod B arming)")

    monkeypatch.setattr(cc, "CloudClient", _patla)
    monkeypatch.setattr(nd, "fact_check", lambda *a, **k: ([], "web_yok"))
    state = {**_STATE, "hedef": "local", "cloud_cagrisi_sayisi": 0}
    out = nd.factcheck_node(state)  # type: ignore[arg-type]
    assert "cloud_cagrisi_sayisi" not in out  # cloud kurulmadı → sayaç aktarımı yok
