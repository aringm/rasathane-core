from __future__ import annotations

import json

from ytcore.models import AnalizGirdi, IndexKaydi


def test_index_kaydi_roundtrip():
    k = IndexKaydi(
        video_url="https://youtu.be/x",
        video_id="x",
        baslik="Test",
        anadil="tr",
        kanal="Kanal",
        konu="hukuk",
        uretici_slug="kanal",
        video_slug="test",
        analiz_tarihi="2026-06-07",
        keywords=["a", "b"],
        faz0_stub=True,
        sema_versiyonu=1,
    )
    d = json.loads(k.model_dump_json())
    assert d["faz0_stub"] is True
    assert d["degerleme_puani"] is None
    assert IndexKaydi.model_validate(d).video_id == "x"


def test_analiz_girdi_url_required():
    g = AnalizGirdi(url="https://youtu.be/x")
    assert g.url.startswith("https")


def test_analiz_girdi_asr_izin_default_false():
    assert AnalizGirdi(url="x").asr_izin is False


def test_transkript_sonuc_alanlari():
    from ytcore.models import TranskriptSonuc

    t = TranskriptSonuc(metin="abc", durum="altyazi", kaynak_dil="tr", segment_sayisi=2)
    assert t.metin == "abc" and t.durum == "altyazi" and t.asr_tier is None


def test_analiz_sonucu_yeni_alanlar():
    from ytcore.models import AnalizSonucu

    k = IndexKaydi(
        video_url="u",
        video_id="i",
        baslik="b",
        anadil="tr",
        kanal="k",
        konu="g",
        uretici_slug="k",
        video_slug="v",
        analiz_tarihi="2026-06-07",
    )
    s = AnalizSonucu(
        index=k,
        klasor="/x",
        transkript_durumu="altyazi",
        transkript_kaynak_dil="tr",
        asr_tier=None,
        stub=False,
    )
    assert s.transkript_durumu == "altyazi" and s.stub is False


def test_analiz_sonucu_faz3_alanlari():
    from ytcore.models import AnalizSonucu, FactIddia

    fi = FactIddia(iddia="X", karar="BELİRSİZ", guven=0.0, gerekce="y", kaynaklar=[])
    assert fi.karar == "BELİRSİZ"
    s = AnalizSonucu(
        index=IndexKaydi(
            video_url="u",
            video_id="v",
            baslik="b",
            anadil="tr",
            kanal="k",
            konu="h",
            uretici_slug="u",
            video_slug="v",
            analiz_tarihi="2026-06-08",
        ),
        klasor="/tmp",
    )
    assert s.degerleme_puani is None
    assert s.kisisel_durum == "atlandi"
    assert s.factcheck_durum == "atlandi"
    assert s.factcheck_iddia_sayisi == 0
    assert s.index_eklendi is False


def test_analiz_sonucu_faz4_varsayilanlari():
    from ytcore.models import AnalizSonucu, IndexKaydi

    k = IndexKaydi(
        video_url="https://youtu.be/x",
        video_id="x",
        baslik="B",
        anadil="tr",
        kanal="K",
        konu="genel",
        uretici_slug="k",
        video_slug="x",
        analiz_tarihi="2026-06-08",
    )
    s = AnalizSonucu(index=k, klasor="/tmp")
    assert s.harita_durum == "atlandi"
    assert s.harita_dugum_sayisi == 0
    assert s.ses_durum == "atlandi"
    assert s.ses_kaynak is None


def test_faz5_cloud_token_alanlari_default():
    # Faz 5 maliyet takibi (A14): default 0; routing kararı gözlemlenebilir.
    from ytcore.models import AnalizSonucu, IndexKaydi

    s = AnalizSonucu(
        index=IndexKaydi(
            video_url="u", video_id="v", baslik="b", anadil="tr", kanal="k",
            konu="genel", uretici_slug="x", video_slug="y", analiz_tarihi="2026-06-10",
        ),
        klasor=".",
    )
    assert s.cloud_girdi_token == 0 and s.cloud_cikti_token == 0
    assert s.hedef == "local" and s.karmasiklik == ""
