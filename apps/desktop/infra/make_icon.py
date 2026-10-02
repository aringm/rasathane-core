"""Rasathane uygulama ikonlarını tek kanonik rasterden üretir.

Kaynak: `gui/src-tauri/icons/rasathane-logo.png` (512×512 RGBA, muhakeme aile deseni:
yuvarlatılmış kare #3A3D63 + krem #F7F0DF Cambria Bold "r").

Çalıştırma (Pillow üretim bağımlılığı DEĞİL — ikonlar commit'li artifact):

    uv run --with pillow --no-project python infra/make_icon.py

`--dogrula` ile hiçbir dosya yazılmaz; mevcut çıktılar kaynakla tutarlı mı diye bakılır
(çıkış kodu 1 = tutarsız). Küçültme premultiplied alpha (`RGBa`) üzerinden yapılır;
şeffaf köşelerde kenar halesi oluşmaz.

ICO konteyneri elle yazılır: 256 px girdi PNG-sıkıştırmalı, küçükler 32bpp BMP. NSIS ve
eski Windows shell yolları PNG-in-ICO'yu her boyutta kabul etmez; bu karma en güvenlisi.
"""

from __future__ import annotations

import argparse
import io
import struct
import sys
from pathlib import Path

from PIL import Image

KOK = Path(__file__).resolve().parent.parent
IKON_DIZINI = KOK / "gui" / "src-tauri" / "icons"
KAYNAK = IKON_DIZINI / "rasathane-logo.png"

# Marka değişmezleri — kaynak raster bunları taşımazsa üretim durur (yanlış logo koruması).
ZEMIN = (0x3A, 0x3D, 0x63)
HARF = (0xF7, 0xF0, 0xDF)

# ICO içine gömülecek boyutlar. 16/32/48/256 Windows'un fiilen kullandıkları;
# ara boyutlar yüksek-DPI görev çubuğu ve Alt+Tab için.
ICO_BOYUTLARI = (16, 20, 24, 32, 40, 48, 64, 96, 128, 256)

# Tek tek PNG çıktıları: dosya adı -> kenar uzunluğu.
PNG_CIKTILARI: dict[str, int] = {
    "icon.png": 512,
    "32x32.png": 32,
    "64x64.png": 64,
    "128x128.png": 128,
    "128x128@2x.png": 256,
    # Tauri/MSIX Windows Store karoları
    "Square30x30Logo.png": 30,
    "Square44x44Logo.png": 44,
    "Square71x71Logo.png": 71,
    "Square89x89Logo.png": 89,
    "Square107x107Logo.png": 107,
    "Square142x142Logo.png": 142,
    "Square150x150Logo.png": 150,
    "Square284x284Logo.png": 284,
    "Square310x310Logo.png": 310,
    "StoreLogo.png": 50,
}


def kaynagi_yukle() -> Image.Image:
    if not KAYNAK.is_file():
        raise SystemExit(f"Kanonik marka rasteri yok: {KAYNAK}")
    im = Image.open(KAYNAK).convert("RGBA")
    if im.size != (512, 512):
        raise SystemExit(f"Kaynak 512×512 olmalı, {im.size} bulundu: {KAYNAK}")
    renkler = {renk[:3] for _, renk in im.getcolors(maxcolors=512 * 512) or [] if renk[3] == 255}
    for beklenen, ad in ((ZEMIN, "zemin laciverti"), (HARF, "krem harf")):
        if beklenen not in renkler:
            hexed = "#{:02X}{:02X}{:02X}".format(*beklenen)
            raise SystemExit(f"Kaynak rasterde {ad} {hexed} yok — yanlış logo mu? {KAYNAK}")
    return im


def kucult(kaynak: Image.Image, kenar: int) -> Image.Image:
    """Premultiplied alpha ile yeniden örnekle (şeffaf köşede hale/koyu kenar olmaz)."""
    if kenar == kaynak.width:
        return kaynak.copy()
    return (
        kaynak.convert("RGBa")
        .resize((kenar, kenar), Image.LANCZOS, reducing_gap=3.0)
        .convert("RGBA")
    )


def png_baytlari(im: Image.Image) -> bytes:
    tampon = io.BytesIO()
    # optimize=True + sabit girdi => deterministik çıktı (yeniden üretilebilir hash).
    im.save(tampon, format="PNG", optimize=True)
    return tampon.getvalue()


def bmp_baytlari(im: Image.Image) -> bytes:
    """32bpp BMP (BITMAPINFOHEADER + BGRA XOR + 1bpp AND maskesi), satırlar alttan üste."""
    w, h = im.size
    pikseller = im.load()
    xor = bytearray()
    for y in range(h - 1, -1, -1):
        for x in range(w):
            r, g, b, a = pikseller[x, y]
            xor += bytes((b, g, r, a))
    # AND maskesi: şeffaf piksel = 1. Satır uzunluğu 4 bayta hizalı.
    satir_bayt = ((w + 31) // 32) * 4
    maske = bytearray()
    for y in range(h - 1, -1, -1):
        satir = bytearray(satir_bayt)
        for x in range(w):
            if pikseller[x, y][3] < 128:
                satir[x // 8] |= 0x80 >> (x % 8)
        maske += satir
    bih = struct.pack("<IiiHHIIiiII", 40, w, h * 2, 1, 32, 0, len(xor), 0, 0, 0, 0)
    return bytes(bih + xor + maske)


def ico_baytlari(kaynak: Image.Image) -> bytes:
    girdiler: list[tuple[int, bytes]] = []
    for kenar in ICO_BOYUTLARI:
        im = kucult(kaynak, kenar)
        girdiler.append((kenar, png_baytlari(im) if kenar >= 256 else bmp_baytlari(im)))

    baslik = struct.pack("<HHH", 0, 1, len(girdiler))  # reserved, type=1 (ikon), adet
    ofset = 6 + 16 * len(girdiler)
    dizin = bytearray()
    govde = bytearray()
    for kenar, veri in girdiler:
        # 256 px, tek baytlık alana sığmaz: 0 = "256" konvansiyonu.
        alan = 0 if kenar >= 256 else kenar
        dizin += struct.pack("<BBBBHHII", alan, alan, 0, 0, 1, 32, len(veri), ofset)
        govde += veri
        ofset += len(veri)
    return baslik + bytes(dizin) + bytes(govde)


def icns_baytlari(kaynak: Image.Image) -> bytes:
    """macOS ikonu. Windows ürünü için kullanılmıyor; eski logo kalmasın diye üretilir."""
    tampon = io.BytesIO()
    kaynak.save(tampon, format="ICNS")
    return tampon.getvalue()


def uret(kaynak: Image.Image) -> dict[Path, bytes]:
    cikti: dict[Path, bytes] = {}
    for ad, kenar in PNG_CIKTILARI.items():
        cikti[IKON_DIZINI / ad] = png_baytlari(kucult(kaynak, kenar))
    cikti[IKON_DIZINI / "icon.ico"] = ico_baytlari(kaynak)
    cikti[IKON_DIZINI / "icon.icns"] = icns_baytlari(kaynak)
    return cikti


def main() -> int:
    ayristirici = argparse.ArgumentParser(description=__doc__)
    ayristirici.add_argument(
        "--dogrula",
        action="store_true",
        help="yazma; mevcut ikonlar kaynakla tutarlı mı diye bak (tutarsızsa çıkış 1)",
    )
    argumanlar = ayristirici.parse_args()

    kaynak = kaynagi_yukle()
    beklenen = uret(kaynak)

    if argumanlar.dogrula:
        sapan = [
            yol for yol, veri in beklenen.items() if not yol.is_file() or yol.read_bytes() != veri
        ]
        for yol in sapan:
            print(f"SAPMA: {yol.relative_to(KOK)}")
        if sapan:
            print(
                f"\n{len(sapan)} dosya kaynakla tutarsız. `python infra/make_icon.py` çalıştırın."
            )
            return 1
        print(f"{len(beklenen)} ikon çıktısı kaynak rasterle tutarlı.")
        return 0

    for yol, veri in beklenen.items():
        yol.write_bytes(veri)
        print(f"yazıldı: {yol.relative_to(KOK)} ({len(veri):,} bayt)")
    print(f"\n{len(beklenen)} dosya üretildi. Kaynak: {KAYNAK.relative_to(KOK)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
