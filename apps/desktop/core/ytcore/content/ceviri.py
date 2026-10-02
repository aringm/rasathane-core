from __future__ import annotations

from ytcore.content.llm import LLMClient

_SISTEM = (
    "Sen profesyonel bir hukuk çevirmenisin. Verilen metni İngilizceden modern, akıcı, "
    "profesyonel Türkçeye çevir. Yalnız çeviriyi döndür; açıklama/yorum ekleme. "
    "Terimleri tutarlı çevir.{glossary}"
)


def ceviri_gerekli_mi(kaynak_dil: str | None) -> bool:
    """Kaynak TR ise çeviri ATLA. tr/TR/tr-* → False; aksi True (None/boş dahil — A02
    çeviri-atla mantığı). Yanlış 'tr' tespiti riski node düzeyinde guard'lı."""
    if not kaynak_dil:
        return True
    return not kaynak_dil.strip().lower().startswith("tr")


def cevir(metin: str, llm: LLMClient, glossary_metni: str = "", model: str | None = None) -> str:
    """EN→TR çeviri (glossary kısıtlı, torch-free Ollama). Boş girdi → boş çıktı (atlama).
    Boş model çıktısı → ValueError (boş≠başarı; sessiz boş çeviri ÜRETME — Faz 1 dersi)."""
    if not metin.strip():
        return ""
    glossary_ek = f"\n{glossary_metni}" if glossary_metni.strip() else ""
    sistem = _SISTEM.format(glossary=glossary_ek)
    cikti = llm.uret(sistem, metin, model=model).strip()
    if not cikti:
        raise ValueError("Çeviri boş döndü (boş≠başarı)")
    return cikti
