from __future__ import annotations

import os
from typing import Protocol, runtime_checkable

from ytcore.config import get_config


@runtime_checkable
class LLMClient(Protocol):
    def uret(self, sistem: str, kullanici: str, *, model: str | None = None) -> str: ...


class OllamaLLM:
    """Ollama chat — torch-free üretim (çeviri/özet/judge). Düşük sıcaklık (tutarlılık).

    Engine yalnız HTTP istemcisi; torch/transformers IMPORT ETMEZ (#2 değişmez —
    Ollama dış-server). Model config'ten (qwen2.5:14b) ya da çağrı-bazlı override.
    """

    def __init__(
        self, model: str | None = None, host: str | None = None, num_ctx: int | None = None
    ) -> None:
        cfg = get_config()
        self.model = model or cfg.ollama_reduce_model
        self.host = host or cfg.ollama_host
        # ≤16GB (#2): num_ctx KV cache'i sınırlar (qwen2.5:14b@32K=17GB tek-GPU'ya sığmaz).
        self.num_ctx = num_ctx or cfg.ollama_num_ctx

    def uret(self, sistem: str, kullanici: str, *, model: str | None = None) -> str:
        import ollama

        istemci = ollama.Client(host=self.host)
        yanit = istemci.chat(
            model=model or self.model,
            messages=[
                {"role": "system", "content": sistem},
                {"role": "user", "content": kullanici},
            ],
            options={"temperature": 0.2, "num_ctx": self.num_ctx},
            think=False,
        )
        return str(yanit["message"]["content"])


class FakeLLM:
    """Deterministik test LLM (ağsız/Ollama'sız). Görevi sistem prompt'undan sezer →
    tüm Faz 2 hattı hermetik koşar (exe selftest 02/03/04 üretir, fast testler ağsız)."""

    def uret(self, sistem: str, kullanici: str, *, model: str | None = None) -> str:
        s = sistem.lower()
        # Faz 4 harita EN BAŞTA (en spesifik): JSON şema token'ı '"cocuklar"' ile tespit —
        # ASCII (Türkçe İ.lower()="zi̇hi̇n" combining-dot tuzağından kaçınır) + şemadaki
        # "kök başlık" örneği aşağıdaki başlık dalını yanlış tetiklemesin diye önce gelir.
        # YALNIZ deterministik şema token'ı (review tur-1: "mind map" kolu kaldırıldı —
        # dinamik persona/memory.md "mind map" içerirse kişisel-analiz'i yanlış yönlendirirdi).
        if '"cocuklar"' in sistem:
            import json

            kelimeler = [w.strip(".,;:") for w in kullanici.split() if len(w) > 4][:3]
            cocuklar = [{"label": k[:20], "cocuklar": []} for k in kelimeler] or [
                {"label": "dal", "cocuklar": []}
            ]
            return json.dumps({"label": "Harita", "cocuklar": cocuklar}, ensure_ascii=False)
        # Faz 6 temizlik: ÇEVİR/ÖZET dallarından ÖNCE (prompt "çevirme/özetleme" içerir → yanlış
        # dalı tetiklemesin). Temizlik = içerik-koruyan passthrough (hermetik: metin kaybolmaz).
        if "temizle" in s:
            return kullanici.strip()
        if "evet/hayir" in s or "destekleniyor mu" in s:
            return "EVET"
        if "çevir" in s or "cevir" in s or "translate" in s:
            return "[tr] " + kullanici.strip()
        if "özet" in s or "ozet" in s or "tl;dr" in s or "tek cümle" in s:
            cumleler = [c.strip() for c in kullanici.replace("\n", " ").split(".") if c.strip()]
            return (cumleler[0] if cumleler else "özet") + "."
        if "başlık" in s or "baslik" in s:
            kelimeler = kullanici.split()[:4]
            return " ".join(kelimeler).title() or "Bölüm"
        return kullanici.strip()[:200]


def llm_al(model: str | None = None) -> LLMClient:
    """Backend seçimi: YT_LLM_FIXTURE set ise FakeLLM (hermetik); değilse config
    motor_backend'e göre gömülü llama.cpp (kurulumda Ollama GEREKMEZ) ya da Ollama."""
    if os.environ.get("YT_LLM_FIXTURE", "").strip():
        return FakeLLM()
    if get_config().motor_backend == "llamacpp":
        from ytcore.local.llamacpp import LlamaCppLLM

        return LlamaCppLLM(model=model)
    return OllamaLLM(model=model)
