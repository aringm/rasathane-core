"""TR ad-soyad NER worker — AYRI PROSES (`ner` dependency-group; exe-DIŞI; ASR deseni).

torch/transformers YALNIZ bu proseste yaşar; CPU'da koşar (VRAM 0 — değişmez #2).
Model akdeniz27/bert-base-turkish-cased-ner — HF cache'ten (D:\\huggingface salt-okunur;
HF_HUB_OFFLINE=1 → indirme YOK, cache yoksa hata → engine fail-closed sayar).
Sözleşme: --in {"metinler":[...]} → --out {"kisi_var":[bool,...]}.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any

_MODEL = "akdeniz27/bert-base-turkish-cased-ner"
_PARCA_KAR = 1200  # bert 512-token limiti; karakter-parça + bindirme (ad sınırda bölünmesin)
_BINDIRME = 100


def _parcala(metin: str) -> list[str]:
    if len(metin) <= _PARCA_KAR:
        return [metin]
    parcalar = []
    i = 0
    # i + _BINDIRME < len: son parça öncekinin alt-kümesi olmasın (gereksiz inference yok;
    # bindirme zaten kapsamı garanti eder — review tur-1).
    while i + _BINDIRME < len(metin):
        parcalar.append(metin[i : i + _PARCA_KAR])
        i += _PARCA_KAR - _BINDIRME
    return parcalar


def kisi_var_listesi(metinler: list[str]) -> list[bool]:
    # ZORLA offline (setdefault DEĞİL — review tur-1): kullanıcı env'inde HF_HUB_OFFLINE=0
    # olsa bile worker huggingface.co'ya ÇIKMAZ (offline-by-design; model D: cache'te).
    os.environ["HF_HUB_OFFLINE"] = "1"
    from transformers import pipeline  # lazy: yalnız worker prosesi

    # CPU (device=-1; VRAM 0). Transformers TASK_ALIASES'de "ner" doğrudan
    # "token-classification" olur; canonical ad aynı modeli/stub sözleşmesini korur.
    model = os.environ.get("RASATHANE_NER_MODEL", "").strip() or _MODEL
    ner: Any = pipeline(
        "token-classification", model=model, aggregation_strategy="simple", device=-1
    )
    sonuc: list[bool] = []
    for metin in metinler:
        kisi = False
        for parca in _parcala(metin):
            if any(e.get("entity_group") == "PER" for e in ner(parca)):
                kisi = True
                break
        sonuc.append(kisi)
    return sonuc


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--in", dest="girdi", required=True)
    p.add_argument("--out", dest="cikti", required=True)
    a = p.parse_args()
    metinler = json.loads(Path(a.girdi).read_text(encoding="utf-8"))["metinler"]
    Path(a.cikti).write_text(
        json.dumps({"kisi_var": kisi_var_listesi(metinler)}, ensure_ascii=False),
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
