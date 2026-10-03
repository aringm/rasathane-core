from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field
from rasathane.sources import KaynakSinyali


class AnalizGirdi(BaseModel):
    url: str
    konu: str = "genel"
    thread_id: str | None = None
    asr_izin: bool = False  # altyazı yoksa Whisper'a düşmek için AÇIK izin (sessiz fallback YOK)
    kaynak_turu: str = "auto"


class TranskriptSonuc(BaseModel):
    """Transcript node'unun dahili çıktısı (metin + edinim durumu)."""

    metin: str
    durum: str  # "altyazi" | "asr" | "altyazi_yok"
    kaynak_dil: str | None = None
    segment_sayisi: int = 0
    asr_tier: str | None = None  # "whisperx" | "faster-whisper"
    # Faz 2: zaman-damgalı segmentler [{baslangic_sn, metin}] — kronolojik döküm timestamp
    # kaynağı (altyazı yolunda VTT cue'larından; ASR yolunda şimdilik boş). Additive.
    segmentler: list[dict[str, object]] = Field(default_factory=list)


class DegerlemeFaktorleri(BaseModel):
    novelty: float | None = None
    rarity: float | None = None
    nis: float | None = None
    recency: float | None = None
    length: float | None = None


class IndexKaydi(BaseModel):
    video_url: str
    video_id: str
    baslik: str
    anadil: str
    kanal: str
    yayin_tarihi: str | None = None
    sure_sn: int | None = None
    konu: str
    uretici_slug: str
    video_slug: str
    analiz_tarihi: str
    keywords: list[str] = Field(default_factory=list)
    degerleme_puani: float | None = None
    degerleme_faktorleri: DegerlemeFaktorleri = Field(default_factory=DegerlemeFaktorleri)
    faz0_stub: bool = False
    sema_versiyonu: int = 1
    # Rasathane çok-kaynak sözleşmesi. Eski video_* alanları geriye uyumluluk için korunur;
    # yeni kodun kanonik kimliği bu alanlardır. YouTube kayıtlarında boş değerler legacy
    # alanlardan okunabilir, yeni edinimlerde iki taraf birlikte doldurulur.
    kaynak_turu: str = "youtube"
    kaynak_url: str = ""
    kaynak_id: str = ""
    kaynak_sahibi: str = ""
    kaynak_tarihi: str | None = None
    kaynak_guncelleme_tarihi: str | None = None
    kaynak_etiketleri: list[str] = Field(default_factory=list)
    kaynak_metrikleri: dict[str, Any] = Field(default_factory=dict)
    kaynak_ozel: dict[str, Any] = Field(default_factory=dict)
    # Motor kökeni (2026-08-24 kullanıcı isteği): hangi backend/model/profil ile analiz
    # edildi — 00_index.json'a girer. Additive (default {} — eski kayıtlar validate olur).
    motor: dict[str, Any] = Field(default_factory=dict)


class FactIddia(BaseModel):
    """Fact-check tek iddia sonucu (06_fact-check.md satırı)."""

    iddia: str
    karar: str  # DESTEKLİYOR | ÇELİŞİYOR | BELİRSİZ
    guven: float = 0.0
    gerekce: str = ""
    kaynaklar: list[str] = Field(default_factory=list)
    ilgili_kaynaklar: list[str] = Field(default_factory=list)
    aday_karar: str | None = None
    kanit_turu: str = "bilinmiyor"
    bagimsiz_dogrulama: bool = False


class AnalizSonucu(BaseModel):
    index: IndexKaydi
    klasor: str
    pii_tespit: bool = False
    cloud_cagrisi_sayisi: int = 0
    ollama_ping_ms: float | None = None
    commit_yapildi: bool = False
    # "altyazi" | "asr" | "kaynak" | "altyazi_yok" | "icerik_bos" | "hata"
    transkript_durumu: str = "altyazi_yok"
    transkript_kaynak_dil: str | None = None
    transkript_karakter: int = 0  # gerçek transkript gövde uzunluğu (eval moat ölçer)
    asr_tier: str | None = None
    # Faz 2 içerik hattı sonuçları
    ceviri_durumu: str = "atlandi"  # "atlandi"|"cevrildi"|"hata"|"icerik_yok"
    dokum_segment_sayisi: int = 0
    ozet_faithfulness: float | None = None
    ozet_faithfulness_durum: str | None = None
    # Model tahmininin karşılaştırdığı metin ve sınırları. Skor doğruluk onayı değildir.
    quality_provenance: dict[str, Any] = Field(default_factory=dict)
    analysis_mode: str = "model_analysis"
    # Faz 9: çıktı İÇERİĞİ ekrana taşınır (dosyada da yazılı; GUI inline gösterim için). KVKK:
    # local-only, egress yok — yalnız WebView'a (127.0.0.1) gider. Boş = üretilmedi (durum kanıt).
    ozet_kisa: str = ""  # TL;DR (tek cümle)
    ozet_orta: str = ""  # paragraf özeti
    ozet_detay: str = ""  # detaylı özet
    # Faz 3 zeka katmanı
    degerleme_puani: float | None = None
    degerleme_durum: str = "atlandi"  # uretildi|atlandi|icerik_yok|hata
    kisisel_durum: str = "atlandi"  # uretildi|model_bos|atlandi|icerik_yok|hata
    kisisel_analiz: str = ""  # Faz 9: avukat-lens analiz metni (GUI inline gösterim)
    # uretildi|web_yok|web_hata|hepsi_atlandi|atlandi|icerik_yok|hata
    factcheck_durum: str = "atlandi"
    factcheck_reason: str = ""
    factcheck_iddia_sayisi: int = 0
    factcheck_iddialar: list[FactIddia] = Field(default_factory=list)  # Faz 9: iddia kartları
    index_eklendi: bool = False
    bellek_eklendi: bool = False  # episodik bellek best-effort sonucu (gözlemlenebilirlik)
    # Faz 4 üretim & sunum
    harita_durum: str = "atlandi"  # uretildi|icerik_yok|atlandi|hata
    harita_dugum_sayisi: int = 0
    # uretildi|ses_modeli_yok|piper_kurulu_degil|anahtar_yok|icerik_yok|atlandi|hata
    ses_durum: str = "atlandi"
    ses_kaynak: str | None = None  # "piper" | "cloud" | "fake"
    # Faz 7: sunum PDF yazıldı mı (Typst best-effort) — GUI butonu gate'ler.
    sunum_durum: str = "atlandi"  # uretildi|atlandi|hata
    # Hata DETAYLARI (2026-08-24 saha dersi): node'lar state'e *_hata yazıyordu ama sonuca
    # hiç taşınmıyordu → GUI yalnız "Hata" gösterebiliyordu, kök neden kayboluyordu.
    # Boş string = hata yok (durum alanlarıyla birlikte okunur; durum=hata ⇔ detay dolu).
    transkript_hata: str = ""
    degerleme_hata: str = ""
    kisisel_hata: str = ""
    factcheck_hata: str = ""
    harita_hata: str = ""
    ses_hata: str = ""
    # Motor kökeni: hangi backend/model/profil (GUI Teknik bölümü + 00_index.json motor).
    motor: dict[str, Any] = Field(default_factory=dict)
    # Faz 5 hibrit servis: routing kararı gözlemlenebilir (stub kalktı — kontrast kanıtı
    # artık hedef alanından; sayaç yalnız GERÇEK cloud çağrısı) + maliyet takibi (A14).
    hedef: str = "local"  # local|cloud (router kararı)
    karmasiklik: str = ""  # simple|medium|complex|reasoning ("" = içerik yok)
    cloud_girdi_token: int = 0
    cloud_cikti_token: int = 0
    # Kaynak adapter'ı ve kaynağa özgü açıklanabilir sinyaller (UI + çıktı provenance).
    kaynak_turu: str = "youtube"
    kaynak_durumu: str = "altyazi_yok"
    kaynak_sinyalleri: list[KaynakSinyali] = Field(default_factory=list)
    stub: bool = True


class PipelineState(BaseModel):
    url: str
    konu: str = "genel"
    pii_tespit: bool = False
    hedef: str = "local"  # local|cloud
    cloud_cagrisi_sayisi: int = 0
    ollama_ping_ms: float | None = None
    sonuc: AnalizSonucu | None = None
