from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any


def _cihaz() -> str:
    try:
        import torch

        return "cuda" if torch.cuda.is_available() else "cpu"
    except Exception:  # noqa: BLE001 — torch yoksa cpu
        return "cpu"


# int8: ~1.5GB VRAM (Issue #1030); CPU'da da geçerli. Global compute_type.
_COMPUTE = "int8"


def _whisperx_calistir(audio: str, dil: str, diarize: bool) -> dict[str, Any]:
    # NOT: `diarize` parametresi plumb edilmiş ama HENÜZ no-op. Diarizasyon (pyannote +
    # assign_word_speakers, HF token) opsiyonel ve Faz 2/4 kapsamında; node hep False geçer.
    import whisperx

    device = _cihaz()
    model = whisperx.load_model("large-v3-turbo", device, compute_type=_COMPUTE, language=dil)
    ses = whisperx.load_audio(audio)
    sonuc = model.transcribe(ses, language=dil, batch_size=16)
    model_a, meta = whisperx.load_align_model(language_code=dil, device=device)
    hizali = whisperx.align(
        sonuc["segments"], model_a, meta, ses, device, return_char_alignments=False
    )
    segmentler = hizali.get("segments", sonuc["segments"])
    metin = " ".join(s.get("text", "").strip() for s in segmentler).strip()
    return {"metin": metin, "segmentler": segmentler, "dil": dil, "tier": "whisperx"}


def _faster_whisper_degrade(audio: str, dil: str) -> dict[str, Any]:
    from faster_whisper import WhisperModel

    device = "cpu" if os.environ.get("RASATHANE_WORKER_EXE") else _cihaz()
    model_path = os.environ.get("RASATHANE_ASR_MODEL", "").strip() or "large-v3-turbo"
    model = WhisperModel(
        model_path, device=device, compute_type=_COMPUTE, cpu_threads=4, num_workers=1
    )
    segs, info = model.transcribe(audio, language=dil, beam_size=5)
    seg_list = [{"start": s.start, "end": s.end, "text": s.text} for s in segs]
    metin = " ".join(s["text"].strip() for s in seg_list).strip()
    return {
        "metin": metin,
        "segmentler": seg_list,
        "dil": info.language,
        "tier": "faster-whisper",
    }


def main(argv: list[str] | None = None) -> int:
    """Ayrı-proses ASR entry: whisperx (TR align) → JSON; whisperx patlarsa faster-whisper.

    ≤16GB hot-swap: torch/whisperx YALNIZ bu proseste yüklenir; ana engine hafif kalır.
    """
    ap = argparse.ArgumentParser()
    ap.add_argument("--audio", required=True)
    ap.add_argument("--dil", default="tr")
    ap.add_argument("--out", required=True)
    ap.add_argument("--diarize", action="store_true")
    a = ap.parse_args(argv)
    try:
        if os.environ.get("RASATHANE_WORKER_EXE"):
            data = _faster_whisper_degrade(a.audio, a.dil)
        else:
            data = _whisperx_calistir(a.audio, a.dil, a.diarize)
    except Exception as e:  # noqa: BLE001 — whisperx başarısız → degrade tier
        print(f"[asr] whisperx basarisiz, faster-whisper degrade: {e}", file=sys.stderr)
        data = _faster_whisper_degrade(a.audio, a.dil)
    Path(a.out).write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
