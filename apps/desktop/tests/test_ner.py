from __future__ import annotations

import json
from pathlib import Path

from ytcore.router.ner import FakeNER, SubprocessNER, ner_al


def test_fake_ner_kisi_tespiti():
    n = FakeNER()
    assert n.kisi_var_mi(["Ahmet Yılmaz dün duruşmaya katıldı."]) == [True]
    assert n.kisi_var_mi(["Yargıtay kararı bozdu."]) == [False]
    assert n.kisi_var_mi(["a", "Ahmet Yılmaz", "b"]) == [False, True, False]


def test_ner_al_fixture_seam(monkeypatch):
    monkeypatch.setenv("YT_NER_FIXTURE", "1")
    assert isinstance(ner_al(), FakeNER)
    monkeypatch.delenv("YT_NER_FIXTURE")
    assert isinstance(ner_al(), SubprocessNER)


def test_subprocess_ner_worker_yoksa_fail_closed():
    # KVKK fail-closed: worker çalışmazsa (bozuk python yolu) HER metin 'kişi VAR' sayılır
    # → cloud/web egress engellenir (deny-by-default). Sessiz fail-open YASAK.
    n = SubprocessNER(python="boyle-bir-exe-yok-12345", timeout_sn=10)
    assert n.kisi_var_mi(["tamamen masum metin", "ikinci metin"]) == [True, True]


def test_subprocess_ner_bozuk_cikti_fail_closed():
    # Worker 0 dönse de çıktı parse edilemiyorsa / uzunluk uyuşmuyorsa fail-closed.
    n = SubprocessNER(python="boyle-bir-exe-yok-12345", timeout_sn=10)
    assert n._parse("BOZUK JSON DEĞİL", beklenen=2) == [True, True]
    assert n._parse(json.dumps({"kisi_var": [False]}), beklenen=2) == [True, True]
    assert n._parse(json.dumps({"yanlis_anahtar": []}), beklenen=1) == [True]
    assert n._parse(json.dumps({"kisi_var": [False, True]}), beklenen=2) == [False, True]


def test_subprocess_ner_memo_cache():
    n = SubprocessNER(python="boyle-bir-exe-yok-12345", timeout_sn=10)
    n._memo["onceden bilinen"] = False
    # memo'daki metin için subprocess HİÇ çağrılmaz (bozuk python'a rağmen sonuç döner)
    assert n.kisi_var_mi(["onceden bilinen"]) == [False]


def test_parse_bool_olmayan_eleman_fail_closed():
    # review tur-1 (boş≠başarı LOW): doğru uzunlukta ama bool-olmayan eleman (null/0) fail-OPEN
    # olmamalı — "her bozulmada fail-closed" docstring sözleşmesi tip için de geçerli.
    n = SubprocessNER(python="boyle-bir-exe-yok-12345", timeout_sn=10)
    assert n._parse('{"kisi_var": [null, null]}', beklenen=2) == [True, True]
    assert n._parse('{"kisi_var": [0, 1]}', beklenen=2) == [True, True]


def test_frozen_exe_kendini_spawn_etmez(monkeypatch):
    # review tur-1 HIGH: frozen exe'de sys.executable = exe'nin KENDİSİ → self-spawn child
    # stdio moduna düşer (180s blok + stdin çalma). YT_NER_PYTHON ile ayrı env verilmedikçe
    # spawn ETMEDEN fail-closed dönmeli.
    import sys

    monkeypatch.setattr(sys, "frozen", True, raising=False)
    n = SubprocessNER(python=sys.executable, timeout_sn=10)

    def patlat(*a, **k):  # spawn olursa test KIRMIZI
        raise AssertionError("frozen exe kendini spawn etti!")

    import subprocess

    monkeypatch.setattr(subprocess, "run", patlat)
    assert n.kisi_var_mi(["herhangi bir metin"]) == [True]  # fail-closed, spawn YOK


def test_gercek_core_root_dev_modul_goreli():
    # Dev: _CORE_ROOT zaten ner_worker.py içerir → onu döndür (walk-up YOK, kısa-devre).
    from ytcore.router import ner

    assert (ner._gercek_core_root() / "ytcore" / "router" / "ner_worker.py").is_file()


def test_gercek_core_root_frozen_repo_core_bulur(monkeypatch, tmp_path):
    # Frozen exe HIGH: _CORE_ROOT = _MEIPASS (worker PYZ'de/exclude → harici python import
    # EDEMEZ). PYTHONPATH gerçek repo core'a işaret etmeli; sys.executable/cwd'den yukarı yürüyüp
    # ner_worker.py'yi içeren core'u bul (yoksa harici NER env tam web fact-check'i koşamaz).
    import sys

    from ytcore.router import ner

    meipass = tmp_path / "_MEI12345"
    meipass.mkdir()  # frozen _CORE_ROOT: worker YOK
    worker = tmp_path / "repo" / "core" / "ytcore" / "router" / "ner_worker.py"
    worker.parent.mkdir(parents=True)
    worker.write_text("")
    exe = tmp_path / "repo" / "gui" / "src-tauri" / "binaries" / "sidecar.exe"
    exe.parent.mkdir(parents=True)
    exe.write_text("")
    monkeypatch.setattr("ytcore.config.motor_core_root", lambda: None)  # motor_kok yok
    monkeypatch.setattr(ner, "_CORE_ROOT", meipass)
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(exe))
    assert ner._gercek_core_root() == (tmp_path / "repo" / "core").resolve()


def test_gercek_core_root_frozen_guvenilmez_cwd_secilmez(monkeypatch, tmp_path):
    # GÜVENLİK (review HIGH): frozen exe'de cwd'ye konmuş SAHTE core/ner_worker.py PYTHONPATH'e
    # GİRMEMELİ (keyfi worker = KVKK fail-OPEN). Walk-up yalnız sys.executable kökünden.
    import sys

    from ytcore.router import ner

    meipass = tmp_path / "_MEI"
    meipass.mkdir()
    sahte_worker = tmp_path / "indirilenler" / "core" / "ytcore" / "router" / "ner_worker.py"
    sahte_worker.parent.mkdir(parents=True)
    sahte_worker.write_text("# saldırgan worker", encoding="utf-8")
    exe = tmp_path / "izole" / "sidecar.exe"  # repo DIŞI, core yok
    exe.parent.mkdir(parents=True)
    exe.write_text("")
    monkeypatch.setattr("ytcore.config.motor_core_root", lambda: None)  # motor_kok yok
    monkeypatch.setattr(ner, "_CORE_ROOT", meipass)
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(exe))
    monkeypatch.chdir(tmp_path / "indirilenler")  # güvenilmez cwd
    # sahte cwd core'u SEÇİLMEZ → _CORE_ROOT (fail-closed; harici spawn worker'ı bulamaz)
    assert ner._gercek_core_root() == meipass


def test_frozen_self_yol_normalize_karsilastirir(monkeypatch):
    # GÜVENLİK (review): frozen-self guard yol-STRING'i değil NORMALİZE yolu karşılaştırmalı —
    # aynı dosyaya işaret eden farklı string (../bin/python; Windows'ta case) yine self sayılmalı
    # (self-spawn YOK, fail-closed). Aksi halde guard atlanır + 180s stdio-blok riski.
    import subprocess
    import sys

    exe = Path(sys.executable)
    varyant = str(exe.parent / ".." / exe.parent.name / exe.name)  # aynı dosya, farklı string
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    n = SubprocessNER(python=varyant, timeout_sn=5)

    def patlat(*a, **k):
        raise AssertionError("frozen-self (yol varyantı) spawn etmemeli!")

    monkeypatch.setattr(subprocess, "run", patlat)
    assert n.kisi_var_mi(["metin"]) == [True]  # fail-closed, spawn YOK


def test_parcala_bindirme_sinir():
    # review tur-1 LOW: len % adım == 0 sınırında öncekinin alt-kümesi olan gereksiz son parça
    # üretilmemeli; kapsam (tüm karakterler) korunmalı.
    from ytcore.router.ner_worker import _parcala

    metin = "".join(chr(65 + (i % 26)) for i in range(2300))  # ayırt edilebilir içerik
    p = _parcala(metin)
    assert p[0] == metin[:1200] and p[-1].endswith(metin[-1])
    # hiçbir parça bir öncekinin alt-kümesi değil (gereksiz inference yok)
    for once, sonra in zip(p, p[1:], strict=False):
        assert sonra not in once
    # kapsam: bindirmeler atılınca orijinal metin geri çıkar
    assert p[0] + "".join(parca[100:] for parca in p[1:]) == metin
    assert _parcala("kisa") == ["kisa"]
