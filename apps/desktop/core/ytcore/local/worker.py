"""Paketli worker veya geliştirme Python'u için tek dar komut sözleşmesi."""

from __future__ import annotations

import os
from pathlib import Path

_MODES = {
    "ner": "ytcore.router.ner_worker",
    "asr": "ytcore.transcript.asr_worker",
    "tts": "ytcore.uretim.tts_worker",
}


def worker_command(kind: str, python: str, args: list[str]) -> list[str]:
    if kind not in _MODES:
        raise ValueError("Bilinmeyen worker türü")
    executable = os.environ.get("RASATHANE_WORKER_EXE", "").strip()
    if executable:
        if not Path(executable).is_file():
            raise FileNotFoundError("Kurulumun bağımsız worker runtime'ı eksik. Kurulumu onarın.")
        from ytcore.local.llamacpp import _prosesleri_kapat
        from ytcore.local.resources import require_memory

        # Yalnız bu sidecar'ın sahip olduğu modeller kapatılır; yabancı servise dokunulmaz.
        _prosesleri_kapat()
        require_memory({"ner": 900 * 1024**2, "asr": 1200 * 1024**2, "tts": 256 * 1024**2}[kind])
        return [executable, kind, *args]
    return [python, "-m", _MODES[kind], *args]
