from __future__ import annotations

from typing import Any, TypedDict


class GState(TypedDict, total=False):
    """Pipeline paylaşılan durum sözleşmesi (graph + content node'ları ortak kullanır).

    total=False → her node yalnız ürettiği alanları döndürür (kısmi güncelleme; LangGraph
    merge eder). Faz 1 (transcript→pii_gate→router→local_ping) + Faz 2 (ceviri→dokum→ozet).
    """

    url: str
    konu: str
    asr_izin: bool
    output_run_id: str | None  # Product job UUID; yalnız çıktı dizini ayrılır, index sabit.
    kaynak_turu: str
    kaynak_durumu: str
    kaynak_sinyalleri: list[dict[str, Any]]
    kaynak_ozel: dict[str, Any]
    analysis_mode: str
    transkript_metni: str
    transkript_durumu: str
    transkript_kaynak_dil: str | None
    transkript_hata: str
    asr_tier: str | None
    transkript_segmentler: list[dict[str, Any]]
    metadata: dict[str, Any]
    pii_tespit: bool
    hedef: str
    cloud_cagrisi_sayisi: int
    ollama_ping_ms: float | None
    # Faz 5 hibrit servis
    karmasiklik: str  # router'ın hesapladığı complexity (gözlem + factcheck cloud kararı)
    cloud_girdi_token: int  # maliyet takibi (A14)
    cloud_cikti_token: int
    # Faz 2 içerik hattı
    icerik_tr: str
    ceviri_durumu: str
    ceviri_hata: str
    dokum_bolumler: list[dict[str, Any]]
    dokum_segment_sayisi: int
    keywords: list[str]
    ozet: dict[str, str]
    ozet_faithfulness: float | None
    ozet_faithfulness_durum: str | None
    ozet_hata: str
    # Faz 3 zeka katmanı
    govde_index: str
    degerleme_puani: float | None
    degerleme_durum: str
    degerleme_hata: str
    degerleme_faktorleri: dict[str, Any]
    kisisel_analiz: str
    kisisel_durum: str
    kisisel_hata: str
    factcheck_iddialar: list[dict[str, Any]]
    factcheck_durum: str
    factcheck_reason: str
    factcheck_hata: str
    klasor: str
    # Faz 4 üretim & sunum
    harita_durum: str
    harita_dugum_sayisi: int
    harita_hata: str
    ses_durum: str
    ses_kaynak: str | None
    ses_hata: str
    sonuc: dict[str, Any]
