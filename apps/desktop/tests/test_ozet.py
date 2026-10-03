from __future__ import annotations

import pytest
from ytcore.content.llm import FakeLLM
from ytcore.content.ozet import abstract_cumleleri, ozetle, semantic_chunk
from ytcore.infra.embedding import FakeEmbedding


def test_semantic_chunk_kisa_tek_parca():
    parcalar = semantic_chunk(["Kısa metin.", "İki cümle."], FakeEmbedding(), hedef_kar=10000)
    assert len(parcalar) == 1


def test_semantic_chunk_bos():
    assert semantic_chunk([], FakeEmbedding()) == []


def test_semantic_chunk_uzun_bolunur():
    cumleler = [f"Bu {i}. cümledir ve yeterince uzundur." for i in range(50)]
    parcalar = semantic_chunk(cumleler, FakeEmbedding(), hedef_kar=200)
    assert len(parcalar) >= 2
    assert all(p.strip() for p in parcalar)


def test_ozetle_uretir():
    metin = "Sözleşme hukuku önemlidir. İrade serbestisi temeldir. " * 30
    sonuc = ozetle(metin, FakeLLM(), FakeEmbedding())
    assert sonuc["kisa"].strip()
    assert sonuc["orta"].strip()
    assert sonuc["detay"].strip()


def test_ozetle_bos_metin_bos_sonuc():
    sonuc = ozetle("", FakeLLM(), FakeEmbedding())
    assert sonuc["kisa"] == "" and sonuc["detay"] == ""


def test_ozetle_bos_model_ciktisi_hata():
    class BosLLM:
        def uret(self, sistem, kullanici, *, model=None):
            return ""

    with pytest.raises(ValueError, match="boş"):
        ozetle("Uzun metin cümlesi. " * 20, BosLLM(), FakeEmbedding())


def test_ozetle_orta_kisa_bos_detaydan_turetir():
    # MED fix: orta/kısa boş dönerse detay'dan türet (boş katman + 'gecti' çelişkisi olmasın)
    class DetayOnlyLLM:
        def uret(self, sistem, kullanici, *, model=None):
            s = sistem.lower()
            if "birleştir" in s:  # _REDUCE_DETAY
                return "Detay birinci cümle. Detay ikinci cümle."
            if "tek paragraf" in s or "tl;dr" in s or "tek cümle" in s:  # orta + kısa
                return ""
            return "map özeti."  # map

    sonuc = ozetle("Uzun metin cümlesi. " * 20, DetayOnlyLLM(), FakeEmbedding())
    assert sonuc["detay"].strip()
    assert sonuc["orta"].strip()  # detay'dan türedi (boş kalmadı)
    assert sonuc["kisa"].strip()  # orta ilk cümlesinden türedi


@pytest.mark.parametrize("abbreviation", ["Dr.", "Prof.", "e.g.", "U.S."])
def test_abstract_ambiguous_abbreviation_keeps_whole_text(abbreviation):
    text = (
        "Eski modeller tekrarlayan ağ kullanır. Yeni Transformer yalnız dikkat kullanır. "
        f"{abbreviation} Smith sonraki modeli sundu. "
        "Model 28.4 BLEU ve 41.8 BLEU elde etti. Eğitim 3.5 gün sürdü."
    )
    selected = abstract_cumleleri(text)
    assert selected["kisa"] == text
    assert selected["orta"] == text


@pytest.mark.parametrize(
    "clause",
    [
        (
            'Yazarlar "Dikkat mekanizması başarılıdır. '
            'Sonuçlar tekrarlanmalıdır." ifadesini kullanmıştır.'
        ),
        "Yazarlar “Dikkat başarılıdır. Sonuç tekrarlanmalıdır.” ifadesini kullanmıştır.",
        "Değerlendirme 1. Transformer sonuçları ve 2. Çözümleme üzerinden yapılmıştır.",
        "Dikkat mekanizması (İlk model. Son model.) ile değerlendirilmiştir.",
        "İlk sonuç açıklanmıştır... Yeni açıklama üçüncü değerlendirmeyi tamamlamıştır.",
    ],
)
def test_abstract_quotes_numbered_sections_or_brackets_keep_whole_text(clause):
    text = (
        "İlk sonuç açıklanmıştır. İkinci sonuç doğrulanmıştır. "
        f"{clause} Dördüncü sonuç paylaşılmıştır."
    )
    assert abstract_cumleleri(text) == {"kisa": text, "orta": text}
