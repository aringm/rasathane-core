from __future__ import annotations

import pytest
from yteval.metrics import (
    KEYWORD_F1,
    OZET_FAITHFULNESS,
    RETRIEVAL_RECALL,
    SEGMENTASYON_PK,
    TRANSCRIPT_WER,
)
from yteval.runner import eval_kos


def test_structural_metrik_gecer(tmp_output_base, tmp_path, monkeypatch):
    monkeypatch.setenv("YT_FORCE_COMPLEX", "0")
    rapor = eval_kos(checkpoint_dir=tmp_path)
    assert rapor["structural"]["gecti"] is True
    assert rapor["toplam"] >= 1


def test_transcript_metrik_eval_raporunda(tmp_output_base, tmp_path, monkeypatch):
    # Faz 1 değişmez #3: eval harness transcript metriğini ölçer.
    monkeypatch.setenv("YT_FORCE_COMPLEX", "0")
    rapor = eval_kos(checkpoint_dir=tmp_path)
    assert "transcript" in rapor
    assert rapor["transcript"]["gecti"] is True


def test_transcript_metrik_dolu_gecer():
    from yteval.metrics import transcript_metrik

    r = transcript_metrik(transkript_var=True, metin_uzunluk=200, durum="altyazi")
    assert r["gecti"] is True


def test_transcript_metrik_bos_gecmez():
    from yteval.metrics import transcript_metrik

    r = transcript_metrik(transkript_var=True, metin_uzunluk=0, durum="altyazi_yok")
    assert r["gecti"] is False


def test_transcript_metrik_bos_govde_altyazi_gecmez():
    # Review M9: durum='altyazi'/'asr' olsa bile GERÇEK gövde boşsa (metin_uzunluk=0)
    # metrik GEÇMEMELİ — moat dosya-boyutunu değil transkript gövdesini ölçer.
    from yteval.metrics import transcript_metrik

    assert transcript_metrik(True, 0, "altyazi")["gecti"] is False
    assert transcript_metrik(True, 0, "asr")["gecti"] is False


def test_segmentasyon_pk_metrik():
    # Faz 2: GERÇEK Pk/WindowDiff (saf-python). ref==tahmin → 0.0
    from yteval.metrics import segmentasyon_metrik

    r = segmentasyon_metrik([0, 0, 1, 1], [0, 0, 1, 1])
    assert r["pk"] == 0.0 and r["windowdiff"] == 0.0


def test_keyword_f1_metrik():
    from yteval.metrics import keyword_metrik

    assert keyword_metrik(["a", "b"], ["a", "b"])["f1"] == 1.0


def test_faithfulness_metrik_fake():
    from yteval.metrics import faithfulness_metrik

    class _EvetLLM:
        def uret(self, sistem, kullanici, *, model=None):
            return "EVET"

    r = faithfulness_metrik("İddia bir.", "kaynak", _EvetLLM())
    assert r["skor"] == 1.0


def test_segmentasyon_pk_metrik_objesi_float():
    # Metrik.hesapla birincil float döndürür (Callable[...,float] sözleşmesi)
    assert SEGMENTASYON_PK.hesapla([0, 0, 1], [0, 0, 1]) == 0.0
    assert KEYWORD_F1.hesapla(["a"], ["a"]) == 1.0


def test_faithfulness_metrik_objesi_float():
    class _EvetLLM:
        def uret(self, sistem, kullanici, *, model=None):
            return "EVET"

    assert OZET_FAITHFULNESS.hesapla("İddia.", "kaynak", _EvetLLM()) == 1.0


def test_transcript_wer_notimplemented():
    # TRANSCRIPT_WER (korpus-bekler) hâlâ NotImplemented (sözleşme sabit)
    with pytest.raises(NotImplementedError):
        TRANSCRIPT_WER.hesapla()


def test_retrieval_recall_ayirt_edici():
    """RETRIEVAL_RECALL gerçek + ayırt-edici: iyi sıralama yüksek, kötü düşük recall."""
    from yteval.metrics import retrieval_recall_hesapla

    golden = {"q1": {"d1", "d2"}}
    iyi = {"q1": ["d1", "d2", "d3"]}  # ilgili belgeler üstte
    kotu = {"q1": ["d3", "d4", "d5"]}  # ilgili belge yok
    r_iyi = retrieval_recall_hesapla(golden, iyi, k=2)
    r_kotu = retrieval_recall_hesapla(golden, kotu, k=2)
    assert r_iyi["recall"] == 1.0
    assert r_kotu["recall"] == 0.0
    assert r_iyi["recall"] > r_kotu["recall"]  # metrik kötüyü cezalandırır (totoloji DEĞİL)
    assert r_iyi["ndcg"] > r_kotu["ndcg"]


def test_retrieval_recall_metrik_iface():
    assert RETRIEVAL_RECALL.ad == "retrieval_recall"
    # Metrik.hesapla artık gerçek (NotImplemented değil) — birincil float (recall)
    skor = RETRIEVAL_RECALL.hesapla({"q": {"d1"}}, {"q": ["d1"]}, 1)
    assert skor == 1.0


def test_eval_kos_retrieval_ayirt_edici(tmp_output_base, tmp_path):
    # Faz 3: eval_kos retrieval + değerleme ayırt-ediciliğini doğrular (sentetik, hermetik).
    rapor = eval_kos(checkpoint_dir=tmp_path)
    ic = rapor["icerik"]
    assert ic["retrieval_ayirt_edici"] is True  # iyi > kötü recall
    assert ic["degerleme_ayirt_edici"] is True  # benzer belge < 100 novelty


def test_eval_kos_icerik_bolumu(tmp_output_base, tmp_path):
    # Faz 2: eval_kos içerik metriklerini koşar — pk GOLDEN'a karşı (totoloji DEĞİL, review fix)
    rapor = eval_kos(checkpoint_dir=tmp_path)
    assert "icerik" in rapor
    ic = rapor["icerik"]
    assert "segmentasyon_pk_golden" in ic  # gerçek pk (golden vs üretilen)
    assert ic["metrik_ayirt_edici"] is True  # metrik KÖTÜ tahmini cezalandırıyor (ayırt-edici)
    assert ic["dokum_segment"] >= 1
    assert "faithfulness_skor" not in ic  # fake-judge dekoratif → sentetik path'te yok


def test_eval_kos_fixture_env_sizdirmaz(tmp_output_base, tmp_path, monkeypatch):
    # review LOW #18: eval_kos fixture env'lerini KENDI set ettiyse restore etmeli (sızıntı yok)
    import os

    for k in ("YT_TRANSCRIPT_FIXTURE", "YT_LLM_FIXTURE", "YT_EMBED_FIXTURE"):
        monkeypatch.delenv(k, raising=False)
    eval_kos(checkpoint_dir=tmp_path)  # hermetik koşar (kendi setdefault'u) + restore
    for k in ("YT_TRANSCRIPT_FIXTURE", "YT_LLM_FIXTURE", "YT_EMBED_FIXTURE"):
        assert k not in os.environ  # eval sonrası prod'a fixture sızmadı


def test_mindmap_kapsam_ayirt_edici():
    from yteval.metrics import mindmap_kapsam

    ozet = "Sözleşme hukuku irade beyanı ve tazminat sorumluluğu üzerinedir."
    iyi = ["Sözleşme hukuku", "İrade beyanı", "Tazminat sorumluluğu"]
    kotu = ["Kedi", "Hava durumu"]
    s_iyi = mindmap_kapsam(iyi, ozet)
    s_kotu = mindmap_kapsam(kotu, ozet)
    assert 0.0 <= s_kotu < s_iyi <= 1.0  # ilgili ağaç > alakasız (ayırt-edici)
    assert mindmap_kapsam([], ozet) == 0.0  # boş ağaç = 0 (sessiz 1 değil)
    assert mindmap_kapsam(["tek"], ozet) == 0.0  # <2 düğüm = 0 (anlamlı ağaç değil)
