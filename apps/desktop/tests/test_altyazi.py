from __future__ import annotations

from ytcore.transcript.altyazi import altyazi_sec


def test_tr_oncelik():
    assert altyazi_sec(["en", "tr", "de"]) == "tr"


def test_tr_orig_tr_yoksa():
    assert altyazi_sec(["en", "tr-orig"]) == "tr-orig"


def test_en_son_care():
    assert altyazi_sec(["en", "fr"]) == "en"


def test_hicbiri_yoksa_none():
    assert altyazi_sec(["de", "fr"]) is None


def test_bos_none():
    assert altyazi_sec([]) is None


def test_tr_tr_orig_uzerine_tercih():
    assert altyazi_sec(["tr-orig", "tr"]) == "tr"
