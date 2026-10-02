"""Phase 36-iii: Addendum altyapısı testleri."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from rasathane_mcp.core import addendum


@pytest.mark.asyncio
async def test_suggest_angles_parses_json_array(tmp_path, monkeypatch):
    monkeypatch.setattr(addendum, "DEEP_DIR", tmp_path)
    job_id = "j1"
    (tmp_path / job_id).mkdir()
    (tmp_path / job_id / "summary.md").write_text("özet", encoding="utf-8")
    fake_response = """Önümde şu açılar var:
[
  {"slug": "hukuki_acilim", "title": "Hukuki açılım", "why": "değerli"},
  {"slug": "acik_kaynak", "title": "Açık kaynak boyutu", "why": "ilgi"}
]
Umarım faydalı."""
    with patch.object(
        addendum,
        "synthesize_with_claude",
        new=AsyncMock(return_value=fake_response),
    ):
        angles = await addendum.suggest_angles(job_id)
    assert len(angles) == 2
    assert angles[0]["slug"] == "hukuki_acilim"
    # Cache yazılmış mı?
    assert (tmp_path / job_id / addendum.ANGLES_CACHE).is_file()


@pytest.mark.asyncio
async def test_generate_freeform_writes_md_and_index(tmp_path, monkeypatch):
    monkeypatch.setattr(addendum, "DEEP_DIR", tmp_path)

    async def fake_tag_ctx(tags, limit=5):
        return "- Test başlık (kaynak)\n"

    monkeypatch.setattr(addendum, "_fetch_tag_context", fake_tag_ctx)
    job_id = "j2"
    (tmp_path / job_id).mkdir()
    (tmp_path / job_id / "summary.md").write_text("özet metni", encoding="utf-8")
    with patch.object(
        addendum,
        "synthesize_with_claude",
        new=AsyncMock(return_value="## Analiz\n\nBu hukuki açıdan…"),
    ):
        entry = await addendum.generate_freeform_addendum(
            job_id, "Bunu hukuki açıdan değerlendir", ["tr_hukuk"]
        )
    assert entry["type"] == "freeform"
    assert entry["tags"] == ["tr_hukuk"]
    assert entry["slug"].startswith("freeform_")
    # .md dosyası var
    assert (tmp_path / job_id / f"addendum_{entry['slug']}.md").is_file()
    # index güncellendi
    idx = addendum.load_index(job_id)
    assert len(idx) == 1
    assert idx[0]["slug"] == entry["slug"]


@pytest.mark.asyncio
async def test_generate_compare_rejects_invalid_count(tmp_path, monkeypatch):
    monkeypatch.setattr(addendum, "DEEP_DIR", tmp_path)
    job_id = "j3"
    (tmp_path / job_id).mkdir()
    (tmp_path / job_id / "summary.md").write_text("s", encoding="utf-8")
    with pytest.raises(ValueError, match="2-5 items"):
        await addendum.generate_compare_addendum(job_id, [1])
    with pytest.raises(ValueError, match="2-5 items"):
        await addendum.generate_compare_addendum(job_id, [1, 2, 3, 4, 5, 6])


def test_load_index_handles_corrupt_json(tmp_path, monkeypatch):
    monkeypatch.setattr(addendum, "DEEP_DIR", tmp_path)
    job_id = "j4"
    (tmp_path / job_id).mkdir()
    (tmp_path / job_id / addendum.INDEX_FILENAME).write_text(
        "{ not valid json", encoding="utf-8"
    )
    assert addendum.load_index(job_id) == []


def test_delete_addendum_removes_md_and_index_entry(tmp_path, monkeypatch):
    monkeypatch.setattr(addendum, "DEEP_DIR", tmp_path)
    job_id = "j5"
    (tmp_path / job_id).mkdir()
    md = tmp_path / job_id / "addendum_test.md"
    md.write_text("x", encoding="utf-8")
    addendum.save_index(job_id, [{"slug": "test", "type": "angle", "title": "T"}])
    assert addendum.delete_addendum(job_id, "test") is True
    assert not md.is_file()
    assert addendum.load_index(job_id) == []


@pytest.mark.asyncio
async def test_synthesize_addendum_audio_marks_index(tmp_path, monkeypatch):
    monkeypatch.setattr(addendum, "DEEP_DIR", tmp_path)
    job_id = "j_audio"
    (tmp_path / job_id).mkdir()
    md = tmp_path / job_id / "addendum_test.md"
    md.write_text("# Başlık\n\nBu **kalın** metin.", encoding="utf-8")
    addendum.save_index(
        job_id,
        [{"slug": "test", "type": "angle", "title": "T", "has_audio": False}],
    )

    async def fake_synth(text, *, output_path, **kwargs):
        output_path.write_bytes(b"\xff\xfb" + b"\0" * 512)

    with patch("llm.tts.synthesize_to_mp3", new=fake_synth):
        result = await addendum.synthesize_addendum_audio(job_id, "test")
    assert result["ok"] is True
    assert result["bytes"] > 0
    idx = addendum.load_index(job_id)
    assert idx[0]["has_audio"] is True
