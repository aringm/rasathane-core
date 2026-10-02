from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import pytest


@pytest.mark.asr
def test_asr_worker_gercek_ses(tmp_path):
    """ASR worker uçtan uca koşar mı (model indirir + transkribe eder)? GPU/torch gerekir.

    GERÇEK seam üzerinden (SubprocessASR) — PYTHONPATH enjeksiyonunu da test eder.
    Gerçek konuşma değil (sine ton) — amaç worker'ın çökmeden ASRSonuc ürettiğini ve
    tier sözleşmesini kanıtlamak. Gerçek WER ölçümü gerçek TR korpusla (eval/real_docs/).
    """
    if shutil.which("ffmpeg") is None:
        pytest.skip("ffmpeg yok")
    import importlib.util

    if importlib.util.find_spec("whisperx") is None and (
        importlib.util.find_spec("faster_whisper") is None
    ):
        pytest.skip("asr grubu kurulu değil (uv run --group asr ile koş)")
    from ytcore.transcript.asr import SubprocessASR

    ses = tmp_path / "ses.wav"
    subprocess.run(
        ["ffmpeg", "-f", "lavfi", "-i", "sine=frequency=440:duration=2", str(ses)],
        check=True,
        capture_output=True,
    )
    asr = SubprocessASR(python=sys.executable)
    r = asr.calistir(ses, dil="tr", diarize=False)
    assert r.tier in ("whisperx", "faster-whisper")
    assert isinstance(r.metin, str)


@pytest.mark.network
def test_gercek_en_video_altyazi(tmp_path, monkeypatch):
    """Canlı E2E: gerçek public EN video → temiz transkript + metadata.

    Çalıştırmadan önce <EN_VIDEO> yerine bilinen, altyazılı, telifsiz/CC public
    video ID gir; gerekirse YT_COOKIES_BROWSER=firefox set et.
    """
    monkeypatch.delenv("YT_TRANSCRIPT_FIXTURE", raising=False)
    monkeypatch.setenv("YT_OUTPUT_BASE", str(tmp_path))
    from ytcore.pipeline.api import analiz_et

    # Rick Astley — manuel EN altyazılı, kalıcı public video.
    s = analiz_et(
        url="https://www.youtube.com/watch?v=dQw4w9WgXcQ",
        konu="general",
        thread_id="e2e-en",
        checkpoint_dir=tmp_path,
    )
    assert s.transkript_durumu == "altyazi"
    metin = (Path(s.klasor) / "01_transcript_orijinal.md").read_text(encoding="utf-8")
    assert metin.strip()
    assert s.index.anadil
    assert s.index.kanal  # metadata doldu (kanal/başlık)


@pytest.mark.network
def test_gercek_tr_video_altyazi(tmp_path, monkeypatch):
    """Canlı E2E: gerçek public TR video → temiz transkript + metadata."""
    monkeypatch.delenv("YT_TRANSCRIPT_FIXTURE", raising=False)
    monkeypatch.setenv("YT_OUTPUT_BASE", str(tmp_path))
    from ytcore.pipeline.api import analiz_et

    # Barış Özcan — native Türkçe video, manuel TR altyazı (dil=tr).
    s = analiz_et(
        url="https://www.youtube.com/watch?v=GW3MMtJMeq4",
        konu="genel",
        thread_id="e2e-tr",
        checkpoint_dir=tmp_path,
    )
    assert s.transkript_durumu == "altyazi"
    assert s.transkript_kaynak_dil == "tr"
    metin = (Path(s.klasor) / "01_transcript_orijinal.md").read_text(encoding="utf-8")
    assert metin.strip() and "-->" not in metin  # temizlenmiş (timestamp yok)
    assert s.index.anadil == "tr"
