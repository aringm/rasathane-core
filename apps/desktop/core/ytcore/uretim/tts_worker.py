"""Piper TTS sentez worker'ı — AYRI PROSES (`uretim` dependency-group; exe-DIŞI; ASR/NER deseni).

piper/onnxruntime YALNIZ bu proseste yaşar (frozen exe bunları --exclude-module ile dışlar;
<200MB sınırı — değişmez #2). Engine (SubprocessPiperTTS) bu worker'ı sürer; sentez mantığı
in-process `PiperTTS`'ten yeniden kullanılır (tek doğruluk kaynağı). KVKK: yalnız YEREL sentez
(ağ yok, egress yok) — PII gate egress kararını ZATEN engine tarafında (seslendirme_node) verdi.

Sözleşme: --in {"metin":..., "voice_dir":...} → --out WAV + --meta {"durum":...}.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--in", dest="girdi", required=True)
    p.add_argument("--out", dest="cikti", required=True)  # WAV hedefi
    p.add_argument("--meta", dest="meta", required=True)  # {"durum":...} sonucu
    a = p.parse_args()

    # Worker DAİMA meta yazar (boş≠başarı: engine durumu net okusun; beklenmeyen hatada bile
    # 'hata' döner, sessiz kayıp yok). PiperTTS sentez mantığını yeniden kullanır (DRY).
    durum = "hata"
    try:
        veri = json.loads(Path(a.girdi).read_text(encoding="utf-8"))
        from ytcore.uretim.tts import PiperTTS

        sonuc = PiperTTS(voice_dir=Path(veri["voice_dir"])).seslendir(
            veri.get("metin", ""), Path(a.cikti)
        )
        durum = sonuc.durum
    except Exception:  # noqa: BLE001 — worker sınırı: her hata 'hata' meta'sına indirgenir
        durum = "hata"
    Path(a.meta).write_text(json.dumps({"durum": durum}, ensure_ascii=False), encoding="utf-8")


if __name__ == "__main__":
    main()
