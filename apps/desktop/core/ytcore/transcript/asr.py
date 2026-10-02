from __future__ import annotations

import json
import os
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

# Bu dosya: core/ytcore/transcript/asr.py → parents[2] = core/ (ytcore'un kökü).
# Worker AYRI PROSES olduğundan pytest/engine pythonpath'ini miras almaz; core'u
# açıkça PYTHONPATH'e veririz. (Frozen exe — Faz 5 — worker'ın kendi env'iyle çözer.)
_CORE_ROOT = Path(__file__).resolve().parents[2]


@dataclass
class ASRSonuc:
    metin: str
    segment_sayisi: int
    dil: str | None
    tier: str  # "whisperx" | "faster-whisper"


class ASRWorker(Protocol):
    def calistir(self, ses: Path, dil: str, diarize: bool) -> ASRSonuc: ...


class SubprocessASR:
    """ASR'ı AYRI PROSESTE çalıştırır (≤16GB hot-swap: torch ana engine'e girmez).

    Engine tarafı — yalnız subprocess'i sürer ve JSON parse eder; torch/whisperx
    IMPORT ETMEZ. Worker (asr_worker) ayrı `asr` dependency-group'unda çalışır.
    """

    def __init__(
        self,
        python: str,
        worker_modul: str = "ytcore.transcript.asr_worker",
        modul_mu: bool = True,
    ) -> None:
        self.python = python
        self.worker_modul = worker_modul
        self.modul_mu = modul_mu

    def calistir(self, ses: Path, dil: str, diarize: bool) -> ASRSonuc:
        with tempfile.TemporaryDirectory() as d:
            out = Path(d) / "asr.json"
            args = ["--audio", str(ses), "--dil", dil, "--out", str(out)]
            if diarize:
                args.append("--diarize")
            from ytcore.local.worker import worker_command

            cmd = (
                worker_command("asr", self.python, args)
                if self.modul_mu
                else [self.python, self.worker_modul, *args]
            )
            env = dict(os.environ)
            # Worker sandbox (ner.py deseni): PYTHONPATH'e YALNIZ core ver — parent'ın
            # PYTHONPATH'ini MİRAS VERME (kirli parent PYTHONPATH kötücül modülü worker'a
            # shadow-import edebilirdi; savunma derinliği). ASR egress-gate DEĞİL, ama seam
            # NER worker'la aynı — tutarlı tut.
            env["PYTHONPATH"] = str(_CORE_ROOT)
            proc = subprocess.run(
                cmd, capture_output=True, text=True, env=env, timeout=1800, stdin=subprocess.DEVNULL
            )
            if proc.returncode != 0 or not out.exists():
                # stderr KUYRUĞU da göster: iki-katmanlı çökmede (whisperx fail →
                # faster-whisper degrade fail) asıl kök sebep SONDA olur (M3).
                err = proc.stderr or ""
                kuyruk = err[-1500:] if len(err) > 1500 else err
                raise RuntimeError(f"ASR worker başarısız (rc={proc.returncode}): {kuyruk}")
            data = json.loads(out.read_text(encoding="utf-8"))
        return ASRSonuc(
            metin=data["metin"],
            segment_sayisi=len(data.get("segmentler", [])),
            dil=data.get("dil"),
            tier=data.get("tier", "faster-whisper"),
        )
