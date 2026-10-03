from __future__ import annotations

import pytest
from ytcore.intel.factcheck import fact_check
from ytcore.intel.websearch import AramaSonuc


class _Model:
    def __init__(self, verdict: str = "DESTEKLİYOR") -> None:
        self.verdict = verdict
        self.verdict_calls = 0

    def uret(self, system: str, user: str, *, model: str | None = None) -> str:
        if "verdict" in system:
            self.verdict_calls += 1
            return self.verdict
        return user


class _Search:
    def __init__(self, *items: AramaSonuc) -> None:
        self.items = list(items)

    def ara(self, query: str, n: int = 5) -> list[AramaSonuc]:
        return self.items[:n]


def test_irrelevant_snippets_cannot_validate_transformer_claim() -> None:
    claim = "Transformer WMT 2014 çeviri görevinde 28,4 BLEU puanı elde etti."
    model = _Model()
    search = _Search(
        AramaSonuc(claim, "https://bilet.ornek.test/", "Konser takvimi ve bilet fiyatları."),
        AramaSonuc(
            "Üniversite",
            "https://universite.ornek.test/",
            "Başvuru takvimi 2014 yılında yenilendi.",
        ),
    )

    items, status = fact_check(claim, model, search)

    assert status == "uretildi"
    assert items[0]["karar"] == "BELİRSİZ"
    assert items[0]["guven"] == 0.0
    assert model.verdict_calls == 0
    assert "ilişkili" in items[0]["gerekce"]
    assert items[0]["ilgili_kaynaklar"] == []
    assert items[0]["bagimsiz_dogrulama"] is False


@pytest.mark.parametrize("verdict", ["DESTEKLİYOR", "ÇELİŞİYOR"])
def test_even_exact_search_snippet_is_not_independent_verification(verdict: str) -> None:
    claim = "Transformer WMT 2014 çeviri görevinde 28,4 BLEU puanı elde etti."
    model = _Model(verdict)
    url = "https://makale.ornek.test/transformer"
    items, _ = fact_check(claim, model, _Search(AramaSonuc("Makale", url, claim)))

    assert model.verdict_calls == 1
    assert items[0]["karar"] == "BELİRSİZ"
    assert items[0]["aday_karar"] == verdict
    assert items[0]["guven"] == 0.0
    assert items[0]["kanit_turu"] == "arama_ozeti"
    assert items[0]["bagimsiz_dogrulama"] is False
    assert items[0]["ilgili_kaynaklar"] == [url]
    assert "tam metni okunmadı" in items[0]["gerekce"]


def test_related_text_without_claim_numbers_is_not_grounded() -> None:
    claim = "Transformer WMT 2014 çeviri görevinde 28,4 BLEU puanı elde etti."
    snippet = "Transformer WMT 2014 çeviri görevinde yüksek BLEU puanı elde etti."
    model = _Model()
    items, _ = fact_check(
        claim, model, _Search(AramaSonuc("Makale", "https://makale.ornek.test/", snippet))
    )

    assert model.verdict_calls == 0
    assert items[0]["karar"] == "BELİRSİZ"
    assert items[0]["guven"] == 0.0
    assert "sayısal" in items[0]["gerekce"]


def test_numbers_cannot_be_combined_between_unrelated_snippets() -> None:
    claim = "Transformer WMT 2014 çeviri görevinde 28,4 BLEU puanı elde etti."
    model = _Model()
    items, _ = fact_check(
        claim,
        model,
        _Search(
            AramaSonuc(
                "Makale",
                "https://makale.ornek.test/",
                "Transformer WMT 2014 çeviri görevinde BLEU puanı elde etti.",
            ),
            AramaSonuc("Konser", "https://bilet.ornek.test/", "Konser giriş bileti 28,4 liradır."),
        ),
    )

    assert model.verdict_calls == 0
    assert items[0]["karar"] == "BELİRSİZ"
    assert items[0]["ilgili_kaynaklar"] == []


def test_decimal_comma_and_case_folding_only_enable_candidate_assessment() -> None:
    claim = "Enflasyon 2025 yılında yüzde 40 arttı."
    model = _Model()
    items, _ = fact_check(
        claim,
        model,
        _Search(
            AramaSonuc(
                "İSTATİSTİK",
                "https://bilet.ornek.test/",
                "ENFLASYON 2025 YILINDA YÜZDE 40,0 ARTTI.",
            )
        ),
    )

    assert model.verdict_calls == 1  # Domain reputation cannot replace text relevance.
    assert items[0]["karar"] == "BELİRSİZ"
    assert items[0]["aday_karar"] == "DESTEKLİYOR"
    assert items[0]["bagimsiz_dogrulama"] is False


def test_cloud_is_not_called_for_unrelated_snippets() -> None:
    class Cloud:
        def cagir(self, *args: object, **kwargs: object) -> None:
            pytest.fail("İlgisiz arama özeti cloud verdict çağrısı başlatmamalı.")

    items, _ = fact_check(
        "Transformer WMT çeviri mimarisi yalnız dikkat mekanizması kullanır.",
        _Model(),
        _Search(AramaSonuc("Gezi", "https://makale.ornek.test/", "Tatil rehberi ve biletler.")),
        cloud=Cloud(),
    )
    assert items[0]["karar"] == "BELİRSİZ"
    assert items[0]["aday_karar"] is None


def test_grounding_metadata_survives_result_serialization() -> None:
    from ytcore.models import FactIddia

    claim = "Enflasyon 2025 yılında yüzde 40 arttı."
    items, _ = fact_check(
        claim, _Model(), _Search(AramaSonuc("Veri", "https://makale.ornek.test/", claim))
    )
    serialized = FactIddia.model_validate(items[0]).model_dump()
    assert serialized["aday_karar"] == "DESTEKLİYOR"
    assert serialized["kanit_turu"] == "arama_ozeti"
    assert serialized["bagimsiz_dogrulama"] is False
    assert serialized["ilgili_kaynaklar"] == ["https://makale.ornek.test/"]


def test_old_model_verdict_export_does_not_claim_verification(tmp_path) -> None:
    from ytcore.models import IndexKaydi
    from ytcore.output.factcheck_yaz import factcheck_yaz

    record = IndexKaydi(
        video_url="https://makale.ornek.test/",
        video_id="public",
        baslik="Kaynak",
        anadil="tr",
        kanal="Kaynak",
        konu="genel",
        uretici_slug="kaynak",
        video_slug="public",
        analiz_tarihi="2026-10-03",
    )
    path = factcheck_yaz(
        tmp_path,
        record,
        [{"iddia": "Enflasyon arttı.", "karar": "DESTEKLİYOR", "guven": 0.6}],
        "uretildi",
    )
    text = path.read_text(encoding="utf-8")
    assert "**Karar:** BELİRSİZ" in text
    assert "**Güven:**" not in text
    assert "Bağımsız doğrulama kayıtlı değil" in text
    assert "Web doğrulama:" not in text
