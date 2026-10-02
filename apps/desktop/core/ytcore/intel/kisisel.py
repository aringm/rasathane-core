from __future__ import annotations

from pathlib import Path

from ytcore.content.llm import LLMClient
from ytcore.intel.memory import MemoryStore

_LENS_SISTEM = (
    "Sen bir hukuk uzmanısın (avukat perspektifi). Verilen içeriği şu açılardan "
    "değerlendir ve Türkçe, sade-profesyonel bir analiz yaz: (1) hukuki boyut, "
    "(2) etik sorunlar, (3) KVKK/veri-koruma açısı, (4) mesleki ilgi. Kısa başlıklar kullan."
)
_BAGLAM_LIMIT = 6000

_KAYNAK_YONERGESI = {
    "youtube": "Konuşulan iddiaları yazılı mevzuat veya birincil kaynak doğrulaması gibi sunma.",
    "github": (
        "README beyanlarını kod incelemesi yapılmış gibi sunma; bakım, lisans ve güvenlik "
        "sinyallerini birbirinden ayır."
    ),
    "arxiv": (
        "Analiz yalnız edinilen abstract ve metadata'ya dayanıyorsa yöntem, deney ve sonuçlar "
        "hakkında full-text doğrulaması yapılmış gibi çıkarım yapma; preprint statüsünü belirt."
    ),
    "reddit": (
        "Gönderi ve yorumları anekdot/topluluk görüşü olarak ele al; temsilî veri veya uzman "
        "görüşü gibi genelleme."
    ),
    "huggingface": (
        "Model/dataset card beyanlarını bağımsız benchmark veya veri denetimi gibi sunma; "
        "lisans, gated erişim ve remote-code riskini görünür kıl."
    ),
    "web": (
        "Yayıncı beyanı ile bağımsız kanıtı ayır; yazar, tarih ve kaynak bağlantısı eksikse bu "
        "sınırlılığı belirt."
    ),
}


def _oku(yol: Path) -> str:
    try:
        return yol.read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def kisisel_analiz(
    govde: str,
    llm: LLMClient,
    bellek: MemoryStore,
    *,
    kullanici_base: Path | None,
    model: str | None = None,
    kaynak_turu: str | None = None,
) -> tuple[str, str]:
    """3-katman kişiselleştirme: user.md (persona) + bellek retrieval + memory.md → avukat lens.

    durum: 'uretildi' | 'icerik_yok' (govde boş) | 'model_bos' (içerik var, model boş döndü).
    Persona/memory yoksa graceful (jenerik lens).
    Bellek perf ~%50 (digest) → retrieval yalnız 'öneri' katmanı, deterministik değil.
    """
    if not govde.strip():
        return "", "icerik_yok"
    persona = _oku(kullanici_base / "user.md") if kullanici_base else ""
    kurallar = _oku(kullanici_base / "memory.md") if kullanici_base else ""
    gecmis = bellek.ara(govde[:500], k=3)
    gecmis_metin = "\n".join(f"- {a.metin}" for a in gecmis)

    sistem = _LENS_SISTEM
    if kaynak_turu and (yonerge := _KAYNAK_YONERGESI.get(kaynak_turu)):
        sistem += f"\n\nKAYNAK SINIRI ({kaynak_turu}): {yonerge}"
    if persona:
        sistem += f"\n\nKULLANICI: {persona[:1000]}"
    if kurallar:
        sistem += f"\n\nKURALLAR: {kurallar[:1000]}"

    kullanici = f"İÇERİK:\n{govde[:_BAGLAM_LIMIT]}"
    if gecmis_metin:
        kullanici += f"\n\nGEÇMİŞ İLGİLİ ANALİZLER (bağlantı kur):\n{gecmis_metin}"

    analiz = llm.uret(sistem, kullanici, model=model).strip()
    if not analiz:
        # govde DOLU ama model boş döndü (timeout/refuse) → 'model_bos' (review MED): içerik
        # VAR; bunu 'icerik_yok' (govde boş) ile karıştırma — model başarısızlığını maskeleme.
        return "", "model_bos"
    # Bellek bağlantısı LLM yanıtında yoksa şeffaf bir bölüm olarak ekle (retrieval görünür).
    if gecmis_metin and "geçmiş" not in analiz.lower():
        analiz += f"\n\n## Geçmiş Analizlerle Bağlantı\n{gecmis_metin}"
    return analiz, "uretildi"
