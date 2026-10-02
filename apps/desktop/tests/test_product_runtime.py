from __future__ import annotations

from pathlib import Path
from unittest.mock import Mock

import pytest
from ytcore.local import llamacpp, resources
from ytcore.local.worker import worker_command


def test_memory_gate_measures_free_not_total(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(resources, "available_bytes", lambda: 1024**3)
    with pytest.raises(RuntimeError, match="boş RAM yetersiz"):
        resources.require_memory(1024**3)
    monkeypatch.setattr(resources, "available_bytes", lambda: None)
    with pytest.raises(RuntimeError, match="ölçülemedi"):
        resources.require_memory(1)


def test_missing_packaged_worker_never_falls_back_to_repo(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("RASATHANE_WORKER_EXE", str(tmp_path / "missing.exe"))
    with pytest.raises(FileNotFoundError, match="bağımsız worker"):
        worker_command("ner", "unexpected-python", [])


def test_packaged_worker_is_independent_and_unloads_owned_models(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    worker = tmp_path / "worker.exe"
    worker.write_bytes(b"test")
    monkeypatch.setenv("RASATHANE_WORKER_EXE", str(worker))
    unload = Mock()
    monkeypatch.setattr(llamacpp, "_prosesleri_kapat", unload)
    monkeypatch.setattr(resources, "available_bytes", lambda: 6 * 1024**3)
    assert worker_command("ner", "repo-python", ["--in", "input.json"]) == [
        str(worker),
        "ner",
        "--in",
        "input.json",
    ]
    unload.assert_called_once()


def test_port_collision_host_is_persisted_and_removed_on_shutdown(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    process = Mock()
    process.poll.return_value = None
    monkeypatch.setitem(llamacpp._prosesler, "llm", process)
    monkeypatch.setitem(llamacpp._aktif_hostlar, "llm", "http://127.0.0.1:8080")
    fingerprint = ("model.gguf", "ram8", 4096, 100, 100)
    monkeypatch.setitem(llamacpp._model_fingerprints, "llm", fingerprint)
    monkeypatch.setattr(llamacpp, "_model_fingerprint", lambda tur: fingerprint)
    monkeypatch.setattr(llamacpp, "aktif_profil", lambda: "ram8")
    monkeypatch.setattr(
        llamacpp,
        "sunucu_model_kimligi",
        lambda host: str(llamacpp.PROFILLER["ram8"]["llm_dosya"]),
    )
    monkeypatch.setattr(
        llamacpp, "sunucu_saglikli_mi", lambda host, **kwargs: host.endswith(":8080")
    )
    assert llamacpp.sunucu_baslat_gerekirse("llm") == "http://127.0.0.1:8080"
    llamacpp._proses_kapat("llm")
    assert "llm" not in llamacpp._aktif_hostlar
    process.terminate.assert_called_once()


def test_ram8_context_is_bounded() -> None:
    assert llamacpp.profil_bilgisi("ram8")["num_ctx"] == 4096
