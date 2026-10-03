"""Edge-tts mp3 dosyalarına Xing header inject davranışını pin'le.

Browser ``<audio preload="metadata">`` Xing/Info header'ı olmayan
mp3'lerde duration tahmininde başarısız (Chrome 0:05 gösteriyor —
gerçek 8:34). Fix `llm.tts._inject_xing_header_sync` ffmpeg ile
copy-mux yapar; bu test header'ın gerçekten yazıldığını + ffmpeg
yokken graceful skip davranışını doğrular.
"""

from __future__ import annotations

import shutil
from pathlib import Path
from unittest.mock import patch

import pytest
from llm.tts import _inject_xing_header_sync, inject_xing_header
from mutagen.mp3 import MP3, BitrateMode


def _find_real_edge_tts_mp3() -> Path | None:
    """Test sırasında gerçek bir edge-tts mp3'ü fixture olarak kullan.

    Repo'da `archive/YYYY-MM-DD/00-brief.mp3` dosyaları edge-tts
    çıktısı. CI'da yoksa skip — bu test local-only davranış pin'liyor.
    """
    repo_root = Path(__file__).resolve().parents[1]
    archive = repo_root / "archive"
    if not archive.is_dir():
        return None
    for child in sorted(archive.iterdir(), reverse=True):
        if not child.is_dir() or not child.name.replace("-", "").isdigit():
            continue
        mp3 = child / "00-brief.mp3"
        if mp3.is_file():
            return mp3
    return None


def test_inject_xing_header_yields_known_bitrate_mode(tmp_path: Path) -> None:
    """Edge-tts mp3'ünden sonra ``bitrate_mode`` UNKNOWN olmaz.

    İki patika:
    - Fresh edge-tts mp3 (UNKNOWN): inject sonrası CBR olur.
    - Önceden fix edilmiş mp3 (CBR): inject idempotent, yine CBR kalır.
    """
    if not shutil.which("ffmpeg"):
        pytest.skip("ffmpeg not available — best-effort skip path covered elsewhere")
    source = _find_real_edge_tts_mp3()
    if source is None:
        pytest.skip("no real edge-tts mp3 fixture in archive/")

    target = tmp_path / "test.mp3"
    target.write_bytes(source.read_bytes())

    before = MP3(target).info
    before_mode = before.bitrate_mode
    assert before_mode in {BitrateMode.UNKNOWN, BitrateMode.CBR}, (
        f"unexpected fixture mode {before_mode!r}; edge-tts writes UNKNOWN, "
        "batch fix converts to CBR — anything else means fixture drifted"
    )

    ok = _inject_xing_header_sync(target)
    assert ok is True

    after = MP3(target).info
    # Asıl invariant: header artık tanımlı, browser duration'ı okuyabilir
    assert after.bitrate_mode != BitrateMode.UNKNOWN
    assert abs(after.length - before.length) < 0.5  # süre korundu
    assert target.stat().st_size > 0


def test_inject_xing_header_ffmpeg_missing_graceful_skip(tmp_path: Path) -> None:
    """ffmpeg yoksa False döner, mp3 dokunulmaz, hata fırlatmaz."""
    mp3 = tmp_path / "x.mp3"
    mp3.write_bytes(b"\xff\xfb\x90\x00fake mp3 bytes")
    original_bytes = mp3.read_bytes()

    with patch("llm.tts.shutil.which", return_value=None):
        ok = _inject_xing_header_sync(mp3)

    assert ok is False
    assert mp3.read_bytes() == original_bytes


def test_inject_xing_header_invalid_mp3_returns_false(tmp_path: Path) -> None:
    """Bozuk mp3'te ffmpeg fail → False, orijinal korunur."""
    if not shutil.which("ffmpeg"):
        pytest.skip("ffmpeg not available")
    mp3 = tmp_path / "bad.mp3"
    mp3.write_bytes(b"not an mp3 at all, just garbage bytes")
    original_bytes = mp3.read_bytes()

    ok = _inject_xing_header_sync(mp3)

    assert ok is False
    # ffmpeg fail'lerse temp dosya temizlenir, original dokunulmaz
    assert mp3.read_bytes() == original_bytes
    assert not (tmp_path / "bad.mp3.xingfix.tmp").exists()


@pytest.mark.asyncio
async def test_inject_xing_header_async_delegates(tmp_path: Path) -> None:
    """Async wrapper sync core'u to_thread'de çağırır."""
    mp3 = tmp_path / "y.mp3"
    mp3.write_bytes(b"\xff\xfb\x90\x00")

    with patch("llm.tts.shutil.which", return_value=None):
        ok = await inject_xing_header(mp3)

    assert ok is False
