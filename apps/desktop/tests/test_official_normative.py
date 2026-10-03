"""Gerçek RG çıktısındaki hüküm karışması ve yanlış web verdict regresyonları."""

from __future__ import annotations

import hashlib
import socket
from pathlib import Path
from typing import Any

import httpx
import pytest
from rasathane.sources import kaynak_edin
from ytcore.content.node import dokum_node, ozet_node
from ytcore.intel.node import factcheck_node, kisisel_node
from ytcore.pipeline.state import GState

_FIXTURE = Path(__file__).parent / "fixtures" / "resmigazete-20261003-1.htm"
_URL = "https://www.resmigazete.gov.tr/eskiler/2026/10/20261003-1.htm"


@pytest.fixture
def official_state(monkeypatch: pytest.MonkeyPatch) -> GState:
    monkeypatch.delenv("RASATHANE_SOURCE_FIXTURE", raising=False)
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *a, **k: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443))],
    )
    with httpx.Client(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200, content=_FIXTURE.read_bytes(), headers={"content-type": "text/html"}
            )
        )
    ) as client:
        source = kaynak_edin(_URL, client=client)
    from ytcore.pipeline.graph import _kaynak_belgesi_node

    monkeypatch.setattr("rasathane.sources.kaynak_edin", lambda *a, **k: source)
    state = _kaynak_belgesi_node(_URL, "enerji")
    state["icerik_tr"] = source.metin
    state["ceviri_durumu"] = "atlandi"
    return state


def _forbid(*args: Any, **kwargs: Any) -> Any:
    raise AssertionError("Resmî normatif metin modelle yeniden yazılamaz veya web'e aratılamaz.")


def test_official_summary_preserves_articles_and_conditions_without_model(
    official_state: GState, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("ytcore.content.node.llm_al", _forbid)
    monkeypatch.setattr("ytcore.content.node.embedding_al", _forbid)
    result = ozet_node(official_state)
    assert result["analysis_mode"] == "source_extracts"
    assert result["ozet_faithfulness"] is None
    assert result["ozet_faithfulness_durum"] == "kaynak_alintisi"
    detail = result["ozet"]["detay"]
    for term in ("Bağdaşmaz alan", "önlisans", "LÜY", "YEPDİS", "rotor kanat çapı"):
        assert term in detail
    assert (
        "herhangi birinin tespit edilmesi halinde başvurunun teknik değerlendirmesi uygun bulunmaz"
        in detail
    )
    assert "(5) Rüzgâr kaynağına dayalı" in detail
    assert "(8) Başvuru kapsamında" in detail
    assert "(9) Maden işletme ruhsatı sahiplerinin" in detail
    assert "MADDE 6- Bu Yönetmelik yayımı tarihinde yürürlüğe girer." in detail
    assert "Madde 8 uyarınca" not in detail
    assert "Madde 9 ise" not in detail
    assert "hataların düzeltilmesini şart koşmuştur" not in str(result["ozet"])
    assert _URL in result["ozet"]["kisa"]
    assert hashlib.sha256(_FIXTURE.read_bytes()).hexdigest() in detail
    assert "33389" in detail and "20/10/2015" in detail and "29508" in detail


def test_official_document_and_quotation_ranges_are_exact(
    official_state: GState, monkeypatch: pytest.MonkeyPatch
) -> None:
    from ytcore.content.resmi import resmi_belge

    monkeypatch.setattr("ytcore.content.node.llm_al", _forbid)
    monkeypatch.setattr("ytcore.content.node.embedding_al", _forbid)
    document = resmi_belge(official_state)
    assert document is not None
    out = dokum_node(official_state)
    assert " ".join(b["metin"] for b in out["dokum_bolumler"]) == official_state["icerik_tr"]
    assert len(document.maddeler) == 7
    assert document.yayin_tarihi == "2026-10-03"
    assert document.sayi == "33389"
    for block in document.maddeler:
        assert official_state["icerik_tr"][block.start : block.end] == block.metin


def test_official_personal_analysis_and_external_factcheck_are_explicitly_skipped(
    official_state: GState, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("ytcore.intel.node.llm_al", _forbid)
    monkeypatch.setattr("ytcore.intel.node.websearch_al", _forbid)
    monkeypatch.setattr("ytcore.intel.node.memory_al", _forbid)
    personal = kisisel_node(official_state)
    fact = factcheck_node(official_state)
    assert personal["kisisel_durum"] == "atlandi_resmi_kaynak"
    assert "Teknik Detay Raporu" not in personal["kisisel_analiz"]
    assert "kişisel veri niteliği taşır" not in personal["kisisel_analiz"]
    assert fact["factcheck_durum"] == "atlandi_resmi_kaynak"
    assert fact["factcheck_iddialar"] == []
    assert "genel web" in fact["factcheck_reason"]


@pytest.mark.parametrize(
    "overrides",
    [
        {"kaynak_turu": "youtube"},
        {"transkript_kaynak_dil": "en"},
        {"metadata_url": "https://example.com/eskiler/2026/10/20261003-1.htm"},
        {"metadata_url": "https://www.resmigazete.gov.tr.evil.test/document"},
        {"kaynak_ozel": {}},
    ],
)
def test_general_or_unverified_source_keeps_model_path(
    official_state: GState, overrides: dict[str, Any]
) -> None:
    from ytcore.content.resmi import resmi_belge

    state: GState = {**official_state}
    if "metadata_url" in overrides:
        state["metadata"] = {**state["metadata"], "kaynak_url": overrides.pop("metadata_url")}
    state.update(overrides)  # type: ignore[typeddict-item]
    assert resmi_belge(state) is None


def test_official_acquisition_keeps_actual_title_date_and_authority(official_state: GState) -> None:
    meta = official_state["metadata"]
    assert meta["baslik"].startswith("RÜZGAR KAYNAĞINA DAYALI")
    assert meta["kaynak_sahibi"] == "Enerji ve Tabii Kaynaklar Bakanlığı"
    assert meta["yayin_tarihi"] == "2026-10-03"
    assert meta["kaynak_tarihi"] == "2026-10-03"


def _replacement_text(state: GState, body: str) -> GState:
    header = state["icerik_tr"].split("MADDE 1-", 1)[0]
    return {**state, "icerik_tr": header + body, "transkript_metni": header + body}


def test_quoted_replacement_article_is_not_a_top_level_article(official_state: GState) -> None:
    from ytcore.content.resmi import resmi_belge

    state = _replacement_text(
        official_state,
        "MADDE 1- Önceki yönetmeliğin 7 nci maddesi değiştirilmiştir. "
        "“MADDE 7- (1) Birinci hüküm uygulanır. (2) İkinci hüküm uygulanır.” "
        "MADDE 2- Bu Yönetmelik yayımı tarihinde yürürlüğe girer.",
    )
    document = resmi_belge(state)
    assert document is not None
    assert [m.baslik for m in document.maddeler] == ["MADDE 1", "MADDE 2"]
    assert "“MADDE 7- (1)" in document.maddeler[0].metin
    assert document.maddeler[0].metin.endswith("uygulanır.”")
    assert " ".join(b["metin"] for b in document.dokum()) == state["icerik_tr"]


def test_inline_paragraph_reference_is_not_a_paragraph_boundary(official_state: GState) -> None:
    from ytcore.content.resmi import resmi_belge

    state = _replacement_text(
        official_state,
        "MADDE 1- (1) Bu maddenin (2) numaralı fıkrasına göre işlem yapılır. "
        "(2) Son hüküm uygulanır.",
    )
    document = resmi_belge(state)
    assert document is not None
    leaves = document.harita().cocuklar[0].cocuklar
    assert len(leaves) == 2
    assert "(2) numaralı fıkrasına göre işlem yapılır." in leaves[0].label
    assert leaves[1].label == "(2) Son hüküm uygulanır."


def test_unbalanced_quote_keeps_raw_source_without_guessed_hierarchy(
    official_state: GState,
) -> None:
    from ytcore.content.resmi import resmi_belge

    state = _replacement_text(
        official_state,
        "MADDE 1- Yeni metin: “MADDE 7- (1) Hüküm uygulanır. "
        "MADDE 2- Bu Yönetmelik yayımı tarihinde yürürlüğe girer.",
    )
    document = resmi_belge(state)
    assert document is not None
    assert document.provenance()["structure_status"] == "unbalanced_quotes_raw_text"
    assert " ".join(b["metin"] for b in document.dokum()) == state["icerik_tr"]
    assert document.harita().cocuklar[0].cocuklar == []


def test_inline_quoted_term_never_truncates_a_condition_sentence(official_state: GState) -> None:
    from ytcore.content.resmi import resmi_belge

    sentence = "MADDE 1- Belgenin “izin” alanı doldurulmadığında başvuru reddedilir."
    document = resmi_belge(_replacement_text(official_state, sentence))
    assert document is not None
    assert sentence in document.ozet()["kisa"]
    assert sentence in document.ozet()["orta"]


def test_full_official_pipeline_has_no_paraphrase_and_skipped_verdict_artifact(
    official_state: GState,
    tmp_output_base: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from ytcore.pipeline.api import kaynak_analiz_et

    monkeypatch.setattr("ytcore.content.node.llm_al", _forbid)
    monkeypatch.setattr("ytcore.intel.node.llm_al", _forbid)
    monkeypatch.setattr("ytcore.intel.node.websearch_al", _forbid)
    monkeypatch.setattr("ytcore.uretim.node.llm_al", _forbid)
    result = kaynak_analiz_et(
        url=_URL, konu="enerji", thread_id="official-source-only", checkpoint_dir=tmp_path
    )
    assert result.analysis_mode == "source_extracts"
    assert result.ozet_faithfulness is None
    assert result.factcheck_durum == "atlandi_resmi_kaynak"
    assert result.factcheck_iddia_sayisi == 0
    assert result.kisisel_durum == "atlandi_resmi_kaynak"
    assert result.harita_durum == "uretildi"
    summary = result.quality_provenance["summary"]
    assert summary["method"] == "direct_source_quotes"
    assert summary["independent_verification"] is False
    assert summary["attachments_followed"] is False
    folder = Path(result.klasor)
    md = (folder / "04_ozet.md").read_text(encoding="utf-8")
    assert "Skor: 0.00" not in md
    assert "Doğrudan kaynak alıntıları" in md
    skipped = (folder / "06_fact-check.md").read_text(encoding="utf-8")
    assert "atlandı" in skipped
    assert _URL in skipped
    assert "**Karar:**" not in skipped


def test_model_claim_intro_is_never_queried() -> None:
    from ytcore.intel.factcheck import fact_check
    from ytcore.intel.websearch import AramaSonuc

    class Model:
        def uret(self, system: str, user: str, *, model: str | None = None) -> str:
            if "verdict" in system:
                return "BELİRSİZ"
            return (
                "İşte metinden çıkarılan doğrulanabilir olgusal iddialar:\n\n"
                "1. Rüzgâr enerjisi payı yüzde 20 oldu.\n- Yıllık artış yüzde 1 oldu."
            )

    class Search:
        def __init__(self) -> None:
            self.queries: list[str] = []

        def ara(self, query: str, n: int = 5) -> list[AramaSonuc]:
            self.queries.append(query)
            return []

    web = Search()
    claims, _ = fact_check("Örnek kaynak metni.", Model(), web)
    assert len(claims) == 2
    assert len(web.queries) == 2
    assert all("İşte metinden" not in q for q in web.queries)
    assert claims[0]["iddia"].startswith("Rüzgâr enerjisi")
