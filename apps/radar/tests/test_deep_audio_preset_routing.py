"""Phase 36-ii: audio_only(preset_id=...) routing + audio_meta.json."""

import json
from unittest.mock import AsyncMock, patch

import pytest
from rasathane_mcp.core import deep_analyze


@pytest.mark.asyncio
async def test_audio_only_unknown_preset_falls_back(tmp_path, monkeypatch):
    """preset_id geçersizse klasik_panel fallback + warning log."""
    monkeypatch.setattr(deep_analyze, "DEEP_DIR", tmp_path)
    job_id = "test_job_abc"
    job_dir = tmp_path / job_id
    job_dir.mkdir()
    (job_dir / "meta.json").write_text(
        json.dumps({"type": "youtube", "title": "T", "channel": "C", "url": "u"}),
        encoding="utf-8",
    )
    (job_dir / "summary.md").write_text("dummy summary", encoding="utf-8")
    (job_dir / "transcript.md").write_text("dummy transcript", encoding="utf-8")

    with patch.object(
        deep_analyze,
        "synthesize_with_claude",
        new=AsyncMock(return_value='[{"speaker":"Filiz","text":"x"}]'),
    ), patch("llm.tts.synthesize_podcast", new=AsyncMock()) as m_synth:
        # Audio dosyasını sahte üret
        async def fake_synth(*a, **kw):
            kw["output_path"].write_bytes(b"\xff\xfb" + b"\0" * 1024)

        m_synth.side_effect = fake_synth
        await deep_analyze.audio_only(
            job_id, force=True, preset_id="bilinmeyen_xyz"
        )
    meta_path = job_dir / "audio_meta.json"
    assert meta_path.is_file()
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    assert meta["preset_id"] == "klasik_panel"  # fallback


@pytest.mark.asyncio
async def test_audio_only_hizli_brifing_uses_fast_prompt(tmp_path, monkeypatch):
    """preset_id=hizli_brifing → prompt 'youtube_podcast_script_fast' yüklenir."""
    monkeypatch.setattr(deep_analyze, "DEEP_DIR", tmp_path)
    job_id = "test_job_def"
    job_dir = tmp_path / job_id
    job_dir.mkdir()
    (job_dir / "meta.json").write_text(
        json.dumps({"type": "youtube", "title": "T", "channel": "C", "url": "u"}),
        encoding="utf-8",
    )
    (job_dir / "summary.md").write_text("s", encoding="utf-8")
    (job_dir / "transcript.md").write_text("t", encoding="utf-8")

    loaded_prompts: list[str] = []
    original_load = deep_analyze.load_prompt

    def spy_load_prompt(name):
        loaded_prompts.append(name)
        return original_load(name)

    with patch.object(
        deep_analyze, "load_prompt", side_effect=spy_load_prompt
    ), patch.object(
        deep_analyze,
        "synthesize_with_claude",
        new=AsyncMock(return_value='[{"speaker":"Filiz","text":"x"}]'),
    ), patch("llm.tts.synthesize_podcast", new=AsyncMock()) as m_synth:

        async def fake_synth(*a, **kw):
            kw["output_path"].write_bytes(b"\xff\xfb" + b"\0" * 1024)

        m_synth.side_effect = fake_synth
        await deep_analyze.audio_only(
            job_id, force=True, preset_id="hizli_brifing"
        )
    assert "youtube_podcast_script_fast" in loaded_prompts


@pytest.mark.asyncio
async def test_audio_meta_json_contains_required_fields(tmp_path, monkeypatch):
    """audio_meta.json: preset_id, preset_name, voices_used, regen_count, etc."""
    monkeypatch.setattr(deep_analyze, "DEEP_DIR", tmp_path)
    job_id = "test_job_meta"
    job_dir = tmp_path / job_id
    job_dir.mkdir()
    (job_dir / "meta.json").write_text(
        json.dumps({"type": "youtube", "title": "T", "channel": "C", "url": "u"}),
        encoding="utf-8",
    )
    (job_dir / "summary.md").write_text("s", encoding="utf-8")
    (job_dir / "transcript.md").write_text("t", encoding="utf-8")

    with patch.object(
        deep_analyze,
        "synthesize_with_claude",
        new=AsyncMock(return_value='[{"speaker":"Filiz","text":"x"}]'),
    ), patch("llm.tts.synthesize_podcast", new=AsyncMock()) as m_synth:

        async def fake_synth(*a, **kw):
            kw["output_path"].write_bytes(b"\xff\xfb" + b"\0" * 1024)

        m_synth.side_effect = fake_synth
        await deep_analyze.audio_only(job_id, force=True, preset_id="klasik_panel")
    meta = json.loads((job_dir / "audio_meta.json").read_text(encoding="utf-8"))
    assert meta["preset_id"] == "klasik_panel"
    assert meta["preset_name"] == "Klasik Panel"
    assert "generated_at" in meta
    assert "voices_used" in meta
    assert meta["regen_count"] == 1


@pytest.mark.asyncio
async def test_regen_count_increments_on_force(tmp_path, monkeypatch):
    """İkinci force=True çağrısı regen_count'u 2'ye çıkarır."""
    monkeypatch.setattr(deep_analyze, "DEEP_DIR", tmp_path)
    job_id = "test_job_regen"
    job_dir = tmp_path / job_id
    job_dir.mkdir()
    (job_dir / "meta.json").write_text(
        json.dumps({"type": "youtube", "title": "T", "channel": "C", "url": "u"}),
        encoding="utf-8",
    )
    (job_dir / "summary.md").write_text("s", encoding="utf-8")
    (job_dir / "transcript.md").write_text("t", encoding="utf-8")

    with patch.object(
        deep_analyze,
        "synthesize_with_claude",
        new=AsyncMock(return_value='[{"speaker":"Filiz","text":"x"}]'),
    ), patch("llm.tts.synthesize_podcast", new=AsyncMock()) as m_synth:

        async def fake_synth(*a, **kw):
            kw["output_path"].write_bytes(b"\xff\xfb" + b"\0" * 1024)

        m_synth.side_effect = fake_synth
        await deep_analyze.audio_only(job_id, force=True, preset_id="klasik_panel")
        await deep_analyze.audio_only(job_id, force=True, preset_id="klasik_panel")
    meta = json.loads((job_dir / "audio_meta.json").read_text(encoding="utf-8"))
    assert meta["regen_count"] == 2
