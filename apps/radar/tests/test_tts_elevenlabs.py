"""Phase 32-iv + 35-i: ElevenLabs TTS provider testleri.

Phase 35-i sonrası ElevenLabs tek provider; dispatcher (edge/xtts) silindi.
httpx mock'lu — gerçek ElevenLabs API çağrısı yapılmaz. ffmpeg concat +
xing inject de mock'lanır.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import httpx
import pytest
import respx
from llm import tts
from llm.tts import (
    ELEVENLABS_BASE_URL,
    ELEVENLABS_DEFAULT_VOICES,
    PODCAST_VOICES_ELEVENLABS_BRIEF,
    PODCAST_VOICES_ELEVENLABS_YOUTUBE,
    synthesize_podcast,
)

# ── Voice mapping sanity ────────────────────────────────────────────────


def test_elevenlabs_brief_has_three_distinct_voices() -> None:
    """Filiz/Mehmet/Burak — 3 farklı voice_id (gerçek timbre ayrımı)."""
    assert set(PODCAST_VOICES_ELEVENLABS_BRIEF.keys()) == {"Filiz", "Mehmet", "Burak"}
    voice_ids = {cfg["voice_id"] for cfg in PODCAST_VOICES_ELEVENLABS_BRIEF.values()}
    assert len(voice_ids) == 3, "Her speaker farklı voice_id kullanmalı"


def test_elevenlabs_youtube_has_three_distinct_voices() -> None:
    """Filiz/Burak/Esra — 3 farklı voice_id."""
    assert set(PODCAST_VOICES_ELEVENLABS_YOUTUBE.keys()) == {"Filiz", "Burak", "Esra"}
    voice_ids = {cfg["voice_id"] for cfg in PODCAST_VOICES_ELEVENLABS_YOUTUBE.values()}
    assert len(voice_ids) == 3


def test_elevenlabs_voice_settings_in_valid_range() -> None:
    """stability/similarity_boost 0-1; style 0-1 (ElevenLabs API kontratı)."""
    for voices in (PODCAST_VOICES_ELEVENLABS_BRIEF, PODCAST_VOICES_ELEVENLABS_YOUTUBE):
        for cfg in voices.values():
            assert 0.0 <= float(cfg["stability"]) <= 1.0
            assert 0.0 <= float(cfg["similarity_boost"]) <= 1.0
            assert 0.0 <= float(cfg["style"]) <= 1.0


def test_elevenlabs_default_voices_include_core_premade_set() -> None:
    """Hesaba shipping'le gelen ``premade`` voice'lar (free-tier API accessible).

    Library voice'lar (community pool) 402 döner; yalnız bu liste güvenli.
    Mayıs 2026 itibarıyla 11 voice dict'te tutulur (GET /v1/voices kaynak).
    """
    expected = {"Sarah", "Adam", "Liam"}  # brief 3-spiker için minimum
    assert expected.issubset(ELEVENLABS_DEFAULT_VOICES.keys())
    assert len(ELEVENLABS_DEFAULT_VOICES) >= 6, "En az 6 voice listede olmalı"


# ── synthesize_podcast (Phase 35-i rename: elevenlabs → tek provider) ───


@pytest.mark.asyncio
async def test_synthesize_podcast_empty_dialog_raises(tmp_path: Path) -> None:
    """Boş dialog → ValueError; API çağrısı tetiklenmez."""
    with pytest.raises(ValueError, match="Empty dialog"):
        await synthesize_podcast(
            dialog=[],
            output_path=tmp_path / "out.mp3",
            voices=PODCAST_VOICES_ELEVENLABS_BRIEF,
        )


@pytest.mark.asyncio
async def test_synthesize_podcast_no_api_key_raises_runtime_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """ELEVENLABS_API_KEY yoksa RuntimeError açıklayıcı mesaj."""
    monkeypatch.delenv("ELEVENLABS_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match=r"ELEVENLABS_API_KEY|elevenlabs\.io"):
        await synthesize_podcast(
            dialog=[{"speaker": "Filiz", "text": "x"}],
            output_path=tmp_path / "out.mp3",
            voices=PODCAST_VOICES_ELEVENLABS_BRIEF,
        )


@pytest.mark.asyncio
async def test_synthesize_podcast_empty_api_key_string_treated_as_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Whitespace-only ya da boş string API key → RuntimeError."""
    monkeypatch.setenv("ELEVENLABS_API_KEY", "   ")
    with pytest.raises(RuntimeError, match="ELEVENLABS_API_KEY"):
        await synthesize_podcast(
            dialog=[{"speaker": "Filiz", "text": "x"}],
            output_path=tmp_path / "out.mp3",
            voices=PODCAST_VOICES_ELEVENLABS_BRIEF,
        )


@pytest.mark.asyncio
async def test_synthesize_podcast_two_segments_happy_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Mock httpx + ffmpeg: 2 dialog → 2 API POST + 1 concat + 1 xing."""
    monkeypatch.setenv("ELEVENLABS_API_KEY", "test_key_abc")
    concat_calls: list[tuple[list[Path], Path]] = []
    xing_calls: list[Path] = []

    def fake_concat(segments: list[Path], output_path: Path) -> None:
        concat_calls.append((segments, output_path))
        output_path.write_bytes(b"FINALMP3")

    async def fake_xing(p: Path) -> bool:
        xing_calls.append(p)
        return True

    async def fake_loudnorm(_p: Path) -> bool:
        return True

    async def fake_per_seg_loudnorm(_segs: list[Path]) -> int:
        return len(_segs)

    monkeypatch.setattr(tts, "_ffmpeg_concat_sync", fake_concat)
    monkeypatch.setattr(tts, "inject_xing_header", fake_xing)
    monkeypatch.setattr(tts, "apply_loudnorm", fake_loudnorm)
    monkeypatch.setattr(tts, "apply_per_segment_loudnorm", fake_per_seg_loudnorm)

    filiz_id = PODCAST_VOICES_ELEVENLABS_BRIEF["Filiz"]["voice_id"]
    mehmet_id = PODCAST_VOICES_ELEVENLABS_BRIEF["Mehmet"]["voice_id"]
    with respx.mock(assert_all_called=True) as router:
        router.post(f"{ELEVENLABS_BASE_URL}/text-to-speech/{filiz_id}").respond(
            200, content=b"MP3_FILIZ_BYTES", headers={"Content-Type": "audio/mpeg"}
        )
        router.post(f"{ELEVENLABS_BASE_URL}/text-to-speech/{mehmet_id}").respond(
            200, content=b"MP3_MEHMET_BYTES", headers={"Content-Type": "audio/mpeg"}
        )
        out = tmp_path / "podcast.mp3"
        result = await synthesize_podcast(
            dialog=[
                {"speaker": "Filiz", "text": "Merhaba"},
                {"speaker": "Mehmet", "text": "Selamlar"},
            ],
            output_path=out,
            voices=PODCAST_VOICES_ELEVENLABS_BRIEF,
        )
    assert result == out
    assert len(concat_calls) == 1
    assert len(concat_calls[0][0]) == 2  # 2 segment
    assert len(xing_calls) == 1
    assert out.read_bytes() == b"FINALMP3"


@pytest.mark.asyncio
async def test_synthesize_podcast_api_500_raises_runtime_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """ElevenLabs server hatası (500) RuntimeError'a dönüşür."""
    monkeypatch.setenv("ELEVENLABS_API_KEY", "test_key_abc")
    filiz_id = PODCAST_VOICES_ELEVENLABS_BRIEF["Filiz"]["voice_id"]
    with respx.mock(assert_all_called=True) as router:
        router.post(f"{ELEVENLABS_BASE_URL}/text-to-speech/{filiz_id}").respond(
            500, text="Internal Server Error"
        )
        with pytest.raises(RuntimeError, match=r"ElevenLabs API 500"):
            await synthesize_podcast(
                dialog=[{"speaker": "Filiz", "text": "x"}],
                output_path=tmp_path / "out.mp3",
                voices=PODCAST_VOICES_ELEVENLABS_BRIEF,
            )


@pytest.mark.asyncio
async def test_synthesize_podcast_unknown_speaker_uses_fallback_voice(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """voices'ta olmayan spiker → fallback_voice_id (Sarah default)."""
    monkeypatch.setenv("ELEVENLABS_API_KEY", "test_key_abc")
    monkeypatch.setattr(tts, "_ffmpeg_concat_sync", lambda segs, out: out.write_bytes(b"X"))

    async def fake_xing(_p: Path) -> bool:
        return True

    async def fake_loudnorm(_p: Path) -> bool:
        return True

    async def fake_per_seg_loudnorm(_segs: list[Path]) -> int:
        return len(_segs)

    monkeypatch.setattr(tts, "inject_xing_header", fake_xing)
    monkeypatch.setattr(tts, "apply_loudnorm", fake_loudnorm)
    monkeypatch.setattr(tts, "apply_per_segment_loudnorm", fake_per_seg_loudnorm)

    sarah_id = ELEVENLABS_DEFAULT_VOICES["Sarah"]
    with respx.mock(assert_all_called=True) as router:
        # Beklenen: fallback_voice_id=Sarah (default) kullanılır
        route = router.post(f"{ELEVENLABS_BASE_URL}/text-to-speech/{sarah_id}").respond(
            200, content=b"FAKE", headers={"Content-Type": "audio/mpeg"}
        )
        await synthesize_podcast(
            dialog=[{"speaker": "Bilinmeyen", "text": "Test"}],
            output_path=tmp_path / "out.mp3",
            voices=PODCAST_VOICES_ELEVENLABS_BRIEF,
        )
        assert route.called


@pytest.mark.asyncio
async def test_synthesize_podcast_apply_transliteration_replaces_acronyms(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """apply_transliteration=True (default) → 'AI' → 'ey-ay' API'ye gider."""
    monkeypatch.setenv("ELEVENLABS_API_KEY", "test_key_abc")
    monkeypatch.setattr(tts, "_ffmpeg_concat_sync", lambda segs, out: out.write_bytes(b"X"))

    async def fake_xing(_p: Path) -> bool:
        return True

    async def fake_loudnorm(_p: Path) -> bool:
        return True

    async def fake_per_seg_loudnorm(_segs: list[Path]) -> int:
        return len(_segs)

    monkeypatch.setattr(tts, "inject_xing_header", fake_xing)
    monkeypatch.setattr(tts, "apply_loudnorm", fake_loudnorm)
    monkeypatch.setattr(tts, "apply_per_segment_loudnorm", fake_per_seg_loudnorm)

    filiz_id = PODCAST_VOICES_ELEVENLABS_BRIEF["Filiz"]["voice_id"]
    captured_body: dict[str, Any] = {}

    def capture(request: httpx.Request) -> httpx.Response:
        import json as _json

        captured_body.update(_json.loads(request.content))
        return httpx.Response(200, content=b"FAKE", headers={"Content-Type": "audio/mpeg"})

    with respx.mock(assert_all_called=True) as router:
        router.post(f"{ELEVENLABS_BASE_URL}/text-to-speech/{filiz_id}").mock(side_effect=capture)
        await synthesize_podcast(
            dialog=[{"speaker": "Filiz", "text": "AI ve GPU geliştirmesi"}],
            output_path=tmp_path / "out.mp3",
            voices=PODCAST_VOICES_ELEVENLABS_BRIEF,
        )
    assert "ey-ay" in captured_body["text"]
    assert "ci-pi-yu" in captured_body["text"]


# ── Phase 33-i + 35-i: Mehmet default voice ──────────────────────────────


def test_mehmet_default_voice_is_adam_tr() -> None:
    """Phase 33-i: Mehmet 'Adam TR' voice rename regression.

    Voice tuning değerleri için Phase 35-vii
    ``test_podcast_voices_per_speaker_anchor_tuning`` (test_phase35_elevenlabs_only.py)
    kapsıyor — burada sadece voice_id mapping korunsun.
    """
    from llm.tts import ELEVENLABS_TR_NATIVE_VOICES

    expected_voice_id = ELEVENLABS_TR_NATIVE_VOICES["Adam TR"]
    assert PODCAST_VOICES_ELEVENLABS_BRIEF["Mehmet"]["voice_id"] == expected_voice_id
    assert PODCAST_VOICES_ELEVENLABS_BRIEF["Mehmet"]["use_speaker_boost"] is True
