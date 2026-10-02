from __future__ import annotations

from pathlib import Path

import pytest
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
