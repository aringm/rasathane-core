from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import urlparse

from ytcore.content.llm import LLMClient
from ytcore.intel.memory import Ani, MemoryStore

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


def _gecmis_bolumu(anilar: list[Ani]) -> str:
    """Retrieval geçmiş kaydıdır; ana modelin güncel kaynak bağlamına katılmaz."""
    if not anilar:
        return ""
    lines = [
        "## Geçmiş Analiz Kayıtları",
        "Bu kayıtlar benzerlik aramasıyla getirilmiştir; güncel kaynağın kanıtı değildir. "
        "Önceki model yorumları kaynak metni veya doğrulama sonucu sayılmaz.",
    ]
    for index, ani in enumerate(anilar, 1):
        identifier = ani.meta.get("video_id") or "bilinmiyor"
        kind = ani.meta.get("kaynak_turu") or identifier.partition(":")[0]
        if kind not in _KAYNAK_YONERGESI:
            kind = "bilinmiyor"
        url = ani.meta.get("kaynak_url") or ani.meta.get("video_url") or ""
        if not url:
            match = re.search(
                r"(?:^|\n)\s*>?\s*(?:Kaynak|Resmî kaynak|Kanonik URL):\s*(https?://[^\s<>]+)",
                ani.metin,
                re.I,
            )
            url = match[1] if match else ""
        parsed = urlparse(url)
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.hostname
            or parsed.username
            or parsed.password
            or any(char.isspace() or char in "<>" for char in url)
        ):
            url = ""
        lines.extend(
            [
                f"\n### Geçmiş kayıt {index}",
                f"Kaynak türü: {kind} · Kayıt kimliği: {identifier}",
                f"Kaynak: {url}" if url else "Kaynak bağlantısı bu eski kayıtta yok.",
                "\nÖnceki analiz kaydından önizleme:",
                "\n".join("> " + line for line in ani.metin[:1000].splitlines()),
            ]
        )
        if len(ani.metin) > 1000:
            lines.append("\nÖnizleme kısaltılmıştır; eski kaydın tam metni değildir.")
    return "\n\n".join(lines)


def kisisel_analiz(
    govde: str,
    llm: LLMClient,
    bellek: MemoryStore,
    *,
    kullanici_base: Path | None,
    model: str | None = None,
    kaynak_turu: str | None = None,
) -> tuple[str, str]:
    """Persona/kurallar ve güncel kaynak → avukat lens; geçmiş retrieval ayrı kayıt bölümü.

    durum: 'uretildi' | 'icerik_yok' (govde boş) | 'model_bos' (içerik var, model boş döndü).
    Persona/memory yoksa graceful (jenerik lens).
    Bellek perf ~%50 (digest) → retrieval yalnız 'öneri' katmanı, deterministik değil.
    """
    if not govde.strip():
        return "", "icerik_yok"
    persona = _oku(kullanici_base / "user.md") if kullanici_base else ""
    kurallar = _oku(kullanici_base / "memory.md") if kullanici_base else ""
    gecmis = bellek.ara(govde[:500], k=3)

    sistem = _LENS_SISTEM
    if kaynak_turu and (yonerge := _KAYNAK_YONERGESI.get(kaynak_turu)):
        sistem += f"\n\nKAYNAK SINIRI ({kaynak_turu}): {yonerge}"
    if persona:
        sistem += f"\n\nKULLANICI: {persona[:1000]}"
    if kurallar:
        sistem += f"\n\nKURALLAR: {kurallar[:1000]}"

    kullanici = f"İÇERİK:\n{govde[:_BAGLAM_LIMIT]}"

    analiz = llm.uret(sistem, kullanici, model=model).strip()
    if not analiz:
        # govde DOLU ama model boş döndü (timeout/refuse) → 'model_bos' (review MED): içerik
        # VAR; bunu 'icerik_yok' (govde boş) ile karıştırma — model başarısızlığını maskeleme.
        return "", "model_bos"
    # Geçmiş belge gövdeleri modele verilmez; eski kayıtlar deterministik olarak ayrılır.
    if gecmis_bolumu := _gecmis_bolumu(gecmis):
        analiz += f"\n\n{gecmis_bolumu}"
    return analiz, "uretildi"
