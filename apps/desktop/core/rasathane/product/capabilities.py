"""Kurulu bağımsız runtime dosyaları; modelleri yüklemeden yapılan hazırlık kontrolü."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any


def _file_ready(path: Path) -> bool:
    try:
        return path.is_file() and path.stat().st_size > 0
    except OSError:
        return False


def _model_ready(name: str, required: tuple[str, ...], weights: tuple[str, ...]) -> bool:
    value = os.environ.get(name, "").strip()
    if not value:
        return False
    directory = Path(value)
    return all(_file_ready(directory / item) for item in required) and any(
        _file_ready(directory / item) for item in weights
    )


def windows_turkish_voice_ready() -> bool:
    """SAPI/OneCore kurulu Türkçe ses kaydı; ses üretimi yapmadan capability kontrolü."""
    if os.name != "nt":
        return False
    import winreg

    paths = (
        r"SOFTWARE\Microsoft\Speech_OneCore\Voices\Tokens",
        r"SOFTWARE\Microsoft\Speech\Voices\Tokens",
    )
    for hive in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
        for path in paths:
            try:
                with winreg.OpenKey(hive, path) as key:
                    for index in range(winreg.QueryInfoKey(key)[0]):
                        name = winreg.EnumKey(key, index)
                        try:
                            with winreg.OpenKey(key, name + r"\Attributes") as attributes:
                                language = str(winreg.QueryValueEx(attributes, "Language")[0])
                                if any(
                                    value.lower().lstrip("0") == "41f"
                                    for value in language.split(";")
                                ):
                                    return True
                        except OSError:
                            continue
            except OSError:
                continue
    return False


def packaged_runtime_status() -> dict[str, Any]:
    worker = os.environ.get("RASATHANE_WORKER_EXE", "").strip()
    worker_ready = bool(worker) and _file_ready(Path(worker))
    ner_ready = worker_ready and _model_ready(
        "RASATHANE_NER_MODEL",
        ("config.json", "tokenizer_config.json"),
        ("model.safetensors", "pytorch_model.bin"),
    )
    asr_ready = worker_ready and _model_ready(
        "RASATHANE_ASR_MODEL",
        ("config.json", "tokenizer.json"),
        ("model.bin",),
    )
    native_tts = os.environ.get("RASATHANE_NATIVE_TTS") == "1"
    tts_ready = native_tts and windows_turkish_voice_ready()
    return {
        "packaged_runtime": bool(worker),
        "worker_runtime_hazir": worker_ready,
        "ner_erisilebilir": ner_ready,
        "ner_kaynak": "packaged_worker" if ner_ready else "packaged_worker_missing",
        "ner_python": worker or None,
        "asr_hazir": asr_ready,
        "asr_kaynak": "packaged_faster_whisper" if asr_ready else "missing",
        "tts_hazir": tts_ready,
        "tts_saglayici": "windows" if native_tts else "piper",
        "tts_python": "windows_native" if native_tts else None,
        "runtime_verification": "installed_files",
    }
