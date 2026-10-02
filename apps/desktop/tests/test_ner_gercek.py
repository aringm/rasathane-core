from __future__ import annotations

import pytest
from ytcore.router.ner import SubprocessNER

pytestmark = pytest.mark.ner  # gerçek bert-base-turkish-NER (torch, ayrı proses, CPU)


def test_gercek_ner_kisi_adi_yakalar(monkeypatch):
    monkeypatch.delenv("YT_NER_FIXTURE", raising=False)
    n = SubprocessNER()
    sonuc = n.kisi_var_mi(
        [
            "Müvekkilim Ayşe Kaya dün duruşmaya katıldı ve ifade verdi.",
            "Yargıtay 4. Hukuk Dairesi kararı oybirliğiyle bozdu.",
        ]
    )
    assert sonuc[0] is True  # çıplak ad-soyad (pii_gate'in KAÇIRDIĞI sınıf) yakalandı
    assert sonuc[1] is False  # kurum adı kişi DEĞİL (over-flag yok — Faz 1 regex dersi)
