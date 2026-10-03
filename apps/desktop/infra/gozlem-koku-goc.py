"""Legacy masaüstü çıktı klasörünü Documents/Rasathane konumuna taşır.

Kaynak kodu Desktop/Rasathane klasörüne dokunulmaz. Varsayılan kuru çalışmadır.
Tek legacy kaynak, boş/eksik hedef ve symlink/junction olmayan kökler gerekir.
Klasörler birleştirilmez, dosya üzerine yazılmaz. Taşınan kaynak dizinin adı
makbuzda gösterilir; aynı güvenli koşullarda ters rename ile geri alınabilir.

    uv run python infra/gozlem-koku-goc.py
    uv run python infra/gozlem-koku-goc.py --uygula

YT_OUTPUT_BASE açık seçimse otomatik göç yapılmaz. Electron'un özel çıktı ayarı
bu helper'ın kapsamına girmez; paket güncellemesinde ayrıca doğrulanır.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "core"))

from ytcore.config import GOZLEM_KOKU_ADI, GOZLEM_KOKU_LEGACY_ADLARI  # noqa: E402


def _guvenli_kok(path: Path, home: Path) -> None:
    if path.is_symlink() or path.is_junction():
        raise ValueError("Symlink veya junction kökü taşınamaz.")
    if not path.resolve().is_relative_to(home.resolve()):
        raise ValueError("Göç yolu kullanıcı klasörü sınırının dışında.")
    if (path / ".git").exists():
        raise ValueError("Kaynak repo çıktı klasörü olarak taşınamaz.")
    if path.exists() and not path.is_dir():
        raise ValueError("Göç yolu bir dizin olmalı.")


def migration_plan(home: Path) -> tuple[Path | None, Path]:
    target = home / "Documents" / GOZLEM_KOKU_ADI
    _guvenli_kok(target, home)
    sources = [
        home / "Desktop" / name
        for name in GOZLEM_KOKU_LEGACY_ADLARI
        if (home / "Desktop" / name).exists()
    ]
    for source in sources:
        _guvenli_kok(source, home)
    if not sources:
        return None, target
    if len(sources) != 1:
        raise ValueError("Birden çok legacy kök var; otomatik birleştirme yapılmaz.")
    if target.exists() and any(target.iterdir()):
        raise ValueError("Hedef klasör dolu; birleştirme veya üzerine yazma yapılmaz.")
    return sources[0], target


def migrate(home: Path, *, apply: bool = False) -> tuple[Path | None, Path]:
    source, target = migration_plan(home)
    if not apply or source is None:
        return source, target
    # Mutation öncesi planı tekrar doğrula; kaynak repo ile isim benzerliği
    # bu whitelist sınırlarını genişletmez.
    current_source, current_target = migration_plan(home)
    if current_source != source or current_target != target:
        raise ValueError("Göç planı değişti.")
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        target.rmdir()  # Yalnız doğrulanan boş hedef; recursive silme yok.
    source.rename(target)
    return source, target


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--uygula", action="store_true", help="varsayılan kuru planı uygula")
    args = parser.parse_args()
    if os.environ.get("YT_OUTPUT_BASE", "").strip():
        print("YT_OUTPUT_BASE tanımlı; açık çıktı seçimi korunur. Göç yapılmadı.")
        return 0
    try:
        source, target = migrate(Path.home(), apply=args.uygula)
    except (OSError, ValueError) as exc:
        print(f"Göç uygulanmadı: {exc}")
        return 1
    print(f"Hedef: {target}")
    if source is None:
        print("Legacy çıktı klasörü bulunamadı.")
    else:
        print(f"Kaynak: {source}")
        print("Taşındı." if args.uygula else "Kuru çalışma; hiçbir dosya değişmedi.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
