from __future__ import annotations

import json
import os
import subprocess
import tempfile
from pathlib import Path
from typing import Protocol

# ASR deseni (asr.py): worker AYRI PROSES — core'u açıkça PYTHONPATH'e ver.
_CORE_ROOT = Path(__file__).resolve().parents[2]


def _is_file_guvenli(p: Path) -> bool:
    """is_file() POSIX'te EACCES/ELOOP'ta OSError ATABİLİR (review MED) → fail-closed sözleşmesi
    (asla yükselme) için yut."""
    try:
        return p.is_file()
    except OSError:
        return False


def _ayni_yol(a: str, b: str) -> bool:
    """İki yol AYNI dosyayı mı gösteriyor (NORMALİZE — Windows case-insensitive + ../ varyantı)?
    String eşitlik frozen-self guard'ı atlatabilirdi (review)."""
    try:
        return Path(a).resolve() == Path(b).resolve()
    except OSError:
        return a == b


def _gercek_core_root() -> Path:
    """ner_worker.py'yi içeren GERÇEK repo `core/` dizinini bul (harici NER python'a PYTHONPATH).

    Dev'de (frozen DEĞİL) _CORE_ROOT modül-göreli `core/` (doğru). Frozen exe'de _CORE_ROOT =
    _MEIPASS olur ama ner_worker.py PYZ'de/`--exclude-module` (harici python ORADAN import EDEMEZ)
    → sys.executable'dan YUKARI yürüyüp gerçek repo core'unu bul. Bulamazsa _CORE_ROOT (harici
    spawn fail-closed döner — sessiz fail-open YOK).
    """
    import sys

    # Kurulu app: motor kökü (config; YT_MOTOR_KOK/_ayarlar.json/standart konum) — AppData'dan
    # bulunamayan gerçek repo core'unu açık konumdan çöz (tam özellik; tts.py ile aynı desen).
    from ytcore.config import motor_core_root

    mk = motor_core_root()
    if mk and _is_file_guvenli(mk / "ytcore" / "router" / "ner_worker.py"):
        return mk
    # Frozen'da ASLA kısa-devre (review HIGH): _MEIPASS'a worker extract edilse bile walk-up'a
    # zorla (yanlış-pozitif _MEIPASS dönüşü engellenir). Dev'de modül-göreli core doğru.
    if not getattr(sys, "frozen", False) and _is_file_guvenli(
        _CORE_ROOT / "ytcore" / "router" / "ner_worker.py"
    ):
        return _CORE_ROOT
    # GÜVENLİK (review HIGH): YALNIZ sys.executable yukarı-yürümesi. cwd KÖK DEĞİL — güvenilmez
    # cwd'ye konmuş sahte core/ner_worker.py keyfi worker spawn'ı (KVKK fail-OPEN) açardı.
    try:
        kok = Path(sys.executable).resolve().parent
    except OSError:
        return _CORE_ROOT
    isaret = Path("core") / "ytcore" / "router" / "ner_worker.py"
    for ata in (kok, *kok.parents):
        if _is_file_guvenli(ata / isaret):
            return (ata / "core").resolve()
    return _CORE_ROOT


class NERTespit(Protocol):
    def kisi_var_mi(self, metinler: list[str]) -> list[bool]: ...


class FakeNER:
    """Hermetik NER (torch'suz/modelsiz/proses-süz). Bilinen test adlarını literal yakalar."""

    def __init__(self, adlar: tuple[str, ...] = ("Ahmet Yılmaz", "Mehmet Demir")) -> None:
        self._adlar = adlar

    def kisi_var_mi(self, metinler: list[str]) -> list[bool]:
        return [any(a in m for a in self._adlar) for m in metinler]


class SubprocessNER:
    """TR ad-soyad NER'i AYRI PROSESTE koşar (ASR deseni: torch ana engine'e/exe'ye GİRMEZ).

    KVKK FAIL-CLOSED (değişmez #1): worker hata/timeout/bozuk-çıktı → TÜM metinler için
    'kişi VAR' döner (deny-by-default; egress engellenir, yerel yol sürer). Proses-içi memo:
    aynı analizde aynı metin için subprocess tekrar SPAWN edilmez.
    """

    def __init__(self, python: str | None = None, timeout_sn: float = 180.0) -> None:
        if python is None:
            from ytcore.config import get_config

            python = get_config().ner_python
        self.python = python
        self.timeout_sn = timeout_sn
        self._memo: dict[str, bool] = {}

    def kisi_var_mi(self, metinler: list[str]) -> list[bool]:
        eksikler = [m for m in dict.fromkeys(metinler) if m not in self._memo]
        if eksikler:
            for m, v in zip(eksikler, self._calistir(eksikler), strict=True):
                self._memo[m] = v
        return [self._memo[m] for m in metinler]

    def _parse(self, ham: str, beklenen: int) -> list[bool]:
        """Worker çıktısını doğrula; her bozulmada fail-closed (hepsi 'kişi VAR').

        Tip de doğrulanır (review tur-1): doğru uzunlukta null/0 listesi fail-OPEN olmasın.
        """
        try:
            data = json.loads(ham)
            ham_liste = data["kisi_var"]
        except (json.JSONDecodeError, KeyError, TypeError):
            return [True] * beklenen
        if not isinstance(ham_liste, list) or len(ham_liste) != beklenen:
            return [True] * beklenen
        if not all(isinstance(x, bool) for x in ham_liste):
            return [True] * beklenen
        return list(ham_liste)

    def _calistir(self, metinler: list[str]) -> list[bool]:
        import sys

        # Frozen exe guard (review tur-1 HIGH): sys.executable = exe'nin KENDİSİ olur;
        # self-spawn child stdio MCP moduna düşer (180s blok + stdin çalma). YT_NER_PYTHON
        # ile AYRI python env verilmedikçe spawn ETMEDEN fail-closed dön (frozen'da gerçek
        # NER desteklenmez — worker PYZ arşivinde, harici python'dan import edilemez).
        if (
            getattr(sys, "frozen", False)
            and _ayni_yol(self.python, sys.executable)
            and not os.environ.get("RASATHANE_WORKER_EXE")
        ):
            return [True] * len(metinler)
        try:
            # try TÜM gövdeyi sarar (review tur-1 MED): tempdir/write/read OSError'u da
            # fail-closed — son node'da (seslendirme) analiz çökmesin.
            with tempfile.TemporaryDirectory() as d:
                girdi = Path(d) / "in.json"
                cikti = Path(d) / "out.json"
                girdi.write_text(
                    json.dumps({"metinler": metinler}, ensure_ascii=False), encoding="utf-8"
                )
                from ytcore.local.worker import worker_command

                cmd = worker_command(
                    "ner",
                    self.python,
                    [
                        "--in",
                        str(girdi),
                        "--out",
                        str(cikti),
                    ],
                )
                env = dict(os.environ)
                # Worker sandbox (review): PYTHONPATH'e YALNIZ core_root ver — parent'ın
                # PYTHONPATH'ini MİRAS VERME (kirli parent PYTHONPATH kötücül modülü worker'a
                # shadow-import edebilirdi). Frozen exe'de _CORE_ROOT=_MEIPASS → gerçek repo core.
                env["PYTHONPATH"] = str(_gercek_core_root())
                # stdin=DEVNULL: child parent'ın stdin'ini (stdio MCP pipe'ı) miras almasın.
                proc = subprocess.run(
                    cmd,
                    capture_output=True,
                    text=True,
                    env=env,
                    timeout=self.timeout_sn,
                    stdin=subprocess.DEVNULL,
                )
                if proc.returncode != 0 or not cikti.exists():
                    return [True] * len(metinler)  # fail-closed
                return self._parse(cikti.read_text(encoding="utf-8"), beklenen=len(metinler))
        except (subprocess.TimeoutExpired, OSError, ValueError):
            return [True] * len(metinler)  # fail-closed (KVKK deny-by-default)


def ner_al() -> NERTespit:
    """YT_NER_FIXTURE set ise FakeNER (hermetik test/exe selftest), değilse SubprocessNER."""
    if os.environ.get("YT_NER_FIXTURE", "").strip():
        return FakeNER()
    return SubprocessNER()
