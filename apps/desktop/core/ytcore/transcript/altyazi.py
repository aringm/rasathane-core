from __future__ import annotations

from collections.abc import Iterable

_ONCELIK = ("tr", "tr-orig", "en")


def altyazi_sec(diller: Iterable[str]) -> str | None:
    """Mevcut altyazı dillerinden öncelik sırasına göre seç: tr > tr-orig > en.

    A01 #9371: manuel altyazı otomatiğe tercih edilir (bu seçim çağıran katmanda);
    burada yalnız DİL önceliği uygulanır. Hiçbiri yoksa None (→ ASR kararı).
    """
    mevcut = set(diller)
    for dil in _ONCELIK:
        if dil in mevcut:
            return dil
    return None
