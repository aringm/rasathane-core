"""Phase 36-i: PODCAST_VOICES_ELEVENLABS_YOUTUBE Esra anchor pin."""
from llm.tts import (
    ELEVENLABS_TR_NATIVE_VOICES,
    PODCAST_VOICES_ELEVENLABS_YOUTUBE,
)


def test_esra_voice_is_tomris():
    """Esra rolü 'eleştirmen' karakteriyle uyumlu Tomris voice'una pin'li."""
    esra = PODCAST_VOICES_ELEVENLABS_YOUTUBE["Esra"]
    assert esra["voice_id"] == ELEVENLABS_TR_NATIVE_VOICES["Tomris"]


def test_esra_settings_match_critic_anchor():
    """Phase 36-i: stability=0.45, style=0.50 — eleştirmen tonu için anchor."""
    esra = PODCAST_VOICES_ELEVENLABS_YOUTUBE["Esra"]
    assert esra["stability"] == 0.45
    assert esra["similarity_boost"] == 0.78
    assert esra["style"] == 0.50
    assert esra["use_speaker_boost"] is True
