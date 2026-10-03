"""Phase 34-i: per-segment loudnorm tests."""

from pathlib import Path
from unittest.mock import patch

import pytest


@pytest.mark.asyncio
async def test_apply_per_segment_loudnorm_calls_once_per_segment(tmp_path):
    """Phase 34-i: 3 segment → apply_loudnorm 3 kez çağrılır."""
    from llm import tts

    segs = [tmp_path / f"seg{i}.mp3" for i in range(3)]
    for s in segs:
        s.write_bytes(b"\x00" * 1000)

    async def fake_apply(p: Path) -> bool:
        return True

    with patch.object(tts, "apply_loudnorm", side_effect=fake_apply) as mock_apply:
        result = await tts.apply_per_segment_loudnorm(segs)

    assert mock_apply.await_count == 3
    assert result == 3


@pytest.mark.asyncio
async def test_apply_per_segment_loudnorm_returns_success_count(tmp_path):
    """1 başarısız → return 2 (3 total)."""
    from llm import tts

    segs = [tmp_path / f"seg{i}.mp3" for i in range(3)]
    for s in segs:
        s.write_bytes(b"\x00" * 1000)

    call_count = 0

    async def maybe_fail(p: Path) -> bool:
        nonlocal call_count
        call_count += 1
        return call_count != 2  # 2. segment fail

    with patch.object(tts, "apply_loudnorm", side_effect=maybe_fail):
        result = await tts.apply_per_segment_loudnorm(segs)

    assert result == 2


@pytest.mark.asyncio
async def test_apply_per_segment_loudnorm_empty_list_returns_zero():
    from llm import tts

    result = await tts.apply_per_segment_loudnorm([])
    assert result == 0
