from __future__ import annotations

from pathlib import Path

from ytcore.content.dokum import DokumBolum
from ytcore.models import IndexKaydi
from ytcore.output.dokum_yaz import dokum_yaz


def _kayit() -> IndexKaydi:
    return IndexKaydi(
        video_url="https://youtu.be/x",
        video_id="x",
        baslik="B",
        anadil="tr",
        kanal="K",
        konu="hukuk",
        uretici_slug="k",
        video_slug="x",
        analiz_tarihi="2026-06-08",
        sure_sn=120,
    )


def _bolumler() -> list[DokumBolum]:
    return [
        DokumBolum(0, "Giriş", "Metin bir.", ["sözleşme"]),
        DokumBolum(60, "Gelişme", "Metin iki.", ["tazminat"]),
    ]


def test_dokum_yaz_md(tmp_path: Path):
    paths = dokum_yaz(tmp_path, _kayit(), _bolumler(), pdf=False, docx=False)
    md = tmp_path / "03_dokum.md"
    assert md in paths
    icerik = md.read_text(encoding="utf-8")
    assert "Giriş" in icerik and "Gelişme" in icerik
    assert "[00:00]" in icerik and "[01:00]" in icerik
    assert "**Anahtar:** sözleşme" in icerik
    assert "Av. Mehmet Arın Gülüm" in icerik


def test_dokum_yaz_timestamp_yok(tmp_path: Path):
    bolumler = [DokumBolum(None, "Tek", "Metin.", [])]
    md = (dokum_yaz(tmp_path, _kayit(), bolumler, pdf=False, docx=False))[0]
    icerik = md.read_text(encoding="utf-8")
    assert "## Tek" in icerik  # timestamp yoksa sadece başlık


def test_dokum_yaz_docx(tmp_path: Path):
    paths = dokum_yaz(tmp_path, _kayit(), _bolumler(), pdf=False, docx=True)
    docx_p = tmp_path / "03_dokum.docx"
    assert docx_p.is_file()
    assert docx_p in paths


def test_dokum_yaz_typ_temizlik_basarisizlikta(tmp_path: Path, monkeypatch):
    # review MED #14: typst patlasa bile geçici _dokum.typ teslim klasöründe KALMASIN
    import subprocess

    def patla(*a, **k):
        raise subprocess.CalledProcessError(1, "typst")

    monkeypatch.setattr("ytcore.output.typst_runtime.subprocess.run", patla)
    dokum_yaz(tmp_path, _kayit(), _bolumler(), pdf=True, docx=False)
    assert (tmp_path / "03_dokum.md").is_file()  # md birincil korunur
    assert not (tmp_path / "_dokum.typ").exists()  # geçici temizlendi (try/finally)


def test_dokum_yaz_pdf_typst(tmp_path: Path):
    # Typst kurulu (0.14.2) → gerçek PDF; kurulu değilse best-effort (md yine var)
    paths = dokum_yaz(tmp_path, _kayit(), _bolumler(), pdf=True, docx=False)
    assert (tmp_path / "03_dokum.md").is_file()  # md HER ZAMAN
    pdf_p = tmp_path / "03_dokum.pdf"
    if pdf_p.is_file():  # Typst başarılıysa
        assert pdf_p in paths
        assert pdf_p.stat().st_size > 0
