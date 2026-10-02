from __future__ import annotations

import hashlib
import os
from pathlib import Path

import pytest
from ytcore.pipeline.api import AnalysisCancelled, kaynak_analiz_et


def test_streamed_engine_result_and_profile_restore(tmp_output_base, tmp_path, monkeypatch):
    monkeypatch.setenv("YT_LLAMACPP_PROFIL", "auto")
    stages = []
    result = kaynak_analiz_et(
        "https://youtu.be/test-product",
        "hukuk",
        "product-progress",
        tmp_path,
        cancel_check=lambda: False,
        progress=stages.append,
        profile="ram8",
    )
    assert result.stub is False
    assert result.ozet_detay
    assert "pii_gate" in stages and "output" in stages
    assert os.environ["YT_LLAMACPP_PROFIL"] == "auto"


def test_cancellation_after_first_node_stops_before_content(tmp_output_base, tmp_path):
    stopped, stages = False, []

    def progress(stage):
        nonlocal stopped
        stages.append(stage)
        stopped = True

    with pytest.raises(AnalysisCancelled):
        kaynak_analiz_et(
            "https://youtu.be/test-cancel",
            "hukuk",
            "product-cancel",
            tmp_path,
            cancel_check=lambda: stopped,
            progress=progress,
            profile="ram8",
        )
    assert stages == ["transcript"]
    assert not list(tmp_output_base.rglob("04_ozet.md"))


def test_two_product_runs_same_source_keep_first_bytes_and_no_stale_translation(
    tmp_output_base, tmp_path
):
    from ytcore.config import get_config
    from ytmcp.tools import kutuphane_listele_core

    first = kaynak_analiz_et(
        "https://youtu.be/same-source",
        "hukuk",
        "1" * 32,
        tmp_path / "checkpoints",
        output_run_id="1" * 32,
    )
    first_folder = Path(first.klasor)
    # Simulate an earlier run which had a translated artifact. It belongs only to run1.
    translated = first_folder / "02_transcript_tr.md"
    translated.write_text("Önceki run çevirisi", encoding="utf-8")
    first_hashes = {
        path.name: hashlib.sha256(path.read_bytes()).hexdigest()
        for path in first_folder.iterdir()
        if path.is_file()
    }
    cfg = get_config()
    second = kaynak_analiz_et(
        "https://youtu.be/same-source",
        "hukuk",
        "2" * 32,
        tmp_path / "checkpoints",
        output_run_id="2" * 32,
    )
    second_folder = Path(second.klasor)
    assert second_folder != first_folder
    assert first_folder.name.endswith("1" * 32)
    assert second_folder.name.endswith("2" * 32)
    assert len(second_folder.relative_to(tmp_output_base).parts) == 3
    assert second.ceviri_durumu == "atlandi"
    assert not (second_folder / "02_transcript_tr.md").exists()
    for name, content_hash in first_hashes.items():
        assert hashlib.sha256((first_folder / name).read_bytes()).hexdigest() == content_hash
    assert get_config().output_base == cfg.output_base
    assert get_config().index_base == cfg.index_base
    listed = kutuphane_listele_core()
    assert {item["klasor"] for item in listed} == {str(first_folder), str(second_folder)}


@pytest.mark.parametrize("run_id", ["../evil", "", "f" * 31, "F" * 32, "g" * 32])
def test_product_run_id_is_exact_lowercase_uuid_hex(tmp_output_base, tmp_path, run_id):
    with pytest.raises(ValueError, match="run"):
        kaynak_analiz_et(
            "https://youtu.be/run-id",
            "hukuk",
            "run-id-test",
            tmp_path / "checkpoints",
            output_run_id=run_id,
        )
    assert not list(tmp_output_base.rglob("00_index.json"))


def test_reusing_immutable_run_id_cannot_overwrite_completed_files(tmp_output_base, tmp_path):
    run_id = "a" * 32
    result = kaynak_analiz_et(
        "https://youtu.be/immutable",
        "hukuk",
        run_id,
        tmp_path / "checkpoints",
        output_run_id=run_id,
    )
    original = (Path(result.klasor) / "00_index.json").read_bytes()
    with pytest.raises(FileExistsError):
        kaynak_analiz_et(
            "https://youtu.be/immutable",
            "hukuk",
            "another-checkpoint",
            tmp_path / "checkpoints",
            output_run_id=run_id,
        )
    assert (Path(result.klasor) / "00_index.json").read_bytes() == original
