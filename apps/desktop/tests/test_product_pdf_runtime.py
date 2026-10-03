from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest
from ytcore.content.dokum import DokumBolum
from ytcore.models import DegerlemeFaktorleri, IndexKaydi
from ytcore.output import typst_runtime
from ytcore.output.dokum_yaz import dokum_yaz
from ytcore.output.sunum_yaz import sunum_yaz


@pytest.fixture
def executable(tmp_path, monkeypatch):
    path = tmp_path / "tooling" / "typst.exe"
    path.parent.mkdir()
    path.write_bytes(b"installed-typst")
    monkeypatch.setenv("RASATHANE_TYPST_BIN", str(path))
    return path


def test_frozen_requires_packaged_typst_never_searches_path(monkeypatch):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.delenv("RASATHANE_TYPST_BIN", raising=False)

    def forbidden(*args, **kwargs):
        raise AssertionError("Paketli uygulama sistem PATH'ini kullanmamalı.")

    monkeypatch.setattr(typst_runtime.shutil, "which", forbidden)
    with pytest.raises(FileNotFoundError, match="PDF motoru"):
        typst_runtime.typst_executable()


@pytest.mark.parametrize("value", ["tooling/typst.exe", "missing"])
def test_invalid_configured_typst_does_not_fall_back_to_path(tmp_path, monkeypatch, value):
    configured = str(tmp_path / "missing.exe") if value == "missing" else value
    monkeypatch.setenv("RASATHANE_TYPST_BIN", configured)
    monkeypatch.setattr(typst_runtime.shutil, "which", lambda name: "unused.exe")
    with pytest.raises((FileNotFoundError, ValueError)):
        typst_runtime.typst_executable()


def test_dev_path_compatibility_remains_explicit(monkeypatch, executable):
    monkeypatch.delenv("RASATHANE_TYPST_BIN", raising=False)
    monkeypatch.setattr(sys, "frozen", False, raising=False)
    monkeypatch.setattr(typst_runtime.shutil, "which", lambda name: str(executable))
    assert typst_runtime.typst_executable() == executable.resolve()


def _write_pdf(kind: str, directory: Path):
    record = IndexKaydi(
        video_url="https://example.org/regulation",
        video_id="x",
        baslik="Kaynak analizi",
        anadil="tr",
        kanal="Resmî kaynak",
        konu="hukuk",
        uretici_slug="resmi",
        video_slug="x",
        analiz_tarihi="2026-10-03",
        kaynak_turu="web",
        kaynak_url="https://example.org/regulation",
    )
    if kind == "sunum":
        return sunum_yaz(
            directory,
            record,
            {"kisa": "Özet", "detay": "Türkçe içerik"},
            None,
            "Analiz",
            None,
            DegerlemeFaktorleri(),
        )
    return dokum_yaz(directory, record, [DokumBolum(None, "Kural", "Kaynak metni", [])], docx=False)


@pytest.mark.parametrize("kind", ["sunum", "dokum"])
def test_both_pdf_writers_use_packaged_binary_and_verified_output(
    kind, tmp_path, executable, monkeypatch
):
    commands = []

    def compile(command, **kwargs):
        commands.append(command)
        assert command[0] == str(executable.resolve())
        assert kwargs["timeout"] == 180 and kwargs["stdin"] == subprocess.DEVNULL
        assert "--root" in command
        Path(command[-1]).write_bytes(b"%PDF-1.7\nverified PDF output\n")

    monkeypatch.setattr(typst_runtime.subprocess, "run", compile)
    result = _write_pdf(kind, tmp_path)
    pdf = tmp_path / ("04_ozet-sunum.pdf" if kind == "sunum" else "03_dokum.pdf")
    assert result == pdf if kind == "sunum" else pdf in result
    assert pdf.read_bytes().startswith(b"%PDF-")
    assert len(commands) == 1
    assert not list(tmp_path.glob("*.typ")) and not list(tmp_path.glob("*.partial.pdf"))


@pytest.mark.parametrize("kind", ["sunum", "dokum"])
@pytest.mark.parametrize("failure", ["empty", "html", "timeout"])
def test_zero_exit_without_pdf_or_timeout_never_claims_success(
    kind, failure, tmp_path, executable, monkeypatch
):
    def compile(command, **kwargs):
        if failure == "timeout":
            raise subprocess.TimeoutExpired(command, 180)
        if failure == "html":
            Path(command[-1]).write_bytes(b"<html>failure page</html>")

    monkeypatch.setattr(typst_runtime.subprocess, "run", compile)
    result = _write_pdf(kind, tmp_path)
    assert result is None if kind == "sunum" else result == [tmp_path / "03_dokum.md"]
    assert not list(tmp_path.glob("*.pdf")) and not list(tmp_path.glob("*.typ"))
