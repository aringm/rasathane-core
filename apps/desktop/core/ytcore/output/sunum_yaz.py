"""Faz 6 (#3+#5): profesyonel Typst SUNUM PDF'i — özet + kişisel analiz + değerleme tek dosyada.

Kapak → TL;DR → Özet → Detaylı Özet → Kişisel Analiz → Değerleme (faktör tablosu) → imza.
Dinamik LLM metni Typst STRING'i olarak gömülür (literal — `*`/`_`/`#` markup'ı yorumlanmaz,
güvenli). Typst yoksa graceful None (md/diğer dosyalar birincil — Faz 1 'md kaybetme' dersi).
"""

from __future__ import annotations

import sys
from pathlib import Path

from ytcore.models import DegerlemeFaktorleri, IndexKaydi
from ytcore.output.klasor import IMZA
from ytcore.output.typst_runtime import compile_pdf


def _ts(s: str) -> str:
    """Python str → Typst string-literal gövdesi (kaçışlı): \\ " ve newline güvenli."""
    return (
        (s or "").replace("\\", "\\\\").replace('"', '\\"').replace("\r", "").replace("\n", "\\n")
    )


def _fakt_satir(ad: str, agirlik: float, skor: float | None) -> str:
    s = "—" if skor is None else f"{skor:.0f}"
    return f"  [{ad}], [{agirlik:.0%}], [{s}],\n"


def _typ_kaynak(
    kayit: IndexKaydi,
    ozet: dict[str, str],
    faithfulness_skor: float | None,
    kisisel_metni: str,
    degerleme_puani: float | None,
    fakt: DegerlemeFaktorleri,
) -> str:
    sure = f"{kayit.sure_sn // 60} dk {kayit.sure_sn % 60} sn" if kayit.sure_sn else "?"
    puan_txt = f"{degerleme_puani:.1f} / 100" if degerleme_puani is not None else "—"
    fth = "—" if faithfulness_skor is None else f"{faithfulness_skor:.2f}"
    kisisel = kisisel_metni.strip() or "(kişisel analiz üretilmedi)"
    if kayit.kaynak_ozel.get("analysis_mode") == "source_extracts":
        destek_notu = "Doğrudan kaynak alıntıları; model destek puanı hesaplanmadı."
        kapsam_notu = (
            "Edinilen resmî ana metin korunur; bağımsız doğrulama veya konsolide "
            "mevzuat üretimi yapılmadı."
        )
    else:
        destek_notu = f"Model destek tahmini (faithfulness): {fth}"
        kapsam_notu = (
            "Yalnız detaylı özet ile analiz metni karşılaştırılır. "
            "Skor, resmî kaynak doğruluğu veya hukuki doğruluk onayı değildir. "
            "Çeviri varsa karşılaştırma çeviri metniyle yapılır."
        )
    tablo = (
        _fakt_satir("Novelty (yenilik)", 0.35, fakt.novelty)
        + _fakt_satir("Rarity (nadirlik)", 0.25, fakt.rarity)
        + _fakt_satir("Niş", 0.20, fakt.nis)
        + _fakt_satir("Recency (güncellik)", 0.15, fakt.recency)
        + _fakt_satir("Length (doluluk)", 0.05, fakt.length)
    )
    return f"""#set text(font: ("Segoe UI", "Arial", "DejaVu Sans"), size: 11pt, lang: "tr")
#set page(margin: (x: 2.2cm, y: 2.2cm), numbering: "1 / 1", footer-descent: 0.8cm)
#let ink = rgb("#1d2733")
#let altin = rgb("#a4803a")
#let bordo = rgb("#8c2f39")
#let mut = rgb("#5a6675")
#set par(justify: true, leading: 0.72em)
#show heading.where(level: 1): it => block(above: 1.3em, below: 0.7em)[
  #text(15pt, weight: "bold", fill: bordo)[#it.body]
  #v(-0.4em) #line(length: 100%, stroke: 0.6pt + altin.lighten(40%))
]
// Dinamik metin KOD-MODU string'i ($ # * _ literal — içerik-modu markup tuzağı yok).
#let v_baslik = "{_ts(kayit.baslik)}"
#let v_kanal = "{_ts(kayit.kaynak_sahibi or kayit.kanal or "?")}"
#let v_dil = "{_ts(kayit.anadil or "?")}"
#let v_tarih = "{_ts(kayit.analiz_tarihi)}"
#let v_url = "{_ts(kayit.kaynak_url or kayit.video_url)}"
#let v_imza = "{_ts(IMZA)}"
#let v_tldr = "{_ts(ozet.get("kisa", ""))}"
#let v_ozet = "{_ts(ozet.get("orta") or ozet.get("kisa", ""))}"
#let v_detay = "{_ts(ozet.get("detay", ""))}"
#let v_kisisel = "{_ts(kisisel)}"
#let para(s) = {{
  for p in s.split("\\n\\n") {{ if p.trim() != "" [ #p.trim() #parbreak() ] }}
}}

// ───────── Kapak ─────────
#align(center)[
  #v(3.2cm)
  #text(12pt, fill: altin, tracking: 4pt)[RASATHANE · KAYNAK ANALİZİ]
  #v(0.7cm)
  #text(23pt, weight: "bold", fill: ink)[#v_baslik]
  #v(0.35cm)
  #line(length: 32%, stroke: 2pt + altin)
  #v(0.5cm)
  #text(12.5pt, fill: mut)[#v_kanal · #v_dil · {sure}]
  #v(0.2cm)
  #text(10.5pt, fill: mut)[Analiz: #v_tarih]
  #v(1.1cm)
  #box(fill: bordo, inset: (x: 18pt, y: 13pt), radius: 10pt)[
    #text(white, weight: "bold", size: 17pt)[BilgiDeğeri  {puan_txt}]
  ]
  #v(0.5cm)
  #text(9.5pt, fill: mut)[Kaynak: #v_url]
]
#pagebreak()

= TL;DR
#para(v_tldr)

= Özet
#para(v_ozet)

= Detaylı Özet
#para(v_detay)
#v(0.3em) #text(9.5pt, fill: mut)[{destek_notu}]
#text(9pt, fill: mut)[{kapsam_notu}]

= Kişisel Analiz
#para(v_kisisel)

= Değerleme — BilgiDeğeri {puan_txt}
#v(0.3em)
#table(
  columns: (2fr, 1fr, 1fr),
  inset: 8pt,
  align: (left, center, center),
  stroke: 0.5pt + rgb("#d9d2c3"),
  table.header(
    [*Faktör*], [*Ağırlık*], [*Skor (0-100)*],
  ),
{tablo})

#v(1.5cm)
#align(right)[#text(11pt, style: "italic", fill: ink)[#v_imza]]
"""


def sunum_yaz(
    klasor: Path,
    kayit: IndexKaydi,
    ozet: dict[str, str],
    faithfulness_skor: float | None,
    kisisel_metni: str,
    degerleme_puani: float | None,
    degerleme_fakt: DegerlemeFaktorleri,
) -> Path | None:
    """04_ozet-sunum.pdf (Typst). Typst yoksa/derleme patlarsa None (best-effort; diğer
    çıktılar birincil). Geçici .typ teslim klasöründe bırakılmaz (review #14 dersi)."""
    typ = klasor / "_sunum.typ"
    typ.write_text(
        _typ_kaynak(kayit, ozet, faithfulness_skor, kisisel_metni, degerleme_puani, degerleme_fakt),
        encoding="utf-8",
    )
    pdf_p = klasor / "04_ozet-sunum.pdf"
    try:
        compile_pdf(typ, pdf_p)
    except Exception as e:  # noqa: BLE001 — typst yok/derleme hatası → best-effort None
        print(f"[uyari] Sunum PDF uretilemedi (best-effort): {e}", file=sys.stderr)
        return None
    finally:
        typ.unlink(missing_ok=True)
    return pdf_p
