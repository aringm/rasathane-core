from __future__ import annotations

from pathlib import Path

from ytcore.models import DegerlemeFaktorleri, IndexKaydi

IMZA = "Av. Mehmet Arın Gülüm"

# (etiket, ağırlık, gerekçe) — şeffaflık: her faktör ne ölçüyor.
_FAKTORLER = [
    ("novelty", "Novelty", 0.35, "korpusa uzaklık (yeni içerik mi)"),
    ("rarity", "Rarity", 0.25, "anahtar kelime IDF (nadir mi)"),
    ("nis", "Niş", 0.20, "konu yoğunluğu tersi (kalabalık mı)"),
    ("recency", "Recency", 0.15, "90-gün half-life güncellik"),
    ("length", "Length", 0.05, "içerik uzunluğu (log-normalize)"),
]


def degerleme_yaz(klasor: Path, kayit: IndexKaydi, puan: float, fakt: DegerlemeFaktorleri) -> Path:
    """08_degerleme.md — BilgiDeğeri + şeffaf faktör tablosu (her faktör ham + gerekçe)."""
    d = fakt.model_dump()
    satirlar = [
        f"# {kayit.baslik} — BilgiDeğeri: {puan}/100",
        "",
        "| Faktör | Ağırlık | Skor | Gerekçe |",
        "|---|---|---|---|",
    ]
    for anahtar, etiket, agirlik, gerekce in _FAKTORLER:
        skor = d.get(anahtar)
        skor_s = f"{skor}" if skor is not None else "—"
        satirlar.append(f"| {etiket} | {agirlik} | {skor_s} | {gerekce} |")
    satirlar += ["", "---", f"_{IMZA}_", ""]
    yol = klasor / "08_degerleme.md"
    yol.write_text("\n".join(satirlar), encoding="utf-8")
    return yol
