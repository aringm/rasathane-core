"""Masaüstü gözlem kökünü yeni marka adına taşır: `Rasathane  Gözlemevi` (çift boşluk).

Legacy zinciri (eskiden yeniye): `Youtube Analizleri` → `Rasathane Gözlemleri` → yeni ad.
`core.ytcore.config._default_output_base()` yeni ad yoksa legacy kökü kullanmaya devam eder;
bu betik olmadan da veri kaybolmaz. Betik yalnız tek köke sadeleştirir.

    uv run python infra/gozlem-koku-goc.py            # kuru çalışma, hiçbir şey taşınmaz
    uv run python infra/gozlem-koku-goc.py --uygula   # taşı

`YT_OUTPUT_BASE` tanımlıysa varsayılan kök devre dışıdır; betik bunu söyleyip çıkar.
Hedef zaten varsa birleştirme YAPILMAZ (sessiz üzerine yazma riski) — elle çözülmelidir.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "core"))

from ytcore.config import GOZLEM_KOKU_ADI, GOZLEM_KOKU_LEGACY_ADLARI  # noqa: E402


def _dolu_mu(p: Path) -> bool:
    return any(p.iterdir())


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--uygula", action="store_true", help="gerçekten taşı (varsayılan: kuru çalışma)"
    )
    args = ap.parse_args()

    if os.environ.get("YT_OUTPUT_BASE", "").strip():
        print("YT_OUTPUT_BASE tanımlı — çıktı kökü zaten elle yönetiliyor. Göç gereksiz.")
        return 0

    masaustu = Path.home() / "Desktop"
    hedef = masaustu / GOZLEM_KOKU_ADI
    kaynaklar = [masaustu / ad for ad in GOZLEM_KOKU_LEGACY_ADLARI if (masaustu / ad).is_dir()]

    print(f"hedef : {hedef}")
    for k in kaynaklar:
        print(f"legacy: {k}")

    if not kaynaklar:
        print("\nTaşınacak legacy klasör yok. Yapılacak bir şey yok.")
        return 0

    if hedef.exists():
        if _dolu_mu(hedef):
            print(f"\nHEDEF ZATEN DOLU: {hedef}")
            print("İki kökü birleştirmek sessizce dosya ezebilir. Elle birleştirin.")
            return 1
        print("\nHedef var ama boş; kaldırılıp legacy klasör onun yerine taşınacak.")

    if len(kaynaklar) > 1:
        print(f"\nBİRDEN ÇOK legacy kök var ({len(kaynaklar)}). Otomatik göç yapılmaz.")
        print("Hangisinin canlı veri olduğuna karar verip elle birleştirin.")
        return 1

    kaynak = kaynaklar[0]
    print(f"\nPLAN: {kaynak.name}  ->  {hedef.name}")

    if not args.uygula:
        print("\n(kuru çalışma — hiçbir şey değişmedi. Uygulamak için: --uygula)")
        return 0

    if hedef.exists():
        hedef.rmdir()  # yalnız boşsa buraya gelinir
    kaynak.rename(hedef)
    print(f"\nTaşındı: {hedef}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
