from __future__ import annotations

import json

from ytcore.models import IndexKaydi
from ytcore.output.klasor import analiz_klasoru_yaz


def _kayit() -> IndexKaydi:
    return IndexKaydi(
        video_url="https://youtu.be/x",
        video_id="x",
        baslik="Yapay Zeka",
        anadil="tr",
        kanal="Hukuk TV",
        konu="hukuk",
        uretici_slug="hukuk-tv",
        video_slug="yapay-zeka",
        analiz_tarihi="2026-06-07",
        keywords=["ai"],
        faz0_stub=True,
    )


def test_klasor_konvansiyonu(tmp_output_base):
    klasor = analiz_klasoru_yaz(_kayit(), tmp_output_base)
    # klasör adı video_id ile biter (çakışma-önleyici).
    p = tmp_output_base / "hukuk" / "hukuk-tv" / "2026-06-07_yapay-zeka_x"
    assert p == klasor and p.is_dir()
    idx = json.loads((p / "00_index.json").read_text(encoding="utf-8"))
    assert idx["video_id"] == "x" and idx["faz0_stub"] is True
    kapak = (p / "00_kapak.md").read_text(encoding="utf-8")
    assert "Av. Mehmet Arın Gülüm" in kapak


def test_ayni_slug_farkli_video_cakismaz(tmp_output_base):
    # HIGH (denetim): aynı kanal+başlık+gün ama FARKLI video → ayrı klasör (sessiz ezme yok).
    k1 = _kayit().model_copy(update={"video_id": "AAA111"})
    k2 = _kayit().model_copy(update={"video_id": "BBB222"})
    p1 = analiz_klasoru_yaz(k1, tmp_output_base)
    p2 = analiz_klasoru_yaz(k2, tmp_output_base)
    assert p1 != p2
    assert p1.name == "2026-06-07_yapay-zeka_AAA111"
    assert p2.name == "2026-06-07_yapay-zeka_BBB222"
