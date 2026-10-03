from __future__ import annotations

import pytest
from ytcore.content.ceviri import cevir, ceviri_gerekli_mi
from ytcore.content.llm import FakeLLM


@pytest.mark.parametrize(
    "dil,beklenen",
    [("tr", False), ("TR", False), ("tr-orig", False), ("en", True), (None, True), ("", True)],
)
def test_ceviri_gerekli_mi(dil, beklenen):
    assert ceviri_gerekli_mi(dil) is beklenen


def test_cevir_bos_metin_bos_doner():
    assert cevir("", FakeLLM()) == ""


def test_cevir_uretir():
    out = cevir("Hello world.", FakeLLM(), glossary_metni="")
    assert out.strip()
    assert out != "Hello world."


def test_cevir_glossary_promptta(monkeypatch):
    yakalanan = {}

    class KayitLLM:
        def uret(self, sistem, kullanici, *, model=None):
            yakalanan["sistem"] = sistem
            return "çeviri"

    cevir("Hello.", KayitLLM(), glossary_metni="- contract → sözleşme")
    assert "contract → sözleşme" in yakalanan["sistem"]


def test_cevir_bos_model_ciktisi_hata():
    class BosLLM:
        def uret(self, sistem, kullanici, *, model=None):
            return "   "

    with pytest.raises(ValueError, match="boş"):
        cevir("Hello.", BosLLM())
