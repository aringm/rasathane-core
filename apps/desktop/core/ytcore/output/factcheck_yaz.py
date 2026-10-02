from __future__ import annotations

from pathlib import Path
from typing import Any

from ytcore.models import IndexKaydi

IMZA = "Av. Mehmet Arın Gülüm"


def factcheck_yaz(
    klasor: Path,
    kayit: IndexKaydi,
    iddialar: list[dict[str, Any]],
    durum: str,
    *,
    reason: str = "",
) -> Path:
    """06_fact-check.md — iddia-bazlı doğrulama tablosu + web-durumu notu + imza."""
    web = {
        "web_yok": "devre-dışı (anahtar yok)",
        "web_hata": "yapılamadı (servis hatası — geçici)",  # anahtar-yok'tan AYRI (review HIGH)
        "atlandi_resmi_kaynak": "atlandı (resmî normatif kaynak)",
    }.get(durum, "aktif")
    satirlar = [f"# {kayit.baslik} — Fact-check", f"> Web doğrulama: {web}", ""]
    if durum == "atlandi_resmi_kaynak":
        satirlar += [reason, "", f"Resmî kaynak: {kayit.kaynak_url or kayit.video_url}", ""]
    for i, it in enumerate(iddialar, 1):
        kaynaklar = ", ".join(it.get("kaynaklar") or []) or "(web doğrulaması yapılamadı)"
        guven = float(it.get("guven", 0.0))
        satirlar += [
            f"## İddia {i}: {it['iddia']}",
            f"- **Karar:** {it['karar']} · **Güven:** {guven:.2f}",
            f"- **Gerekçe:** {it.get('gerekce', '')}",
            f"- **Kaynaklar:** {kaynaklar}",
            "",
        ]
    satirlar += ["---", f"_{IMZA}_", ""]
    yol = klasor / "06_fact-check.md"
    yol.write_text("\n".join(satirlar), encoding="utf-8")
    return yol
