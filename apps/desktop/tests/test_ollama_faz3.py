from __future__ import annotations

from pathlib import Path

import pytest


@pytest.mark.ollama
def test_faz3_gercek_e2e(tmp_path, monkeypatch):
    """Gerçek bge-m3 + LanceDB + qwen2.5:14b: değerleme + kişisel + fact-check(web fixture).

    Tüm Faz 2/3 hattı gerçek modelle (transcript fixture clean — YouTube'a gitmez).
    0-cloud korunur; index/bellek gerçek LanceDB'ye yazılır (tmp).
    """
    # Gerçek model/embedding/index/bellek (fixture KAPALI); transcript + web fixture açık.
    for k in ("YT_INDEX_FIXTURE", "YT_MEMORY_FIXTURE", "YT_LLM_FIXTURE", "YT_EMBED_FIXTURE"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("YT_TRANSCRIPT_FIXTURE", "clean")  # TR altyazı (ağsız)
    monkeypatch.setenv("YT_WEBSEARCH_FIXTURE", "1")  # web fixture (anahtar yok)
    monkeypatch.setenv("YT_OLLAMA_PING", "0")
    out = tmp_path / "out"
    out.mkdir()
    monkeypatch.setenv("YT_OUTPUT_BASE", str(out))

    from ytcore.pipeline.api import analiz_et

    s = analiz_et(
        url="https://youtu.be/x", konu="hukuk", thread_id="f3-ollama", checkpoint_dir=tmp_path
    )
    klasor = Path(s.klasor)
    assert (klasor / "08_degerleme.md").is_file()
    assert (klasor / "07_kisisel-analiz.md").is_file()
    assert (klasor / "06_fact-check.md").is_file()
    assert s.degerleme_puani is not None and 0 <= s.degerleme_puani <= 100
    assert s.index_eklendi is True
    assert s.kisisel_durum == "uretildi"
    assert s.cloud_cagrisi_sayisi == 0  # 0-cloud korunur (yeni egress'ler de buluta gitmez)
    # Gerçek LanceDB index korpusa yazıldı (output_base/_index)
    assert (out / "_index").is_dir()
