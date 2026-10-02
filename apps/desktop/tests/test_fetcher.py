from __future__ import annotations

import pytest
from ytcore.transcript.fetcher import FixtureFetcher, fetcher_al


def _fake_ydl(monkeypatch, info_value):
    """yt_dlp.YoutubeDL'i sahte bir context manager ile değiştir (ağsız boundary testi)."""
    import yt_dlp

    class FakeYDL:
        def __init__(self, opts):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def extract_info(self, url, download=False):
            return info_value

    monkeypatch.setattr(yt_dlp, "YoutubeDL", FakeYDL)


def test_fixture_clean_altyazi_verir():
    f = FixtureFetcher("clean")
    meta = f.metadata("https://youtu.be/x")
    alt = f.altyazi("https://youtu.be/x")
    assert meta.info["title"]
    assert alt is not None and "WEBVTT" in alt.vtt and alt.dil == "tr"


def test_fixture_altyazi_yok():
    f = FixtureFetcher("altyazi_yok")
    assert f.altyazi("https://youtu.be/x") is None


def test_fixture_pii_altyazida_rakam():
    f = FixtureFetcher("pii")
    alt = f.altyazi("https://youtu.be/x")
    assert alt is not None and any(c.isdigit() for c in alt.vtt)


def test_fixture_dosya_yolu(tmp_path):
    p = tmp_path / "ozel.vtt"
    p.write_text("WEBVTT\n\n00:00:01.000 --> 00:00:02.000\nözel içerik", encoding="utf-8")
    f = FixtureFetcher(str(p))
    alt = f.altyazi("https://youtu.be/x")
    assert alt is not None and "özel içerik" in alt.vtt


def test_factory_env_fixture(monkeypatch):
    monkeypatch.setenv("YT_TRANSCRIPT_FIXTURE", "clean")
    assert isinstance(fetcher_al(), FixtureFetcher)


def test_factory_env_yoksa_ytdlp(monkeypatch):
    monkeypatch.delenv("YT_TRANSCRIPT_FIXTURE", raising=False)
    f = fetcher_al()
    assert f.__class__.__name__ == "YtDlpFetcher"


def test_metadata_none_info_runtimeerror(monkeypatch):
    # Re-review MED: yt-dlp extract_info None döner (extractor boş) → dict(None) TypeError
    # DEĞİL, net RuntimeError (graph graceful 'hata' yakalar; re-raise listesine kaçmaz).
    from ytcore.transcript.ytdlp_fetcher import YtDlpFetcher

    _fake_ydl(monkeypatch, None)
    with pytest.raises(RuntimeError):
        YtDlpFetcher().metadata("https://youtu.be/x")


def test_altyazi_vtt_url_yoksa_cokmez(monkeypatch):
    # Re-review MED: vtt format VAR ama 'url' anahtarı YOK (yt-dlp data-only) → f['url']
    # KeyError ATMAMALI → kullanılabilir altyazı yok say (None).
    from ytcore.transcript.ytdlp_fetcher import YtDlpFetcher

    info = {
        "subtitles": {"tr": [{"ext": "vtt", "data": "inline"}]},  # url YOK
        "automatic_captions": {},
    }
    _fake_ydl(monkeypatch, info)
    assert YtDlpFetcher().altyazi("https://youtu.be/x") is None


def test_audio_download_preserves_container_for_packaged_asr(monkeypatch, tmp_path):
    """ASR girişi external ffmpeg gerektirmeden indirilen media dosyasıdır."""
    import yt_dlp
    from ytcore.transcript.ytdlp_fetcher import YtDlpFetcher

    media = b"compressed-media-boundary"

    class FakeYDL:
        def __init__(self, opts):
            assert opts["format"] == "bestaudio/best"
            assert not opts.get("postprocessors")

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def download(self, urls):
            assert urls == ["https://youtu.be/audio"]
            (tmp_path / "ses.webm").write_bytes(media)

    monkeypatch.setattr(yt_dlp, "YoutubeDL", FakeYDL)
    downloaded = YtDlpFetcher().ses_indir("https://youtu.be/audio", tmp_path)
    assert downloaded.name == "ses.webm"
    assert downloaded.read_bytes() == media
