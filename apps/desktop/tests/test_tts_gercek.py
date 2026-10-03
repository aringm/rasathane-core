from __future__ import annotations

import wave

import pytest


@pytest.mark.tts
def test_piper_gercek_sentez(tmp_path, monkeypatch):
    monkeypatch.delenv("YT_TTS_FIXTURE", raising=False)
    from ytcore.uretim.tts import PiperTTS, piper_voice_indir

    voice_dir = tmp_path / "piper"
    piper_voice_indir(voice_dir)  # dfki TR voice HF'den indir
    hedef = tmp_path / "04_ozet.wav"
    s = PiperTTS(voice_dir=voice_dir).seslendir(
        "Merhaba. Bu bir Türkçe seslendirme testidir.", hedef
    )
    assert s.durum == "uretildi" and s.kaynak == "piper"
    assert hedef.exists() and hedef.stat().st_size > 1000  # gerçek ses (boş≠başarı)
    with wave.open(str(hedef), "rb") as w:
        assert w.getnframes() > 0  # geçerli WAV, sıfır-olmayan frame


@pytest.mark.tts
def test_subprocess_piper_gercek_sentez(tmp_path, monkeypatch):
    # AYRI PROSES yolu (frozen GUI'nin kullandığı): gerçek .venv python tts_worker'ı koşar,
    # piper sentezler → 'uretildi' + geçerli WAV. tts_al("piper") artık bunu döndürür.
    monkeypatch.delenv("YT_TTS_FIXTURE", raising=False)
    from ytcore.uretim.tts import SubprocessPiperTTS, piper_voice_indir

    voice_dir = tmp_path / "piper"
    piper_voice_indir(voice_dir)
    hedef = tmp_path / "04_ozet.wav"
    s = SubprocessPiperTTS(voice_dir=voice_dir).seslendir(
        "Merhaba. Bu ayrı proses seslendirme testidir.", hedef
    )
    assert s.durum == "uretildi" and s.kaynak == "piper"
    assert hedef.exists() and hedef.stat().st_size > 1000
    with wave.open(str(hedef), "rb") as w:
        assert w.getnframes() > 0
