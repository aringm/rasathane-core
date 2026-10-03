"""YouTube ingestion tests — yt-dlp mocked, faster-whisper not invoked."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from ingestion.youtube import (
    Transcript,
    VideoMetadata,
    _extract_text_from_vtt,
    fetch_metadata,
    fetch_subs_via_ytdlp,
    fetch_transcript,
    transcribe_via_whisper_api,
)


def test_extract_text_from_vtt_strips_header() -> None:
    vtt = """WEBVTT
Kind: captions
Language: tr

1
00:00:01.000 --> 00:00:03.000
Merhaba dünya

2
00:00:04.000 --> 00:00:06.000
İkinci satır
"""
    text = _extract_text_from_vtt(vtt)
    assert "Merhaba dünya" in text
    assert "İkinci satır" in text
    assert "WEBVTT" not in text
    assert "00:00:01" not in text


def test_extract_text_from_vtt_strips_inline_tags() -> None:
    vtt = """WEBVTT

1
00:00:01.000 --> 00:00:03.000
<v Speaker>Önemli <c>vurgu</c> burada"""
    text = _extract_text_from_vtt(vtt)
    assert "<v" not in text
    assert "<c>" not in text
    assert "Önemli" in text
    assert "vurgu" in text


def test_extract_text_from_vtt_empty_returns_empty() -> None:
    assert _extract_text_from_vtt("") == ""
    assert _extract_text_from_vtt("WEBVTT\n\n") == ""


async def test_fetch_metadata_uses_ytdlp_python_api(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_info = {
        "id": "abc123",
        "title": "Test Video Türkçe",
        "uploader": "TestChannel",
        "duration": 180,
    }
    fake_ydl = MagicMock()
    fake_ydl.__enter__ = MagicMock(return_value=fake_ydl)
    fake_ydl.__exit__ = MagicMock(return_value=None)
    fake_ydl.extract_info = MagicMock(return_value=fake_info)

    fake_factory = MagicMock(return_value=fake_ydl)
    monkeypatch.setattr("ingestion.youtube.yt_dlp.YoutubeDL", fake_factory)

    metadata = await fetch_metadata("https://youtube.com/watch?v=abc123")

    assert isinstance(metadata, VideoMetadata)
    assert metadata.video_id == "abc123"
    assert metadata.title == "Test Video Türkçe"
    assert metadata.channel == "TestChannel"
    assert metadata.duration_seconds == 180


async def test_fetch_metadata_handles_missing_fields(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_info = {"id": "noinfo"}
    fake_ydl = MagicMock()
    fake_ydl.__enter__ = MagicMock(return_value=fake_ydl)
    fake_ydl.__exit__ = MagicMock(return_value=None)
    fake_ydl.extract_info = MagicMock(return_value=fake_info)

    monkeypatch.setattr("ingestion.youtube.yt_dlp.YoutubeDL", MagicMock(return_value=fake_ydl))

    metadata = await fetch_metadata("https://youtube.com/watch?v=noinfo")
    assert metadata.title == "(başlıksız)"
    assert metadata.channel == "(bilinmeyen)"
    assert metadata.duration_seconds == 0


async def test_fetch_subs_returns_none_when_no_caption_files(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    """Phase 27: yt-dlp metadata altyazı bulamazsa priority boş → None."""
    fake_ydl = MagicMock()
    fake_ydl.__enter__ = MagicMock(return_value=fake_ydl)
    fake_ydl.__exit__ = MagicMock(return_value=None)
    fake_ydl.download = MagicMock()  # nothing written
    # Phase 27: extract_info önce çağrılıyor — empty subs → priority empty → None
    fake_ydl.extract_info = MagicMock(
        return_value={
            "id": "nosubs",
            "language": "en",
            "subtitles": {},
            "automatic_captions": {},
        }
    )

    monkeypatch.setattr("ingestion.youtube.yt_dlp.YoutubeDL", MagicMock(return_value=fake_ydl))

    result = await fetch_subs_via_ytdlp("https://youtube.com/watch?v=nosubs")
    assert result is None


async def test_fetch_subs_sequential_fallback_after_429(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    """Phase 28-i: ilk dil 429 alır → diğer dile geç → o başarılı → o döner.

    yt-dlp'nin batch `subtitleslangs` davranışı tek 429 ile tüm chain'i
    bozuyor. Sequential fallback bunu önler — her dil ayrı yt-dlp call.
    """
    from pathlib import Path

    call_log = []

    class FakeYDL:
        def __init__(self, opts):
            self.opts = opts
            self.subs_langs = opts.get("subtitleslangs", [])

        def __enter__(self):
            return self

        def __exit__(self, *_a):
            return None

        def extract_info(self, _url, download=False):
            # Step 1 metadata: TR + EN auto altyazı var
            return {
                "id": "vid1",
                "language": "tr",
                "subtitles": {},
                "automatic_captions": {"tr": [{}], "en": [{}]},
            }

        def download(self, _urls):
            # Step 2: tek dil call — sequential fallback test
            lang = self.subs_langs[0]
            call_log.append(lang)
            if lang == "tr":
                # 429 simule
                raise RuntimeError(
                    "ERROR: Unable to download video subtitles for 'tr': "
                    "HTTP Error 429: Too Many Requests"
                )
            # EN için success: outtmpl dizininde dosya yarat
            outtmpl = self.opts["outtmpl"]
            base_dir = Path(outtmpl).parent
            # outtmpl: tmp/%(id)s.%(ext)s → dosya: tmp/vid1.en.vtt
            (base_dir / "vid1.en.vtt").write_text(
                "WEBVTT\n\n00:00:01.000 --> 00:00:03.000\nHello world\n",
                encoding="utf-8",
            )

    monkeypatch.setattr("ingestion.youtube.yt_dlp.YoutubeDL", FakeYDL)

    result = await fetch_subs_via_ytdlp("https://youtube.com/watch?v=seq")
    assert result is not None, "Sequential fallback should succeed on EN after TR 429"
    assert result.source == "yt-dlp:en"
    assert "Hello world" in result.text
    # TR önce, fail; EN ikinci, success
    assert call_log == ["tr", "en"]


async def test_fetch_transcript_falls_back_to_whisper_on_subs_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When yt-dlp subs fail, whisper path is invoked."""
    called = {"subs": 0, "whisper": 0}

    async def fake_subs(url: str) -> None:
        called["subs"] += 1
        return None

    async def fake_whisper(url: str, *, model_name: str = "medium") -> Transcript:
        called["whisper"] += 1
        return Transcript(text="whispered text", source="whisper")

    monkeypatch.setattr("ingestion.youtube.fetch_subs_via_ytdlp", fake_subs)
    monkeypatch.setattr("ingestion.youtube.fetch_audio_and_transcribe", fake_whisper)

    result = await fetch_transcript("https://youtube.com/watch?v=x")
    assert called["subs"] == 1
    assert called["whisper"] == 1
    assert result is not None
    assert result.source == "whisper"


async def test_fetch_transcript_returns_none_when_both_fail(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_subs(url: str) -> None:
        return None

    async def fake_whisper(url: str, *, model_name: str = "medium") -> None:
        raise RuntimeError("whisper failed too")

    monkeypatch.setattr("ingestion.youtube.fetch_subs_via_ytdlp", fake_subs)
    monkeypatch.setattr("ingestion.youtube.fetch_audio_and_transcribe", fake_whisper)

    result = await fetch_transcript("https://youtube.com/watch?v=x")
    assert result is None


async def test_fetch_transcript_skips_whisper_when_subs_succeed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Phase 5 design: cheap path wins; whisper only if subs miss."""
    called = {"whisper": 0}

    async def fake_subs(url: str) -> Transcript:
        return Transcript(text="cheap subs", source="yt-dlp")

    async def fake_whisper(url: str, *, model_name: str = "medium") -> Transcript:
        called["whisper"] += 1  # should not run
        return Transcript(text="x", source="whisper")

    monkeypatch.setattr("ingestion.youtube.fetch_subs_via_ytdlp", fake_subs)
    monkeypatch.setattr("ingestion.youtube.fetch_audio_and_transcribe", fake_whisper)

    result = await fetch_transcript("https://youtube.com/watch?v=x")
    assert result is not None
    assert result.source == "yt-dlp"
    assert called["whisper"] == 0


# ── Phase 26: Docker whisper service entegrasyonu ────────────────────


async def test_transcribe_via_whisper_api_returns_transcript_on_success(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Mock httpx — multipart audio_file POST + JSON response parse."""
    import httpx

    audio = tmp_path / "test.mp3"
    audio.write_bytes(b"\xff\xfb\x90\x44ID3 fake mp3")

    captured: dict = {}

    class FakeResp:
        def __init__(self, payload):
            self._payload = payload

        def raise_for_status(self):
            return None

        def json(self):
            return self._payload

    class FakeClient:
        def __init__(self, *_a, **kw):
            captured["timeout"] = kw.get("timeout")

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_a):
            return None

        async def post(self, url, *, params=None, files=None):
            captured["url"] = url
            captured["params"] = params
            captured["has_audio_file"] = "audio_file" in (files or {})
            return FakeResp(
                {
                    "text": "Merhaba dünya, bu bir testtir.",
                    "language": "tr",
                    "segments": [],
                }
            )

    monkeypatch.setattr(httpx, "AsyncClient", FakeClient)

    result = await transcribe_via_whisper_api(audio, api_url="http://localhost:9000")

    assert isinstance(result, Transcript)
    assert result.source == "whisper-api"
    assert "Merhaba dünya" in result.text
    assert captured["url"] == "http://localhost:9000/asr"
    assert captured["params"]["task"] == "transcribe"
    assert captured["params"]["language"] == "tr"
    assert captured["params"]["vad_filter"] == "true"
    assert captured["has_audio_file"]


async def test_transcribe_via_whisper_api_raises_on_empty_text(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """API'den boş text → RuntimeError (caller fallback'a düşer)."""
    import httpx

    audio = tmp_path / "test.mp3"
    audio.write_bytes(b"\xff\xfb")

    class FakeResp:
        def raise_for_status(self):
            return None

        def json(self):
            return {"text": "", "language": "tr"}

    class FakeClient:
        def __init__(self, *_a, **_kw):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_a):
            return None

        async def post(self, *_a, **_kw):
            return FakeResp()

    monkeypatch.setattr(httpx, "AsyncClient", FakeClient)

    with pytest.raises(RuntimeError, match="empty transcript"):
        await transcribe_via_whisper_api(audio, api_url="http://localhost:9000")


async def test_fetch_transcript_uses_whisper_api_when_env_set(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """WHISPER_API_URL set'liyse 2. tier (Docker API) devreye girer."""
    monkeypatch.setenv("WHISPER_API_URL", "http://localhost:9000")

    called = {"subs": 0, "audio": 0, "api": 0, "local": 0}

    async def fake_subs(url: str) -> None:
        called["subs"] += 1
        return None

    async def fake_audio(url: str) -> Path:
        called["audio"] += 1
        out = tmp_path / "audio_dir"
        out.mkdir(exist_ok=True)
        f = out / "x.mp3"
        f.write_bytes(b"\xff\xfb")
        return f

    async def fake_api(audio_path, *, api_url, language="tr", timeout_seconds=600.0):
        called["api"] += 1
        return Transcript(text="api transcript", source="whisper-api")

    async def fake_local(url: str, *, model_name: str = "medium") -> Transcript:
        called["local"] += 1
        return Transcript(text="local", source="whisper")

    monkeypatch.setattr("ingestion.youtube.fetch_subs_via_ytdlp", fake_subs)
    monkeypatch.setattr("ingestion.youtube.fetch_audio_only", fake_audio)
    monkeypatch.setattr("ingestion.youtube.transcribe_via_whisper_api", fake_api)
    monkeypatch.setattr("ingestion.youtube.fetch_audio_and_transcribe", fake_local)

    result = await fetch_transcript("https://youtu.be/test")

    assert called == {"subs": 1, "audio": 1, "api": 1, "local": 0}
    assert result is not None
    assert result.source == "whisper-api"


async def test_fetch_transcript_falls_back_to_local_when_api_fails(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Docker API fail → lokal whisper'a düş."""
    monkeypatch.setenv("WHISPER_API_URL", "http://localhost:9000")

    async def fake_subs(_url):
        return None

    async def fake_audio(_url):
        out = tmp_path / "audio_dir2"
        out.mkdir(exist_ok=True)
        f = out / "x.mp3"
        f.write_bytes(b"\xff\xfb")
        return f

    async def fake_api(*_a, **_kw):
        raise RuntimeError("api down")

    called_local = {"n": 0}

    async def fake_local(_url, *, model_name="medium"):
        called_local["n"] += 1
        return Transcript(text="local fallback", source="whisper")

    monkeypatch.setattr("ingestion.youtube.fetch_subs_via_ytdlp", fake_subs)
    monkeypatch.setattr("ingestion.youtube.fetch_audio_only", fake_audio)
    monkeypatch.setattr("ingestion.youtube.transcribe_via_whisper_api", fake_api)
    monkeypatch.setattr("ingestion.youtube.fetch_audio_and_transcribe", fake_local)

    result = await fetch_transcript("https://youtu.be/test")
    assert called_local["n"] == 1
    assert result is not None
    assert result.source == "whisper"


# ── Phase 27: orijinal dil-aware altyazı priority ────────────────────


def test_normalize_lang_code_strips_region() -> None:
    from ingestion.youtube import _normalize_lang_code

    assert _normalize_lang_code("tr-TR") == "tr"
    assert _normalize_lang_code("en-US") == "en"
    assert _normalize_lang_code("ja") == "ja"
    assert _normalize_lang_code("") == ""


def test_resolve_caption_priority_prefers_manual_in_original_language() -> None:
    """Türkçe video + manuel TR altyazı + auto EN → manuel TR önce."""
    from ingestion.youtube import _resolve_caption_priority

    out = _resolve_caption_priority(
        language="tr",
        manual_langs=["tr", "tr-TR"],
        auto_langs=["en", "tr"],
    )
    # Manuel "tr" ve "tr-TR" en başta — sonra auto'lar
    assert out[0] == "tr"
    # Manuel grubu auto grubundan önce gelmeli
    assert out.index("tr") < out.index("en")


def test_resolve_caption_priority_falls_back_to_auto_when_no_manual() -> None:
    """Manuel altyazı yoksa auto-captions'tan orijinal dil + EN + TR."""
    from ingestion.youtube import _resolve_caption_priority

    out = _resolve_caption_priority(
        language="ja",  # Japonca video
        manual_langs=[],
        auto_langs=["ja", "en", "tr"],
    )
    assert out[0] == "ja"  # orijinal dil önce
    assert "en" in out
    assert "tr" in out


def test_resolve_caption_priority_handles_unknown_original_language() -> None:
    """language metadata yoksa fallback EN > TR."""
    from ingestion.youtube import _resolve_caption_priority

    out = _resolve_caption_priority(
        language=None,
        manual_langs=["en"],
        auto_langs=["tr"],
    )
    # En öncelik: manuel EN > auto TR
    assert out[0] == "en"
    assert "tr" in out


def test_resolve_caption_priority_returns_empty_when_no_subtitles() -> None:
    from ingestion.youtube import _resolve_caption_priority

    out = _resolve_caption_priority(
        language="tr",
        manual_langs=[],
        auto_langs=[],
    )
    assert out == []


def test_resolve_caption_priority_uses_fallback_when_none_match() -> None:
    """Orijinal dil/EN/TR yoksa ama başka dil var → fallback liste devreye girsin."""
    from ingestion.youtube import _resolve_caption_priority

    # Hiçbir target match etmiyor; ama mevcut "fr" auto var
    # ve "fr" fallback liste'sinde değil → boş döner
    out = _resolve_caption_priority(
        language="fr",
        manual_langs=[],
        auto_langs=["fr"],
    )
    # "fr" orijinal dil targets'ta var → priority'e eklenir
    assert "fr" in out


def test_resolve_caption_priority_dedupes_region_variants() -> None:
    """`tr` ve `tr-TR` ikisi de varsa duplicate eklenmemeli."""
    from ingestion.youtube import _resolve_caption_priority

    out = _resolve_caption_priority(
        language="tr-TR",
        manual_langs=["tr-TR", "tr"],
        auto_langs=["tr"],
    )
    # Her dil yalnız bir kez (manuel grubunda)
    assert len(out) == len(set(out))
    assert "tr-TR" in out
    assert "tr" in out


async def test_fetch_transcript_cleans_up_audio_dir_after_api(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """fetch_audio_only'nin oluşturduğu temp dizin API success sonrası silinir."""
    monkeypatch.setenv("WHISPER_API_URL", "http://localhost:9000")

    audio_dir = tmp_path / "to_be_cleaned"
    audio_dir.mkdir()
    audio_file = audio_dir / "v.mp3"
    audio_file.write_bytes(b"\xff\xfb")

    async def fake_subs(_url):
        return None

    async def fake_audio(_url):
        return audio_file

    async def fake_api(audio_path, **_kw):
        return Transcript(text="ok", source="whisper-api")

    monkeypatch.setattr("ingestion.youtube.fetch_subs_via_ytdlp", fake_subs)
    monkeypatch.setattr("ingestion.youtube.fetch_audio_only", fake_audio)
    monkeypatch.setattr("ingestion.youtube.transcribe_via_whisper_api", fake_api)

    result = await fetch_transcript("https://youtu.be/test")
    assert result is not None
    # Cleanup gerçekleşmiş olmalı
    assert not audio_dir.exists()


# Quiet the unused-import warnings for `patch`
_ = patch
