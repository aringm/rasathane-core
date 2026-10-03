from __future__ import annotations

from pathlib import Path

import pytest
from rasathane.sources import KaynakBelgesi, KaynakTuru
from ytcore.pipeline.api import analiz_et, kaynak_analiz_et


@pytest.mark.parametrize(
    ("url", "tur"),
    [
        ("https://github.com/openai/openai-python", "github"),
        ("https://arxiv.org/abs/2401.12345", "arxiv"),
        ("https://www.reddit.com/r/python/comments/abc123/ornek/", "reddit"),
        ("https://huggingface.co/openai/model", "huggingface"),
        ("https://example.com/yazi", "web"),
    ],
)
def test_youtube_disi_kaynak_ortak_hattan_gecer(
    tmp_output_base: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    url: str,
    tur: str,
) -> None:
    monkeypatch.setenv("RASATHANE_SOURCE_FIXTURE", "1")
    sonuc = kaynak_analiz_et(
        url=url,
        konu="genel",
        thread_id=f"source-{tur}",
        checkpoint_dir=tmp_path / tur,
    )

    assert sonuc.stub is False
    assert sonuc.kaynak_turu == tur
    assert sonuc.kaynak_durumu == "fixture"
    assert sonuc.transkript_durumu == "kaynak"
    assert sonuc.transkript_karakter > 0
    assert sonuc.index.kaynak_turu == tur
    assert sonuc.index.kaynak_url.startswith("https://")
    assert sonuc.index.video_id.startswith(f"{tur}:")
    assert sonuc.kaynak_sinyalleri
    klasor = Path(sonuc.klasor)
    assert (klasor / "01_kaynak-icerigi.md").is_file()
    assert not (klasor / "01_transcript_orijinal.md").exists()


def test_legacy_analiz_et_youtube_dosya_adini_korur(
    tmp_output_base: Path,
    tmp_path: Path,
) -> None:
    sonuc = analiz_et(
        url="https://youtu.be/abc123",
        konu="genel",
        thread_id="legacy-youtube-source-fields",
        checkpoint_dir=tmp_path,
    )

    assert sonuc.kaynak_turu == "youtube"
    assert sonuc.index.kaynak_turu == "youtube"
    assert sonuc.index.kaynak_id == sonuc.index.video_id
    assert (Path(sonuc.klasor) / "01_transcript_orijinal.md").is_file()
    assert not (Path(sonuc.klasor) / "01_kaynak-icerigi.md").exists()


def test_guvensiz_web_url_ag_istegi_yapmadan_hata_sonucu_uretir(
    tmp_output_base: Path,
    tmp_path: Path,
) -> None:
    sonuc = kaynak_analiz_et(
        url="http://127.0.0.1:8000/gizli",
        konu="genel",
        thread_id="ssrf-block",
        checkpoint_dir=tmp_path,
    )

    assert sonuc.kaynak_turu == "web"
    assert sonuc.kaynak_durumu == "guvensiz_hedef"
    assert sonuc.transkript_durumu == "hata"
    assert sonuc.cloud_cagrisi_sayisi == 0


def test_arxiv_abstract_scope_and_summary_method_reach_actual_saved_outputs(
    tmp_output_base: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import hashlib

    original = (
        "Old sequence models use RNN or CNN. Attention connects these models. "
        "Our new Transformer uses only attention. Performance is 28.4 BLEU and 41.8 BLEU."
    )
    translated = (
        "Eski dizi modelleri RNN veya CNN kullanır. Dikkat bu modelleri bağlar. "
        "Yeni Transformer yalnız dikkat kullanır. Sonuçlar 28,4 BLEU ve 41,8 BLEU'dur."
    )
    original_hash = hashlib.sha256(original.encode()).hexdigest()
    source = KaynakBelgesi(
        tur=KaynakTuru.arxiv,
        kimlik="1706.03762v7",
        kanonik_url="https://arxiv.org/abs/1706.03762v7",
        baslik="Örnek akademik yayın",
        dil="en",
        metin=original,
        ozel={
            "text_scope": "abstract_only",
            "full_text_fetched": False,
            "original_text_sha256": original_hash,
        },
        edinim_durumu="kismi",
    )
    monkeypatch.setattr("rasathane.sources.kaynak_edin", lambda *args, **kwargs: source)
    monkeypatch.setattr("ytcore.content.node.cevir", lambda *args, **kwargs: translated)
    result = kaynak_analiz_et(
        url=source.kanonik_url,
        konu="genel",
        thread_id="arxiv-abstract-scope",
        checkpoint_dir=tmp_path,
    )
    assert result.kaynak_durumu == "kismi"
    assert result.analysis_mode == "model_analysis"
    assert result.ozet_orta == translated
    assert result.ozet_kisa == ". ".join(translated.split(". ")[:3]) + "."
    provenance = result.quality_provenance
    assert provenance["source"]["text_scope"] == "abstract_only"
    assert provenance["source"]["full_text_fetched"] is False
    assert provenance["source"]["original_text_sha256"] == original_hash
    assert provenance["summary"]["method"] == "source_sentence_selection_and_model_summary"
    assert provenance["summary"]["layers"]["kisa"] == "translated_source_sentences"
    assert provenance["summary"]["layers"]["orta"] == "translated_source_sentences"
    assert provenance["summary"]["layers"]["detay"] == "local_model_summary"
    assert (
        provenance["summary"]["reference_sha256"] == hashlib.sha256(translated.encode()).hexdigest()
    )
    assert provenance["summary"]["original_reference"] == "01_kaynak-icerigi.md"
    assert provenance["faithfulness"]["evaluated_output"] == "ozet_detay"
    assert provenance["faithfulness"]["independent_verification"] is False
    folder = Path(result.klasor)
    raw = (folder / "01_kaynak-icerigi.md").read_text(encoding="utf-8")
    assert original in raw
    assert "tam makale edinilmedi" in raw
    report = (folder / "04_ozet.md").read_text(encoding="utf-8")
    assert "Türkçe model çevirisinden doğrudan cümleler" in report
    assert "tam makale incelenmedi" in report
    assert "28,4 BLEU" in report
