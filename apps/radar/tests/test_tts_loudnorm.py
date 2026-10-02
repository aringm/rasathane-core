"""Phase 32-v: loudnorm post-process testleri.

`_apply_loudnorm_sync` ffmpeg subprocess'i mock'lanır — gerçek ffmpeg
çağrılmaz. Hata path'leri (ffmpeg yok, non-zero rc) graceful False döner.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest
from llm import tts


def test_apply_loudnorm_returns_false_when_ffmpeg_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """ffmpeg PATH'te yok → warning + False, mp3 dokunulmaz."""
    mp3 = tmp_path / "test.mp3"
    mp3.write_bytes(b"FAKEMP3DATA")
    original = mp3.read_bytes()
    monkeypatch.setattr(tts.shutil, "which", lambda _: None)
    assert tts._apply_loudnorm_sync(mp3) is False
    assert mp3.read_bytes() == original  # değişmedi


def test_apply_loudnorm_returns_false_when_ffmpeg_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """ffmpeg returncode != 0 → tmp silinir, False döner."""
    mp3 = tmp_path / "test.mp3"
    mp3.write_bytes(b"FAKEMP3DATA")
    monkeypatch.setattr(tts.shutil, "which", lambda _: "/fake/ffmpeg")

    def fake_run(*_args: Any, **_kwargs: Any) -> Any:
        result = MagicMock()
        result.returncode = 1
        result.stderr = b"loudnorm: input invalid"
        return result

    monkeypatch.setattr(tts.subprocess, "run", fake_run)
    assert tts._apply_loudnorm_sync(mp3) is False
    # Tmp dosya silindi
    tmp = mp3.with_suffix(mp3.suffix + ".loudnorm.tmp")
    assert not tmp.exists()


def test_apply_loudnorm_swallows_os_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """subprocess fırlatırsa (OSError/SubprocessError) → False, mp3 korunur."""
    mp3 = tmp_path / "test.mp3"
    mp3.write_bytes(b"FAKEMP3DATA")
    monkeypatch.setattr(tts.shutil, "which", lambda _: "/fake/ffmpeg")

    def raise_oserror(*_args: Any, **_kwargs: Any) -> Any:
        raise OSError("simulated subprocess failure")

    monkeypatch.setattr(tts.subprocess, "run", raise_oserror)
    assert tts._apply_loudnorm_sync(mp3) is False
    assert mp3.is_file()  # original korunur


def test_apply_loudnorm_succeeds_when_ffmpeg_returns_zero(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Mock ffmpeg returncode=0 + tmp'a normalize output yazar → True + dosya replace."""
    mp3 = tmp_path / "test.mp3"
    mp3.write_bytes(b"ORIGINAL_MP3_DATA")
    monkeypatch.setattr(tts.shutil, "which", lambda _: "/fake/ffmpeg")

    def fake_run(*args: Any, **_kwargs: Any) -> Any:
        # ffmpeg args: 4. arg = output tmp path (heuristic)
        argv = args[0]
        out_path_str = argv[-1]
        Path(out_path_str).write_bytes(b"NORMALIZED_MP3_DATA_DIFFERENT_SIZE")
        result = MagicMock()
        result.returncode = 0
        return result

    monkeypatch.setattr(tts.subprocess, "run", fake_run)
    # Phase 35-iii: dual_pass=False → single-pass (Pass 1 JSON parse mock'sız çalışmaz)
    assert tts._apply_loudnorm_sync(mp3, dual_pass=False) is True
    # Tmp dosya os.replace ile mp3'e taşındı
    assert mp3.read_bytes() == b"NORMALIZED_MP3_DATA_DIFFERENT_SIZE"
    tmp = mp3.with_suffix(mp3.suffix + ".loudnorm.tmp")
    assert not tmp.exists()


def test_apply_loudnorm_respects_target_parameters(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Custom target_i/true_peak/lra ffmpeg argv'sine geçiyor."""
    mp3 = tmp_path / "test.mp3"
    mp3.write_bytes(b"DATA")
    monkeypatch.setattr(tts.shutil, "which", lambda _: "/fake/ffmpeg")
    captured_argv: list[Any] = []

    def fake_run(args: Any, **_kwargs: Any) -> Any:
        captured_argv.extend(args)
        Path(args[-1]).write_bytes(b"OUT")
        return MagicMock(returncode=0)

    monkeypatch.setattr(tts.subprocess, "run", fake_run)
    # Phase 35-iii: dual_pass=False → single-pass; argv'de target_i/TP/LRA görünür
    tts._apply_loudnorm_sync(mp3, target_i=-23.0, true_peak=-2.0, lra=7.0, dual_pass=False)
    af_idx = captured_argv.index("-af")
    af_value = captured_argv[af_idx + 1]
    assert "I=-23.0" in af_value
    assert "TP=-2.0" in af_value
    assert "LRA=7.0" in af_value


def test_apply_loudnorm_passes_explicit_mp3_format_flag(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Phase 35-vii: ffmpeg argv'sinde `-f mp3` flag'i bulunmalı.

    Regression: tmp dosya path'i `.mp3.loudnorm.tmp` (Path.with_suffix
    suffix append davranışı) bittiği için ffmpeg 8.1 muxer auto-detect
    reddediyordu — tüm loudnorm pass'leri silently fail oluyor, brief
    audio -23 LUFS civarında kalıyordu. `-f mp3` explicit format
    container kararını deterministik yapar; .tmp suffix path semantik
    korunur (intermediary file).
    """
    mp3 = tmp_path / "test.mp3"
    mp3.write_bytes(b"DATA")
    monkeypatch.setattr(tts.shutil, "which", lambda _: "/fake/ffmpeg")
    captured_argv: list[Any] = []

    def fake_run(args: Any, **_kwargs: Any) -> Any:
        captured_argv.extend(args)
        Path(args[-1]).write_bytes(b"OUT")
        return MagicMock(returncode=0)

    monkeypatch.setattr(tts.subprocess, "run", fake_run)
    tts._apply_loudnorm_sync(mp3, dual_pass=False)

    # `-f mp3` sırayla bitişik olmalı (positional pair)
    assert "-f" in captured_argv, "ffmpeg argv'sinde `-f` flag yok"
    f_idx = captured_argv.index("-f")
    assert captured_argv[f_idx + 1] == "mp3", "`-f` sonrası 'mp3' bekleniyor"
    # Output path hâlâ `.loudnorm.tmp` ile bitsin (intermediary semantic korundu)
    assert captured_argv[-1].endswith(".loudnorm.tmp")


@pytest.mark.asyncio
async def test_apply_loudnorm_async_wrapper_calls_sync(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`apply_loudnorm` async wrapper'ı `_apply_loudnorm_sync`'i to_thread ile çağırır."""
    mp3 = tmp_path / "test.mp3"
    mp3.write_bytes(b"DATA")
    call_count = {"n": 0}

    def fake_sync(path: Path, **_kwargs: Any) -> bool:
        call_count["n"] += 1
        return True

    monkeypatch.setattr(tts, "_apply_loudnorm_sync", fake_sync)
    result = await tts.apply_loudnorm(mp3)
    assert result is True
    assert call_count["n"] == 1


def test_loudnorm_tmp_suffix_does_not_collide_with_xing(tmp_path: Path) -> None:
    """Loudnorm `.loudnorm.tmp` ve Xing `.xingfix.tmp` aynı suffix kullanmıyor (pipeline'da
    her ikisi sırayla çağrılır, race olmamalı)."""
    mp3 = tmp_path / "test.mp3"
    mp3.write_bytes(b"x")
    ln_tmp = mp3.with_suffix(mp3.suffix + ".loudnorm.tmp")
    xing_tmp = mp3.with_suffix(mp3.suffix + ".xingfix.tmp")
    assert ln_tmp != xing_tmp


# ── Phase 35-iii: Dual-pass loudnorm ─────────────────────────────────


def test_dual_pass_uses_measured_values_from_pass1(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Phase 35-iii: dual_pass=True → Pass 1 JSON parse → Pass 2 measured_* arg'larıyla."""
    mp3 = tmp_path / "test.mp3"
    mp3.write_bytes(b"INPUT")
    monkeypatch.setattr(tts.shutil, "which", lambda _: "/fake/ffmpeg")

    pass1_stderr = b'''
[Parsed_loudnorm_0 @ 0x7f] {
    "input_i" : "-23.5",
    "input_tp" : "-1.2",
    "input_lra" : "8.4",
    "input_thresh" : "-33.7",
    "output_i" : "-16.0",
    "output_tp" : "-1.5",
    "output_lra" : "11.0",
    "output_thresh" : "-26.2",
    "normalization_type" : "dynamic",
    "target_offset" : "0.50"
}
'''
    captured_calls: list[list[str]] = []

    def fake_run(args: Any, **_kwargs: Any) -> Any:
        captured_calls.append(list(args))
        result = MagicMock()
        result.returncode = 0
        # Pass 1 detect: "-f null -" var
        if "-f" in args and args[args.index("-f") + 1] == "null":
            result.stderr = pass1_stderr
            return result
        # Pass 2: output file yazılır
        Path(args[-1]).write_bytes(b"NORMALIZED")
        result.stderr = b""
        return result

    monkeypatch.setattr(tts.subprocess, "run", fake_run)
    ok = tts._apply_loudnorm_sync(mp3, dual_pass=True)
    assert ok is True
    # 2 ffmpeg çağrısı yapıldı (pass1 measure + pass2 apply)
    assert len(captured_calls) == 2
    pass2_argv = captured_calls[1]
    af_idx = pass2_argv.index("-af")
    af_value = pass2_argv[af_idx + 1]
    assert "measured_I=-23.5" in af_value
    assert "measured_LRA=8.4" in af_value
    assert "measured_TP=-1.2" in af_value
    assert "linear=true" in af_value


def test_dual_pass_falls_back_to_single_when_pass1_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Phase 35-iii: Pass 1 JSON parse edemezse single-pass'a düşer (silently)."""
    mp3 = tmp_path / "test.mp3"
    mp3.write_bytes(b"INPUT")
    monkeypatch.setattr(tts.shutil, "which", lambda _: "/fake/ffmpeg")
    call_count = {"n": 0}

    def fake_run(args: Any, **_kwargs: Any) -> Any:
        call_count["n"] += 1
        result = MagicMock()
        result.returncode = 0
        if "-f" in args and args[args.index("-f") + 1] == "null":
            # Pass 1: invalid stderr (no JSON)
            result.stderr = b"no json here"
            return result
        # Pass 2 (single-pass fallback): output yazılır
        Path(args[-1]).write_bytes(b"NORMALIZED")
        result.stderr = b""
        return result

    monkeypatch.setattr(tts.subprocess, "run", fake_run)
    ok = tts._apply_loudnorm_sync(mp3, dual_pass=True)
    assert ok is True
    # Pass 1 + single-pass apply = 2 ffmpeg çağrısı (Pass 1 fail edip single'a düşer)
    assert call_count["n"] == 2
