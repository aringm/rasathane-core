from __future__ import annotations

from ytcore.content.llm import FakeLLM
from ytcore.content.temizle import _regex_on_temizlik, temizle_youtube


def test_regex_ses_etiket_ve_tekrar_ve_bosluk():
    m = "[Music] Merhaba merhaba merhaba dünya [Alkış]  çok    boşluk (♪)"
    out = _regex_on_temizlik(m)
    assert "[Music]" not in out and "[Alkış]" not in out and "(♪)" not in out
    assert "merhaba merhaba" not in out.lower()  # ardışık tekrar tekilleşti
    assert "    " not in out  # çoklu boşluk sadeleşti


def test_temizle_kisa_metin_yalniz_regex():
    # <200 char → LLM'e gitmez (FakeLLM çağrılsa da fark etmez), regex temizler.
    out = temizle_youtube("[Music] kısa bir metin parçası", FakeLLM())
    assert "[Music]" not in out and out.strip()


def test_temizle_uzun_metin_icerik_korunur():
    # >200 char → FakeLLM 'temizle' dalı passthrough (içerik KAYBOLMAZ; boş≠başarı).
    metin = "[Music] " + ("Bu bir test cümlesidir. " * 40)
    out = temizle_youtube(metin, FakeLLM())
    assert len(out) > 200  # içerik korundu
    assert "[Music]" not in out  # regex etiketi temizledi


def test_temizle_node_altyazi_yolunda_gunceller(monkeypatch):
    # temizle_node: durum=altyazi → transkript_metni güncellenir; altyazi_yok → dokunmaz.
    import ytcore.content.node as n

    monkeypatch.setenv("YT_LLM_FIXTURE", "1")
    g = {"transkript_metni": "[Music] " + ("söz. " * 60), "transkript_durumu": "altyazi"}
    out = n.temizle_node(g)  # type: ignore[arg-type]
    assert "transkript_metni" in out and "[Music]" not in out["transkript_metni"]
    # içerik yok → değiştirme
    assert n.temizle_node({"transkript_metni": "", "transkript_durumu": "altyazi_yok"}) == {}
