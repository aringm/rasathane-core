from __future__ import annotations

import pytest


@pytest.mark.ollama
def test_harita_gercek_qwen_json_agac(monkeypatch):
    monkeypatch.delenv("YT_LLM_FIXTURE", raising=False)  # gerçek Ollama
    from ytcore.content.llm import llm_al
    from ytcore.uretim.harita import agac_to_markmap, dugum_say, harita_agaci
    from ytcore.uretim.markmap import markmap_html

    govde = (
        "Türk Borçlar Kanunu'na göre sözleşme, tarafların iradelerini karşılıklı ve birbirine "
        "uygun olarak açıklamalarıyla kurulur. İrade beyanı açık veya örtülü olabilir. "
        "Sözleşmenin kurulması için tarafların ehliyeti ve konunun hukuka uygunluğu gerekir. "
        "Haksız fiil sonucu doğan zarar tazminat sorumluluğu doğurur."
    )
    agac = harita_agaci(govde, llm_al())
    assert dugum_say(agac) >= 3  # gerçek model anlamlı ağaç üretti
    veri = agac_to_markmap(agac, video_url="https://youtu.be/x")
    h = markmap_html(veri, baslik="Borçlar Hukuku")
    assert "Markmap.create" in h and "<script src=" not in h.lower()  # offline geçerli
