from __future__ import annotations

import os

import pytest
from ytcore.pipeline.api import analiz_et


def test_faz5_hermetik_e2e_cloud_kapali(tmp_output_base, tmp_path, monkeypatch):
    # Faz 5 uçtan uca (hermetik): anahtarsız kurulumda dürüst 0-cloud + token alanları 0 +
    # gerçek complexity hesaplandı + Faz 4 çıktıları (harita/ses) bozulmadı.
    monkeypatch.setenv("YT_CHECKPOINT_DIR", str(tmp_path))
    s = analiz_et(
        "https://youtu.be/faz5test", konu="genel", thread_id="faz5", checkpoint_dir=tmp_path
    )
    assert s.cloud_cagrisi_sayisi == 0  # anahtarsız: dürüst 0-cloud (stub kalktı)
    assert s.cloud_girdi_token == 0 and s.cloud_cikti_token == 0
    assert s.hedef in ("local", "cloud") and s.karmasiklik != ""  # router gerçek sınıflandırdı
    assert s.transkript_durumu == "altyazi"
    assert s.harita_durum == "uretildi" and s.ses_durum == "uretildi"  # Faz 4 regresyon yok


def test_faz5_pii_transkript_hedef_local(tmp_output_base, tmp_path, monkeypatch):
    # Değişmez #1 kontrast: PII'li transkript + FORCE_COMPLEX → hedef yine LOCAL (hard-override).
    monkeypatch.setenv("YT_CHECKPOINT_DIR", str(tmp_path))
    monkeypatch.setenv("YT_TRANSCRIPT_FIXTURE", "pii")
    monkeypatch.setenv("YT_FORCE_COMPLEX", "1")
    s = analiz_et(
        "https://youtu.be/faz5pii", konu="genel", thread_id="faz5pii", checkpoint_dir=tmp_path
    )
    assert s.pii_tespit is True
    assert s.hedef == "local"  # KVKK hard-override (complexity'den ÖNCE)
    assert s.cloud_cagrisi_sayisi == 0


@pytest.mark.cloud
def test_gercek_cloud_verdict_anahtar_varsa():
    # Mod B gerçek-kaynak E2E iskeleti: ANTHROPIC_API_KEY gelince koşulur (şimdilik skip).
    if not os.environ.get("ANTHROPIC_API_KEY"):
        pytest.skip("ANTHROPIC_API_KEY yok — Mod B anahtar gelince koşulur")
    from ytcore.router.cloud_client import CloudClient

    cc = CloudClient(os.environ["ANTHROPIC_API_KEY"])
    y = cc.cagir(
        "Türkiye'nin başkenti Ankara'dır. Bu iddia doğru mu?", system="Tek kelime yanıtla."
    )
    assert y.metin.strip() and cc.cagri_sayisi == 1
    assert y.girdi_token > 0 and y.cikti_token > 0  # maliyet takibi gerçek usage'dan
