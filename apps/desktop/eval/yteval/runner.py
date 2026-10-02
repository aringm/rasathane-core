from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from ytcore.models import IndexKaydi
from ytcore.pipeline.api import analiz_et

from yteval.metrics import structural_metrik, transcript_metrik

ORNEKLER: list[dict[str, str]] = [
    {"url": "https://youtu.be/eval-tr-1", "konu": "hukuk"},  # sentetik TR
    {"url": "https://youtu.be/eval-en-1", "konu": "general"},  # İngilizce smoke
]


def eval_kos(checkpoint_dir: Path | None = None) -> dict[str, Any]:
    """Held-out eval runner — Faz 1: structural + transcript metriği koşar.

    Sentetik örnekler gerçek video DEĞİL → ağsız fixture ile koşar (clean). Gerçek
    TR kalite metrikleri (WER/segmentasyon) sahip eval/real_docs/'a belge koyunca
    kalibre edilir (moat #1 bağımlılığı).
    """
    # Fixture env'leri process-global; os.environ.setdefault KALICI sızdırır (review LOW #18:
    # eval sonrası aynı process'te gerçek analiz fake'e düşebilirdi). try/finally ile restore.
    # Faz 3 (review MED): index/bellek/web fixture'ları da setdefault — yoksa sentetik eval
    # gerçek LanceDB'ye yazar / SERPER_API_KEY varsa web egress yapar (docstring 'hermetik'
    # iddiasıyla çelişir + kalıcı disk yan-etkisi).
    _fixture_anahtarlar = (
        "YT_TRANSCRIPT_FIXTURE",
        "YT_LLM_FIXTURE",
        "YT_EMBED_FIXTURE",
        "YT_INDEX_FIXTURE",
        "YT_MEMORY_FIXTURE",
        "YT_WEBSEARCH_FIXTURE",
    )
    _onceki = {k: os.environ.get(k) for k in _fixture_anahtarlar}
    try:
        # Fixture'ları ORNEKLER döngüsünden ÖNCE (Faz 1/2/3 node'ları hermetik koşsun).
        os.environ.setdefault("YT_TRANSCRIPT_FIXTURE", "clean")
        os.environ.setdefault("YT_LLM_FIXTURE", "1")
        os.environ.setdefault("YT_EMBED_FIXTURE", "1")
        os.environ.setdefault("YT_INDEX_FIXTURE", "1")
        os.environ.setdefault("YT_MEMORY_FIXTURE", "1")
        os.environ.setdefault("YT_WEBSEARCH_FIXTURE", "1")
        yapisal: list[dict[str, bool]] = []
        transkript: list[dict[str, object]] = []
        for o in ORNEKLER:
            s = analiz_et(
                url=o["url"],
                konu=o["konu"],
                thread_id=f"eval-{o['url'][-6:]}",
                checkpoint_dir=checkpoint_dir,
            )
            klasor = Path(s.klasor)
            idx_path = klasor / "00_index.json"
            gecerli = False
            if idx_path.exists():
                IndexKaydi.model_validate(json.loads(idx_path.read_text(encoding="utf-8")))
                gecerli = True
            yapisal.append(structural_metrik(klasor.is_dir(), gecerli))
            tr_path = klasor / "01_transcript_orijinal.md"
            # GERÇEK transkript gövde uzunluğu (header+imza dosya-boyutu DEĞİL — M9): boş
            # gövdeli "altyazi"/"asr" çıktısı moat'tan sessizce geçmesin (değişmez #3).
            transkript.append(
                transcript_metrik(tr_path.exists(), s.transkript_karakter, s.transkript_durumu)
            )
        yapisal_gecti = all(s["gecti"] for s in yapisal)
        transkript_gecti = all(bool(t["gecti"]) for t in transkript)
        return {
            "toplam": len(yapisal),
            "structural": {"gecti": yapisal_gecti, "detay": yapisal},
            "transcript": {"gecti": transkript_gecti, "detay": transkript},
            "icerik": _icerik_metrikleri(),
            "not": "Pk/F1/faithfulness GERÇEK; eşik kalibrasyonu eval/real_docs/ korpus-bekler",
        }
    finally:
        for k, v in _onceki.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


def _icerik_metrikleri() -> dict[str, Any]:
    """Faz 2 içerik metrik makinesinin GERÇEK + AYIRT-EDİCİ çalıştığını sentetik örnekte
    doğrula (FakeEmbedding ile hermetik). Önceki pk_self(etiket,etiket)=0 TOTOLOJİKTİ
    (review MED #10/#13): segmentasyon kalitesinden bağımsız her zaman 0 → sıfır ayırt-edici güç.

    Yeni: segmentasyon_metrik(GOLDEN, üretilen) gerçek Pk hesaplar (golden=elle-işaretli sınır);
    'metrik_ayirt_edici' metriğin KÖTÜ tahmini cezalandırdığını kanıtlar. Kalite eşik
    kalibrasyonu bge-m3 + held-out TR korpus bekler (#3).

    NOT: faithfulness BURADA çalıştırılmaz — fake-judge ('EVET' sabiti) dekoratiftir; gerçek
    faithfulness yalnız @pytest.mark.ollama (test_ollama_faz2 + gerçek-Ollama pipeline) ile.
    """
    os.environ.setdefault("YT_EMBED_FIXTURE", "1")
    from ytcore.content.dokum import dokum_derle
    from ytcore.content.keyword import keyword_cikar
    from ytcore.content.segment import cumlelere_bol, etiketler_uret, segmentle
    from ytcore.infra.embedding import embedding_al

    from yteval.metrics import segmentasyon_metrik

    # 4 cümle, 2 konu (sözleşme/irade | tazminat/mahkeme) → golden sınır 2. cümlede
    ornek = (
        "Sözleşme hukuku temeldir. İrade serbestisi önemli ilkedir. "
        "Tazminat hukuku haksız fiilden doğar. Mahkeme delilleri değerlendirir."
    )
    golden = [0, 0, 1, 1]  # elle-işaretli "doğru" segmentasyon
    embed = embedding_al()
    cumleler = cumlelere_bol(ornek)
    uretilen = etiketler_uret(segmentle(cumleler, embed), len(cumleler))
    seg = segmentasyon_metrik(golden, uretilen)  # GERÇEK pk vs golden (totoloji DEĞİL)
    # Ayırt-edici kanıtı: metrik her-birim-ayrı kötü tahmini cezalandırıyor mu (>0)
    kotu = list(range(len(golden)))
    ayirt_edici = segmentasyon_metrik(golden, kotu)["pk"] > 0.0
    bolumler = dokum_derle(ornek, embed)

    # Faz 3: retrieval (RETRIEVAL_RECALL) + değerleme ayırt-ediciliği (hermetik, FakeEmbed).
    from ytcore.infra.index import FakeIndexStore
    from ytcore.intel.degerleme import bilgi_degeri
    from ytcore.models import IndexKaydi as _IK

    from yteval.metrics import retrieval_recall_hesapla

    golden_r = {"q": {"d1", "d2"}}
    recall_iyi = retrieval_recall_hesapla(golden_r, {"q": ["d1", "d2"]}, k=2)["recall"]
    recall_kotu = retrieval_recall_hesapla(golden_r, {"q": ["d3", "d4"]}, k=2)["recall"]

    def _ik(vid: str) -> _IK:
        return _IK(
            video_url=f"u{vid}",
            video_id=vid,
            baslik="A",
            anadil="tr",
            kanal="k",
            konu="h",
            uretici_slug="k",
            video_slug=vid,
            analiz_tarihi="2026-06-08",
            keywords=["a"],
        )

    s_idx = FakeIndexStore()
    s_idx.ekle(_ik("d0"), "Aynı metin burada.", embed.embed(["Aynı metin burada."])[0])
    # AYIRT-EDİCİ (review totoloji): BİREBİR-AYNI string (özdeşlik, cos=1.0) novelty'si
    # ALAKASIZ'dan KESİN düşük olmalı (yalnız 'korpus dolu' değil). NOT: FakeEmbedding
    # string-yakınlığı semantiğe TAŞIMAZ → özdeşlik-vakası; DERECE kalibrasyonu bge-m3 bekler.
    _, fakt = bilgi_degeri(_ik("d1"), "Aynı metin burada.", embed, s_idx)
    _, fakt_alakasiz = bilgi_degeri(_ik("d2"), "Tamamen başka konu uzay roket.", embed, s_idx)

    # Faz 4: zihin haritası kapsamı ayırt-ediciliği (ilgili etiketler > alakasız; totoloji yok).
    from yteval.metrics import mindmap_kapsam

    mm_iyi = mindmap_kapsam(["Sözleşme hukuku", "İrade serbestisi", "Tazminat hukuku"], ornek)
    mm_kotu = mindmap_kapsam(["Uzay roket", "Hava durumu"], ornek)

    return {
        "segmentasyon_pk_golden": seg["pk"],  # gerçek pk (FakeEmbed→arbitrary; korpus-bekler)
        "segmentasyon_windowdiff_golden": seg["windowdiff"],
        "metrik_ayirt_edici": ayirt_edici,  # metrik kötü tahmini cezalandırıyor (wiring+discrim)
        "dokum_segment": len(bolumler),
        "keyword_ornek": keyword_cikar(ornek, ust_n=5),
        # Faz 3 ayırt-edicilik (held-out TR korpus eşik kilidini bekler)
        "retrieval_recall_iyi": recall_iyi,
        "retrieval_recall_kotu": recall_kotu,
        "retrieval_ayirt_edici": recall_iyi > recall_kotu,
        "degerleme_novelty_benzer": fakt.novelty,  # neredeyse-aynı belge → düşük novelty
        "degerleme_novelty_alakasiz": fakt_alakasiz.novelty,
        # KARŞILAŞTIRMALI ayırt-edicilik: benzer < alakasız (totoloji değil — review HIGH).
        # 0.0 falsy idiom tuzağı yok; is-not-None + kesin küçüklük.
        "degerleme_ayirt_edici": (
            fakt.novelty is not None
            and fakt_alakasiz.novelty is not None
            and fakt.novelty < fakt_alakasiz.novelty
        ),
        # Faz 4 zihin haritası kapsamı (ilgili etiketler özeti kapsar > alakasız; ayırt-edici).
        "mindmap_kapsam_iyi": mm_iyi,
        "mindmap_kapsam_kotu": mm_kotu,
        "mindmap_ayirt_edici": mm_iyi > mm_kotu,
        "not": "Pk/retrieval/değerleme/mindmap GERÇEK + ayırt-edici; kalite eşiği bge-m3+held-out "
        "TR korpus bekler. TTS=öznel A/B insan (oto-metrik yok). faithfulness fake-judge dekoratif "
        "→ atlandı (gerçek @pytest.mark.ollama).",
    }
