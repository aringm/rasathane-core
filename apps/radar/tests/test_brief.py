"""Phase 33-i: brief.py — purge_audio_artifacts + appendix unit tests."""

from __future__ import annotations


def test_purge_audio_artifacts_clears_json_script(tmp_path):
    """Phase 33-i: regen sırasında 00-brief.audio.json da temizlenir."""
    from rasathane_mcp.core.brief import _purge_audio_artifacts

    target = tmp_path / "2026-05-19"
    target.mkdir()
    (target / "00-brief.mp3").write_bytes(b"old mp3")
    (target / "00-brief.audio.txt").write_text("old script")
    (target / "00-brief.audio.json").write_text('[{"speaker":"X","text":"old"}]')
    (target / ".audio.lock").write_text("{}")

    _purge_audio_artifacts(target)

    assert not (target / "00-brief.mp3").exists()
    assert not (target / "00-brief.audio.txt").exists()
    assert not (target / "00-brief.audio.json").exists()
    assert not (target / ".audio.lock").exists()
