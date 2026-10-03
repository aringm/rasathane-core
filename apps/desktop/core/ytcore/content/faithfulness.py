from __future__ import annotations

from ytcore.content.llm import LLMClient
from ytcore.content.segment import benzerlik, cumlelere_bol, semantic_chunk
from ytcore.infra.embedding import EmbeddingProvider

_JUDGE = (
    "Sen bir doğruluk denetçisisin. Verilen İDDİA, KAYNAK metinde destekleniyor mu? "
    "Yalnız tek kelime yanıtla: EVET veya HAYIR. (destekleniyor mu)"
)
_BAGLAM_LIMIT = 6000  # judge çağrısı başına karakter (num_ctx=8192 ile uyumlu, #2)


def iddialari_cikar(ozet: str) -> list[str]:
    """Özeti cümle/iddia birimlerine böl (her birini ayrı denetlemek için)."""
    return cumlelere_bol(ozet)


def faithfulness(
    ozet: str,
    kaynak: str,
    llm: LLMClient,
    *,
    esik: float = 0.8,
    model: str | None = None,
    embed: EmbeddingProvider | None = None,
    ust_chunk: int = 3,
) -> tuple[float, str]:
    """Her iddia kaynak metinde destekleniyor mu (LLM-judge entailment) → destekli oranı.

    durum: 'gecti' (skor>=esik) | 'esik_alti' | 'ozet_yok'. SelfCheckGPT/DeepEval
    SummarizationMetric deseninin torch-free lokal-judge eşi (Ollama; #2 değişmez).

    Uzun kaynak: naif kaynak[:6000] kesimi (review MED #11) sistematik düşük faithfulness
    + bosa retry üretiyordu. embed verilirse kaynak chunk'lanır ve her iddia için EN İLGİLİ
    chunk'lar (embedding benzerliği) judge'a verilir → tüm kaynak kapsanır, num_ctx korunur.
    embed yoksa kısa kaynakta [:6000] yeterli (geriye-dönük).
    Tüm kanıt bağlamları judge'dan önce hazırlanır; RAM8'de iddia başına karşı modeli
    yeniden yüklemek yerine embedding'den LLM'e yalnız bir kez geçilir.
    """
    iddialar = iddialari_cikar(ozet)
    if not iddialar:
        return 0.0, "ozet_yok"
    chunklar: list[str] | None = None
    chunk_vekt: list[list[float]] | None = None
    if embed is not None and len(kaynak) > _BAGLAM_LIMIT:
        chunklar = semantic_chunk(cumlelere_bol(kaynak), embed, hedef_kar=2000)
        if chunklar:
            chunk_vekt = embed.embed(chunklar)
    sorular: list[str] = []
    for iddia in iddialar:
        if chunklar and chunk_vekt:
            iv = embed.embed([iddia])[0]  # type: ignore[union-attr]
            sirali = sorted(range(len(chunklar)), key=lambda i: -benzerlik(iv, chunk_vekt[i]))
            secili = sorted(sirali[:ust_chunk])
            baglam = "\n".join(chunklar[i] for i in secili)
        else:
            baglam = kaynak
        sorular.append(f"İDDİA: {iddia}\n\nKAYNAK: {baglam[:_BAGLAM_LIMIT]}")
    destekli = 0
    for soru in sorular:
        yanit = llm.uret(_JUDGE, soru, model=model).strip().upper()
        if yanit.startswith("EVET"):
            destekli += 1
    skor = destekli / len(iddialar)
    return skor, ("gecti" if skor >= esik else "esik_alti")
