"""Marka varlıkları sözleşmesi: tüm ikonlar tek kanonik SVG’den türer ve eski logo kalmaz.

Saf stdlib — Pillow üretim/test bağımlılığı değil (ikonlar commit'li artifact).
"""

from __future__ import annotations

import json
import re
import struct
import xml.etree.ElementTree as ET
from pathlib import Path

KOK = Path(__file__).resolve().parents[1]
IKONLAR = KOK / "gui" / "src-tauri" / "icons"

ZEMIN = "#153d34"  # Canlı web sitesindeki koyu yeşil
ISARET = "#f7f0df"  # krem küçük r

# Eski "kubbe/teleskop" logosunun imzası — hiçbir marka varlığında kalmamalı.
ESKI_LOGO_HEXLERI = ("#B9C0FA", "#A9C8F0", "#A6E6D6", "#EAF0FF", "#FFD9A8", "#F6A98A", "#FFE6C4")
ESKI_TELESKOP_PATH = "M4 17a8 8 0 0 1 16 0"

PNG_IMZASI = b"\x89PNG\r\n\x1a\n"


def _png_boyutu(yol: Path) -> tuple[int, int]:
    ham = yol.read_bytes()
    assert ham[:8] == PNG_IMZASI, f"PNG değil: {yol}"
    # IHDR her zaman ilk chunk: [8:12]=uzunluk [12:16]='IHDR' [16:24]=genişlik,yükseklik
    assert ham[12:16] == b"IHDR", f"IHDR ilk chunk değil: {yol}"
    return struct.unpack(">II", ham[16:24])


def test_kanonik_marka_rasteri_512():
    kaynak = IKONLAR / "rasathane-logo.png"
    assert kaynak.is_file(), "kanonik marka rasteri yok"
    assert _png_boyutu(kaynak) == (512, 512)


def test_ico_windows_icin_gereken_boyutlari_tasiyor():
    ham = (IKONLAR / "icon.ico").read_bytes()
    reserved, tur, adet = struct.unpack("<HHH", ham[:6])
    assert (reserved, tur) == (0, 1), "geçerli ICONDIR değil"
    assert adet >= 7, f"ICO yalnız {adet} boyut taşıyor"

    boyutlar = set()
    for i in range(adet):
        w, h, _cc, _r, _pl, bit, uzunluk, ofset = struct.unpack(
            "<BBBBHHII", ham[6 + 16 * i : 22 + 16 * i]
        )
        kenar = w or 256  # 0 = 256 konvansiyonu
        assert kenar == (h or 256), "kare olmayan ICO girdisi"
        assert bit == 32, f"{kenar}px girdi 32bpp değil"
        assert ofset + uzunluk <= len(ham), f"{kenar}px girdi dosya dışını gösteriyor"
        boyutlar.add(kenar)

    # Windows'un fiilen kullandıkları: liste/simge/görev çubuğu/jumbo.
    assert {16, 32, 48, 256} <= boyutlar, f"eksik boyut: {sorted(boyutlar)}"

    # Windows ICO, PNG veya BMP/DIB payload taşıyabilir; payload boyutu girdiye uymalı.
    for i in range(adet):
        w, *_, uzunluk, ofset = struct.unpack("<BBBBHHII", ham[6 + 16 * i : 22 + 16 * i])
        kenar = w or 256
        png_mi = ham[ofset : ofset + 8] == PNG_IMZASI
        if png_mi:
            assert ham[ofset + 12 : ofset + 16] == b"IHDR"
            assert struct.unpack(">II", ham[ofset + 16 : ofset + 24]) == (kenar, kenar)
        else:
            assert struct.unpack("<I", ham[ofset : ofset + 4])[0] in (40, 108, 124)
            # ICO DIB yüksekliği piksel ve maske yüzünden iki katıdır.
            assert struct.unpack("<ii", ham[ofset + 4 : ofset + 12]) == (kenar, kenar * 2)


def test_turetilmis_pngler_beklenen_boyutta():
    beklenen = {
        "icon.png": 512,
        "32x32.png": 32,
        "64x64.png": 64,
        "128x128.png": 128,
        "128x128@2x.png": 256,
        "StoreLogo.png": 50,
        "Square44x44Logo.png": 44,
        "Square150x150Logo.png": 150,
        "Square310x310Logo.png": 310,
    }
    for ad, kenar in beklenen.items():
        yol = IKONLAR / ad
        assert yol.is_file(), f"türetilmiş ikon yok: {ad}"
        assert _png_boyutu(yol) == (kenar, kenar), f"{ad} yanlış boyutta"


def test_marka_svgsi_aile_desenini_tasiyor_ve_eski_logo_gitti():
    svg = (IKONLAR / "rasathane-logo.svg").read_text(encoding="utf-8")
    assert ZEMIN in svg.lower() and ISARET in svg.lower(), "aile renkleri SVG'de yok"
    mark = ET.fromstring(svg)
    assert mark.attrib["viewBox"] == "0 0 64 64"
    glyph = mark.find(".//{http://www.w3.org/2000/svg}path")
    assert glyph is not None and glyph.attrib["d"].startswith("M160 0V1038H364V0Z")
    assert "#c86e42" not in svg.lower(), "turuncu logo geri gelmemeli"
    # Site, UI ve installer ayrı bir eski logo kullanmamalı.
    assert svg == (KOK / "gui/ui/brand/rasathane-mark.svg").read_text(encoding="utf-8")
    assert svg == (KOK.parent / "web/public/brand/rasathane-mark.svg").read_text(encoding="utf-8")
    for eski in ESKI_LOGO_HEXLERI:
        assert eski not in svg, f"eski kubbe logosu rengi hâlâ SVG'de: {eski}"


def test_arayuz_eski_teleskop_ikonunu_kullanmiyor():
    html = (KOK / "gui/ui/index.html").read_text(encoding="utf-8")
    assert ESKI_TELESKOP_PATH not in html, "eski teleskop çizimi hâlâ arayüzde"
    assert 'id="marka-r"' not in html, "ayrı inline marka kopyası kalmamalı"
    assert html.count('src="/brand/rasathane-mark.svg"') == 4, (
        "giriş, wordmark, onboarding ve hesap ortak SVG kullanmalı"
    )


def test_acilis_arka_plani_koyu_tema_ile_ayni():
    """Renderer yüklenene kadar boyanan renk, arayüz zeminiyle aynı olmalı (flash yok)."""
    main = (KOK / "gui/electron/main.cjs").read_text(encoding="utf-8")
    css = (KOK / "gui/ui/styles.css").read_text(encoding="utf-8")

    # CSS cascade'deki son :root tema tanımı başlangıçta etkili olandır.
    kokler = re.findall(r":root\s*\{([^}]+)\}", css)
    zemin = re.search(r"--zemin:\s*([^;]+);", kokler[-1]).group(1).strip()
    assert f'backgroundColor: "{zemin}"' in main, (
        f"BrowserWindow arka planı --zemin ({zemin}) değil"
    )


def test_tauri_bundle_ikon_listesi_diskte_var():
    conf = json.loads((KOK / "gui/src-tauri/tauri.conf.json").read_text(encoding="utf-8"))
    for goreli in conf["bundle"]["icon"]:
        assert (KOK / "gui/src-tauri" / goreli).is_file(), f"tauri bundle ikonu yok: {goreli}"
