from __future__ import annotations

from pathlib import Path

from ytcore.models import IndexKaydi

IMZA = "Av. Mehmet Arın Gülüm"


def kisisel_yaz(klasor: Path, kayit: IndexKaydi, analiz: str) -> Path:
    """07_kisisel-analiz.md — avukat lens analizi + imza."""
    govde = f"# {kayit.baslik} — Kişisel Analiz (Avukat Lens)\n\n{analiz}\n\n---\n_{IMZA}_\n"
    yol = klasor / "07_kisisel-analiz.md"
    yol.write_text(govde, encoding="utf-8")
    return yol
