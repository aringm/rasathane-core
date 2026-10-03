from __future__ import annotations

import pytest
from ytcore.content.node import ceviri_node, dokum_node, ozet_node


@pytest.fixture(autouse=True)
def _fake(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("YT_LLM_FIXTURE", "1")
    monkeypatch.setenv("YT_EMBED_FIXTURE", "1")


def test_ceviri_node_kaynak_tr_atlar():
    out = ceviri_node({"transkript_metni": "Türkçe metin.", "transkript_kaynak_dil": "tr"})
    assert out["ceviri_durumu"] == "atlandi"
    assert out["icerik_tr"] == "Türkçe metin."


def test_ceviri_node_en_cevirir():
    out = ceviri_node({"transkript_metni": "Hello world.", "transkript_kaynak_dil": "en"})
    assert out["ceviri_durumu"] == "cevrildi"
    assert out["icerik_tr"].strip()


def test_ceviri_node_bos_icerik_yok():
    out = ceviri_node({"transkript_metni": "", "transkript_kaynak_dil": "en"})
    assert out["ceviri_durumu"] == "icerik_yok"
    assert out["icerik_tr"] == ""


def test_dokum_node_uretir():
    state = {
        "icerik_tr": "Sözleşme hukuku temeldir. İrade serbestisi önemlidir. Tazminat ayrıdır.",
        "transkript_segmentler": [],
    }
    out = dokum_node(state)
    assert out["dokum_segment_sayisi"] >= 1
    assert out["keywords"]
    assert out["dokum_bolumler"]


def test_dokum_node_bos():
    out = dokum_node({"icerik_tr": "", "transkript_segmentler": []})
    assert out["dokum_segment_sayisi"] == 0
    assert out["dokum_bolumler"] == []


def test_dokum_node_timestamp_haritalama():
    state = {
        "icerik_tr": "Bir cümle. İki cümle. Üç cümle.",
        "transkript_segmentler": [{"baslangic_sn": 0, "metin": "Bir cümle."}],
    }
    out = dokum_node(state)
    assert out["dokum_bolumler"][0]["baslangic_sn"] is not None


def test_ozet_node_uretir():
    out = ozet_node({"icerik_tr": "Sözleşme hukuku temeldir. İrade serbestisi. " * 20})
    assert out["ozet"]["detay"].strip()
    assert "ozet_faithfulness" in out
    assert out["ozet_faithfulness_durum"] in ("gecti", "esik_alti", "yeniden_uretildi")


def test_ozet_node_bos():
    out = ozet_node({"icerik_tr": ""})
    assert out["ozet_faithfulness_durum"] == "ozet_yok"


def test_ceviri_node_hata_icerik_bos(monkeypatch):
    # Çeviri model/ağ hatası → icerik_tr="" (cevrilmemiş İngilizce'den döküm/özet ÜRETME)
    class PatlaLLM:
        def uret(self, sistem, kullanici, *, model=None):
            raise RuntimeError("ollama down")

    monkeypatch.setattr("ytcore.content.node.llm_al", lambda *a, **k: PatlaLLM())
    out = ceviri_node({"transkript_metni": "Hello world.", "transkript_kaynak_dil": "en"})
    assert out["ceviri_durumu"] == "hata"
    assert out["icerik_tr"] == ""


def test_dokum_node_fallback_yok():
    # icerik_tr boş + transkript_metni dolu → döküm ATLAR (eski transkript_metni fallback bug'i yok)
    out = dokum_node({"icerik_tr": "", "transkript_metni": "Sözleşme hukuku temeldir."})
    assert out["dokum_segment_sayisi"] == 0
    assert out["dokum_bolumler"] == []


def test_ozet_node_fallback_yok():
    out = ozet_node({"icerik_tr": "", "transkript_metni": "Sözleşme hukuku. " * 20})
    assert out["ozet_faithfulness_durum"] == "ozet_yok"


def test_arxiv_short_medium_keep_source_sentences_instead_of_bad_compression(monkeypatch):
    from ytcore.content.llm import FakeLLM

    calls = []
    body = (
        "Eski dizi modelleri RNN veya CNN kullanır. "
        "Bu modellerde kodlayıcı ve kod çözücü dikkat mekanizmasıyla bağlanır. "
        "Yeni Transformer yalnız dikkat kullanır, RNN ve CNN kullanmaz. "
        "İngilizce-Almanca sonucu 28,4 BLEU, İngilizce-Fransızca sonucu 41,8 BLEU'dur. "
        "Eğitim 3,5 gün ve sekiz GPU gerektirmiştir."
    )

    class BadCompression(FakeLLM):
        def uret(self, sistem, kullanici, *, model=None):
            calls.append(sistem)
            if "tek paragraflık" in sistem or "TL;DR" in sistem:
                return "Eski RNN ve CNN modelleri Transformer kullanır."
            if "birleştir" in sistem:
                return "Detaylı model özeti; kaynak sonuçları ayrıca incelenmelidir."
            return super().uret(sistem, kullanici, model=model)

    monkeypatch.setattr("ytcore.content.node.llm_al", lambda *args, **kwargs: BadCompression())
    out = ozet_node(
        {
            "icerik_tr": body,
            "kaynak_turu": "arxiv",
            "kaynak_ozel": {"text_scope": "abstract_only", "full_text_fetched": False},
        }
    )
    assert out["ozet"]["kisa"] == ". ".join(body.split(". ")[:3]) + "."
    assert out["ozet"]["orta"] == body
    assert "28,4 BLEU" in out["ozet"]["orta"]
    assert "41,8 BLEU" in out["ozet"]["orta"]
    assert "3,5 gün" in out["ozet"]["orta"]
    assert "Eski RNN ve CNN modelleri Transformer kullanır." not in str(out)
    assert not any("tek paragraflık" in call or "TL;DR" in call for call in calls)
    assert out["ozet"]["detay"].startswith("Detaylı model özeti")
