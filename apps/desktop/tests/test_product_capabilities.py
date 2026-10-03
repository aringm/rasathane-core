from __future__ import annotations

import httpx
import pytest
from rasathane.product import capabilities
from ytcore.local import llamacpp
from ytmcp import tools
from ytmcp.server import gui_http_app


@pytest.fixture
def packaged_files(tmp_path, monkeypatch):
    worker = tmp_path / "worker.exe"
    worker.write_bytes(b"installed-worker")
    monkeypatch.setenv("RASATHANE_WORKER_EXE", str(worker))
    monkeypatch.setenv("RASATHANE_NATIVE_TTS", "1")
    monkeypatch.delenv("YT_NER_FIXTURE", raising=False)
    monkeypatch.setattr(capabilities, "windows_turkish_voice_ready", lambda: True)
    for kind, names in {
        "NER": ("config.json", "tokenizer_config.json", "model.safetensors"),
        "ASR": ("config.json", "tokenizer.json", "model.bin"),
    }.items():
        directory = tmp_path / kind
        directory.mkdir()
        for name in names:
            (directory / name).write_bytes(b"installed-model-file")
        monkeypatch.setenv(f"RASATHANE_{kind}_MODEL", str(directory))
    motor = tmp_path / "motor"
    (motor / "bin").mkdir(parents=True)
    (motor / "bin" / "llama-server.exe").write_bytes(b"server")
    (motor / "modeller").mkdir()
    for key in ("llm_dosya", "embed_dosya"):
        (motor / "modeller" / str(llamacpp.PROFILLER["ram8"][key])).write_bytes(b"gguf")
    monkeypatch.setenv("RASATHANE_MOTOR_DIR", str(motor))
    monkeypatch.setenv("YT_MOTOR_BACKEND", "llamacpp")
    monkeypatch.setenv("YT_LLAMACPP_PROFIL", "ram8")
    return tmp_path


async def test_packaged_installation_reports_worker_instead_of_external_python(
    packaged_files, monkeypatch
):
    def external_spawn_forbidden(*args, **kwargs):
        raise AssertionError("Paketli kurulum harici Python çalıştırmamalı.")

    monkeypatch.setattr("subprocess.run", external_spawn_forbidden)
    assert tools._ner_erisilebilir_mi() is True
    assert tools._ner_kaynak() == "packaged_worker"
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=gui_http_app()),
        base_url="http://localhost",
        headers={"Origin": "rasathane://app"},
    ) as client:
        response = await client.get("/gui/kurulum")
        assert response.status_code == 200
        status = response.json()
        assert status["ner_erisilebilir"] is True and status["asr_hazir"] is True
        assert status["tts_hazir"] is True and status["tts_saglayici"] == "windows"
        assert status["tam_ozellik_hazir"] is True
        assert status["runtime_verification"] == "installed_files"


def test_incomplete_packaged_model_and_missing_voice_are_visible(packaged_files, monkeypatch):
    (packaged_files / "NER" / "model.safetensors").unlink()
    (packaged_files / "ASR" / "model.bin").write_bytes(b"")
    monkeypatch.setattr(capabilities, "windows_turkish_voice_ready", lambda: False)
    status = tools.kurulum_kontrol_core()
    assert status["worker_runtime_hazir"] is True
    assert status["ner_erisilebilir"] is False and status["asr_hazir"] is False
    assert status["tts_hazir"] is False and status["tam_ozellik_hazir"] is False
    assert status["ner_kaynak"] == "packaged_worker_missing"


def test_missing_worker_cannot_claim_model_ready(packaged_files):
    (packaged_files / "worker.exe").unlink()
    status = capabilities.packaged_runtime_status()
    assert status["worker_runtime_hazir"] is False
    assert status["ner_erisilebilir"] is False and status["asr_hazir"] is False
