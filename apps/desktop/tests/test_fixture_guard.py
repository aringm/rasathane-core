from __future__ import annotations

import os
import sys
from pathlib import Path

# infra pyproject pythonpath'inde degil → sidecar_entry'yi test icin path'e ekle.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "infra"))

import sidecar_entry  # noqa: E402


def test_fixture_guard_uretimde_fixture_yoksayar(monkeypatch):
    # KÖK NEDEN (PewDiePie vakası): üretim http/stdio modunda DIŞARIDAN sızan fixture env'leri
    # _fixture_guard YOK SAYMALI (GUI/MCP gerçek video işlesin, kanned içerik değil).
    monkeypatch.setenv("YT_TRANSCRIPT_FIXTURE", "clean")
    monkeypatch.setenv("YT_LLM_FIXTURE", "1")
    monkeypatch.setenv("YT_EMBED_FIXTURE", "1")
    monkeypatch.setenv("RASATHANE_SOURCE_FIXTURE", "1")
    monkeypatch.delenv("YT_ALLOW_FIXTURES", raising=False)
    sidecar_entry._fixture_guard()
    assert "YT_TRANSCRIPT_FIXTURE" not in os.environ  # pop edildi → gerçek yt-dlp
    assert "YT_LLM_FIXTURE" not in os.environ  # pop edildi → gerçek Ollama
    assert "YT_EMBED_FIXTURE" not in os.environ
    assert "RASATHANE_SOURCE_FIXTURE" not in os.environ


def test_fixture_guard_bilincli_izin_korur(monkeypatch):
    # YT_ALLOW_FIXTURES=1 → bilinçli demo/test: fixture KORUNUR (uyarı basılır ama pop edilmez).
    monkeypatch.setenv("YT_TRANSCRIPT_FIXTURE", "clean")
    monkeypatch.setenv("RASATHANE_SOURCE_FIXTURE", "1")
    monkeypatch.setenv("YT_ALLOW_FIXTURES", "1")
    sidecar_entry._fixture_guard()
    assert os.environ.get("YT_TRANSCRIPT_FIXTURE") == "clean"  # bilinçli → korundu
    assert os.environ.get("RASATHANE_SOURCE_FIXTURE") == "1"


def test_fixture_guard_temiz_ortam_noop(monkeypatch):
    # Fixture yoksa guard hiçbir şey yapmaz (gerçek üretim ortamı — normal akış).
    for k in [
        k
        for k in os.environ
        if "FIXTURE" in k and (k.startswith("YT_") or k.startswith("RASATHANE_"))
    ]:
        monkeypatch.delenv(k, raising=False)
    sidecar_entry._fixture_guard()  # exception YOK
    assert not [
        k
        for k in os.environ
        if "FIXTURE" in k and (k.startswith("YT_") or k.startswith("RASATHANE_"))
    ]


def test_phoenix_varsayilan_kapali(monkeypatch):
    import ytcore.obs.tracer as tracer

    cagrilar: list[bool] = []
    monkeypatch.delenv("YT_PHOENIX", raising=False)
    monkeypatch.setattr(tracer, "phoenix_tracer_kur", lambda: cagrilar.append(True))

    sidecar_entry._phoenix_baslat()

    assert cagrilar == []


def test_phoenix_acik_opt_in(monkeypatch):
    import ytcore.obs.tracer as tracer

    cagrilar: list[bool] = []
    monkeypatch.setenv("YT_PHOENIX", "1")
    monkeypatch.setattr(tracer, "phoenix_tracer_kur", lambda: cagrilar.append(True))

    sidecar_entry._phoenix_baslat()

    assert cagrilar == [True]
