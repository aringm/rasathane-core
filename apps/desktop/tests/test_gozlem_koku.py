"""Masaüstü gözlem kökü: yeni marka adı + legacy fallback zinciri.

Regresyon koruması: varsayılan ad değişince mevcut kullanıcının verisi ikinci bir köke
bölünmemeli. `_default_output_base()` bu dosyadan önce hiç test edilmiyordu.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from ytcore.config import (
    GOZLEM_KOKU_ADI,
    GOZLEM_KOKU_LEGACY_ADLARI,
    _default_output_base,
)


@pytest.fixture
def sahte_ev(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    """Path.home()'u geçici dizine yönlendir; gerçek masaüstüne dokunma."""
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    (tmp_path / "Desktop").mkdir()
    return tmp_path / "Desktop"


def test_yeni_ad_cift_bosluk_tasiyor():
    """'Rasathane  Gözlemevi' — iki boşluk kasıtlı (Explorer etiketi temiz bölünsün)."""
    assert GOZLEM_KOKU_ADI == "Rasathane  Gözlemevi"
    assert "  " in GOZLEM_KOKU_ADI
    assert GOZLEM_KOKU_ADI.split() == ["Rasathane", "Gözlemevi"]


def _veri_koy(kok: Path) -> Path:
    """Dizini oluştur ve içine bir işaret dosyası koy (dolu = canlı veri)."""
    kok.mkdir(parents=True, exist_ok=True)
    (kok / "_index").mkdir(exist_ok=True)
    return kok


def test_temiz_kurulum_yeni_adi_secer(sahte_ev: Path):
    assert _default_output_base() == sahte_ev / GOZLEM_KOKU_ADI


@pytest.mark.parametrize("legacy_ad", GOZLEM_KOKU_LEGACY_ADLARI)
def test_dolu_legacy_klasor_varsa_veri_bolunmez(sahte_ev: Path, legacy_ad: str):
    _veri_koy(sahte_ev / legacy_ad)
    assert _default_output_base() == sahte_ev / legacy_ad


def test_bos_yeni_kok_dolu_legacyi_gizlemez(sahte_ev: Path):
    """Kenar durum: yeni kök elle açılıp boş kalmış, legacy dolu → legacy seçilmeli."""
    (sahte_ev / GOZLEM_KOKU_ADI).mkdir()  # boş
    _veri_koy(sahte_ev / "Rasathane Gözlemleri")  # dolu
    assert _default_output_base() == sahte_ev / "Rasathane Gözlemleri"


def test_dolu_yeni_ad_varsa_legacy_yok_sayilir(sahte_ev: Path):
    for ad in GOZLEM_KOKU_LEGACY_ADLARI:
        _veri_koy(sahte_ev / ad)
    _veri_koy(sahte_ev / GOZLEM_KOKU_ADI)
    assert _default_output_base() == sahte_ev / GOZLEM_KOKU_ADI


def test_legacy_onceligi_yeniden_eskiye(sahte_ev: Path):
    """İki dolu legacy birden varsa daha yeni olanı (Rasathane Gözlemleri) kazanır."""
    for ad in GOZLEM_KOKU_LEGACY_ADLARI:
        _veri_koy(sahte_ev / ad)
    assert _default_output_base() == sahte_ev / "Rasathane Gözlemleri"


def test_legacy_zinciri_eskiden_yeniye_siralanmis():
    assert GOZLEM_KOKU_LEGACY_ADLARI == ("Rasathane Gözlemleri", "Youtube Analizleri")
