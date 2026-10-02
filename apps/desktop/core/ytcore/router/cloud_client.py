from __future__ import annotations

from dataclasses import dataclass

_ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"
_API_SURUM = "2023-06-01"


class CloudAnahtarYok(Exception):
    """ANTHROPIC_API_KEY yok — cloud çağrısı yapılamaz (env-gated; sessiz no-op YOK)."""


class KVKKEgressEngellendi(Exception):
    """Metin PII/kişi-adı içeriyor — cloud egress KVKK fail-closed reddedildi (değişmez #1)."""


@dataclass
class CloudYanit:
    metin: str
    girdi_token: int
    cikti_token: int


def _egress_temiz_mi(metin: str, ner: object | None = None) -> bool:
    """Pattern-PII (egress_pii_var_mi) VE ad-soyad NER — İKİSİ de temiz olmalı (fail-closed).

    ner: çağıranın memo'lu instance'ı (review tur-1: cagir-başına yeni SubprocessNER spawn
    etme — CloudClient kendi instance'ını geçirir; None → taze ner_al()).
    """
    from ytcore.intel.anonim import egress_pii_var_mi
    from ytcore.router.ner import NERTespit, ner_al

    if egress_pii_var_mi(metin):
        return False
    tespit: NERTespit = ner if ner is not None else ner_al()  # type: ignore[assignment]
    return not tespit.kisi_var_mi([metin])[0]


class CloudClient:
    """Anthropic Messages API istemcisi (httpx REST — CloudTTS/Serper deseni).

    OAuth/abonelik token YASAK (ToS enforcement 2026-01-09) — yalnız ANTHROPIC_API_KEY.
    KVKK guard ÇAĞRININ İÇİNDE (tek enforcement noktası — Faz 3 'fonksiyon var ≠ çağrılıyor'
    dersi): çağıran unutamaz. cagri_sayisi = '0-cloud' kanıtı (yalnız GERÇEK HTTP çağrıları
    sayar; Faz 0-4 stub'ı kaldırıldı); token sayaçları = maliyet takibi (A14).
    """

    def __init__(self, api_key: str | None, model: str | None = None) -> None:
        if model is None:
            from ytcore.config import get_config

            model = get_config().anthropic_model
        self.api_key = api_key
        self.model = model
        self.cagri_sayisi = 0
        self.toplam_girdi_token = 0
        self.toplam_cikti_token = 0
        self._ner: object | None = None  # memo'lu NER reuse (cagir-başına spawn yok)

    def cagir(self, anonim_metin: str, system: str, max_tokens: int = 1024) -> CloudYanit:
        if not self.api_key:
            raise CloudAnahtarYok("ANTHROPIC_API_KEY yok: cloud çağrısı yapılamaz")
        if self._ner is None:
            from ytcore.router.ner import ner_al

            self._ner = ner_al()
        # Guard system + içerik BİRLEŞİK metne uygulanır (review tur-1: system bugün sabit
        # ama gelecekteki dinamik-system çağıranı guard'ı atlamasın — latent deliği kapat).
        if not _egress_temiz_mi(f"{system}\n{anonim_metin}", self._ner):
            raise KVKKEgressEngellendi(
                "PII/kişi adı tespit edildi ya da NER doğrulanamadı: cloud egress reddedildi "
                "(KVKK fail-closed)"
            )
        import httpx

        r = httpx.post(
            _ANTHROPIC_URL,
            headers={
                "x-api-key": self.api_key,
                "anthropic-version": _API_SURUM,
                "content-type": "application/json",
            },
            json={
                "model": self.model,
                "max_tokens": max_tokens,
                "system": system,
                "messages": [{"role": "user", "content": anonim_metin}],
            },
            timeout=120.0,
        )
        # Sayaç POST'tan hemen sonra (review tur-1: 429/500 yanıtı da GERÇEK egress'tir —
        # '0-cloud kanıtı' başarısız HTTP çağrısını da saymalı; dürüst sayaç).
        self.cagri_sayisi += 1
        r.raise_for_status()
        data = r.json()
        usage = data.get("usage") or {}
        girdi = int(usage.get("input_tokens") or 0)  # null-güvenli (int(None) TypeError olmasın)
        cikti = int(usage.get("output_tokens") or 0)
        self.toplam_girdi_token += girdi
        self.toplam_cikti_token += cikti
        metin = "".join(
            b.get("text", "") for b in data.get("content", []) if b.get("type") == "text"
        )
        return CloudYanit(metin=metin, girdi_token=girdi, cikti_token=cikti)
