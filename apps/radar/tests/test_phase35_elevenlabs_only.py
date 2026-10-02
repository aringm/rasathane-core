"""Phase 35-i: ElevenLabs-only TTS sanity testleri.

Edge-TTS + Coqui XTTS-v2 path'leri tamamen silindi; dispatcher artık yok.
Bu test dosyası purge sonrası sembol mevcudiyetini ve voice defaults
baseline'ı doğrular.
"""

from __future__ import annotations

from pathlib import Path


def test_no_edge_tts_imports() -> None:
    """tts.py'de edge_tts referansı kalmamalı (Phase 35-i Edge-TTS purge)."""
    src = Path("packages/llm/src/llm/tts.py").read_text(encoding="utf-8")
    assert "import edge_tts" not in src
    # Docstring/historical comment yorumları geçer — gerçek kod referansı yok.
    # `from edge_tts` veya `import edge_tts` ya da `edge_tts.` çağrısı
    # olmamalı:
    assert "from edge_tts" not in src
    assert "edge_tts." not in src


def test_no_xtts_symbols() -> None:
    """Phase 35-i: XTTS-v2 path tamamen silindi — sembollere erişim AttributeError."""
    from llm import tts

    assert not hasattr(tts, "synthesize_podcast_xtts")
    assert not hasattr(tts, "_get_xtts_model")
    assert not hasattr(tts, "_synthesize_xtts_segment_sync")
    assert not hasattr(tts, "_reset_xtts_model_cache")
    assert not hasattr(tts, "_wav_to_mp3_sync")
    assert not hasattr(tts, "PODCAST_VOICES_XTTS_BRIEF")
    assert not hasattr(tts, "PODCAST_VOICES_XTTS_YOUTUBE")


def test_no_provider_dispatcher() -> None:
    """Phase 35-i: provider dispatcher kaldırıldı — tek provider ElevenLabs."""
    from llm import tts

    assert not hasattr(tts, "synthesize_podcast_with_provider")
    # Eski edge path symbolu da yok
    assert not hasattr(tts, "_synthesize_segment")
    assert not hasattr(tts, "DEFAULT_TR_VOICE")
    assert not hasattr(tts, "PODCAST_VOICES_BRIEF")
    assert not hasattr(tts, "PODCAST_VOICES_YOUTUBE")
    # Eski elevenlabs adı da artık `synthesize_podcast` olarak rename edildi
    assert not hasattr(tts, "synthesize_podcast_elevenlabs")
    # Yeni tek-provider API
    assert hasattr(tts, "synthesize_podcast")
    assert hasattr(tts, "synthesize_to_mp3")


def test_default_voice_settings_match_api_baseline() -> None:
    """`_DEFAULT_VOICE_SETTINGS` ElevenLabs API hard default'u.

    Phase 35-i'de tanımlandı; Phase 35-vii'de tek-voice fallback baseline
    olarak korundu (multi-speaker BRIEF/YOUTUBE override eder, ama
    `_synthesize_elevenlabs_segment` ve unknown-speaker fallback bu
    değerleri kullanır).
    """
    from llm.tts import _DEFAULT_VOICE_SETTINGS

    assert _DEFAULT_VOICE_SETTINGS["stability"] == 0.5
    assert _DEFAULT_VOICE_SETTINGS["similarity_boost"] == 0.75
    assert _DEFAULT_VOICE_SETTINGS["style"] == 0.0
    assert _DEFAULT_VOICE_SETTINGS["use_speaker_boost"] is True


def test_podcast_voices_per_speaker_anchor_tuning() -> None:
    """Phase 35-vii: per-speaker anchor profili — flat reset değil.

    Phase 35-i `_DEFAULT_VOICE_SETTINGS` spread'i kullanıyordu (tüm voice'ler
    style=0.0 narrator-flat). Phase 35-vii'de her speaker explicit tuning:
    Filiz/Burak style 0.40 (anchor expression), Mehmet style 0.30 (deeper
    voice, daha az style boost gerekiyor), Burak stability 0.55 (Marcus TR
    biraz fazla varyasyon vermesin).

    Phase 36-i: Esra (YouTube) Elvan→Tomris voice değişikliği ile birlikte
    style 0.35 → 0.50 (eleştirmen rolü için daha dinamik telaffuz). Detaylı
    Esra anchor pin'i tests/test_voice_anchor_youtube.py içinde.

    Regression: ileride yine "defaults reset" PR'ı silently bu tuning'i
    undo etmeye kalkarsa test yakalar.
    """
    from llm.tts import (
        PODCAST_VOICES_ELEVENLABS_BRIEF,
        PODCAST_VOICES_ELEVENLABS_YOUTUBE,
    )

    expected_brief = {
        "Filiz": {"stability": 0.50, "similarity_boost": 0.78, "style": 0.40},
        "Mehmet": {"stability": 0.50, "similarity_boost": 0.75, "style": 0.30},
        "Burak": {"stability": 0.55, "similarity_boost": 0.78, "style": 0.40},
    }
    for speaker, exp in expected_brief.items():
        cfg = PODCAST_VOICES_ELEVENLABS_BRIEF[speaker]
        assert cfg["stability"] == exp["stability"], f"{speaker} stability"
        assert cfg["similarity_boost"] == exp["similarity_boost"], f"{speaker} similarity"
        assert cfg["style"] == exp["style"], f"{speaker} style"
        assert cfg["use_speaker_boost"] is True, f"{speaker} use_speaker_boost"

    expected_youtube_style = {"Filiz": 0.40, "Burak": 0.40, "Esra": 0.50}
    for speaker, exp_style in expected_youtube_style.items():
        assert (
            PODCAST_VOICES_ELEVENLABS_YOUTUBE[speaker]["style"] == exp_style
        ), f"{speaker} YT style"


def test_loudnorm_defaults_broadcast_tight() -> None:
    """Phase 35-vii: _apply_loudnorm_sync broadcast-tight (Phase 34-v restore).

    Phase 35-i Apple Podcasts (-16/11) bugünün brief audio ölçümünde
    -23.61 LUFS perceived loudness verdi — TR-native voice'lar inherent
    quiet. Phase 34-v `0f41303` -14/5 broadcast değeri user-validated.

    Regression: bir "Apple Podcasts'a geri dönelim" PR'ı bu test'ten
    geçemez — eğer gerçekten gerekirse aynı anda test güncellenmeli +
    user'a "fısıltı" şikayetinin nasıl çözüleceği belgelenmeli.
    """
    import inspect

    from llm.tts import _apply_loudnorm_sync

    sig = inspect.signature(_apply_loudnorm_sync)
    assert sig.parameters["target_i"].default == -14.0, "target_i broadcast -14 LUFS"
    assert sig.parameters["lra"].default == 5.0, "LRA broadcast-tight 5 LU"
    assert sig.parameters["true_peak"].default == -1.5, "true peak -1.5 dB (clip önleme)"
