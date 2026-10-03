from __future__ import annotations

import html
import json
from functools import lru_cache
from pathlib import Path

_ASSETS = Path(__file__).parent / "assets"

# Faz 6 (#2): özel KOYU + özgün tasarım. Derin alt-ağaçlar açık (initialExpandLevel -1),
# bold açık-renk etiketler, derinliğe göre vivid dal paleti, başlık/imza overlay. OFFLINE
# (d3 + markmap-view inline; harici CDN yok). Built-in zoom/collapse/ara markmap-view'dan.
_SABLON = """<!DOCTYPE html>
<html lang="tr"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{baslik} — Zihin Haritası</title>
<style>
  :root{{ --bg:#0d1117; --bg2:#161d2b; --ink:#ece6d6; --altin:#e0a93b; --mut:#7d8aa0; }}
  *{{box-sizing:border-box}}
  html,body{{margin:0;height:100%;overflow:hidden;
    font-family:"Segoe UI",Candara,system-ui,sans-serif;background:var(--bg)}}
  /* atmosfer: radyal ışıma + ince nokta dokusu (saf CSS, offline) */
  body::before{{content:"";position:fixed;inset:0;z-index:0;pointer-events:none;
    background:
      radial-gradient(1200px 700px at 18% 12%, rgba(224,169,59,.10), transparent 60%),
      radial-gradient(1000px 800px at 85% 88%, rgba(138,160,255,.10), transparent 60%),
      linear-gradient(160deg, var(--bg), var(--bg2));}}
  body::after{{content:"";position:fixed;inset:0;z-index:0;pointer-events:none;opacity:.5;
    background-image:radial-gradient(rgba(255,255,255,.05) 1px, transparent 0);
    background-size:24px 24px;}}
  #mindmap{{position:relative;z-index:1;width:100vw;height:100vh}}
  /* başlık overlay (haritayı engellemez) */
  .ust{{position:fixed;top:22px;left:28px;z-index:2;pointer-events:none;max-width:60vw}}
  .ust .etiket{{font:600 11px/1 "Cascadia Mono",Consolas,monospace;letter-spacing:.28em;
    text-transform:uppercase;color:var(--altin);opacity:.85}}
  .ust h1{{margin:.35rem 0 0;font:700 22px/1.25 "Constantia","Palatino Linotype",Georgia,serif;
    color:var(--ink);text-shadow:0 2px 12px rgba(0,0,0,.5)}}
  .ust .cizgi{{width:64px;height:3px;margin-top:10px;border-radius:2px;
    background:linear-gradient(90deg,var(--altin),transparent)}}
  .alt{{position:fixed;bottom:16px;right:22px;z-index:2;pointer-events:none;
    font:italic 12px/1 "Constantia",Georgia,serif;color:var(--mut)}}
  /* markmap düğüm/etiket stilleri: BOLD açık metin (dal renkleri yapı çizgilerinde) */
  .markmap-foreign{{color:var(--ink);font-weight:700;font-size:15px;
    text-shadow:0 1px 6px rgba(0,0,0,.55)}}
  .markmap-foreign a{{color:#9fd6ff;font-weight:600;text-decoration:none}}
  .markmap-foreign a:hover{{text-decoration:underline}}
  .markmap-link{{stroke-width:2.2px;stroke-opacity:.9}}
  .markmap-node>circle{{stroke-width:2.4px}}
</style></head>
<body>
<div class="ust">
  <div class="etiket">Zihin Haritası</div>
  <h1>{baslik}</h1>
  <div class="cizgi"></div>
</div>
<svg id="mindmap"></svg>
<div class="alt">Av. Mehmet Arın Gülüm</div>
<script>{d3}</script>
<script>{view}</script>
<script>
  const veri = {veri};
  const {{ Markmap, deriveOptions }} = window.markmap;
  // deriveOptions: JSON stili seçenekleri (color ARRAY → scaleOrdinal fonksiyonu) markmap'in
  // beklediği biçime çevirir. create()'e ham array verince color(node) patlar (0 düğüm) —
  // canlı kanıtla doğrulandı; deriveOptions ŞART.
  const opts = deriveOptions({{
    initialExpandLevel: -1,
    colorFreezeLevel: 2,
    color: ["#e0a93b","#e0617a","#36c2ad","#8aa0ff","#e8923c","#6fd08c","#d77ad0"],
    maxWidth: 340, spacingVertical: 16, spacingHorizontal: 110, paddingX: 18, duration: 380
  }});
  Markmap.create("#mindmap", opts, veri);
</script>
</body></html>
"""


@lru_cache(maxsize=2)
def _asset(ad: str) -> str:
    yol = _ASSETS / ad
    icerik = yol.read_text(encoding="utf-8")
    if len(icerik) < 1000:  # boş/hata-sayfası indi → görünür çök (sessiz bozuk HTML değil)
        raise RuntimeError(f"markmap asset bozuk/eksik: {ad} ({len(icerik)} bayt)")
    return icerik


def markmap_html(veri: dict[str, object], *, baslik: str) -> str:
    """markmap veri-ağacından standalone OFFLINE interaktif HTML (d3 + markmap-view inline).

    Harici CDN/script-src YOK → çevrimdışı açılır. Faz 6: koyu özgün tema, derin açılım,
    bold etiketler. veri.content zaten HTML-escape'li (harita.agac_to_markmap); baslik DIŞ
    dünya verisi (YouTube başlığı) → burada HTML-escape edilir (overlay + <title> enjeksiyonu)."""
    guvenli_baslik = html.escape(baslik)
    return _SABLON.format(
        baslik=guvenli_baslik,
        d3=_asset("d3.min.js"),
        view=_asset("markmap-view.js"),
        veri=json.dumps(veri, ensure_ascii=False),
    )
