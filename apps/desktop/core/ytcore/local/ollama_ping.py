from __future__ import annotations

import time
from dataclasses import dataclass

import httpx

from ytcore.config import get_config


@dataclass
class PingSonuc:
    basarili: bool
    sure_ms: float
    yanit: str
    model: str


def _mevcut_modeller(host: str, timeout: float = 2.0) -> list[tuple[str, int]]:
    """(ad, byte-boyut) listesi döndür; erişilemezse boş."""
    try:
        r = httpx.get(f"{host}/api/tags", timeout=timeout)
        r.raise_for_status()
        return [(m["name"], int(m.get("size", 0))) for m in r.json().get("models", [])]
    except Exception:
        return []


def modeller_listele(host: str, timeout: float = 3.0) -> list[dict[str, object]]:
    """Yüklü Ollama modellerini ayrıntılı listele (/api/tags details). Erişilemezse [].

    Generation modeli seçimi için: embedding modelleri (adında embed/bge VEYA family=bert)
    embedding_mi=True işaretlenir — GUI bunları generation dropdown'undan eler."""
    try:
        r = httpx.get(f"{host}/api/tags", timeout=timeout)
        r.raise_for_status()
        cikti: list[dict[str, object]] = []
        for m in r.json().get("models", []):
            ad = str(m.get("name", ""))
            det = m.get("details") or {}
            aile = str(det.get("family", ""))
            cikti.append(
                {
                    "ad": ad,
                    "boyut_bayt": int(m.get("size", 0)),
                    "parametre": str(det.get("parameter_size", "")),
                    "quant": str(det.get("quantization_level", "")),
                    "aile": aile,
                    "embedding_mi": _embedding_modeli_mi(ad) or aile == "bert",
                }
            )
        return cikti
    except Exception:
        return []


def ollama_erisilebilir(timeout: float = 5.0) -> bool:
    """Ollama server'a erişilebilir mi (en az bir model gerekmez, sadece API)."""
    try:
        r = httpx.get(f"{get_config().ollama_host}/api/tags", timeout=timeout)
        return r.status_code == 200
    except Exception:
        return False


def ping_modeli_sec(host: str) -> str | None:
    """Yapılandırılan modeli kullan; yoksa mevcut en küçük chat-modeline düş.

    Model değişimlerine bağışık: araştırmanın qwen3:8b'si yoksa makinedeki
    en küçük chat-uygun modeli (embedding hariç) seçer. None = hiç model yok.
    """
    cfg = get_config()
    mevcut = _mevcut_modeller(host)
    adlar = {ad for ad, _ in mevcut}
    if cfg.ollama_ping_model in adlar:
        return cfg.ollama_ping_model
    chat = [(ad, boyut) for ad, boyut in mevcut if not _embedding_modeli_mi(ad)]
    if not chat:
        return None
    return min(chat, key=lambda x: x[1])[0]  # en küçük = en hızlı cold-start


def _embedding_modeli_mi(ad: str) -> bool:
    """Embedding modelini chat-fallback'ten ele. 'embedding' adında geçmeyen ama
    embedding olan modelleri (bge-m3, *-embed) de yakala → /api/chat'te 400 vermesin."""
    a = ad.lower()
    return "embed" in a or a.startswith("bge") or "bge-" in a


def ollama_ping(prompt: str = "Merhaba, tek kelimeyle yanıtla: hazir.") -> PingSonuc:
    """GERÇEK Ollama round-trip — local inference yolunu kanıtlar."""
    cfg = get_config()
    model = ping_modeli_sec(cfg.ollama_host)
    if model is None:
        raise RuntimeError("Ollama'da kullanılabilir chat modeli yok")
    t0 = time.perf_counter()
    r = httpx.post(
        f"{cfg.ollama_host}/api/chat",
        json={
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "stream": False,
            "think": False,
        },
        timeout=180,
    )
    r.raise_for_status()
    sure = (time.perf_counter() - t0) * 1000
    yanit = r.json().get("message", {}).get("content", "")
    return PingSonuc(basarili=True, sure_ms=sure, yanit=yanit, model=model)
