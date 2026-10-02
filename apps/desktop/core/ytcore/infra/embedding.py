from __future__ import annotations

import hashlib
import math
import os
from typing import Protocol, runtime_checkable

from ytcore.config import get_config
from ytcore.infra.vram import bge_m3_batch_guvenli


@runtime_checkable
class EmbeddingProvider(Protocol):
    ad: str
    lisans: str

    def embed(self, metinler: list[str]) -> list[list[float]]: ...


def _ollama_embed_batched(
    host: str, model: str, metinler: list[str], batch: int
) -> list[list[float]]:
    """Ollama embed — listeyi güvenli batch'lere bölerek (≤16GB #2: global batch sınırı).
    Tüm provider'lar bu ortak kontrata uyar (review LOW #15: asimetrik guard yok)."""
    import ollama

    if not metinler:
        return []
    istemci = ollama.Client(host=host)
    cikti: list[list[float]] = []
    for i in range(0, len(metinler), max(1, batch)):
        yanit = istemci.embed(model=model, input=metinler[i : i + batch])
        cikti.extend([list(v) for v in yanit["embeddings"]])
    return cikti


class BgeM3Provider:
    """bge-m3 embedding — Ollama HTTP üzerinden (torch ana engine'e GİRMEZ, #2 değişmez).

    Batch guard: A03-doğrulama batch=256 ~5.7GB global sınır → büyük listeyi güvenli
    batch'lere böler (bge_m3_batch_guvenli ile en geniş güvenli batch). MIT lisans
    (ticari-net — avukat ofisi). Faz 2 segmentasyon/keyword/semantic-chunk bunu kullanır.
    """

    ad = "bge-m3"
    lisans = "MIT"

    def __init__(self, model: str | None = None, host: str | None = None) -> None:
        cfg = get_config()
        self.model = model or cfg.ollama_embedding_model
        self.host = host or cfg.ollama_host

    def _guvenli_batch(self) -> int:
        # En geniş güvenli batch'i bul (kaba; Faz 2 empirik kalibre eder).
        for b in (256, 128, 64, 32, 16, 8):
            if bge_m3_batch_guvenli(b):
                return b
        return 8

    def embed(self, metinler: list[str]) -> list[list[float]]:
        return _ollama_embed_batched(self.host, self.model, metinler, self._guvenli_batch())


class FakeEmbedding:
    """Deterministik test embedding (ağsız/torch'suz/Ollama'sız). Hash→sözde-vektör.

    Normalize edilmiş → kosinüs benzerliği nokta-çarpımına eşit (segment.py varsayımı).
    """

    ad = "fake"
    lisans = "test"
    boyut = 64

    def embed(self, metinler: list[str]) -> list[list[float]]:
        vektorler: list[list[float]] = []
        for m in metinler:
            h = hashlib.sha256(m.encode("utf-8")).digest()
            ham = [h[i % len(h)] / 255.0 for i in range(self.boyut)]
            norm = math.sqrt(sum(x * x for x in ham)) or 1.0
            vektorler.append([x / norm for x in ham])
        return vektorler


class Qwen3EmbeddingProvider:
    """Opsiyonel kalite katmanı — MS MARCO non-commercial lisans riski (A09).

    Varsayılan DEĞİL; eval A/B sonrası bilinçli seçilirse. bge-m3 (MIT) birincil.
    """

    ad = "qwen3-embedding:8b"
    lisans = "Apache-2.0 (MS MARCO non-commercial riski — A09)"

    def __init__(self, host: str | None = None) -> None:
        self.host = host or get_config().ollama_host

    def embed(self, metinler: list[str]) -> list[list[float]]:
        # BgeM3 ile aynı batch'leme kontratı (review LOW #15: asimetrik VRAM guard yok).
        # qwen3-emb için bge-spesifik bütçe modeli yok → muhafazakâr sabit batch=32.
        return _ollama_embed_batched(self.host, "qwen3-embedding:8b", metinler, 32)


def get_embedding_provider(ad: str = "bge-m3") -> EmbeddingProvider:
    """Provider'ı ADA göre döndür (seam YOK — 'varsayılan ne' sorusu). bge-m3 (MIT)
    lisans-net default; qwen3-emb opsiyonel kalite katmanı (A09 lisans riski)."""
    if ad.startswith("qwen3"):
        return Qwen3EmbeddingProvider()
    return BgeM3Provider()


def embedding_al(ad: str | None = None) -> EmbeddingProvider:
    """YT_EMBED_FIXTURE set ise FakeEmbedding (hermetik test/exe), değilse gerçek provider.

    Faz 1 fetcher_al() seam deseninin embedding karşılığı: tüm Faz 2 hattı ağsız/
    torch'suz/Ollama'sız hermetik koşar (exe selftest 03/04 üretimini de doğrular).
    motor_backend=llamacpp ise gömülü bge-m3 GGUF sunucusu kullanılır (kurulumda
    Ollama GEREKMEZ); ad override'ı yalnız Ollama backend'inde anlamlıdır.
    """
    if os.environ.get("YT_EMBED_FIXTURE", "").strip():
        return FakeEmbedding()
    if get_config().motor_backend == "llamacpp":
        from ytcore.local.llamacpp import LlamaCppEmbedding

        return LlamaCppEmbedding()
    return get_embedding_provider(ad or "bge-m3")
