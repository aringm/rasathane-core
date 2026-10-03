from __future__ import annotations

from ytcore.content.llm import FakeLLM
from ytcore.uretim.harita import HaritaDugum, agac_to_markmap, dugum_say, harita_agaci


def test_harita_agaci_coklu_dugum():
    # FakeLLM harita sistem prompt'unu görünce geçerli JSON ağaç döndürür → çok-düğüm.
    agac = harita_agaci("Sözleşme hukuku irade beyanı ve tazminat üzerinedir.", FakeLLM())
    assert isinstance(agac, HaritaDugum)
    assert dugum_say(agac) >= 2  # kök + ≥1 dal (sığ-tek-düğüm değil)
    assert agac.label.strip()


def test_harita_agaci_bos_icerik_tek_dugum():
    agac = harita_agaci("", FakeLLM())
    assert dugum_say(agac) == 1  # içerik yok → tek-düğüm (çağıran icerik_yok ayırt)


def test_harita_agaci_gecersiz_json_graceful():
    # JSON üretmeyen LLM → çökmez, ilk-cümleden tek-düğüm kök (boş≠başarı: durum çağıranda).
    class HamLLM:
        def uret(self, sistem: str, kullanici: str, *, model: str | None = None) -> str:
            return "Bu düz metin, JSON değil."

    agac = harita_agaci("Sözleşme hukuku temeldir. İrade beyanı önemlidir.", HamLLM())
    assert dugum_say(agac) == 1
    assert "Sözleşme" in agac.label


def test_agac_to_markmap_citation_anchor():
    agac = HaritaDugum(
        id="n1",
        label="Kök",
        cocuklar=[HaritaDugum(id="n2", label="Dal", zaman_sn=90)],
    )
    veri = agac_to_markmap(agac, video_url="https://youtu.be/abc")
    assert veri["content"] == "Kök"
    cocuk = veri["children"][0]
    assert "Dal" in cocuk["content"]
    assert "t=90s" in cocuk["content"] and "youtu.be/abc" in cocuk["content"]  # citation link


def test_agac_to_markmap_html_escape():
    agac = HaritaDugum(id="n1", label="a < b & c")
    veri = agac_to_markmap(agac, video_url="")
    assert "&lt;" in veri["content"] and "&amp;" in veri["content"]  # XSS/bozulma yok


def test_json_cikar_trailing_metin_robust():
    # LLM JSON sonrası '}' içeren açıklama eklerse rfind("}") tuzağına düşme; raw_decode
    # ilk tam objeyi alır (trailing metin yutulmaz, graceful tek-düğüme DÜŞMEZ).
    class TrailingLLM:
        def uret(self, sistem: str, kullanici: str, *, model: str | None = None) -> str:
            return '{"label": "Kök", "cocuklar": [{"label": "Dal", "cocuklar": []}]} Not: {geçici}.'

    agac = harita_agaci("içerik", TrailingLLM())
    assert dugum_say(agac) == 2  # kök + dal (doğru parse; graceful'a düşmedi)
    assert agac.label == "Kök"
